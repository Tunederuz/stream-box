#!/usr/bin/env python3
"""Stream Box: companion app for the phone (http://<box>:8080), which drives mpv through its IPC socket.

Streamer and chat changes go through the script-messages of stream-box.lua, so that the on-screen menu, the chat
and the page stay in agreement. Standard library only.

Twitch account: the site's token (auth-token cookie) is stored in streamlink's Twitch config, which streamlink reads
by itself. Twitch only removes ads for subscriptions with that token.
"""
import calendar, datetime, hashlib, json, os, uuid, re, shutil, socket, subprocess, threading, time, urllib.error, urllib.parse, urllib.request, zoneinfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import display   # display.py, same folder
import netsetup  # netsetup.py: setup Wi-Fi access point
import audio     # audio.py: sound output (plugged HDMI, USB, Bluetooth, manual choice)
import btsetup   # btsetup.py: Bluetooth remotes and gamepads (pairing, removal)
import backup    # backup.py: backup and restore of settings (USB stick, file from the page)
import installer  # installer.py: installation to an internal disk from the USB stick
import i18n       # i18n.py: interface language (locales/<lang>.json), tr()
from i18n import tr

PORT = 8080
MPV_SOCKET = "/tmp/stream-box-mpv.sock"
DIR = os.path.dirname(os.path.abspath(__file__))
STREAMERS_FILE = os.path.join(DIR, "streamers.txt")
TWITCH_CONFIG = os.path.expanduser("~/.config/streamlink/config.twitch")
TOKEN_PREFIX = "twitch-api-header=Authorization=OAuth "
# The same token as a cookie for yt-dlp (subscriber-only VODs). yt-dlp rewrites this file as 644 on every
# read: the folder, in 700, is what protects it.
COOKIES_DIR = os.path.expanduser("~/.config/stream-box")
COOKIES_FILE = os.path.join(COOKIES_DIR, "twitch-cookies.txt")
CHECK_EVERY = 1800   # seconds between two token checks with Twitch
LIVE_EVERY = 60      # seconds between two "who is live" polls
PUBLISH_EVERY = 10   # seconds between two sends of already known data to mpv: a restarted mpv gets them quickly
TWITCH_WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"   # the twitch.tv site's one, public (streamlink uses it too)
# Files served as is: the page and what is needed to install it as an app (PWA)
STATIC = {
    "/": ("remote.html", "text/html; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/sw.js": ("sw.js", "text/javascript"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/apple-touch-icon.png": ("icon-180.png", "image/png"),
}
# Translations (companion app, TV menu): /locales/<lang>.json
for _code in i18n.LANGUAGES:
    if _code != "en":
        STATIC[f"/locales/{_code}.json"] = (f"locales/{_code}.json", "application/json; charset=utf-8")


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


def mpv(*commands):
    """Sends commands to mpv; returns the data field of each reply, in order."""
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(2)
        s.connect(MPV_SOCKET)
        for i, cmd in enumerate(commands):
            s.sendall((json.dumps({"command": list(cmd), "request_id": i}) + "\n").encode())
        results, buf = {}, b""
        while len(results) < len(commands):
            data = s.recv(65536)
            if not data:
                raise OSError("mpv closed")
            *lines, buf = (buf + data).split(b"\n")
            for line in lines:
                msg = json.loads(line)
                if "event" not in msg and "request_id" in msg:
                    results[msg["request_id"]] = msg.get("data")
        return [results[i] for i in range(len(commands))]


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
RESULT_FOR = 60      # seconds the result of a finished poll or prediction is shown
EVENTS_QUERY = (
    "query($l:String!){user(login:$l){"
    "viewablePoll{id title status startedAt durationSeconds totalVoters choices{id title votes{total}}} "
    "channel{activePredictionEvents{...p} lockedPredictionEvents{...p} "
    "resolvedPredictionEvents(first:1){edges{node{...p endedAt winningOutcome{id}}}}}}}"
    "fragment p on PredictionEvent{id title status createdAt predictionWindowSeconds "
    "outcomes{id title color totalPoints totalUsers}}")
# With the connected account: its current bet and its channel points balance (to vote from the page)
EVENTS_SELF = "query($l:String!){user(login:$l){channel{self{communityPoints{balance}} " \
    "activePredictionEvents{id self{prediction{points outcome{id}}}} " \
    "lockedPredictionEvents{id self{prediction{points outcome{id}}}}}}}"
events_now = {"channel": None, "at": 0.0, "data": {"poll": None, "prediction": None}}   # last poll
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
        out["prediction"] = {"id": e["id"], "title": e["title"], "status": e["status"],
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


def events_for_page():
    """Poll and prediction of the watched channel, for the page; polled here when the regular poll is not running
    (panel disabled), at most every EVENTS_EVERY seconds"""
    user = mpv(["get_property", "user-data/streambox"])[0] or {}
    login = user.get("channel") if user.get("mode") == "twitch" else None
    if not login:
        return {"channel": None, "poll": None, "prediction": None, "logged_in": bool(read_token())}
    if events_now["channel"] != login or time.time() - events_now["at"] > EVENTS_EVERY:
        events_now.update(channel=login, at=time.time(), data=fetch_events(login, {}))
    return {"channel": login, **events_now["data"], "logged_in": bool(read_token())}


def events_loop():
    seen, current = {}, None
    while True:
        data = {"poll": None, "prediction": None}
        try:
            user, playing = mpv(["get_property", "user-data/streambox"], ["get_property", "video-params"])
            user = user or {}
            login = user.get("channel")
            # Any live channel (also a followed channel or a swapped second stream, outside the list)
            if user.get("mode") == "twitch" and user.get("events", True) and playing and login:
                if login != current:
                    seen, current = {}, login
                data = fetch_events(login, seen)
                events_now.update(channel=login, at=time.time(), data=data)
            mpv(["set_property", "user-data/streambox/polls", data])
        except (OSError, ValueError, KeyError, TypeError):
            pass   # mpv or Twitch unreachable: retry on the next round
        time.sleep(EVENTS_EVERY)


# A streamer's replays and clips of the week, for the page (5 min cache per streamer)

replays_cache = {}   # login -> (time, result)


def fetch_replays(login):
    query = ("query($l:String!){user(login:$l){"
             "videos(first:8,type:ARCHIVE,sort:TIME){edges{node{id title lengthSeconds createdAt "
             "previewThumbnailURL(width:320,height:180) self{viewingHistory{position}}}}} "
             "clips(first:6,criteria:{period:LAST_WEEK}){edges{node{slug title durationSeconds viewCount "
             "thumbnailURL}}}}}")
    user = twitch_gql(query, {"l": login})["user"] or {}
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
    known = {e["key"]: e for e in read_history()}
    result = json.loads(json.dumps(cached[1]))
    for item in result["vods"] + result["clips"]:
        entry = known.get(media_key(item["url"])[0])
        if entry and entry.get("updated", 0) > cached[0] - 300:
            item["position"] = entry["position"]
        item["finished"] = finished(item.get("position") or 0, item.get("seconds"))
    return result


# Ambient screen (drawn by stream-box.lua when nothing is playing): weather and upcoming scheduled lives, published in
# user-data/streambox/ambient. Weather comes from Open-Meteo (no account); location in ~/.config/stream-box/ambient.json:
# {"city": "...", "latitude": ..., "longitude": ..., "timezone": "Europe/..."} (without this file: no weather).

AMBIENT_FILE = os.path.join(COOKIES_DIR, "ambient.json")
AMBIENT_FETCH = 600   # seconds between two fetches (weather, schedules)
# WMO code -> text (English; translated with tr() when published)
WEATHER = [((0,), "Clear sky"), ((1,), "Mostly clear"), ((2,), "Partly cloudy"), ((3,), "Overcast"),
           ((45, 48), "Fog"), ((51, 53, 55), "Drizzle"), ((56, 57), "Freezing drizzle"), ((61,), "Light rain"),
           ((63,), "Rain"), ((65,), "Heavy rain"), ((66, 67), "Freezing rain"), ((71,), "Light snow"),
           ((73,), "Snow"), ((75,), "Heavy snow"), ((77,), "Snow grains"), ((80, 81, 82), "Showers"),
           ((85, 86), "Snow showers"), ((95,), "Thunderstorm"), ((96, 99), "Thunderstorm with hail")]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def ambient_conf():
    try:
        with open(AMBIENT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def fetch_weather(conf):
    if "latitude" not in conf:
        return None
    query = urllib.parse.urlencode({
        "latitude": conf["latitude"], "longitude": conf["longitude"], "timezone": conf.get("timezone", "auto"),
        "current": "temperature_2m,weather_code", "forecast_days": 1,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=10) as r:
        d = json.load(r)
    code = d["current"]["weather_code"]
    return {"city": conf.get("city"), "temp": round(d["current"]["temperature_2m"]), "code": code,
            "text": next((tr(t) for codes, t in WEATHER if code in codes), ""),
            "min": round(d["daily"]["temperature_2m_min"][0]), "max": round(d["daily"]["temperature_2m_max"][0]),
            "rain": d["daily"]["precipitation_probability_max"][0]}


def fetch_schedule(logins, tz):
    """Upcoming scheduled lives of the list (Twitch schedules), see next_streams."""
    if not logins:
        return []
    query = ("query($l:[String!]){users(logins:$l){login channel{schedule{"
             "interruption{startAt endAt} segments{startAt endAt title isCancelled}}}}}")
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps({"query": query, "variables": {"l": logins}}).encode(),
        headers={"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        users = json.load(r)["data"]["users"]
    return next_streams(users, datetime.datetime.now(tz))


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December"]


def day_month(d):
    """Day and month, such as "March 5", in the current language"""
    month = tr(MONTHS[d.month - 1])
    return tr("{month} 1", month=month) if d.day == 1 else tr("{month} {day}", month=month, day=d.day)


def next_streams(users, now):
    """Next slot of each streamer, from nearest to furthest, then the streamers on a break.

    Schedules are weekly: a past slot is moved a week later. Cancelled slots are ignored, and so are those falling
    during a break (Twitch "interruption", the streamer's holidays); a streamer currently on a break is shown as
    "on a break until …" instead of a slot.
    """
    tz = now.tzinfo

    def when(value):
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(tz)

    upcoming, paused = [], []
    for u in users:
        schedule = ((u or {}).get("channel") or {}).get("schedule") or {}
        pause = schedule.get("interruption") or {}
        pause = (when(pause["startAt"]), when(pause["endAt"])) if pause.get("startAt") and pause.get("endAt") else None
        if pause and pause[0] <= now < pause[1]:
            end = pause[1]
            paused.append({"login": u["login"], "when": tr("on a break until {date}", date=day_month(end)),
                           "title": ""})
            continue
        best = None
        for seg in schedule.get("segments") or []:
            if seg.get("isCancelled"):
                continue
            start = when(seg["startAt"])
            while start < now - datetime.timedelta(hours=1) or (pause and pause[0] <= start < pause[1]):
                start += datetime.timedelta(days=7)   # past slot, or during the break: the following week
            if not best or start < best[0]:
                best = (start, seg.get("title") or "")
        if best:
            upcoming.append((best[0], u["login"], best[1]))
    out = []
    for start, login, title in sorted(upcoming)[:4]:
        days = (start.date() - now.date()).days
        day = tr("today") if days == 0 else tr("tomorrow") if days == 1 else tr(DAYS[start.weekday()])
        if days >= 7:   # beyond a week (after a break), the day alone would be misleading
            day = tr("{weekday}, {date}", weekday=day, date=day_month(start))
        out.append({"login": login, "when": f"{day} {start:%H:%M}", "title": title})
    return out + paused[:2]


# QR code of the companion app, for guests (ambient screen and TV menu). Address in
# ~/.config/stream-box/remote-url (the HTTPS reverse proxy's, for example), otherwise http://<box IP>:8080.
# The QR code is computed by segno, in the media venv, and published as rows of "0" and "1".

REMOTE_URL_FILE = os.path.join(COOKIES_DIR, "remote-url")
MEDIA_PYTHON = os.path.expanduser("~/.local/share/media-venv/bin/python")


def remote_url():
    try:
        with open(REMOTE_URL_FILE, encoding="utf-8") as f:
            url = f.read().strip()
        if re.match(r"https?://", url):
            return url
    except OSError:
        pass
    return f"http://{lan_ip()}:{PORT}"


def lan_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))   # nothing is sent: only used to learn the outgoing address
        return s.getsockname()[0]


def custom_remote_url():
    try:
        with open(REMOTE_URL_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def set_remote_url(url):
    """Companion app address shown as a QR code: domain name (HTTPS reverse proxy…); empty = local network"""
    url = url.strip()
    if not url:
        try:
            os.remove(REMOTE_URL_FILE)
        except FileNotFoundError:
            pass
        return
    if not re.match(r"https?://[\w.-]+(:\d+)?(/\S*)?$", url):
        raise ValueError(tr("Expected address: https://… (or http://…)"))
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    with open(REMOTE_URL_FILE, "w", encoding="utf-8") as f:
        f.write(url + "\n")


qr_cache = {}   # address -> QR code rows


def qr_rows(text):
    if text not in qr_cache:
        try:
            r = subprocess.run([MEDIA_PYTHON, "-I", "-c", "import segno, sys\n"
                                "for row in segno.make(sys.argv[1], error='m', micro=False).matrix:\n"
                                "    print(''.join(str(int(bool(v))) for v in row))", text],
                               capture_output=True, text=True, timeout=20, check=True)
            qr_cache[text] = r.stdout.split()
        except (OSError, subprocess.SubprocessError):
            qr_cache[text] = None   # segno missing: no new attempt before the next start
    return qr_cache[text]


# First setup (new box): until it is done from the phone's page ("setup" screen), the TV stays on the home screen
# with the QR code in large. Done: ~/.config/stream-box/setup-done (also created by a restore). A box that has already
# been used (history) counts as set up; stream-box.lua follows the same rule
SETUP_DONE = os.path.expanduser("~/.config/stream-box/setup-done")


def setup_done():
    if os.path.exists(SETUP_DONE):
        return True
    if os.path.exists(HISTORY_FILE):
        finish_setup(notify=False)
        return True
    return False


def finish_setup(notify=True):
    os.makedirs(os.path.dirname(SETUP_DONE), exist_ok=True)
    open(SETUP_DONE, "a").close()
    if notify:
        mpv(["script-message", "streambox-setup-done"])   # the TV moves on to the menu


def remote_qr():
    url = remote_url()
    rows = qr_rows(url)
    return {"url": url, "rows": rows} if rows else None


def ambient_loop():
    data, fetched = {}, 0
    while True:
        try:
            data["qr"] = remote_qr()   # address read again every round: a change shows right away
        except OSError:
            data["qr"] = None   # no network: no address to show
        # Setup mode (the box's Wi-Fi access point): QR code to join its network, then for the page
        try:
            w = netsetup.status()
        except (OSError, subprocess.SubprocessError):
            w = {}
        h = w.get("hotspot")
        data["first_run"] = not setup_done()
        data["setup"] = {"ssid": h["ssid"], "password": h["password"], "url": h["url"],
                         "wifi_rows": qr_rows(f"WIFI:T:WPA;S:{h['ssid']};P:{h['password']};;"),
                         "url_rows": qr_rows(h["url"]), "error": w.get("error")} if h else (
                        {"connecting": w["connecting"]} if w.get("connecting") else None)
        if time.time() - fetched > AMBIENT_FETCH:
            conf = ambient_conf()
            try:
                tz = zoneinfo.ZoneInfo(conf["timezone"])
            except (KeyError, zoneinfo.ZoneInfoNotFoundError, ValueError):
                tz = datetime.datetime.now().astimezone().tzinfo   # system time zone
            for key, fetch in (("weather", lambda: fetch_weather(conf)),
                               ("schedule", lambda: fetch_schedule(read_streamers(), tz))):
                try:
                    data[key] = fetch()
                except (OSError, ValueError, KeyError, TypeError):
                    pass   # service unreachable: keep the last value
            fetched = time.time()
        try:
            mpv(["set_property", "user-data/streambox/ambient", data])
        except OSError:
            pass
        time.sleep(PUBLISH_EVERY)


# TV menu images (tv_menu.lua): over the video, mpv only shows raw images (overlay-add, BGRA with premultiplied
# alpha). They are downloaded, cropped and converted with ffmpeg, cached in /tmp. Only from Twitch's and YouTube's
# image servers: the address comes from the request.

TV_IMAGE_DIR = "/tmp/stream-box-images"


def tv_image(src, width, height, round_, radius=0):
    """Image ready for overlay-add: round_ = disc, otherwise rounded corners of radius pixels (0: square)."""
    host = urllib.parse.urlsplit(src).hostname or ""
    jf_host = urllib.parse.urlsplit((jf_server() or {}).get("address", "")).hostname
    if not (host.endswith(".jtvnw.net") or host in ("i.ytimg.com", "clips-media-assets2.twitch.tv") or host == jf_host):
        raise ValueError(tr("image refused"))
    width, height = max(8, min(1280, width)), max(8, min(1280, height))
    radius = max(0, min(radius, width // 2, height // 2))
    key = hashlib.sha1(f"{src}|{width}|{height}|{round_}|{radius}".encode()).hexdigest()[:24]
    path = os.path.join(TV_IMAGE_DIR, f"{key}.bgra")
    if not os.path.exists(path):
        os.makedirs(TV_IMAGE_DIR, exist_ok=True)
        with urllib.request.urlopen(src, timeout=10) as r:
            data = r.read(8_000_000)
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},format=rgba"
        # Smoothed edges: disc, or rounded corners (distance to the center of the nearest corner's quarter circle).
        # Premultiplied alpha: colors follow the opacity.
        alpha = None
        if round_:
            alpha = "clip(255*(W/2+0.5-hypot(X+0.5-W/2,Y+0.5-H/2)),0,255)"
        elif radius:
            r = radius
            alpha = (f"clip(255*({r}+0.5-hypot(max(0,max({r}-X-0.5,X+0.5-W+{r})),"
                     f"max(0,max({r}-Y-0.5,Y+0.5-H+{r})))),0,255)")
        if alpha:
            vf += (f",geq=a='{alpha}'"
                   ":r='r(X,Y)*alpha(X,Y)/255':g='g(X,Y)*alpha(X,Y)/255':b='b(X,Y)*alpha(X,Y)/255'")
        tmp = f"{path}.{threading.get_ident()}.tmp"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", "pipe:0", "-vf", vf, "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "bgra", tmp], input=data, capture_output=True, timeout=30, check=True)
        os.replace(tmp, path)
    return {"path": path, "w": width, "h": height}


# TV preview for the page, only when the page asks for it (section open): the whole screen, ambient screen and
# menus included, captured by grim through cage's wlr-screencopy protocol. Without grim, mpv capture (window, with
# the chat and the menu), which has nothing to capture when no video is playing (the page then shows a text).

PREVIEW_WIDTH = 960
preview_lock = threading.Lock()
preview_cache = {"at": 0.0, "data": None}


def preview():
    """JPEG of the screen, or None when there is no image to capture."""
    with preview_lock:   # one capture at a time; several phones share the last one for 1 s
        if time.time() - preview_cache["at"] < 1:
            return preview_cache["data"]
        data = None
        playing = mpv(["get_property", "video-params"])[0] is not None
        if shutil.which("grim"):
            try:
                width = mpv(["get_property", "osd-dimensions"])[0].get("w") or PREVIEW_WIDTH
                r = subprocess.run(["grim", "-t", "jpeg", "-q", "70", "-s", f"{min(1.0, PREVIEW_WIDTH / width):.3f}", "-"],
                                   capture_output=True, timeout=10, env=display.wlr_env())
                data = r.stdout if r.returncode == 0 and r.stdout else None
            except (OSError, subprocess.SubprocessError, AttributeError):
                data = None
            if data:
                preview_cache.update(at=time.time(), data=data)
                return data
        if playing:
            shot, small = "/tmp/stream-box-shot.jpg", "/tmp/stream-box-preview.jpg"
            for path in (shot, small):
                if os.path.exists(path):
                    os.remove(path)
            mpv(["screenshot-to-file", shot, "window"])
            for _ in range(30):   # mpv writes the file after replying
                if os.path.exists(shot) and os.path.getsize(shot) > 0:
                    size = os.path.getsize(shot)
                    time.sleep(0.05)
                    if os.path.getsize(shot) == size:
                        break
                time.sleep(0.05)
            if os.path.exists(shot):
                try:
                    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", shot, "-vf", f"scale={PREVIEW_WIDTH}:-2",
                                    "-q:v", "5", small], timeout=10, check=True)
                    shot = small
                except (OSError, subprocess.SubprocessError):
                    pass   # without ffmpeg: full-size capture
                with open(shot, "rb") as f:
                    data = f.read()
        preview_cache.update(at=time.time(), data=data)
        return data


PLAYER_FILE = os.path.join(COOKIES_DIR, "player")   # "qt": Qt app embedding mpv (see player.sh)


def player_choice():
    try:
        with open(PLAYER_FILE, encoding="utf-8") as f:
            return "qt" if f.readline().strip() == "qt" else "mpv"
    except OSError:
        return "mpv"


# Action of the power button of the companion app and Home Assistant: "suspend" (sleep, wake on
# network) or "poweroff" (full shutdown, default). The TV menu has its own two lines, "Sleep" and
# "Turn off the box", which do not depend on this setting. Also read by mqtt_bridge.py.
POWER_ACTION_FILE = os.path.join(COOKIES_DIR, "power-action")


def power_action():
    try:
        with open(POWER_ACTION_FILE, encoding="utf-8") as f:
            return "suspend" if f.readline().strip() == "suspend" else "poweroff"
    except OSError:
        return "poweroff"


def set_power_action(mode):
    if mode not in ("suspend", "poweroff"):
        raise ValueError(tr("unknown action"))
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    with open(POWER_ACTION_FILE, "w", encoding="utf-8") as f:
        f.write(mode + "\n")


def power(mode):
    """"suspend" or "poweroff". Allowed without a password for media by
    /etc/polkit-1/rules.d/50-stream-box.rules (sleep is also allowed by default for an active local session)"""
    r = subprocess.run(["systemctl", "suspend" if mode == "suspend" else "poweroff"],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        error = r.stderr.strip() or r.returncode
        raise ValueError(tr("Sleep refused: {error}", error=error) if mode == "suspend"
                         else tr("Shutdown refused: {error}", error=error))


def hold_power_key():
    """Power button (Bluetooth remote, case): logind would turn the box off by itself; this lock prevents it,
    and stream-box.lua applies the "Power button" setting (sleep or full shutdown). Allowed by default in the TV's
    session (remote.py is started by start.sh); refused elsewhere, and logind then keeps its behavior."""
    subprocess.run(["pkill", "-u", str(os.getuid()), "-f", "who=Stream Box bouton power"], capture_output=True)
    subprocess.Popen(["systemd-inhibit", "--what=handle-power-key", "--mode=block", "--who=Stream Box bouton power",
                      "--why=Power button: sleep or shutdown depending on the setting", "sleep", "infinity"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def resume_loop():
    """Wake-up after sleep: the connections (streamlink, video stream) are dead and the picture would stay
    frozen. logind signals PrepareForSleep(false) on wake-up (followed by gdbus); mpv then restarts playback."""
    while True:
        try:
            mon = subprocess.Popen(["gdbus", "monitor", "--system", "--dest", "org.freedesktop.login1",
                                    "--object-path", "/org/freedesktop/login1"], stdout=subprocess.PIPE, text=True)
            for line in mon.stdout:
                if "PrepareForSleep (false" in line:
                    # Bluetooth dongle (mostly CSR clones) stuck on wake-up: the remote stays "connected" without
                    # its keys arriving. Restart it; the remote reconnects on the first key press
                    for args in (["power", "off"], ["power", "on"]):
                        try:
                            subprocess.run(["bluetoothctl", *args], capture_output=True, timeout=10)
                        except (OSError, subprocess.SubprocessError):
                            pass
                        time.sleep(2)
                    # Network back (NetworkManager resumes the connection within seconds): otherwise streamlink
                    # fails and the box thinks the streamer is offline, then retries 15 s later
                    for _ in range(60):
                        try:
                            socket.create_connection(("www.twitch.tv", 443), timeout=2).close()
                            break
                        except OSError:
                            time.sleep(1)
                    try:
                        mpv(["script-message", "streambox-resume"])
                    except OSError:
                        pass
            mon.wait()
        except OSError:
            pass
        time.sleep(5)


keyboard = {}   # TV menu search keyboard: {open, text, target, at}


def set_player(mode):
    """Player choice, applied right away: quit the player, player.sh's loop starts the right one"""
    if mode not in ("qt", "mpv"):
        raise ValueError(tr("unknown player"))
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    with open(PLAYER_FILE, "w", encoding="utf-8") as f:
        f.write(mode + "\n")
    mpv(["quit"])


# Animated background of the home screen and of the menu without video (qml/Backdrop.qml), chosen in the TV Settings: a
# background, a layer on top, the home screen colors. ~/.config/stream-box/backdrop:
# {"base", "overlay", "color"}
BACKDROP_FILE = os.path.expanduser("~/.config/stream-box/backdrop")
BACKDROP_BASES = ("none", "aurora", "fluid", "borealis")
BACKDROP_OVERLAYS = ("none", "silk", "stars")
BACKDROP_COLORS = ("violet", "blue", "green", "sunset", "pink", "ice")   # home screen (the menu follows its tabs)


def backdrop():
    b = {"base": "aurora", "overlay": "none", "color": "violet"}
    try:
        with open(BACKDROP_FILE) as f:
            raw = f.read().strip()
        saved = json.loads(raw) if raw.startswith("{") else {"base": raw}
        if saved.get("base") == "silk":   # old style that became a layer
            saved = {"base": "aurora", "overlay": saved["base"]}
        b.update({k: v for k, v in saved.items() if k in b})
    except (OSError, ValueError, AttributeError):
        pass
    if b["base"] not in BACKDROP_BASES:
        b["base"] = "aurora"
    if b["overlay"] not in BACKDROP_OVERLAYS:
        b["overlay"] = "none"
    if b["color"] not in BACKDROP_COLORS:
        b["color"] = "violet"
    return b


def set_backdrop(body):
    b = backdrop()
    for key, allowed in (("base", BACKDROP_BASES), ("overlay", BACKDROP_OVERLAYS), ("color", BACKDROP_COLORS)):
        if key in body:
            if body[key] not in allowed:
                raise ValueError(tr("unknown background"))
            b[key] = body[key]
    with open(BACKDROP_FILE, "w") as f:
        json.dump(b, f)


# SSH access (maintenance), turned on or off from the System menu: stream-box-ssh@enable|disable.service (root, polkit
# rule 54-stream-box-ssh.rules, ssh-access script), installed by the image and install.sh. On: password drawn by
# ssh-access, shown on the TV only (not to other devices on the network)
SSH_PASS_FILE = "/var/lib/stream-box/ssh-password"
SSH_UNIT = ("/usr/lib/systemd/system/stream-box-ssh@.service", "/etc/systemd/system/stream-box-ssh@.service")


def ssh_status(local=False):
    def systemctl(*args):
        return subprocess.run(["systemctl", *args, "sshd.service"], capture_output=True, text=True, timeout=10).stdout.strip()
    s = {"available": any(os.path.exists(p) for p in SSH_UNIT),
         "enabled": systemctl("is-enabled") == "enabled", "active": systemctl("is-active") == "active",
         "address": "media@" + lan_ip()}
    if local:
        try:
            with open(SSH_PASS_FILE) as f:
                s["password"] = f.read().strip()
        except OSError:
            s["password"] = None
    return s


def set_ssh(on):
    if not ssh_status()["available"]:
        raise ValueError(tr("SSH setting missing from this installation (run install.sh again)."))
    r = subprocess.run(["systemctl", "start", f"stream-box-ssh@{'enable' if on else 'disable'}.service"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise ValueError(tr("SSH: {error}", error=(r.stderr or r.stdout).strip() or r.returncode))


# Developer mode: passwordless sudo for media, and SSH (stream-box-dev@enable|disable.service, dev-mode script,
# polkit rule 55-stream-box-dev.rules). Without it, the box installed from the image has no root access
DEV_UNIT = ("/usr/lib/systemd/system/stream-box-dev@.service", "/etc/systemd/system/stream-box-dev@.service")
DEV_MARK = "/var/lib/stream-box/dev-mode"
LOCAL_ONLY = ("ssh", "dev")   # access settings: from the TV only (the menu goes through 127.0.0.1)


def dev_status():
    return {"available": any(os.path.exists(p) for p in DEV_UNIT), "enabled": os.path.exists(DEV_MARK)}


def set_dev(on):
    if not dev_status()["available"]:
        raise ValueError(tr("Developer mode missing from this installation (run install.sh again)."))
    r = subprocess.run(["systemctl", "start", f"stream-box-dev@{'enable' if on else 'disable'}.service"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise ValueError(tr("Developer mode: {error}", error=(r.stderr or r.stdout).strip() or r.returncode))


def state():
    user, volume, mute, pause, video, title, position, duration, tracks, cache, vo, path = mpv(
        ["get_property", "user-data/streambox"], ["get_property", "volume"], ["get_property", "mute"],
        ["get_property", "pause"], ["get_property", "video-params"], ["get_property", "media-title"],
        ["get_property", "time-pos"], ["get_property", "duration"], ["get_property", "track-list"],
        ["get_property", "demuxer-cache-state"], ["get_property", "current-vo"], ["get_property", "path"])
    user = user or {}
    media = user.get("mode") == "media"
    # Live: delay behind the end of what is kept in memory (0 = live)
    ranges = (cache or {}).get("seekable-ranges") or []
    delay = max(0.0, ranges[0]["end"] - position) if ranges and position is not None and not media else None
    return {
        "streamers": read_streamers(), "channel": user.get("channel"), "avatars": avatars,
        "chat_visible": user.get("chat_visible", True), "corner": user.get("corner", "bl"),
        "chat_bg": user.get("chat_bg", 60), "chat_size": user.get("chat_size", 32),
        "sub_size": user.get("sub_size", 100), "sub_bg": user.get("sub_bg", 0),
        "auto_switch": user.get("auto_switch", True), "night": user.get("night", False),
        "events": user.get("events", True), "qr": user.get("qr", "always"),
        # Chosen player, and the one actually running (mpv alone after several crashes of the Qt app)
        "backdrop": backdrop(), "first_run": not setup_done(),
        "lang": i18n.language(), "languages": i18n.LANGUAGES,
        "player": player_choice(), "player_running": "qt" if vo == "libmpv" else "mpv", "power_action": power_action(),
        "remote_url": custom_remote_url(),
        # TV menu search keyboard open (forgotten after 10 min, menu closed in the meantime)
        "keyboard": keyboard if keyboard.get("open") and time.time() - keyboard.get("at", 0) < 600 else None,
        "pip": user.get("pip") or {"channel": "", "layout": ""},
        "volume": round(volume or 0), "mute": bool(mute), "pause": bool(pause), "playing": bool(video),
        "live": live_now, "mode": user.get("mode", "twitch"), "delay": delay, "title": title if media else None,
        "position": position if media else None, "duration": duration if media else None,
        # Kind of the current video (youtube, jellyfin, twitch-vod…): the TV menu opens on the matching tab
        "media_kind": media_key(path)[1] if media and path else None,
        "subs": [{"id": t["id"], "name": t.get("title") or t.get("lang") or tr("Track {id}", id=t["id"]),
                  "selected": bool(t.get("selected"))}
                 for t in (tracks or []) if t.get("type") == "sub"] if media else [],
    }


SRT_CUE = re.compile(r"(\d+)\s*\n(\d\d:\d\d:\d\d,\d\d\d) --> (\d\d:\d\d:\d\d,\d\d\d)[^\n]*\n(.*?)(?:\n\s*\n|\Z)", re.S)


def fix_auto_subs(srt):
    """YouTube automatic subtitles: each line lasts until the start of the one after next, so that two lines are
    always shown and the old one never seems to go away. Cut each one at the start of the next."""
    def ms(t):
        h, m, rest = t.split(":")
        s, milli = rest.split(",")
        return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(milli)

    def stamp(v):
        return f"{v // 3600000:02d}:{v // 60000 % 60:02d}:{v // 1000 % 60:02d},{v % 1000:03d}"

    cues = [(ms(a), ms(b), text.strip()) for _, a, b, text in SRT_CUE.findall(srt.replace("\r\n", "\n"))]
    out = []
    for i, (start, end, text) in enumerate(cues):
        if i + 1 < len(cues):
            end = max(start + 1, min(end, cues[i + 1][0]))
        out.append(f"{i + 1}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
    return "\n".join(out)


def fetch_auto_subs(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ("www.youtube.com", "youtube.com"):
        raise ValueError(tr("only YouTube subtitles go through here"))
    with urllib.request.urlopen(url, timeout=15) as r:
        text = r.read().decode("utf-8", "replace")
    return fix_auto_subs(text) if SRT_CUE.search(text) else text


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


def find_url(*texts):
    """First http(s) link found: apps often share "title + link" in the text field. Also
    "jellyfin:ID", the link of Jellyfin videos in the history."""
    for text in texts:
        match = re.search(r"https?://\S+|\bjellyfin:[0-9a-f]{32}\b", text or "")
        if match:
            return match.group(0)
    return None


# History and resume of videos started from the companion app (links, YouTube, Twitch replays and clips,
# Jellyfin: that one keeps its own progress, the box's history only serves to find it again; link
# "jellyfin:ID", without token). Twitch replays are synced with the connected account:
# position read at start, written every 30 s. The rest is known only to the box.

HISTORY_FILE = os.path.expanduser("~/.local/state/stream-box/history.json")
HISTORY_MAX = 60
RESUME_MIN = 30         # seconds: below that, start from the beginning
FINISHED_LEFT = 30      # less than 30 s from the end, or beyond 95 %, the video is watched
TWITCH_PUSH = 30        # seconds between two position sends to Twitch
history_lock = threading.Lock()
now_playing = {}        # video started by play(), tracked by history_loop


def media_key(url):
    """(stable key, kind, identifier): the same video keeps the same key whatever the link's form."""
    m = re.fullmatch(r"jellyfin:([0-9a-f]{32})", url) or re.search(r"/Videos/([0-9a-f]{32})/", url)
    if m:
        return f"jellyfin:{m.group(1)}", "jellyfin", m.group(1)
    m = re.search(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/)|youtu\.be/)([\w-]{11})", url)
    if m:
        return f"youtube:{m.group(1)}", "youtube", m.group(1)
    m = re.search(r"twitch\.tv/videos/(\d+)", url)
    if m:
        return f"twitch-vod:{m.group(1)}", "twitch-vod", m.group(1)
    m = re.search(r"(?:clips\.twitch\.tv/|twitch\.tv/\w+/clip/)([\w-]+)", url)
    if m:
        return f"twitch-clip:{m.group(1)}", "twitch-clip", m.group(1)
    return url, "link", None


# YouTube: followed channels (the box's list, ~/.config/stream-box/youtube.json) and their latest videos through the
# public RSS feed (no API key, 15 videos), search through yt-dlp ("ytsearch"). Caches: 20 min per feed, 10 min per
# search, to query YouTube as little as possible (it quickly blocks an overly curious IP address).

YT_FILE = os.path.join(COOKIES_DIR, "youtube.json")
YT_FEED_CACHE = 1200
YT_FEED_RETRY = 600   # failed feed (address rate-limited by YouTube…): new attempt 10 min later
YT_SEARCH_CACHE = 600
yt_feeds, yt_searches = {}, {}   # channel id → (time, videos); query → (time, results)
yt_lock = threading.Lock()
YTDLP = os.path.expanduser("~/.local/bin/yt-dlp")
# YouTube JavaScript challenges: deno when installed (install.sh), otherwise the system's Node (image, without deno)
YTDLP_JS = [] if os.path.exists(os.path.expanduser("~/.local/bin/deno")) else ["--js-runtimes", "node"]


def yt_channels():
    try:
        with open(YT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def yt_resolve(raw):
    """@name, channel link or UC… identifier → {id, name, handle, avatar} (yt-dlp, one request)"""
    raw = raw.strip()
    if re.fullmatch(r"UC[\w-]{22}", raw):
        url = f"https://www.youtube.com/channel/{raw}"
    elif re.fullmatch(r"@?[\w.-]{3,40}", raw):
        url = f"https://www.youtube.com/@{raw.lstrip('@')}"
    elif re.match(r"https?://(www\.|m\.)?youtube\.com/", raw):
        url = raw.split("?")[0]
    else:
        raise ValueError(tr("Give a YouTube channel @name or the channel link."))
    r = subprocess.run([YTDLP, "--flat-playlist", "-J", "--playlist-items", "0", "--no-warnings", url],
                       capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        raise ValueError(tr("YouTube channel not found.")) from None
    if not d.get("channel_id"):
        raise ValueError(tr("YouTube channel not found."))
    avatar = next((t["url"] for t in d.get("thumbnails") or [] if "avatar" in str(t.get("id"))), None)
    return {"id": d["channel_id"], "name": d.get("channel") or d.get("uploader") or raw,
            "handle": d.get("uploader_id") or "", "avatar": avatar}


def edit_yt_channels(action, raw="", delta=0):
    with yt_lock:
        chans = yt_channels()
        if action == "add":
            # Channel from the subscriptions (UC… id): already known, no request to YouTube
            c = next((dict(x) for x in read_json_file(YT_SUBS_FILE).get("channels") or [] if x["id"] == raw), None) \
                or yt_resolve(raw)
            c.setdefault("handle", "")
            cache = read_json_file(YT_FEED_FILE)
            if (cache.get("channels") or {}).get(c["id"], {}).pop("checked", None) is not None:
                write_private_json(YT_FEED_FILE, cache)   # subscription turned favorite: 15 videos on the next round
            if any(x["id"] == c["id"] for x in chans):
                raise ValueError(tr("{login} is already in the list.", login=c["name"]))
            chans.append(c)
        elif action == "remove":
            chans = [c for c in chans if c["id"] != raw]
        elif action == "move":
            i = next((n for n, c in enumerate(chans) if c["id"] == raw), None)
            j = (i if i is not None else 0) + delta
            if i is None or not 0 <= j < len(chans):
                raise ValueError(tr("cannot move"))
            chans[i], chans[j] = chans[j], chans[i]
        else:
            raise ValueError(tr("unknown action"))
        os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
        with open(YT_FILE, "w", encoding="utf-8") as f:
            json.dump(chans, f, ensure_ascii=False)


def yt_feed(channel_id):
    cached = yt_feeds.get(channel_id)
    if cached and time.time() - cached[0] < (YT_FEED_CACHE if cached[1] is not None else YT_FEED_RETRY):
        if cached[1] is None:
            raise OSError("feed unreachable (new attempt later)")
        return cached[1]
    try:
        return yt_fetch_feed(channel_id)
    except (OSError, ValueError):
        yt_feeds[channel_id] = (time.time(), None)   # failure kept: no new attempt each time the menu opens
        raise


def yt_fetch_feed(channel_id):
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
          "m": "http://search.yahoo.com/mrss/"}
    with urllib.request.urlopen(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}", timeout=10) as r:
        root = ET.fromstring(r.read())
    videos = []
    for e in root.findall("a:entry", ns):
        vid = e.findtext("yt:videoId", namespaces=ns)
        link = (e.find("a:link", ns).get("href") if e.find("a:link", ns) is not None else "") or ""
        if not vid or "/shorts/" in link:   # Shorts (one-minute vertical videos) have no place on the TV
            continue
        stats = e.find("m:group/m:community/m:statistics", ns)
        videos.append({"id": vid, "title": e.findtext("a:title", namespaces=ns) or "",
                       "date": (e.findtext("a:published", namespaces=ns) or "")[:10],
                       "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                       "views": int(stats.get("views")) if stats is not None and stats.get("views") else None,
                       "url": f"https://www.youtube.com/watch?v={vid}"})
    yt_feeds[channel_id] = (time.time(), videos)
    return videos


def yt_meta(video_id):
    """(title, duration) of a video: Google API when the account is connected (1 unit), otherwise oEmbed (title only)"""
    try:
        token = yt_token()
        if token:
            items = yt_api("videos", token, part="snippet,contentDetails", id=video_id).get("items") or []
            if items:
                return items[0]["snippet"]["title"], iso_seconds(items[0]["contentDetails"].get("duration"))
    except (OSError, ValueError, KeyError):
        pass
    try:
        url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}")
        with urllib.request.urlopen(url, timeout=3) as r:
            return json.load(r).get("title"), None
    except (OSError, ValueError):
        return None, None


def with_progress(videos, known=None):
    """Position and "watched" from the box's history; video watched elsewhere: the YouTube account's percentage
    (percent, indicative: YouTube updates it with a delay)"""
    known = known if known is not None else {e["key"]: e for e in read_history()}
    remote = yt_tv_progress()
    out = []
    for v in videos:
        e = known.get(f"youtube:{v['id']}") or {}
        seconds = v.get("seconds") or e.get("duration")
        item = {**v, "position": e.get("position"), "seconds": seconds, "finished": bool(e.get("finished"))}
        pct = remote.get(v["id"])
        mine = 100 * e["position"] / e["duration"] if e.get("duration") else 0
        if pct and (not e or (pct > mine + 2 and not e.get("finished"))):   # watched further elsewhere: YouTube wins
            item.update(percent=pct, finished=pct >= 95,
                        position=round(pct / 100 * seconds) if seconds else None)
        out.append(item)
    return out


# YouTube account progress through the "TV app" access (cast/youtube_tv.js, 127.0.0.1:8091): the box keeps its
# positions (exact resume), sends them back to YouTube (the phone resumes where the TV stops), and shows the
# account's percentage for videos watched elsewhere.
YT_TV = "http://127.0.0.1:8091"
YT_TV_PUSH = 30   # seconds between two position sends
yt_tv_cache = {"at": 0.0, "data": {}}


def yt_tv(path, body=None, timeout=10):
    req = urllib.request.Request(YT_TV + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except (OSError, ValueError):
        return None


def yt_tv_progress():
    if time.time() - yt_tv_cache["at"] > 60:
        yt_tv_cache.update(at=time.time(), data=yt_tv("/progress", timeout=15) or {})
    return yt_tv_cache["data"]


def yt_tv_report(video_id, position, final=False):
    threading.Thread(target=yt_tv, args=("/report", {"id": video_id, "position": position, "final": final}),
                     daemon=True).start()


def yt_fav_videos(cache, channel_id):
    """Videos of a favorite from the subscriptions poll (Google API), or None when it is not there"""
    entry = (cache.get("channels") or {}).get(channel_id) or {}
    if "checked" not in entry or not read_json_file(YT_TOKEN_FILE).get("refresh_token"):
        return None
    details, out = cache.get("details") or {}, []
    for v in entry.get("videos") or []:
        det = details.get(v["id"]) or {}
        if det.get("gone") or det.get("upcoming"):
            continue
        out.append({"id": v["id"], "title": v["title"], "date": v["date"][:10], "thumb": v["thumb"], "url": v["url"],
                    "seconds": det.get("seconds"), "views": det.get("views")})
    return out


def youtube_home():
    """Favorites (one row per channel) and subscriptions. Subscribed favorites: subscriptions poll, no request to
    youtube.com; the others: RSS feeds, read in parallel (yt_feed also keeps failures)"""
    from concurrent.futures import ThreadPoolExecutor
    cache, chans = read_json_file(YT_FEED_FILE), yt_channels()
    videos = {c["id"]: yt_fav_videos(cache, c["id"]) for c in chans}
    rss = [c["id"] for c in chans if videos[c["id"]] is None]
    if rss:
        with ThreadPoolExecutor(8) as pool:
            videos.update(zip(rss, pool.map(lambda cid: yt_safe(yt_feed, cid), rss)))
    known = {e["key"]: e for e in read_history()}
    out = [{**c, "videos": with_progress(videos[c["id"]], known) if videos[c["id"]] is not None else None}
           for c in chans]   # feed unreachable: the channel stays shown, without videos
    try:
        subs = yt_subscriptions()
    except (OSError, ValueError, KeyError) as e:   # YouTube account broken: the list's channels remain
        print(f"remote.py: YouTube subscriptions: {e}", flush=True)
        subs = None
    return {"channels": out, "subs": subs}


def yt_search(query):
    """Videos and channels found: the same request returns the channels whose name matches well"""
    query = " ".join(query.split())[:100]
    if not query:
        return {"results": [], "channels": []}
    cached = yt_searches.get(query.lower())
    if cached and time.time() - cached[0] < YT_SEARCH_CACHE:
        return yt_search_out(*cached[1:])
    # lang=fr: original titles (otherwise YouTube returns its automatic English translations)
    r = subprocess.run([YTDLP, "--flat-playlist", "-J", "--no-warnings", "--extractor-args", "youtube:lang=fr",
                        f"ytsearch20:{query}"],
                       capture_output=True, text=True, timeout=60)
    try:
        entries = json.loads(r.stdout).get("entries") or []
    except ValueError:
        raise ValueError(tr("YouTube search unavailable for now.")) from None
    results, channels = [], []
    for e in entries:
        if re.fullmatch(r"UC[\w-]{22}", e.get("id") or ""):
            thumbs = [t.get("url") or "" for t in e.get("thumbnails") or []]
            avatar = thumbs[-1] if thumbs else ""
            channels.append({"id": e["id"], "name": e.get("title") or e.get("channel") or "",
                             "handle": e.get("uploader_id") or "", "followers": e.get("channel_follower_count"),
                             "avatar": "https:" + avatar if avatar.startswith("//") else avatar or None})
            continue
        # Otherwise videos only (playlists, with longer identifiers, are left out)
        if not re.fullmatch(r"[\w-]{11}", e.get("id") or "") or e.get("live_status") == "is_upcoming":
            continue
        results.append({"id": e["id"], "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
                        "seconds": e.get("duration"), "views": e.get("view_count"),
                        "thumb": f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg",
                        "url": f"https://www.youtube.com/watch?v={e['id']}"})
    yt_searches[query.lower()] = (time.time(), results, channels)
    return yt_search_out(results, channels)


def yt_search_out(results, channels):
    saved = {c["id"] for c in yt_channels()}
    return {"results": with_progress(results), "channels": [{**c, "saved": c["id"] in saved} for c in channels]}


def yt_channel_videos(channel_id):
    """Latest videos of a channel found by the search, whether it is in the list or not"""
    if not re.fullmatch(r"UC[\w-]{22}", channel_id):
        raise ValueError(tr("invalid channel"))
    try:
        videos = with_progress(yt_feed(channel_id))
    except OSError:
        raise ValueError(tr("YouTube unreachable for now.")) from None
    return {"id": channel_id, "videos": videos, "saved": any(c["id"] == channel_id for c in yt_channels())}


# Jellyfin: library of the server already paired with jellyfin-mpv-shim ("Play on…"), with its credentials
# (~/.config/jellyfin-mpv-shim/users.json: address, UserId, AccessToken; nothing more to configure). The box reads
# "Continue watching", "Next up", recent additions per library, searches, and reports progress to the
# server during playback (Sessions/Playing, /Progress, /Stopped): "watched" and resume follow everywhere.

JF_USERS = os.path.expanduser("~/.config/jellyfin-mpv-shim/users.json")
JF_CACHE = 30
jf_cache = {}


def jf_server():
    try:
        with open(JF_USERS, encoding="utf-8") as f:
            d = json.load(f)
        users = d["users"]
        s = next((u for u in users if u.get("id") == d.get("active")), users[0])["credentials"][0]
        return {"address": s["address"].rstrip("/"), "user": s["UserId"], "token": s["AccessToken"], "name": s.get("Name") or ""}
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def jf_api(path, body=None, params=None):
    srv = jf_server()
    if not srv:
        raise ValueError(tr("Jellyfin is not paired with the box."))
    url = srv["address"] + path.replace("{user}", srv["user"])
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f'MediaBrowser Token="{srv["token"]}"',
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = r.read()
    return json.loads(data) if data else None


def jf_item(i):
    """Jellyfin item → card: title, info line, landscape image, duration, position, watched"""
    srv = jf_server() or {"address": ""}
    img = lambda item_id, kind: f"{srv['address']}/Items/{item_id}/Images/{kind}?fillWidth=480&quality=85"
    kind, tags = i.get("Type"), i.get("ImageTags") or {}
    if kind == "Episode" and tags.get("Primary"):
        thumb = img(i["Id"], "Primary")
    elif tags.get("Thumb"):
        thumb = img(i["Id"], "Thumb")
    elif i.get("BackdropImageTags"):
        thumb = img(i["Id"], "Backdrop/0")
    elif i.get("ParentThumbItemId"):
        thumb = img(i["ParentThumbItemId"], "Thumb")
    elif i.get("ParentBackdropItemId"):
        thumb = img(i["ParentBackdropItemId"], "Backdrop/0")
    else:
        thumb = img(i["Id"], "Primary")
    ud = i.get("UserData") or {}
    out = {"id": i["Id"], "type": kind, "title": i.get("Name") or "", "thumb": thumb,
           "seconds": int((i.get("RunTimeTicks") or 0) / 1e7) or None,
           "position": int((ud.get("PlaybackPositionTicks") or 0) / 1e7), "finished": bool(ud.get("Played")),
           "year": i.get("ProductionYear")}
    if kind == "Episode":
        out["title"] = i.get("SeriesName") or out["title"]
        out["episode"] = (f"S{i.get('ParentIndexNumber') or 0}·E{i.get('IndexNumber') or 0} · " if i.get("IndexNumber") else "") + (i.get("Name") or "")
        out["series"] = i.get("SeriesId")
    elif kind == "Season":   # recent additions of a series, grouped by season
        out.update(title=i.get("SeriesName") or out["title"], episode=i.get("Name") or "", series=i.get("SeriesId"))
    elif kind == "Series":
        out.update(series=i["Id"], unplayed=ud.get("UnplayedItemCount"))
    return out


JF_FIELDS = {"Fields": "UserData,RunTimeTicks,ProductionYear", "EnableImageTypes": "Primary,Thumb,Backdrop"}


def jellyfin_home():
    cached = jf_cache.get("home")
    if cached and time.time() - cached[0] < JF_CACHE:
        return cached[1]
    srv = jf_server()
    if not srv:
        return {"configured": False}
    resume = jf_api("/Users/{user}/Items/Resume", params={"Limit": 16, "MediaTypes": "Video", **JF_FIELDS})["Items"]
    nextup = jf_api("/Shows/NextUp", params={"UserId": srv["user"], "Limit": 16, **JF_FIELDS})["Items"]
    libraries = []
    for v in jf_api("/Users/{user}/Views")["Items"]:
        if v.get("CollectionType") not in ("movies", "tvshows", "homevideos", None):
            continue
        latest = jf_api("/Users/{user}/Items/Latest", params={"ParentId": v["Id"], "Limit": 16, **JF_FIELDS})
        libraries.append({"id": v["Id"], "name": v.get("Name") or "", "items": [jf_item(i) for i in latest]})
    home = {"configured": True, "server": srv["name"], "resume": [jf_item(i) for i in resume],
            "nextup": [jf_item(i) for i in nextup], "libraries": libraries}
    jf_cache["home"] = (time.time(), home)
    return home


def jellyfin_search(query):
    query = " ".join(query.split())[:100]
    if not query:
        return []
    items = jf_api("/Users/{user}/Items", params={"searchTerm": query, "IncludeItemTypes": "Movie,Series,Episode",
                                                  "Recursive": "true", "Limit": 30, **JF_FIELDS})["Items"]
    return [jf_item(i) for i in items]


def jellyfin_series(series_id):
    """Episodes of a series, and the index of the first one not yet watched (where to put the focus)"""
    if not re.fullmatch(r"[0-9a-f]{32}", series_id):
        raise ValueError(tr("invalid series"))
    srv = jf_server()
    eps = [jf_item(i) for i in jf_api(f"/Shows/{series_id}/Episodes", params={"UserId": srv["user"], **JF_FIELDS})["Items"]]
    first = next((n for n, e in enumerate(eps) if not e["finished"]), 0)
    return {"id": series_id, "episodes": eps, "first": first}


def jellyfin_play(item_id, from_start=False):
    if not re.fullmatch(r"[0-9a-f]{32}", item_id):
        raise ValueError(tr("invalid item"))
    srv = jf_server()
    raw = jf_api(f"/Users/{{user}}/Items/{item_id}")
    i = jf_item(raw)
    if i["type"] == "Series":
        raise ValueError(tr("Pick an episode."))
    title = f"{i['title']} · {i['episode']}" if i.get("episode") else i["title"]
    start = 0 if from_start or i["position"] < RESUME_MIN or i["finished"] else i["position"]
    url = f"{srv['address']}/Videos/{item_id}/stream?static=true&api_key={srv['token']}"
    now_playing.clear()
    now_playing.update(key=f"jellyfin:{item_id}", url=url, link=f"jellyfin:{item_id}", kind="jellyfin", ident=item_id,
                       title=title, thumb=i["thumb"], position=start)
    mpv(["script-message", "streambox-play", url, str(start), title, i["thumb"] or ""])
    mpv(["set_property", "user-data/streambox/storyboard", {}])
    # Seek bar and pause screen: series, episode, year, overview; next episode for the end card
    mpv(["set_property", "user-data/streambox/meta",
         {"source": "jellyfin", "series": raw.get("SeriesName") or "", "episode": i.get("episode") or "",
          "year": raw.get("ProductionYear") or "", "rating": raw.get("CommunityRating") or 0,
          "overview": (raw.get("Overview") or "")[:3000], "thumb": i.get("thumb") or ""}])
    nxt = {}
    if i["type"] == "Episode" and raw.get("SeriesId"):
        try:
            eps = jf_api(f"/Shows/{raw['SeriesId']}/Episodes",
                         params={"UserId": srv["user"], "AdjacentTo": item_id, **JF_FIELDS})["Items"]
            ids = [e["Id"] for e in eps]
            if item_id in ids and ids.index(item_id) + 1 < len(eps):
                n = jf_item(eps[ids.index(item_id) + 1])
                nxt = {"id": n["id"], "of": item_id, "title": n["title"], "episode": n.get("episode") or "", "thumb": n["thumb"]}
        except (OSError, ValueError, KeyError):
            pass
    mpv(["set_property", "user-data/streambox/next_up", nxt])
    jf_cache.pop("home", None)
    record(dict(now_playing), start, i["seconds"])
    jf_report("", item_id, start)
    # Separate subtitles (.srt… files next to the video): missing from the direct stream, added to mpv once the video
    # is open; those embedded in the file are already there
    source = (raw.get("MediaSources") or [{}])[0]
    external = [m for m in source.get("MediaStreams") or [] if m.get("Type") == "Subtitle" and m.get("IsExternal")]
    if external:
        threading.Thread(target=jf_add_subtitles, args=(url, item_id, source["Id"], external, srv), daemon=True).start()


def jf_add_subtitles(url, item_id, source_id, streams, srv):
    for _ in range(30):   # up to 15 s for the video to open
        time.sleep(0.5)
        try:
            path, loaded = mpv(["get_property", "path"], ["get_property", "duration"])
        except (OSError, ValueError):
            continue
        if path == url and loaded:
            break
    else:
        return
    for m in streams:
        ext = "ass" if m.get("Codec") in ("ass", "ssa") else "srt"
        sub = f"{srv['address']}/Videos/{item_id}/{source_id}/Subtitles/{m['Index']}/Stream.{ext}?api_key={srv['token']}"
        try:
            mpv(["sub-add", sub, "auto", m.get("Title") or m.get("DisplayTitle") or "", m.get("Language") or ""])
        except (OSError, ValueError):
            pass


def jf_report(what, item_id, position, paused=False):
    """Progress to the server: what = "" (start), "/Progress" or "/Stopped" """
    try:
        jf_api(f"/Sessions/Playing{what}", {"ItemId": item_id, "PositionTicks": int(position * 1e7), "IsPaused": paused,
                                            "CanSeek": True, "PlayMethod": "DirectStream"})
    except (OSError, ValueError):
        pass
    if what == "/Stopped":
        jf_cache.pop("home", None)


def finished(position, duration):
    return bool(duration) and (position >= duration - FINISHED_LEFT or position >= 0.95 * duration)


def read_history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def write_history(entries):
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries[:HISTORY_MAX], f, ensure_ascii=False)
    os.replace(tmp, HISTORY_FILE)


def record(video, position, duration, title=None):
    """Puts the video at the top of the history with its position."""
    with history_lock:
        entries = [e for e in read_history() if e["key"] != video["key"]]
        entry = {"key": video["key"], "url": video.get("link") or video["url"], "kind": video["kind"],
                 "title": title or video.get("title") or video["url"], "thumb": video.get("thumb"),
                 "position": int(position or 0), "duration": int(duration or 0), "updated": time.time()}
        entry["finished"] = finished(entry["position"], entry["duration"])
        write_history([entry] + entries)


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


# YouTube video preview on the seek bar (Qt app): thumbnail sheet ("storyboard") given by yt-dlp, published in
# user-data/streambox/storyboard. Each image of the sheet is a rows × columns grid of thumbnails covering "duration"
# seconds.

def fetch_storyboard(url, ident):
    try:
        r = subprocess.run([YTDLP, *YTDLP_JS, "-J", "--no-warnings", "--skip-download",
                            "--no-playlist", url], capture_output=True, text=True, timeout=90)
        info = json.loads(r.stdout or "{}")
        if now_playing.get("ident") == ident:   # info for the seek bar and the pause screen
            d = info.get("upload_date") or ""
            mpv(["set_property", "user-data/streambox/meta",
                 {"source": "youtube", "channel": info.get("channel") or info.get("uploader") or "",
                  "date": f"{d[6:8]}/{d[4:6]}/{d[:4]}" if len(d) == 8 else "",
                  "views": info.get("view_count") or 0, "overview": (info.get("description") or "")[:3000],
                  "thumb": info.get("thumbnail") or ""}])
        boards = [f for f in info.get("formats") or [] if f.get("format_note") == "storyboard" and f.get("fragments")]
        if not boards:
            return
        b = max(boards, key=lambda f: f.get("width") or 0)
        board = {"id": ident, "width": b["width"], "height": b["height"], "rows": b.get("rows") or 1,
                 "columns": b.get("columns") or 1,
                 "fragments": [{"url": f["url"], "duration": f.get("duration") or 0} for f in b["fragments"]]}
        if now_playing.get("ident") == ident:   # still the same video
            mpv(["set_property", "user-data/streambox/storyboard", board])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        pass


def play(url, from_start=False, title=None, thumb=None, at=None):
    """title, thumb: known by the page or menu starting the video (loading screen, history);
    at: forced position (cast from the YouTube app), otherwise resume from the history"""
    if re.fullmatch(r"jellyfin:[0-9a-f]{32}", url or ""):   # from the history
        return jellyfin_play(url.split(":")[1], from_start)
    if not url or not re.match(r"https?://", url):
        raise ValueError(tr("This is not an http(s) link."))
    key, kind, ident = media_key(url)
    entry = next((e for e in read_history() if e["key"] == key), None) or {}
    video = {"key": key, "url": url, "kind": kind, "ident": ident, "title": entry.get("title") or title,
             "thumb": entry.get("thumb") or thumb or (f"https://i.ytimg.com/vi/{ident}/mqdefault.jpg" if kind == "youtube" else None)}
    position, updated, duration = entry.get("position", 0), entry.get("updated", 0), entry.get("duration", 0)
    if kind == "youtube" and not video["title"]:   # video cast from the YouTube app: only its identifier is known
        video["title"], duration = yt_meta(ident)
        duration = duration or 0
    if kind == "youtube" and not from_start and at is None:
        # Watched further elsewhere (phone…): resume at the account's percentage, if beyond the box's position
        pct = yt_tv_progress().get(ident) or 0
        if 3 <= pct and (not duration or pct / 100 * duration > position + 30):
            duration = duration or yt_meta(ident)[1] or 0
            position = int(pct / 100 * duration)
    try:   # Twitch: title, thumbnail, duration and position saved on the account
        if kind == "twitch-vod":
            v = twitch_gql("query($id:ID!){video(id:$id){title lengthSeconds previewThumbnailURL(width:320,height:180) "
                           "self{viewingHistory{position updatedAt}}}}", {"id": ident}).get("video") or {}
            video.update(title=v.get("title") or video["title"], thumb=v.get("previewThumbnailURL") or video["thumb"])
            duration = v.get("lengthSeconds") or duration
            seen = (v.get("self") or {}).get("viewingHistory") or {}
            if seen.get("updatedAt"):
                at = datetime.datetime.fromisoformat(seen["updatedAt"].replace("Z", "+00:00")).timestamp()
                if at > updated:   # watched more recently elsewhere (site, app) than on the box
                    position = seen.get("position") or 0
        elif kind == "twitch-clip":
            c = twitch_gql("query($s:ID!){clip(slug:$s){title durationSeconds thumbnailURL}}", {"s": ident}).get("clip") or {}
            video.update(title=c.get("title") or video["title"], thumb=c.get("thumbnailURL") or video["thumb"])
            duration = c.get("durationSeconds") or duration
    except (OSError, ValueError, KeyError):
        pass   # Twitch unreachable: make do with the box's history
    start = 0 if from_start or position < RESUME_MIN or finished(position, duration) else int(position)
    if at is not None:
        start = max(0, int(at))
    now_playing.clear()
    now_playing.update(video, pushed=0.0, position=start)
    mpv(["script-message", "streambox-play", url, str(start), "", video.get("thumb") or "", video.get("title") or ""])
    record(video, start, duration)
    mpv(["set_property", "user-data/streambox/storyboard", {}])
    mpv(["set_property", "user-data/streambox/meta", {}])
    mpv(["set_property", "user-data/streambox/next_up", {}])
    if kind == "youtube":
        threading.Thread(target=fetch_storyboard, args=(url, ident), daemon=True).start()


shim_items = {}   # Jellyfin identifier → card (title, image), for the history of the shim's playbacks


def shim_video():
    """Jellyfin video started by jellyfin-mpv-shim ("Play on…" from a Jellyfin app), from the link being
    played; None otherwise"""
    try:
        user, path = mpv(["get_property", "user-data/streambox"], ["get_property", "path"])
    except (OSError, ValueError):
        return None
    srv = jf_server()
    if (user or {}).get("mode") != "media" or not srv or not str(path or "").startswith(srv["address"]):
        return None
    key, kind, ident = media_key(path)
    if kind != "jellyfin":
        return None
    if ident not in shim_items:
        try:
            shim_items[ident] = jf_item(jf_api(f"/Users/{{user}}/Items/{ident}"))
        except (OSError, ValueError, KeyError):
            return None
    i = shim_items[ident]
    return {"key": key, "url": path, "link": key, "kind": kind, "ident": ident, "shim": True, "thumb": i["thumb"],
            "title": f"{i['title']} · {i['episode']}" if i.get("episode") else i["title"]}


def history_loop():
    """Every 10 s, records the position of the video started by play(); sends it to Twitch for a replay."""
    while True:
        time.sleep(10)
        video = dict(now_playing) or shim_video()
        if not video:
            continue
        try:
            user, path, position, duration, title = mpv(
                ["get_property", "user-data/streambox"], ["get_property", "path"], ["get_property", "time-pos"],
                ["get_property", "duration"], ["get_property", "media-title"])
        except (OSError, ValueError):
            continue
        playing = (user or {}).get("mode") == "media" and path == video["url"]
        if video.get("shim"):   # started by "Play on…": the shim reports to the server, the box records the history
            if playing and isinstance(position, (int, float)):
                record(video, position, duration)
            continue
        if video["kind"] == "jellyfin":
            if playing and isinstance(position, (int, float)):
                paused = mpv(["get_property", "pause"])[0]
                jf_report("/Progress", video["ident"], position, bool(paused))
                record(video, position, duration)
                now_playing["position"] = position
            elif not playing:
                jf_report("/Stopped", video["ident"], video.get("position") or 0)
                if now_playing.get("key") == video["key"]:
                    now_playing.clear()
            continue
        if playing and isinstance(position, (int, float)):
            record(video, position, duration, title if title and title != video["url"] else None)
            now_playing["position"] = position
            if video["kind"] == "twitch-vod" and time.time() - video["pushed"] >= TWITCH_PUSH:
                try:
                    twitch_save_position(video["ident"], position)
                    now_playing["pushed"] = time.time()
                except (OSError, ValueError, KeyError):
                    pass
            if video["kind"] == "youtube" and time.time() - video["pushed"] >= YT_TV_PUSH:
                yt_tv_report(video["ident"], position)
                now_playing["pushed"] = time.time()
        elif not playing:   # video finished or replaced: last position sent to Twitch
            if video["kind"] == "twitch-vod" and video.get("position"):
                try:
                    twitch_save_position(video["ident"], video["position"])
                except (OSError, ValueError, KeyError):
                    pass
            if video["kind"] == "youtube" and video.get("position"):
                yt_tv_report(video["ident"], video["position"], final=True)
            if now_playing.get("key") == video["key"]:
                now_playing.clear()


def edit_history(action, key=""):
    with history_lock:
        entries = read_history()
        if action == "remove":
            entries = [e for e in entries if e["key"] != key]
        elif action == "clear":
            entries = []
        else:
            raise ValueError(tr("unknown action"))
        write_history(entries)


# Followed channels (Following tab of the TV menu). Twitch refuses this list to the site's token (GQL: "service error",
# Helix: the user:read:follows scope is missing): you need your own Twitch app (dev.twitch.tv), of type Public (no
# secret) or Confidential (with secret), and a code authorization ("device code flow"): the TV or the page
# show a code to type on twitch.tv/activate. Config in twitch-app.json ({"client_id", "client_secret"?}),
# tokens in twitch-follows-token.json, both 600 in ~/.config/stream-box.

TWITCH_APP_FILE = os.path.join(COOKIES_DIR, "twitch-app.json")
FOLLOWS_TOKEN_FILE = os.path.join(COOKIES_DIR, "twitch-follows-token.json")
FOLLOWS_SCOPE = "user:read:follows"
FOLLOWS_CACHE = 60   # seconds between two polls of the list
follows_lock = threading.Lock()
follows_pending = {}           # authorization in progress: user_code, verification_uri, expires_at, error
follows_cache = {"at": 0.0, "data": None}


def read_json_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_private_json(path, data):
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


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
        raise ValueError(tr("no Twitch app configured"))
    fields = {"client_id": app["client_id"]}
    if app.get("client_secret"):
        fields["client_secret"] = app["client_secret"]
    return fields


def save_follows_token(d):
    write_private_json(FOLLOWS_TOKEN_FILE, {"access_token": d["access_token"], "refresh_token": d.get("refresh_token"),
                                            "expires_at": time.time() + int(d.get("expires_in") or 3600)})


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
        raise ValueError(tr("Twitch rejects the app: {error} (check the Client ID)", error=d.get("message") or code))
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
        code, d = twitch_oauth("token", {**app_fields(), "grant_type": "refresh_token",
                                         "refresh_token": tok["refresh_token"]})
        if code != 200 or not d.get("access_token"):
            if code in (400, 401):   # authorization revoked on Twitch: it will have to be redone
                os.remove(FOLLOWS_TOKEN_FILE)
            return None
        save_follows_token(d)
        tok = read_json_file(FOLLOWS_TOKEN_FILE)
    return tok["access_token"]


def helix(path, token):
    req = urllib.request.Request(f"https://api.twitch.tv/helix/{path}",
                                 headers={"Client-Id": app_fields()["client_id"], "Authorization": f"Bearer {token}"})
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
    """State for the page and the menu: app configured, authorization in progress, list."""
    app = read_json_file(TWITCH_APP_FILE)
    out = {"configured": bool(app.get("client_id")), "confidential": bool(app.get("client_secret")),
           "authorized": False, "pending": None, "live": [], "offline": []}
    with follows_lock:
        if follows_pending and follows_pending.get("expires_at", 0) > time.time():
            out["pending"] = {k: follows_pending.get(k) for k in ("user_code", "verification_uri", "error")}
    if not out["configured"]:
        return out
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
    client_id = client_id.strip()
    if not re.fullmatch(r"[a-z0-9]{20,40}", client_id):
        raise ValueError(tr("This is not a Twitch Client ID (30 letters and digits)."))
    app = {"client_id": client_id}
    if client_secret.strip():
        app["client_secret"] = client_secret.strip()
    write_private_json(TWITCH_APP_FILE, app)
    for path in (FOLLOWS_TOKEN_FILE,):   # new app: the old authorization no longer applies
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    with follows_lock:
        follows_pending.clear()
        follows_cache.update(at=0.0, data=None)


def follows_logout():
    try:
        os.remove(FOLLOWS_TOKEN_FILE)
    except FileNotFoundError:
        pass
    with follows_lock:
        follows_cache.update(at=0.0, data=None)


# YouTube account ("Subscriptions" row of the YouTube tab): your own Google app (console.cloud.google.com, YouTube
# Data API v3, "TVs and Limited Input devices" client), code authorization on google.com/device, read-only. Config in
# youtube-app.json ({"client_id", "client_secret"}), tokens in youtube-token.json, subscription list in
# youtube-subs.json, 600 in ~/.config/stream-box. Everything goes through the Google API (googleapis.com), not
# youtube.com: nothing is added to the requests that get the box's IP address rate-limited. API quota: 10,000
# units per day; subscriptions read once a day (1 unit per 50), then per channel 1 unit for its latest
# videos ("UULF…" playlist: videos without Shorts) and 1 unit per 50 videos for durations and views. Each channel is
# read again at its own pace (YT_CHANNEL_RHYTHM, from the age of its latest video: every hour if it posted in the
# last two days, once a day if it has been quiet for a month), by a round every minute in the
# background (yt_subfeed_loop); polls kept in youtube-subfeed.json (nothing to redo on restart), units
# counted so as not to exceed YT_DAILY_BUDGET per day. The tab opens on the latest feed.

YT_APP_FILE = os.path.join(COOKIES_DIR, "youtube-app.json")
YT_TOKEN_FILE = os.path.join(COOKIES_DIR, "youtube-token.json")
YT_SUBS_FILE = os.path.join(COOKIES_DIR, "youtube-subs.json")
YT_FEED_FILE = os.path.join(COOKIES_DIR, "youtube-subfeed.json")
YT_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YT_SUBS_EVERY = 86400
YT_CHANNEL_RHYTHM = ((2 * 86400, 3600), (7 * 86400, 3 * 3600), (30 * 86400, 12 * 3600))   # (age of the latest video, re-read)
YT_DAILY_BUDGET = 7000   # out of the quota's 10,000: margin for "Reload my subscriptions" and tests
YT_SUBFEED_PER_CHANNEL = 4
YT_SUBFEED_MAX = 60
YT_FAV_VIDEOS = 15
yt_account_lock = threading.Lock()
yt_pending = {}                # authorization in progress: user_code, verification_uri, expires_at, error
yt_subfeed = {"at": 0.0, "videos": None, "refreshing": False}
yt_units = {"day": "", "used": 0}  # API quota units spent today


def google_oauth(path, fields):
    """POST to oauth2.googleapis.com; returns (HTTP code, JSON reply)."""
    req = urllib.request.Request(f"https://oauth2.googleapis.com/{path}", data=urllib.parse.urlencode(fields).encode())
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {}


def yt_app():
    app = read_json_file(YT_APP_FILE)
    if not app.get("client_id") or not app.get("client_secret"):
        raise ValueError(tr("no Google app configured"))
    return app


def save_yt_token(d, refresh_token=None):
    write_private_json(YT_TOKEN_FILE, {"access_token": d["access_token"],
                                       "refresh_token": d.get("refresh_token") or refresh_token,
                                       "expires_at": time.time() + int(d.get("expires_in") or 3600)})


def yt_poll(device_code, interval, expires_at):
    """Waits for the user to type the code on google.com/device (separate thread)."""
    while time.time() < expires_at:
        time.sleep(interval)
        try:
            app = yt_app()
            code, d = google_oauth("token", {"client_id": app["client_id"], "client_secret": app["client_secret"],
                                             "device_code": device_code,
                                             "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        except (OSError, ValueError):
            continue
        if code == 200 and d.get("access_token"):
            save_yt_token(d)
            with yt_account_lock:
                yt_pending.clear()
            yt_reset_subs(everything=True)   # maybe another account
            return
        error = d.get("error", "")
        if error == "slow_down":
            interval += 5
        elif error != "authorization_pending":
            with yt_account_lock:
                yt_pending.update(error=tr("access denied") if error == "access_denied"
                                  else error or tr("refused by Google ({code})", code=code))
            return
    with yt_account_lock:
        yt_pending.update(error=tr("code expired"))


def yt_login():
    app = yt_app()
    code, d = google_oauth("device/code", {"client_id": app["client_id"], "scope": YT_SCOPE})
    if code != 200 or not d.get("device_code"):
        raise ValueError(tr("Google rejects the app: {error} (check the client ID and its type "
                            "\"TVs and Limited Input devices\")",
                            error=d.get("error_description") or d.get("error") or code))
    expires_at = time.time() + int(d.get("expires_in") or 1800)
    with yt_account_lock:
        yt_pending.clear()
        yt_pending.update(user_code=d["user_code"], verification_uri=d.get("verification_url") or d.get("verification_uri"),
                          expires_at=expires_at)
    threading.Thread(target=yt_poll, args=(d["device_code"], int(d.get("interval") or 5), expires_at),
                     daemon=True).start()


def yt_token():
    """Valid token for the YouTube API, renewed if needed; None when the box is not authorized."""
    tok = read_json_file(YT_TOKEN_FILE)
    if not tok.get("access_token"):
        return None
    if time.time() > tok.get("expires_at", 0) - 120:
        if not tok.get("refresh_token"):
            return None
        app = yt_app()
        code, d = google_oauth("token", {"client_id": app["client_id"], "client_secret": app["client_secret"],
                                         "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
        if code != 200 or not d.get("access_token"):
            if code in (400, 401):   # authorization revoked on the Google account: it will have to be redone
                os.remove(YT_TOKEN_FILE)
            return None
        save_yt_token(d, tok["refresh_token"])
        tok = read_json_file(YT_TOKEN_FILE)
    return tok["access_token"]


def yt_api(path, token, **params):
    yt_count_units()
    req = urllib.request.Request(f"https://www.googleapis.com/youtube/v3/{path}?{urllib.parse.urlencode(params)}",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def yt_fetch_subs(token):
    """The account's subscribed channels: [{id, name, avatar}] (up to 1000)"""
    subs, page = [], None
    for _ in range(20):
        d = yt_api("subscriptions", token, part="snippet", mine="true", maxResults=50, order="alphabetical",
                   **({"pageToken": page} if page else {}))
        for it in d.get("items", []):
            sn = it.get("snippet") or {}
            cid = (sn.get("resourceId") or {}).get("channelId")
            if cid:
                thumbs = sn.get("thumbnails") or {}
                subs.append({"id": cid, "name": sn.get("title") or cid,
                             "avatar": (thumbs.get("medium") or thumbs.get("default") or {}).get("url")})
        page = d.get("nextPageToken")
        if not page:
            break
    write_private_json(YT_SUBS_FILE, {"at": time.time(), "channels": subs})
    return subs


def iso_seconds(text):
    """"PT1H2M3S" → 3723"""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def yt_channel_uploads(channel, token, count=YT_SUBFEED_PER_CHANNEL):
    for prefix in ("UULF", "UU"):   # UULF: long videos only (no Shorts or lives); UU: everything, as a fallback
        try:
            d = yt_api("playlistItems", token, part="snippet,contentDetails", maxResults=count,
                       playlistId=prefix + channel["id"][2:])
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
        out = []
        for it in d.get("items", []):
            sn, cd = it.get("snippet") or {}, it.get("contentDetails") or {}
            vid = cd.get("videoId")
            if vid:
                out.append({"id": vid, "title": sn.get("title") or "", "channel": channel["name"],
                            "channel_id": channel["id"], "avatar": channel.get("avatar"),
                            "date": cd.get("videoPublishedAt") or sn.get("publishedAt") or "",
                            "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                            "url": f"https://www.youtube.com/watch?v={vid}"})
        return out
    return []


def yt_quota_day():
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - 8 * 3600))   # the quota resets at midnight, Pacific time


def yt_count_units(n=1):
    with yt_account_lock:
        if yt_units["day"] != yt_quota_day():
            yt_units.update(day=yt_quota_day(), used=0)
        yt_units["used"] += n


def yt_channel_every(entry):
    """Re-read pace of a channel from its latest video: often if it posts often"""
    if not entry or "checked" not in entry:
        return 0
    dates = [v["date"] for v in entry.get("videos") or [] if v.get("date")]
    if not dates:
        return 86400
    try:
        age = time.time() - calendar.timegm(time.strptime(max(dates)[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return 86400
    for limit, every in YT_CHANNEL_RHYTHM:
        if age < limit:
            return every
    return 86400


def yt_build_feed(cache, token):
    """The 60 most recent videos from the read channels; durations and views read again at most every hour (also
    for the favorites' videos, served by yt_fav_videos)"""
    details = cache.setdefault("details", {})
    candidates = sorted((v for e in cache["channels"].values() for v in (e.get("videos") or [])[:YT_SUBFEED_PER_CHANNEL]),
                        key=lambda v: v["date"], reverse=True)[:YT_SUBFEED_MAX + 20]   # margin: upcoming lives left out
    favs = [v for c in yt_channels() for v in (cache["channels"].get(c["id"]) or {}).get("videos") or []]
    if token:
        stale = [v["id"] for v in candidates + favs if time.time() - (details.get(v["id"]) or {}).get("at", 0) > 3600]
        for i in range(0, len(stale), 50):
            ids = stale[i:i + 50]
            d = yt_api("videos", token, part="snippet,contentDetails,statistics", id=",".join(ids), maxResults=50)
            found = {it["id"]: it for it in d.get("items", [])}
            for vid in ids:
                it = found.get(vid)
                views = ((it or {}).get("statistics") or {}).get("viewCount")
                details[vid] = {"at": time.time(), "gone": it is None,
                                "upcoming": ((it or {}).get("snippet") or {}).get("liveBroadcastContent") == "upcoming",
                                "seconds": iso_seconds(((it or {}).get("contentDetails") or {}).get("duration")),
                                "views": int(views) if views else None}
    keep = {v["id"] for v in candidates + favs}
    cache["details"] = {k: v for k, v in details.items() if k in keep}
    out = []
    for v in candidates:
        det = details.get(v["id"]) or {}
        if det.get("gone") or det.get("upcoming"):
            continue   # deleted, private, or live not started yet
        out.append({**v, "date": v["date"][:10], "seconds": det.get("seconds"), "views": det.get("views")})
    return out[:YT_SUBFEED_MAX]


def yt_refresh_subfeed():
    """Reads the channels whose turn it is (yt_channel_every), then rebuilds the feed if something changed"""
    from concurrent.futures import ThreadPoolExecutor
    try:
        token = yt_token()
        if not token:
            return
        cache = read_json_file(YT_FEED_FILE)
        cache.setdefault("channels", {})
        with yt_account_lock:   # units already spent today before a restart
            saved = cache.get("units") or {}
            if not yt_units["day"] and saved.get("day") == yt_quota_day():
                yt_units.update(saved)
        listed = read_json_file(YT_SUBS_FILE)
        subs = listed.get("channels")
        if subs is None or time.time() - listed.get("at", 0) > YT_SUBS_EVERY:
            subs = yt_fetch_subs(token)
        cache["channels"] = {c["id"]: cache["channels"].get(c["id"], {}) for c in subs}   # unsubscribed channels forgotten
        favs = {c["id"] for c in yt_channels()}   # favorites: 15 videos for their row (same cost)
        due = [c for c in subs if time.time() - cache["channels"][c["id"]].get("checked", 0) >= yt_channel_every(cache["channels"][c["id"]])
               or (c["id"] in favs and cache["channels"][c["id"]].get("count", 0) < YT_FAV_VIDEOS)]
        with yt_account_lock:
            left = YT_DAILY_BUDGET - (yt_units["used"] if yt_units["day"] == yt_quota_day() else 0)
        due = due[:max(0, left - 10)]   # today's quota nearly used up: the rest waits until tomorrow
        if due:
            with ThreadPoolExecutor(16) as pool:
                lists = list(pool.map(lambda c: yt_safe(yt_channel_uploads, c, token,
                                                        YT_FAV_VIDEOS if c["id"] in favs else YT_SUBFEED_PER_CHANNEL), due))
            for c, videos in zip(due, lists):
                entry = cache["channels"][c["id"]]
                entry["checked"] = time.time()
                entry["count"] = YT_FAV_VIDEOS if c["id"] in favs else YT_SUBFEED_PER_CHANNEL
                if videos is not None:   # unreachable: the old poll stays, new attempt on the next round
                    entry["videos"] = videos
        if due or yt_subfeed["videos"] is None or time.time() - yt_subfeed["at"] > 3600:
            videos = yt_build_feed(cache, token)
            cache["units"] = dict(yt_units)
            write_private_json(YT_FEED_FILE, cache)
            with yt_account_lock:
                yt_subfeed.update(at=time.time(), videos=videos)
        if due:
            print(f"remote.py: YouTube subscriptions: {len(due)} channels read, {yt_units['used']} units today",
                  flush=True)
    except (OSError, ValueError) as e:
        print(f"remote.py: YouTube subscriptions: {e}", flush=True)
        with yt_account_lock:
            if yt_subfeed["videos"] is None:
                yt_subfeed.update(at=time.time(), videos=[])
    finally:
        with yt_account_lock:
            yt_subfeed["refreshing"] = False


def yt_safe(fn, *args):
    try:
        return fn(*args)
    except (OSError, ValueError):
        return None   # channel closed or unreachable: the others remain


def yt_reset_subs(everything=False):
    """Subscription list read again on the next round; everything: channel polls forgotten too (logout)"""
    for path in (YT_SUBS_FILE, YT_FEED_FILE) if everything else (YT_SUBS_FILE,):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    with yt_account_lock:
        yt_subfeed.update(at=0.0, videos=None if everything else yt_subfeed["videos"])


def yt_start_refresh():
    """Starts a poll if there is not one already; returns True when it must be done in this thread"""
    with yt_account_lock:
        if yt_subfeed["refreshing"]:
            return False
        yt_subfeed["refreshing"] = True
        return True


def yt_subfeed_loop():
    """Round of the channels every minute in the background (only those whose turn it is are read)"""
    while True:
        try:
            if read_json_file(YT_TOKEN_FILE).get("refresh_token") and yt_start_refresh():
                yt_refresh_subfeed()
        except Exception as e:   # the thread must not die
            print(f"remote.py: YouTube subscriptions: {e}", flush=True)
        time.sleep(60)


def yt_subscriptions():
    """"Subscriptions" row for /api/youtube: feed from yt_subfeed_loop; the very first one is waited for"""
    status = yt_account_status()
    if not status["authorized"]:
        return {**status, "videos": None}
    if yt_subfeed["videos"] is None:
        if yt_start_refresh():
            yt_refresh_subfeed()
        else:
            for _ in range(150):   # poll in progress in another thread
                if yt_subfeed["videos"] is not None:
                    break
                time.sleep(0.2)
    with yt_account_lock:
        videos = yt_subfeed["videos"]
    return {**status, "videos": with_progress(videos) if videos is not None else None}


def yt_account_status():
    app = read_json_file(YT_APP_FILE)
    out = {"configured": bool(app.get("client_id") and app.get("client_secret")), "authorized": False, "pending": None,
           "channels": None, "synced": None}
    with yt_account_lock:
        if yt_pending and yt_pending.get("expires_at", 0) > time.time():
            out["pending"] = {k: yt_pending.get(k) for k in ("user_code", "verification_uri", "error")}
    if not out["configured"]:
        return out
    try:
        out["authorized"] = bool(yt_token())
    except (OSError, ValueError):
        out["authorized"] = bool(read_json_file(YT_TOKEN_FILE).get("refresh_token"))   # Google unreachable: assume it is
    subs = read_json_file(YT_SUBS_FILE)
    if out["authorized"] and subs.get("channels") is not None:
        out["channels"], out["synced"] = len(subs["channels"]), int(subs.get("at") or 0)
    out["units_today"] = yt_units["used"] if yt_units["day"] == yt_quota_day() else 0
    out["tv"] = yt_tv("/status", timeout=3) or {"unavailable": True}   # progress ("TV app" access)
    return out


def set_yt_app(client_id, client_secret):
    client_id, client_secret = client_id.strip(), client_secret.strip()
    if not re.fullmatch(r"[\w-]+\.apps\.googleusercontent\.com", client_id):
        raise ValueError(tr("This is not a Google client ID (it ends with .apps.googleusercontent.com)."))
    if not client_secret:
        raise ValueError(tr("The client secret is missing."))
    write_private_json(YT_APP_FILE, {"client_id": client_id, "client_secret": client_secret})
    yt_logout()   # new app: the old authorization no longer applies


def yt_logout():
    try:
        os.remove(YT_TOKEN_FILE)
    except FileNotFoundError:
        pass
    with yt_account_lock:
        yt_pending.clear()
    yt_reset_subs(everything=True)


# Box status (page, Settings → System): temperatures, processor, memory, disk, network, player, services,
# updates. Processor and network throughput are measured over an interval: polled every 5 s by a thread.

UPDATE_LOG = os.path.expanduser("~/.local/state/stream-box/update.log")
health_rates = {"cpu": None, "rx": None, "tx": None}


def default_iface():
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if parts[1] == "00000000":
                    return parts[0]
    except OSError:
        pass
    return None


def read_int(path, default=None):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return default


def health_loop():
    prev = None
    while True:
        try:
            with open("/proc/stat") as f:
                cpu = [int(v) for v in f.readline().split()[1:]]
            iface = default_iface()
            rx = read_int(f"/sys/class/net/{iface}/statistics/rx_bytes", 0) if iface else 0
            tx = read_int(f"/sys/class/net/{iface}/statistics/tx_bytes", 0) if iface else 0
            now = time.time()
            if prev:
                busy, total = sum(cpu) - cpu[3] - cpu[4], sum(cpu)
                pbusy, ptotal = sum(prev[0]) - prev[0][3] - prev[0][4], sum(prev[0])
                dt = now - prev[3]
                health_rates.update(cpu=100 * (busy - pbusy) / max(1, total - ptotal),
                                    rx=(rx - prev[1]) * 8 / dt, tx=(tx - prev[2]) * 8 / dt)   # bits/s
            prev = (cpu, rx, tx, now)
        except OSError:
            pass
        time.sleep(5)


def temperatures():
    out = {}
    for h in sorted(os.listdir("/sys/class/hwmon")) if os.path.isdir("/sys/class/hwmon") else []:
        base = f"/sys/class/hwmon/{h}"
        try:
            name = open(f"{base}/name").read().strip()
        except OSError:
            continue
        t = read_int(f"{base}/temp1_input")
        if t is not None and name in ("coretemp", "k10temp", "zenpower", "nvme"):
            out["cpu" if name != "nvme" else "disk"] = round(t / 1000)
    return out


def user_systemctl(*args):
    env = {**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")}
    r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=10, env=env)
    return r.stdout.strip()


def last_update():
    """Last update from update.log: date and lines of that run"""
    try:
        with open(UPDATE_LOG, encoding="utf-8", errors="replace") as f:
            text = f.read()[-20000:]
    except OSError:
        return None
    runs = text.split("=== ")
    if len(runs) < 2:
        return None
    date, _, body = runs[-1].partition("\n")
    lines = [l for l in body.splitlines() if l.strip()]
    failed = any("échec" in l.lower() or "ÉCHEC" in l or "failed" in l.lower() for l in lines)   # old French logs too
    return {"date": date.strip(), "lines": lines[-12:], "ok": not failed}


def health():
    with open("/proc/meminfo") as f:
        mem = {k: int(v.split()[0]) for k, v in (l.split(":", 1) for l in f)}
    disk = shutil.disk_usage(os.path.expanduser("~"))
    with open("/proc/uptime") as f:
        uptime = float(f.read().split()[0])
    iface = default_iface()
    try:
        hwdec, drops, fps, width, height, vo = mpv(
            ["get_property", "hwdec-current"], ["get_property", "frame-drop-count"],
            ["get_property", "estimated-vf-fps"], ["get_property", "video-params/w"],
            ["get_property", "video-params/h"], ["get_property", "current-vo"])
    except OSError:
        hwdec = drops = fps = width = height = vo = None
    services = {}
    for unit, label in (("stream-box-mqtt.service", "mqtt"), ("stream-box-pot.service", "youtube_tokens")):
        try:
            services[label] = user_systemctl("is-active", unit) or tr("unknown")
        except (OSError, subprocess.SubprocessError):
            services[label] = tr("unknown")
    try:
        props = dict(l.split("=", 1) for l in user_systemctl(
            "show", "stream-box-update.service", "-p", "ActiveState").splitlines() if "=" in l)
        timer = user_systemctl("show", "stream-box-update.timer", "-p", "NextElapseUSecRealtime")
        next_run = timer.split("=", 1)[1] if "=" in timer else ""
    except (OSError, subprocess.SubprocessError):
        props, next_run = {}, ""
    return {
        "temps": temperatures(), "cpu": health_rates["cpu"], "load": os.getloadavg()[0], "cores": os.cpu_count(),
        "memory": {"total": mem.get("MemTotal", 0) * 1024, "available": mem.get("MemAvailable", 0) * 1024},
        "disk": {"total": disk.total, "free": disk.free}, "uptime": uptime,
        "network": {"iface": iface, "speed": read_int(f"/sys/class/net/{iface}/speed") if iface else None,
                    "rx": health_rates["rx"], "tx": health_rates["tx"]},
        "player": {"choice": player_choice(), "running": "qt" if vo == "libmpv" else "mpv", "hwdec": hwdec,
                   "dropped": drops, "fps": fps, "size": f"{width}x{height}" if width else None},
        "services": services,
        "update": {"running": props.get("ActiveState") == "activating", "next": next_run, "last": last_update()},
    }


def start_update():
    user_systemctl("start", "--no-block", "stream-box-update.service")


# Twitch account

account = {"login": None, "expired": False}   # last known result, so as not to query Twitch on every request
account_lock = threading.Lock()


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
    restart_stream()


def action(name, body):
    if name == "channel":
        # Streamer from the list, or followed channel (Following tab of the TV menu)
        if body.get("name") not in read_streamers() and body.get("name") not in follows_logins():
            raise ValueError(tr("unknown streamer"))
        mpv(["script-message", "streambox-channel", body["name"]])
    elif name == "chat":
        mpv(["script-message", "streambox-toggle-chat"])
    elif name == "corner":
        mpv(["script-message", "streambox-cycle-corner"])
    elif name == "play":
        play(find_url(str(body.get("url", ""))), bool(body.get("from_start")),
             str(body.get("title") or "")[:200] or None, str(body.get("thumb") or "")[:500] or None,
             body.get("start") if isinstance(body.get("start"), (int, float)) else None)
    elif name == "history":
        edit_history(str(body.get("action", "")), str(body.get("key", "")))
    elif name == "twitch":
        mpv(["script-message", "streambox-twitch"])
    elif name == "home":
        mpv(["script-message", "streambox-home"])
    elif name == "streamers":
        edit_streamers(str(body.get("action", "")), str(body.get("login", "")), int(body.get("delta", 0)))
    elif name == "live_seek":
        target = body.get("delta")
        arg = "live" if target == "live" else str(max(-600, min(600, int(target or 0))))
        mpv(["script-message", "streambox-live-seek", arg])
    elif name == "auto_switch":
        mpv(["script-message", "streambox-auto-switch", "yes" if body.get("enabled") else "no"])
    elif name == "backdrop":
        # {"base", "overlay", "color"} (one or more)
        set_backdrop(body)
    elif name == "flag":
        # Yes / no settings of stream-box.lua: night mode (compressed sound), polls and predictions panel
        if body.get("key") not in ("night", "events"):
            raise ValueError(tr("unknown setting"))
        mpv(["script-message", "streambox-flag", body["key"], "yes" if body.get("enabled") else "no"])
    elif name == "pip":
        # Second stream (Qt app): open <channel> [pip|split], close, swap, layout <pip|split>
        action = str(body.get("action", ""))
        if action not in ("open", "close", "swap", "layout"):
            raise ValueError(tr("unknown action"))
        login = str(body.get("name", "")).strip().lower()
        if action == "open" and not re.fullmatch(r"[a-z0-9_]{2,25}", login):
            raise ValueError(tr("invalid channel"))
        mpv(["script-message", "streambox-pip", action, login, str(body.get("layout", "pip"))])
    elif name == "vote":
        vote_poll(str(body.get("poll", "")), str(body.get("choice", "")))
    elif name == "predict":
        predict(str(body.get("event", "")), str(body.get("outcome", "")), int(body.get("points", 0)))
    elif name == "player":
        set_player(str(body.get("mode", "")))
    elif name == "jellyfin_play":
        jellyfin_play(str(body.get("id", "")), bool(body.get("from_start")))
    elif name == "youtube_channels":
        edit_yt_channels(str(body.get("action", "")), str(body.get("channel", "")), int(body.get("delta", 0)))
    elif name == "update":
        start_update()
    elif name == "qr":
        # Display of the companion app QR code on the TV
        if body.get("mode") not in ("always", "timed", "never"):
            raise ValueError(tr("unknown mode"))
        mpv(["script-message", "streambox-qr", body["mode"]])
    elif name == "set":
        # Bounds and saving handled by stream-box.lua (set_number)
        if body.get("key") not in ("chat_bg", "chat_size", "sub_size", "sub_bg"):
            raise ValueError(tr("unknown setting"))
        mpv(["script-message", "streambox-set", body["key"], str(int(body.get("value", 0)))])
    elif name == "display":
        display.apply(str(body.get("mode", "auto")))
    elif name == "volume":
        mpv(["add", "volume", max(-20, min(20, int(body.get("delta", 0))))])
    elif name == "mute":
        mpv(["cycle", "mute"])
    elif name == "pause":
        mpv(["cycle", "pause"])
    elif name == "login":
        login(str(body.get("token", "")))
    elif name == "logout":
        logout()
    elif name == "follows_app":
        set_twitch_app(str(body.get("client_id", "")), str(body.get("client_secret", "")))
    elif name == "follows_login":
        follows_start()
    elif name == "follows_logout":
        follows_logout()
    elif name == "youtube_app":
        set_yt_app(str(body.get("client_id", "")), str(body.get("client_secret", "")))
    elif name == "youtube_login":
        yt_login()
    elif name == "youtube_logout":
        yt_logout()
    elif name == "youtube_tv_login":
        d = yt_tv("/login", {}, timeout=15)
        if not d or d.get("error"):
            raise ValueError(tr("Unable to connect: {error}",
                                error=(d or {}).get("error") or tr("cast service stopped")))
    elif name == "youtube_tv_logout":
        yt_tv("/logout", {})
        yt_tv_cache.update(at=0.0, data={})
    elif name == "youtube_sync":
        yt_reset_subs()
    elif name == "poweroff":
        # mode: "suspend" (Sleep), "full" (Turn off the box, TV menu); otherwise the setting
        mode = str(body.get("mode") or "")
        power("suspend" if mode == "suspend" else "poweroff" if mode == "full" else power_action())
    elif name == "key":
        # Virtual remote of the page: same keys as the Bluetooth remote (stream-box.lua, KEYS)
        # (the Xiaomi remote's play key changes the chat corner: here, "Play" pauses or resumes)
        # Action sent as is to stream-box.lua (like the keys read by input.py)
        key = str(body.get("key", ""))
        if key == "playpause":
            mpv(["cycle", "pause"])
            return
        if key not in ("up", "down", "left", "right", "ok", "back", "home", "menu", "homescreen"):
            raise ValueError(tr("unknown key"))
        mpv(["script-message", "streambox-input", "VIRTUAL", key])
    elif name == "bluetooth":
        # TV System menu: {"action": "scan"}, {"action": "pair" | "remove", "mac"}
        what, mac = str(body.get("action", "")), str(body.get("mac", "")).upper()
        if what == "scan":
            btsetup.scan()
        elif what == "pair":
            btsetup.pair(mac)
        elif what == "remove":
            btsetup.remove(mac)
        else:
            raise ValueError(tr("unknown action"))
    elif name == "language":
        # Interface language (companion app, TV): {"lang": "en" | "fr" …}; the TV reloads its texts right away
        i18n.set_language(str(body.get("lang", "")))
        mpv(["script-message", "streambox-language", i18n.language()])
    elif name == "setup":
        # Phone page: "Finish" of the first setup
        finish_setup()
    elif name == "ssh":
        set_ssh(bool(body.get("enabled")))
    elif name == "dev":
        set_dev(bool(body.get("enabled")))
    elif name == "install":
        # TV System menu: {"disk": "nvme0n1"}; the disk is entirely erased
        installer.start(str(body.get("disk", ""))[:32])
    elif name == "backup":
        # TV System menu: {"action": "save_usb", "path"}, {"action": "restore_usb", "path", "name"}
        what, path = str(body.get("action", "")), str(body.get("path", ""))[:100]
        if what == "save_usb":
            backup.save_usb(path)
        elif what == "restore_usb":
            backup.restore_usb(path, str(body.get("name", ""))[:100])
        else:
            raise ValueError(tr("unknown action"))
    elif name == "keymap":
        # Remote keys: learning wizard (stream-box.lua), or back to the default keys
        what = str(body.get("action", ""))
        if what not in ("wizard", "reset"):
            raise ValueError(tr("unknown action"))
        mpv(["script-message", "streambox-keymap-" + what])
    elif name == "audio":
        # Sound output: "auto" or the identifier of an output from GET /api/audio
        audio.set_choice(str(body.get("output", "auto"))[:200])
    elif name == "keyboard":
        # TV menu: search keyboard open or closed (the page then offers a text field)
        keyboard.update(open=bool(body.get("open")), text=str(body.get("text", ""))[:80],
                        target=str(body.get("target", ""))[:20], at=time.time())
    elif name == "keyboard_input":
        # Page: text of the field, sent to the menu's keyboard; submit starts the search
        if not keyboard.get("open"):
            raise ValueError(tr("The TV keyboard is no longer open."))
        text = str(body.get("text", ""))[:80]
        keyboard["text"] = text
        mpv(["script-message", "streambox-tvmenu-text", text, "1" if body.get("submit") else "0"])
        if body.get("submit"):
            keyboard["open"] = False
    elif name == "remote_url":
        set_remote_url(str(body.get("url", ""))[:300])
    elif name == "wifi":
        # {"action": "connect", "ssid", "password"}: join a network; {"action": "hotspot"}: setup mode
        if body.get("action") == "hotspot":
            netsetup.manual_hotspot()
        else:
            netsetup.connect(str(body.get("ssid", ""))[:64], str(body.get("password", ""))[:128])
    elif name == "reboot":
        # Allowed by default for the TV session, elsewhere by the polkit rule (login1.reboot*)
        r = subprocess.run(["systemctl", "reboot"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            raise ValueError(tr("Restart refused: {error}", error=r.stderr.strip() or r.returncode))
    elif name == "power_action":
        set_power_action(str(body.get("mode", "")))
    else:
        raise ValueError(tr("unknown action"))


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            if self.path.startswith("/share?"):
                # Android share target (share_target of the manifest): start the video then show the page
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                url = find_url(*(query.get(k, [""])[0] for k in ("url", "text", "title")))
                try:
                    play(url)
                    location = "/"
                except ValueError:
                    location = "/?partage=invalide"
                self.send_response(303)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif self.path.startswith("/subs?"):
                # Called by stream-box.lua (sub-add) for YouTube automatic subtitles
                url = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("u", [""])[0]
                self.send(200, fetch_auto_subs(url).encode(), "application/x-subrip; charset=utf-8")
            elif self.path.split("?")[0] in STATIC:
                name, content_type = STATIC[self.path.split("?")[0]]
                with open(os.path.join(DIR, name), "rb") as f:
                    self.send(200, f.read(), content_type)
            elif self.path == "/api/state":
                self.send(200, state())
            elif self.path.split("?")[0] == "/api/preview":
                image = preview()
                if image:
                    self.send(200, image, "image/jpeg")
                else:
                    self.send_response(204)   # nothing to capture (ambient screen)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
            elif self.path == "/api/history":
                self.send(200, read_history())
            elif self.path.startswith("/api/replays?"):
                login = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("login", [""])[0]
                try:
                    self.send(200, replays(login))
                except ValueError as e:
                    self.send(400, {"error": str(e)})
            elif self.path == "/api/display":
                try:
                    self.send(200, display.info())
                except OSError as e:
                    self.send(503, {"error": str(e)})
            elif self.path.startswith("/api/tvimage?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    self.send(200, tv_image(q.get("src", [""])[0], int(q.get("w", ["0"])[0]), int(q.get("h", ["0"])[0]),
                                            q.get("round", ["0"])[0] == "1", int(q.get("radius", ["0"])[0])))
                except (ValueError, subprocess.SubprocessError) as e:
                    self.send(400, {"error": str(e)})
            elif self.path == "/api/youtube":
                self.send(200, youtube_home())
            elif self.path.startswith("/api/youtube_search?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("q", [""])[0]
                try:
                    self.send(200, {"query": q, **yt_search(q)})
                except ValueError as e:
                    self.send(400, {"error": str(e)})
            elif self.path == "/api/jellyfin":
                try:
                    self.send(200, jellyfin_home())
                except (OSError, ValueError, KeyError) as e:
                    self.send(503, {"error": tr("Jellyfin unreachable: {error}", error=e)})
            elif self.path.startswith("/api/jellyfin_search?") or self.path.startswith("/api/jellyfin_series?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    if self.path.startswith("/api/jellyfin_search?"):
                        query = q.get("q", [""])[0]
                        self.send(200, {"query": query, "results": jellyfin_search(query)})
                    else:
                        self.send(200, jellyfin_series(q.get("id", [""])[0]))
                except (OSError, ValueError, KeyError) as e:
                    self.send(400, {"error": str(e)})
            elif self.path.startswith("/api/youtube_channel?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("id", [""])[0]
                try:
                    self.send(200, yt_channel_videos(q))
                except ValueError as e:
                    self.send(400, {"error": str(e)})
            elif self.path == "/api/bluetooth":
                self.send(200, btsetup.status())
            elif self.path == "/api/dev":
                self.send(200, dev_status())
            elif self.path == "/api/ssh":
                self.send(200, ssh_status(local=self.client_address[0] == "127.0.0.1"))
            elif self.path == "/api/install":
                self.send(200, installer.status())
            elif self.path == "/api/backup":
                self.send(200, backup.status())
            elif self.path.startswith("/api/backup/download"):
                # Companion app: backup file saved on the phone
                data = backup.create()
                self.send_response(200)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition", f'attachment; filename="{backup.file_name()}"')
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            elif self.path == "/api/audio":
                outs = audio.outputs()
                self.send(200, {"choice": audio.choice(), "current": audio.current(outs),
                                "outputs": [{"id": o["id"], "label": o["label"], "kind": o["kind"]} for o in outs]})
            elif self.path == "/api/wifi":
                self.send(200, netsetup.status())
            elif self.path == "/api/health":
                self.send(200, health())
            elif self.path == "/api/events":
                try:
                    self.send(200, events_for_page())
                except (OSError, ValueError, KeyError) as e:
                    self.send(503, {"error": tr("Twitch unreachable: {error}", error=e)})
            elif self.path == "/api/youtube_channels":
                self.send(200, {"channels": yt_channels()})
            elif self.path == "/api/youtube_account":
                self.send(200, yt_account_status())
            elif self.path == "/api/follows":
                try:
                    self.send(200, follows_status())
                except (OSError, ValueError, KeyError) as e:
                    self.send(503, {"error": tr("Twitch unreachable: {error}", error=e)})
            elif self.path.startswith("/api/qr?"):
                text = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("text", [""])[0]
                self.send(200, {"rows": qr_rows(text)})
            elif self.path == "/api/account":
                with account_lock:
                    self.send(200, dict(account))
            else:
                self.send(404, {"error": tr("not found")})
        except (OSError, ValueError) as e:
            self.send(503, {"error": tr("box unreachable: {error}", error=e)})

    def do_POST(self):
        if not self.path.startswith("/api/"):
            return self.send(404, {"error": tr("not found")})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if self.path == "/api/backup_restore":   # companion app: raw backup file, then restart
                if length > backup.MAX_SIZE:
                    raise ValueError(tr("File too large for a backup."))
                backup.restore_upload(self.rfile.read(length))
                return self.send(200, {"ok": True})
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            if self.path[len("/api/"):] in LOCAL_ONLY and self.client_address[0] != "127.0.0.1":
                return self.send(403, {"error": tr("Access setting: only from the TV menu.")})
            action(self.path[len("/api/"):], body)
            self.send(200, {"ok": True})
        except ValueError as e:
            self.send(400, {"error": str(e)})
        except OSError as e:
            self.send(503, {"error": tr("box unreachable: {error}", error=e)})

    def log_message(self, *args):
        pass   # no per-request log


write_cookies(read_token())   # at startup: cookies aligned with the saved token
threading.Thread(target=account_loop, daemon=True).start()
threading.Thread(target=live_loop, daemon=True).start()
threading.Thread(target=ambient_loop, daemon=True).start()
threading.Thread(target=history_loop, daemon=True).start()
threading.Thread(target=events_loop, daemon=True).start()
threading.Thread(target=health_loop, daemon=True).start()
threading.Thread(target=resume_loop, daemon=True).start()
threading.Thread(target=netsetup.setup_loop, daemon=True).start()
threading.Thread(target=yt_subfeed_loop, daemon=True).start()
hold_power_key()
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
