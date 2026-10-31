"""Inlet: Twitch for the companion app. Streamer list (streamers.txt), who is live, polls and predictions of the
watched channel, replays and clips, followed channels (the box's Twitch app, device code), and the Twitch account.

Twitch account: signed in with a code on twitch.tv/activate as the Twitch app for TVs, or (backup) the site's token
pasted from the auth-token cookie; stored in streamlink's Twitch config, which streamlink reads by itself. Twitch
only removes ads for subscriptions with an account token.
"""
import datetime, json, os, re, threading, time, urllib.error, urllib.parse, urllib.request, uuid

import history   # history.py: positions of the replays and clips already watched on the box
from common import COOKIES_DIR, DIR, PUBLISH_EVERY, mpv, read_json_file, write_private_json
from i18n import tr

# In the settings, not next to the code: the code is replaced with the system (A/B updates). A list still in the code
# folder (older box, or restored from an older backup) takes its place.
STREAMERS_FILE = os.path.join(COOKIES_DIR, "streamers.txt")
OLD_STREAMERS_FILE = os.path.join(DIR, "streamers.txt")
if os.path.exists(OLD_STREAMERS_FILE):
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    os.replace(OLD_STREAMERS_FILE, STREAMERS_FILE)
TWITCH_CONFIG = os.path.expanduser("~/.config/streamlink/config.twitch")
TOKEN_PREFIX = "twitch-api-header=Authorization=OAuth "
# The same token as a cookie for yt-dlp (subscriber-only VODs). yt-dlp rewrites this file as 644 on every
# read: the folder, in 700, is what protects it.
COOKIES_FILE = os.path.join(COOKIES_DIR, "twitch-cookies.txt")
CHECK_EVERY = 1800   # seconds between two token checks with Twitch
LIVE_EVERY = 60      # seconds between two "who is live" polls
TWITCH_WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"   # the twitch.tv site's one, public (streamlink uses it too)


def read_streamers():
    # Same rules as read_streamers() in stream-box.lua
    names = []
    try:
        with open(STREAMERS_FILE, encoding="utf-8") as f:
            for line in f:
                name = line.split("#", 1)[0].strip().lower()
                for prefix in ("https://", "http://", "www.", "twitch.tv/"):
                    name = name.removeprefix(prefix)
                if name:
                    names.append(name)
    except OSError:
        pass
    return names


# Who is live: polled every minute for the whole list, published in user-data/streambox/live for stream-box.lua
# (TV menu, automatic switch) and returned by /api/state

live_now = {}   # login -> {"title", "viewers", "game", "thumb"}, live streamers only
avatars = {}    # login -> Twitch profile picture, for the page (live or not)


def fetch_live(logins):
    query = ("query($l:[String!]){users(logins:$l){login profileImageURL(width:70) "
             "stream{title viewersCount createdAt game{displayName} previewImageURL(width:640,height:360)}}}")
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps({"query": query, "variables": {"l": logins}}).encode(),
        headers={"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        users = json.load(r)["data"]["users"]
    avatars.update({u["login"]: u["profileImageURL"] for u in users if u and u.get("profileImageURL")})
    # Live thumbnail: same address from one minute to the next, the poll time forces the phone to reload it
    return {u["login"]: {"title": u["stream"]["title"], "viewers": u["stream"]["viewersCount"],
                         "started": epoch(u["stream"]["createdAt"]) if u["stream"].get("createdAt") else None,
                         "game": (u["stream"].get("game") or {}).get("displayName"),
                         "thumb": f"{u['stream']['previewImageURL']}?t={int(time.time()) // LIVE_EVERY}"
                         if u["stream"].get("previewImageURL") else None}
            for u in users if u and u.get("stream")}


def live_loop():
    global live_now
    first, fetched = True, 0.0
    while True:
        went_live = []
        if time.time() - fetched >= LIVE_EVERY:
            fetched = time.time()
            try:
                previous, live_now = live_now, fetch_live(read_streamers())
                # Streamers who just went live (not on the first poll: they were already live)
                went_live = [] if first else [login for login in live_now if login not in previous]
                first = False
            except (OSError, ValueError, KeyError, TypeError):
                pass   # Twitch unreachable: keep the last poll
        try:
            mpv(["set_property", "user-data/streambox/live", live_now])
            for login in went_live:
                mpv(["script-message", "streambox-went-live", login])
        except OSError:
            pass
        time.sleep(PUBLISH_EVERY)


# Polls and predictions of the watched channel, published in user-data/streambox/polls for stream-box.lua's panel.
# Twitch no longer has a real-time subscription (PubSub) for a plain viewer: we poll, like the twitch.tv page.

EVENTS_EVERY = 10    # seconds between two polls, only during a live stream with the panel enabled
PAGE_EVENTS_EVERY = 3   # while the companion app shows them: a poll or prediction that opens shows up sooner
RESULT_FOR = 60      # seconds the result of a finished poll or prediction is shown
LOCKED_FOR = 60      # seconds a locked prediction (bets closed, waiting for its result) stays on the TV
EVENTS_QUERY = (
    "query($l:String!){user(login:$l){"
    "viewablePoll{id title status startedAt durationSeconds totalVoters choices{id title votes{total}}} "
    "channel{activePredictionEvents{...p} lockedPredictionEvents{...p} "
    "resolvedPredictionEvents(first:1){edges{node{...p endedAt winningOutcome{id}}}}}}}"
    "fragment p on PredictionEvent{id title status createdAt lockedAt predictionWindowSeconds "
    "outcomes{id title color totalPoints totalUsers}}")
# With the connected account: its current bet and its channel points balance (to vote from the page)
EVENTS_SELF = "query($l:String!){user(login:$l){channel{self{communityPoints{balance}} " \
    "activePredictionEvents{id self{prediction{points outcome{id}}}} " \
    "lockedPredictionEvents{id self{prediction{points outcome{id}}}}}}}"
events_now = {"channel": None, "at": 0.0, "data": {"poll": None, "prediction": None}}   # last poll
events_seen = {}   # fetch_events' seen, shared by the TV's poll and the page's, emptied when the channel changes
poll_votes = {}   # poll id → choice voted from the box (Twitch does not give it back)


def epoch(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def fetch_events(login, seen):
    """{"poll", "prediction"} of the channel, each None when there is nothing to show. seen: id → time we saw the
    poll finished (Twitch does not give that time), to show its result for RESULT_FOR seconds only."""
    user = twitch_gql(EVENTS_QUERY, {"l": login}).get("user") or {}
    now, out = time.time(), {"poll": None, "prediction": None}
    p = user.get("viewablePoll")
    if p and p.get("status") in ("ACTIVE", "COMPLETED", "TERMINATED"):
        ended = p["status"] != "ACTIVE"
        if not ended or now - seen.setdefault(p["id"], now) < RESULT_FOR:
            out["poll"] = {"id": p["id"], "title": p["title"], "ended": ended, "voters": p.get("totalVoters") or 0,
                           "ends_at": epoch(p["startedAt"]) + (p.get("durationSeconds") or 0),
                           "mine": poll_votes.get(p["id"]),
                           "choices": [{"id": c["id"], "title": c["title"],
                                        "votes": (c.get("votes") or {}).get("total") or 0}
                                       for c in p.get("choices") or []]}
    channel = user.get("channel") or {}
    events = (channel.get("activePredictionEvents") or []) + (channel.get("lockedPredictionEvents") or [])
    resolved = [e["node"] for e in (channel.get("resolvedPredictionEvents") or {}).get("edges") or []]
    if not events and resolved and resolved[0].get("endedAt") and now - epoch(resolved[0]["endedAt"]) < RESULT_FOR:
        events = resolved
    if events:
        e = events[0]
        winner = (e.get("winningOutcome") or {}).get("id")
        # Locked: shown LOCKED_FOR seconds on the TV, then hidden there until its result (it can take the whole stream;
        # the page keeps it, with the bet made)
        locked_at = (epoch(e["lockedAt"]) if e.get("lockedAt") else seen.setdefault(e["id"] + ":locked", now)) \
            if e["status"] == "LOCKED" else None
        out["prediction"] = {"id": e["id"], "title": e["title"], "status": e["status"],
                             "tv": locked_at is None or now - locked_at < LOCKED_FOR,
                             "ends_at": epoch(e["createdAt"]) + (e.get("predictionWindowSeconds") or 0),
                             "outcomes": [{"id": o["id"], "title": o["title"], "color": o.get("color"),
                                           "points": o.get("totalPoints") or 0, "users": o.get("totalUsers") or 0,
                                           "winner": o["id"] == winner}
                                          for o in e.get("outcomes") or []]}
    if read_token() and (out["poll"] or out["prediction"]):
        try:   # current bet and balance, only when there is something to vote on
            ch = (twitch_gql(EVENTS_SELF, {"l": login}).get("user") or {}).get("channel") or {}
            out["balance"] = ((ch.get("self") or {}).get("communityPoints") or {}).get("balance")
            for ev in (ch.get("activePredictionEvents") or []) + (ch.get("lockedPredictionEvents") or []):
                mine = ((ev.get("self") or {}).get("prediction")) or None
                if out["prediction"] and ev["id"] == out["prediction"]["id"] and mine:
                    out["prediction"]["mine"] = {"outcome": (mine.get("outcome") or {}).get("id"), "points": mine.get("points")}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return out


def current_user_id():
    me = twitch_gql("{currentUser{id}}").get("currentUser")
    if not me:
        raise ValueError(tr("Connect your Twitch account (Settings) to vote."))
    return me["id"]


VOTE_ERRORS = {"POLL_NOT_FOUND": "This poll has ended.", "POLL_NOT_ACTIVE": "This poll has ended.",
               "INVALID_CHOICE_INDEX": "Unknown choice.", "NOT_ENOUGH_POINTS": "Not enough channel points.",
               "EVENT_NOT_ACTIVE": "Betting is closed.", "EVENT_LOCKED": "Betting is closed.",
               "NOT_FOUND": "This prediction has ended.", "MULTI_OUTCOME_PREDICTION": "You already bet on the other choice."}


def vote_poll(poll_id, choice_id):
    if not read_token():
        raise ValueError(tr("Connect your Twitch account (Settings) to vote."))
    d = twitch_gql("mutation($i:VoteInPollInput!){voteInPoll(input:$i){error{code}}}",
                   {"i": {"pollID": poll_id, "choiceID": choice_id, "userID": current_user_id(),
                          "voteID": uuid.uuid4().hex}})
    code = ((d.get("voteInPoll") or {}).get("error") or {}).get("code")
    if code:
        raise ValueError(tr(VOTE_ERRORS[code]) if code in VOTE_ERRORS
                         else tr("Twitch rejected the vote ({code}).", code=code))
    poll_votes[poll_id] = choice_id
    events_now["at"] = 0.0   # poll to redo


def predict(event_id, outcome_id, points):
    if not read_token():
        raise ValueError(tr("Connect your Twitch account (Settings) to bet."))
    if points < 1:
        raise ValueError(tr("Invalid number of points."))
    d = twitch_gql("mutation($i:MakePredictionInput!){makePrediction(input:$i){error{code}}}",
                   {"i": {"eventID": event_id, "outcomeID": outcome_id, "points": points,
                          "transactionID": uuid.uuid4().hex}})
    code = ((d.get("makePrediction") or {}).get("error") or {}).get("code")
    if code:
        raise ValueError(tr(VOTE_ERRORS[code]) if code in VOTE_ERRORS
                         else tr("Twitch rejected the bet ({code}).", code=code))
    events_now["at"] = 0.0


def poll_events(login):
    """fetch_events for the channel, kept in events_now (the seen times start over when the channel changes)"""
    if login != events_now["channel"]:
        events_seen.clear()
    data = fetch_events(login, events_seen)
    events_now.update(channel=login, at=time.time(), data=data)
    return data


def events_for_page():
    """Poll and prediction of the watched channel, for the page (polled every 3 s while it shows them): read again
    when the last poll is older than PAGE_EVENTS_EVERY seconds, the TV's panel updated at the same time"""
    user = mpv(["get_property", "user-data/streambox"])[0] or {}
    login = user.get("channel") if user.get("mode") == "twitch" else None
    if not login:
        return {"channel": None, "poll": None, "prediction": None, "logged_in": bool(read_token())}
    if events_now["channel"] != login or time.time() - events_now["at"] > PAGE_EVENTS_EVERY:
        data = poll_events(login)
        if user.get("events", True):
            mpv(["set_property", "user-data/streambox/polls", data])
    return {"channel": login, **events_now["data"], "logged_in": bool(read_token())}


def events_loop():
    while True:
        data = {"poll": None, "prediction": None}
        try:
            user, playing = mpv(["get_property", "user-data/streambox"], ["get_property", "video-params"])
            user = user or {}
            login = user.get("channel")
            # Any live channel (also a followed channel or a swapped second stream, outside the list); the page's
            # poll may have just read it
            if user.get("mode") == "twitch" and user.get("events", True) and playing and login:
                fresh = events_now["channel"] == login and time.time() - events_now["at"] < EVENTS_EVERY
                data = events_now["data"] if fresh else poll_events(login)
            mpv(["set_property", "user-data/streambox/polls", data])
        except (OSError, ValueError, KeyError, TypeError):
            pass   # mpv or Twitch unreachable: retry on the next round
        time.sleep(EVENTS_EVERY)


# A streamer's replays and clips of the week, for the page (5 min cache per streamer)

replays_cache = {}   # login -> (time, result)


def fetch_replays(login, vods=8, clips=6):
    """The latest replays (vods) and the week's clips of a streamer ("Load more": larger counts, the start cut off)"""
    query = ("query($l:String!,$v:Int!,$c:Int!){user(login:$l){"
             "videos(first:$v,type:ARCHIVE,sort:TIME){edges{node{id title lengthSeconds createdAt "
             "previewThumbnailURL(width:320,height:180) self{viewingHistory{position}}}}} "
             "clips(first:$c,criteria:{period:LAST_WEEK}){edges{node{slug title durationSeconds viewCount "
             "thumbnailURL}}}}}")
    user = twitch_gql(query, {"l": login, "v": vods, "c": clips})["user"] or {}
    vods = [{"title": n["title"], "date": n["createdAt"][:10], "seconds": n["lengthSeconds"],
             "thumb": n["previewThumbnailURL"], "url": f"https://www.twitch.tv/videos/{n['id']}",
             "position": (((n.get("self") or {}).get("viewingHistory") or {}).get("position"))}
            for n in (e["node"] for e in (user.get("videos") or {}).get("edges", []))]
    clips = [{"title": n["title"], "seconds": n["durationSeconds"], "views": n["viewCount"],
              "thumb": n["thumbnailURL"], "url": f"https://clips.twitch.tv/{n['slug']}"}
             for n in (e["node"] for e in (user.get("clips") or {}).get("edges", []))]
    return {"login": login, "vods": vods, "clips": clips}


def replays(login):
    if login not in read_streamers():
        raise ValueError(tr("unknown streamer"))
    cached = replays_cache.get(login)
    if not cached or time.time() - cached[0] > 300:
        cached = (time.time(), fetch_replays(login))
        replays_cache[login] = cached
    # Progress: the one from the box's history when it is more recent than the Twitch poll
    known = {e["key"]: e for e in history.read_history()}
    result = json.loads(json.dumps(cached[1]))
    for item in result["vods"] + result["clips"]:
        entry = known.get(history.media_key(item["url"])[0])
        if entry and entry.get("updated", 0) > cached[0] - 300:
            item["position"] = entry["position"]
        item["finished"] = history.finished(item.get("position") or 0, item.get("seconds"))
    return result


def replays_more(login, kind, offset):
    """"Load more" in the Replays tab: the next replays (8) or clips (6) after offset"""
    if login not in read_streamers() or kind not in ("vods", "clips"):
        raise ValueError(tr("unknown streamer"))
    page = 8 if kind == "vods" else 6
    data = fetch_replays(login, offset + page if kind == "vods" else 1, offset + page if kind == "clips" else 1)
    items = data[kind][offset:]
    known = {e["key"]: e for e in history.read_history()}
    for item in items:
        entry = known.get(history.media_key(item["url"])[0])
        if entry:
            item["position"] = entry["position"]
        item["finished"] = history.finished(item.get("position") or 0, item.get("seconds"))
    return {"items": items, "more": len(items) >= page}


# Streamer list editable from the page: adding (after checking on Twitch) and removing. The comment lines of
# streamers.txt are kept.

def twitch_user(login):
    query = "query($l:String!){user(login:$l){login displayName}}"
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps({"query": query, "variables": {"l": login}}).encode(),
        headers={"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["data"]["user"]


def write_streamers(names):
    """Rewrites the list in the given order, keeping the file's header comments."""
    with open(STREAMERS_FILE, encoding="utf-8") as f:
        lines = f.readlines()
    header = []
    for line in lines:
        if line.split("#", 1)[0].strip():
            break
        header.append(line)
    tmp = STREAMERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(header + [name + "\n" for name in names])
    os.replace(tmp, STREAMERS_FILE)


def edit_streamers(action, raw, delta=0):
    login = raw.strip().lower().removeprefix("https://").removeprefix("www.").removeprefix("twitch.tv/").strip("/ @")
    if not re.fullmatch(r"[a-z0-9_]{3,25}", login):
        raise ValueError(tr("Invalid Twitch username (letters, digits and _ only)."))
    current = read_streamers()
    if action == "add":
        if login in current:
            raise ValueError(tr("{login} is already in the list.", login=login))
        try:
            user = twitch_user(login)
        except OSError as e:
            raise ValueError(tr("Unable to check on Twitch ({error}).", error=e)) from e
        if not user:
            raise ValueError(tr("No Twitch channel \"{login}\".", login=login))
        os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
        with open(STREAMERS_FILE, "a", encoding="utf-8") as f:
            f.write(login + "\n")
        try:   # first streamer of an empty list: start it
            if not mpv(["get_property", "user-data/streambox/channel"])[0]:
                mpv(["script-message", "streambox-channel", login])
        except OSError:
            pass
    elif action == "remove":
        if login not in current:
            raise ValueError(tr("{login} is not in the list.", login=login))
        if len(current) == 1:
            raise ValueError(tr("You must keep at least one streamer."))
        write_streamers([n for n in current if n != login])
    elif action == "move":
        if login not in current:
            raise ValueError(tr("{login} is not in the list.", login=login))
        i = current.index(login)
        j = max(0, min(len(current) - 1, i + (1 if delta > 0 else -1)))
        current[i], current[j] = current[j], current[i]
        write_streamers(current)
    else:
        raise ValueError(tr("unknown action"))
    global live_now
    live_now = {k: v for k, v in live_now.items() if k in read_streamers()}


def twitch_gql(query, variables=None):
    """Twitch GQL request, with the connected account if there is one."""
    headers = {"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"}
    token = read_token()
    if token:
        headers["Authorization"] = f"OAuth {token}"
    req = urllib.request.Request("https://gql.twitch.tv/gql",
                                 data=json.dumps({"query": query, "variables": variables or {}}).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["data"]


def twitch_save_position(video_id, position):
    if not read_token():
        return
    me = twitch_gql("{currentUser{id}}").get("currentUser")
    if me:
        twitch_gql("mutation($i:UpdateUserViewedVideoInput!){updateUserViewedVideo(input:$i){video{id}}}",
                   {"i": {"userID": me["id"], "videoID": video_id, "videoType": "VOD", "position": int(position)}})


# Followed channels (Following tab of the TV menu). Twitch refuses this list to the site's token (GQL: "service error",
# Helix: the user:read:follows scope is missing): it takes a Twitch app and a code authorization ("device code
# flow"): the TV or the page show a code to type on twitch.tv/activate. The Inlet app by default
# (TWITCH_CLIENT_ID, the same for every box: nothing to create). It is of type Public: no secret, its Client ID is
# public by nature (it travels in the clear with every request), like the ones streamlink or yt-dlp carry. Your own
# app instead, if you want (companion app, "Use your own Twitch app"): twitch-app.json ({"client_id",
# "client_secret"?}, also the boxes from before the built-in app), removed to go back to the box's. Tokens in
# twitch-follows-token.json, both 600 in ~/.config/stream-box.

TWITCH_APP_FILE = os.path.join(COOKIES_DIR, "twitch-app.json")
TWITCH_CLIENT_ID = "y2pihopq29jojaskixpelop4gnaisa"
FOLLOWS_TOKEN_FILE = os.path.join(COOKIES_DIR, "twitch-follows-token.json")
FOLLOWS_SCOPE = "user:read:follows"
FOLLOWS_CACHE = 60   # seconds between two polls of the list
follows_lock = threading.Lock()
follows_pending = {}           # authorization in progress: user_code, verification_uri, expires_at, error
follows_cache = {"at": 0.0, "data": None}


def twitch_oauth(path, fields):
    """POST to id.twitch.tv; returns (HTTP code, JSON reply)."""
    req = urllib.request.Request(f"https://id.twitch.tv/oauth2/{path}", data=urllib.parse.urlencode(fields).encode())
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {}


def app_fields():
    app = read_json_file(TWITCH_APP_FILE)
    if not app.get("client_id"):
        return {"client_id": TWITCH_CLIENT_ID}
    fields = {"client_id": app["client_id"]}
    if app.get("client_secret"):
        fields["client_secret"] = app["client_secret"]
    return fields


def save_follows_token(d, client_id=None):
    """client_id: the TV app's, for a token from the account's sign-in by code (it does not expire: expires_in 0)"""
    lasts = int(d.get("expires_in") or 0) or (10 * 365 * 86400 if client_id else 3600)
    write_private_json(FOLLOWS_TOKEN_FILE, {"access_token": d["access_token"], "refresh_token": d.get("refresh_token"),
                                            "expires_at": time.time() + lasts,
                                            **({"client_id": client_id} if client_id else {})})


def follows_poll(device_code, interval, expires_at):
    """Waits for the user to type the code on twitch.tv/activate (separate thread)."""
    while time.time() < expires_at:
        time.sleep(interval)
        try:
            code, d = twitch_oauth("token", {**app_fields(), "scopes": FOLLOWS_SCOPE, "device_code": device_code,
                                              "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        except (OSError, ValueError):
            continue
        if code == 200 and d.get("access_token"):
            save_follows_token(d)
            with follows_lock:
                follows_pending.clear()
                follows_cache.update(at=0.0, data=None)
            return
        message = d.get("message", "")
        if message == "slow_down":
            interval += 5
        elif message != "authorization_pending":
            with follows_lock:
                follows_pending.update(error=message or tr("refused by Twitch ({code})", code=code))
            return
    with follows_lock:
        follows_pending.update(error=tr("code expired"))


def follows_start():
    code, d = twitch_oauth("device", {"client_id": app_fields()["client_id"], "scopes": FOLLOWS_SCOPE})
    if code != 200 or not d.get("device_code"):
        raise ValueError(tr("Twitch refuses the request: {error}", error=d.get("message") or code))
    expires_at = time.time() + int(d.get("expires_in") or 1800)
    with follows_lock:
        follows_pending.clear()
        follows_pending.update(user_code=d["user_code"], verification_uri=d["verification_uri"], expires_at=expires_at)
    threading.Thread(target=follows_poll, args=(d["device_code"], int(d.get("interval") or 5), expires_at),
                     daemon=True).start()


def follows_token():
    """Valid token for Helix, renewed if needed; None when the box is not authorized."""
    tok = read_json_file(FOLLOWS_TOKEN_FILE)
    if not tok.get("access_token"):
        return None
    if time.time() > tok.get("expires_at", 0) - 120:
        if not tok.get("refresh_token"):
            return None
        fields = {"client_id": tok["client_id"]} if tok.get("client_id") else app_fields()
        code, d = twitch_oauth("token", {**fields, "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
        if code != 200 or not d.get("access_token"):
            if code in (400, 401):   # authorization revoked on Twitch: it will have to be redone
                os.remove(FOLLOWS_TOKEN_FILE)
            return None
        save_follows_token(d, tok.get("client_id"))
        tok = read_json_file(FOLLOWS_TOKEN_FILE)
    return tok["access_token"]


def helix(path, token):
    # Helix wants the Client-ID of the app the token comes from (the TV app's after a sign-in by code)
    client = read_json_file(FOLLOWS_TOKEN_FILE).get("client_id") or app_fields()["client_id"]
    req = urllib.request.Request(f"https://api.twitch.tv/helix/{path}",
                                 headers={"Client-Id": client, "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def fetch_follows(token):
    me = validate_helix(token)
    live = []
    for st in helix(f"streams/followed?user_id={me}&first=100", token).get("data", []):
        live.append({"login": st["user_login"], "title": st.get("title"), "viewers": st.get("viewer_count"),
                     "game": st.get("game_name"),
                     "thumb": (st.get("thumbnail_url") or "").replace("{width}", "640").replace("{height}", "360")
                     + f"?t={int(time.time()) // FOLLOWS_CACHE}"})
    logins, cursor = [], ""
    for _ in range(5):   # up to 500 followed channels
        d = helix(f"channels/followed?user_id={me}&first=100" + (f"&after={cursor}" if cursor else ""), token)
        logins += [c["broadcaster_login"] for c in d.get("data", [])]
        cursor = (d.get("pagination") or {}).get("cursor")
        if not cursor:
            break
    avatars_map = {}
    for i in range(0, len(logins), 100):
        query = "&".join(f"login={urllib.parse.quote(l)}" for l in logins[i:i + 100])
        for u in helix(f"users?{query}", token).get("data", []):
            avatars_map[u["login"]] = u.get("profile_image_url")
    avatars.update({k: v for k, v in avatars_map.items() if v})
    live_logins = {c["login"] for c in live}
    for c in live:
        c["avatar"] = avatars_map.get(c["login"])
    offline = [{"login": l, "avatar": avatars_map.get(l)} for l in logins if l not in live_logins]
    return {"live": sorted(live, key=lambda c: -(c["viewers"] or 0)), "offline": offline}


def validate_helix(token):
    req = urllib.request.Request("https://id.twitch.tv/oauth2/validate", headers={"Authorization": f"OAuth {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["user_id"]


def follows_status():
    """State for the page and the menu: own app (instead of the box's), authorization in progress, list."""
    out = {"own_app": bool(read_json_file(TWITCH_APP_FILE).get("client_id")), "authorized": False, "pending": None,
           "live": [], "offline": []}
    with follows_lock:
        if follows_pending and follows_pending.get("expires_at", 0) > time.time():
            out["pending"] = {k: follows_pending.get(k) for k in ("user_code", "verification_uri", "error")}
    token = follows_token()
    if not token:
        return out
    out["authorized"] = True
    with follows_lock:
        if follows_cache["data"] is None or time.time() - follows_cache["at"] > FOLLOWS_CACHE:
            follows_cache.update(at=time.time(), data=fetch_follows(token))
        out.update(follows_cache["data"])
    return out


def follows_logins():
    data = follows_cache["data"] or {}
    return {c["login"] for c in data.get("live", []) + data.get("offline", [])}


def set_twitch_app(client_id, client_secret):
    """Your own Twitch app instead of the box's; an empty Client ID goes back to the box's"""
    client_id = client_id.strip()
    if client_id and not re.fullmatch(r"[a-z0-9]{20,40}", client_id):
        raise ValueError(tr("This is not a Twitch Client ID (30 letters and digits)."))
    if client_id:
        app = {"client_id": client_id}
        if client_secret.strip():
            app["client_secret"] = client_secret.strip()
        write_private_json(TWITCH_APP_FILE, app)
    else:
        try:
            os.remove(TWITCH_APP_FILE)
        except FileNotFoundError:
            pass
    follows_logout()   # another app: the old authorization no longer applies
    with follows_lock:
        follows_pending.clear()


def follows_logout():
    try:
        os.remove(FOLLOWS_TOKEN_FILE)
    except FileNotFoundError:
        pass
    with follows_lock:
        follows_cache.update(at=0.0, data=None)


# Twitch account

account = {"login": None, "expired": False}   # last known result, so as not to query Twitch on every request
account_lock = threading.Lock()
# Sign-in by code (twitch.tv/activate) as the Twitch app for TVs: its public device-code client, as the box does for
# YouTube. Its token works wherever the site's does (streamlink, GQL with the site's Client-ID, yt-dlp's cookie: Twitch
# recognizes the account on the stream) and, with user:read:follows, it also reads the followed channels (Helix, with
# its own Client-ID): one sign-in for both, which does not expire. Pasting the site's auth-token stays as a backup.
TWITCH_TV_CLIENT_ID = "ue6666qo983tsx6so1t0vnawi233wa"
account_pending = {}   # code in progress: user_code, verification_uri, expires_at, error


def read_token():
    try:
        with open(TWITCH_CONFIG, encoding="utf-8") as f:
            for line in f:
                if line.startswith(TOKEN_PREFIX):
                    return line[len(TOKEN_PREFIX):].strip()
    except OSError:
        pass
    return None


def write_cookies(token):
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    os.chmod(COOKIES_DIR, 0o700)
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        if token:
            f.write(f".twitch.tv\tTRUE\t/\tTRUE\t0\tauth-token\t{token}\n")


def write_token(token):
    write_cookies(token)
    if token is None:
        try:
            os.remove(TWITCH_CONFIG)
        except FileNotFoundError:
            pass
        return
    os.makedirs(os.path.dirname(TWITCH_CONFIG), exist_ok=True)
    tmp = TWITCH_CONFIG + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # readable by media only
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(TOKEN_PREFIX + token + "\n")
    os.replace(tmp, TWITCH_CONFIG)


def validate(token):
    """Twitch username of the token, or None if Twitch refuses it. OSError if Twitch is unreachable."""
    req = urllib.request.Request("https://id.twitch.tv/oauth2/validate", headers={"Authorization": f"OAuth {token}"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r).get("login")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return None
        raise OSError(f"Twitch replied {e.code}") from e


def restart_stream():
    # Restart streamlink on the current channel, so it reads its config again
    try:
        channel = mpv(["get_property", "user-data/streambox/channel"])[0]
        if channel:
            mpv(["script-message", "streambox-channel", channel])
    except OSError:
        pass   # mpv not running: it will read the config at startup


def check_account():
    """Checks the saved token again. If it no longer works, remove it: a refused token blocks playback."""
    token = read_token()
    if not token:
        with account_lock:
            account["login"] = None
        return
    try:
        login = validate(token)
    except OSError:
        return   # Twitch unreachable: keep the known state
    with account_lock:
        account["login"] = login
        account["expired"] = login is None
    if login is None:
        write_token(None)
        restart_stream()


def account_loop():
    while True:
        check_account()
        time.sleep(CHECK_EVERY)


def login(raw):
    # Accepts the cookie value as is, in quotes or preceded by "OAuth"
    token = raw.strip().strip("\"'").strip()
    token = re.sub(r"^(OAuth|Bearer)\s+", "", token, flags=re.I)
    if not re.fullmatch(r"[A-Za-z0-9]{20,64}", token):
        raise ValueError(tr("This does not look like a Twitch token: copy the value of the auth-token cookie."))
    try:
        name = validate(token)
    except OSError as e:
        raise ValueError(tr("Unable to reach Twitch to check the token ({error}).", error=e)) from e
    if not name:
        raise ValueError(tr("Twitch refuses this token: it is expired or incomplete."))
    write_token(token)
    with account_lock:
        account.update(login=name, expired=False)
    restart_stream()


def logout():
    write_token(None)
    with account_lock:
        account.update(login=None, expired=False)
        account_pending.clear()
    if read_json_file(FOLLOWS_TOKEN_FILE).get("client_id") == TWITCH_TV_CLIENT_ID:
        follows_logout()   # the same sign-in gave the followed channels
    restart_stream()


def account_start():
    """Sign-in by code: asks Twitch for one (the TV and the page show it), then waits for it in a thread"""
    code, d = twitch_oauth("device", {"client_id": TWITCH_TV_CLIENT_ID, "scopes": FOLLOWS_SCOPE})
    if code != 200 or not d.get("device_code"):
        raise ValueError(tr("Twitch refuses the request: {error}", error=d.get("message") or code))
    expires_at = time.time() + int(d.get("expires_in") or 1800)
    with account_lock:
        account_pending.clear()
        account_pending.update(user_code=d["user_code"], verification_uri=d["verification_uri"], expires_at=expires_at)
    threading.Thread(target=account_poll, args=(d["device_code"], int(d.get("interval") or 5), expires_at),
                     daemon=True).start()


def account_poll(device_code, interval, expires_at):
    """Waits for the code typed on twitch.tv/activate, then signs in: account token and followed channels"""
    while time.time() < expires_at:
        time.sleep(interval)
        try:
            code, d = twitch_oauth("token", {"client_id": TWITCH_TV_CLIENT_ID, "scopes": FOLLOWS_SCOPE,
                                              "device_code": device_code,
                                              "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        except OSError:
            continue
        if code == 200 and d.get("access_token"):
            try:
                name = validate(d["access_token"])
            except OSError:
                name = None
            if not name:
                with account_lock:
                    account_pending.update(error=tr("Twitch refuses this token: it is expired or incomplete."))
                return
            write_token(d["access_token"])
            save_follows_token(d, TWITCH_TV_CLIENT_ID)
            with account_lock:
                account.update(login=name, expired=False)
                account_pending.clear()
            with follows_lock:
                follows_pending.clear()
                follows_cache.update(at=0.0, data=None)
            restart_stream()
            return
        message = d.get("message", "")
        if message == "slow_down":
            interval += 5
        elif message != "authorization_pending":
            with account_lock:
                account_pending.update(error=message or tr("refused by Twitch ({code})", code=code))
            return
    with account_lock:
        account_pending.update(error=tr("code expired"))


def account_status():
    """{login, expired, pending}: pending = code in progress (user_code, verification_uri, error)"""
    with account_lock:
        out = dict(account)
        live = account_pending and account_pending.get("expires_at", 0) > time.time()
        out["pending"] = {k: account_pending.get(k) for k in ("user_code", "verification_uri", "error")} if live else None
    return out
