"""Stream Box: YouTube for the companion app and the TV menu. Followed channels (RSS feeds), search (yt-dlp), automatic
subtitles, seek bar preview, account subscriptions (own Google app, device code) and progress synced with the
account through the "TV app" access (cast/youtube_tv.js). Standard library only.
"""
import calendar, json, os, re, subprocess, threading, time, urllib.error, urllib.parse, urllib.request

import history   # history.py: positions of the videos already watched on the box
from common import COOKIES_DIR, mpv, read_json_file, write_private_json
from i18n import tr

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
    known = known if known is not None else {e["key"]: e for e in history.read_history()}
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
    known = {e["key"]: e for e in history.read_history()}
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


# YouTube automatic subtitles, served at /subs?u=<url> to stream-box.lua (sub-add)

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


# YouTube video preview on the seek bar (Qt app): thumbnail sheet ("storyboard") given by yt-dlp, published in
# user-data/streambox/storyboard. Each image of the sheet is a rows × columns grid of thumbnails covering "duration"
# seconds.

def fetch_storyboard(url, ident):
    try:
        r = subprocess.run([YTDLP, *YTDLP_JS, "-J", "--no-warnings", "--skip-download",
                            "--no-playlist", url], capture_output=True, text=True, timeout=90)
        info = json.loads(r.stdout or "{}") or {}   # "null": yt-dlp could not read the video
        if history.now_playing.get("ident") == ident:   # info for the seek bar and the pause screen
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
        if history.now_playing.get("ident") == ident:   # still the same video
            mpv(["set_property", "user-data/streambox/storyboard", board])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        pass


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
