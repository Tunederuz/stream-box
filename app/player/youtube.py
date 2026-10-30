"""Inlet: YouTube for the companion app and the TV menu. Followed channels (RSS feeds), search (yt-dlp), automatic
subtitles, seek bar preview, and the YouTube account through the "TV app" access (cast/youtube_tv.js: sign-in with a
code, subscriptions, recommendations, progress synced both ways). Standard library only.
"""
import json, os, re, subprocess, threading, time, urllib.parse, urllib.request

import history   # history.py: positions of the videos already watched on the box
from common import COOKIES_DIR, mpv, tool
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
YTDLP = tool("yt-dlp")
# YouTube JavaScript challenges: deno when installed (install.sh), otherwise the system's Node (image, without deno)


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
            c = yt_resolve(raw)
            c.setdefault("handle", "")
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
    """(title, duration) of a video: the YouTube account's TV access when connected, otherwise oEmbed (title only)"""
    d = yt_tv(f"/meta?id={video_id}", timeout=10)
    if d and d.get("title"):
        return d["title"], d.get("seconds")
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


def yt_tv_recommended():
    """Videos of the account's YouTube home ("YouTube TV app" access, kept 30 min by youtube_tv.js): [] when not
    connected, the server not running or YouTube unreachable"""
    videos = yt_tv("/recommended", timeout=20)
    return videos if isinstance(videos, list) else []


def yt_tv_report(video_id, position, final=False):
    threading.Thread(target=yt_tv, args=("/report", {"id": video_id, "position": position, "final": final}),
                     daemon=True).start()


def youtube_home():
    """Recommended for you and subscriptions (the account, through the "YouTube TV app" access), favorites (one row
    per channel: RSS feeds, read in parallel; yt_feed also keeps failures)"""
    from concurrent.futures import ThreadPoolExecutor
    chans = yt_channels()
    with ThreadPoolExecutor(8) as pool:
        videos = dict(zip([c["id"] for c in chans], pool.map(lambda c: yt_safe(yt_feed, c["id"]), chans)))
    known = {e["key"]: e for e in history.read_history()}
    out = [{**c, "videos": with_progress(videos[c["id"]], known) if videos[c["id"]] is not None else None}
           for c in chans]   # feed unreachable: the channel stays shown, without videos
    try:
        subs = yt_subscriptions()
    except (OSError, ValueError, KeyError) as e:   # YouTube account broken: the list's channels remain
        print(f"remote.py: YouTube subscriptions: {e}", flush=True)
        subs = None
    return {"channels": out, "subs": subs, "recommended": with_progress(yt_tv_recommended(), known)}


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
# seconds. Read from the yt-dlp run of mpv's ytdl_hook (user-data/mpv/ytdl/json-subprocess-result, kept until the
# end of the file): a second extraction would double the player requests that make YouTube ask "not a bot".
YTDL_RESULT = "user-data/mpv/ytdl/json-subprocess-result"


def ytdl_info(ident, wait=90):
    """yt-dlp's info of the video being opened, once ytdl_hook has it (None: it failed, or another video plays).
    Until then the property is empty, or still holds the previous video's result."""
    end = time.time() + wait
    while time.time() < end and history.now_playing.get("ident") == ident:
        try:
            info = json.loads((mpv(["get_property", YTDL_RESULT])[0] or {}).get("stdout") or "null")
        except (OSError, ValueError, AttributeError):
            info = None
        if isinstance(info, dict) and info.get("id") == ident:
            return info
        time.sleep(1)
    return None


def fetch_storyboard(ident):
    try:
        info = ytdl_info(ident)
        if not info:
            return
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


# YouTube account ("Subscriptions" row of the YouTube tab, "Recommended for you", progress): the "YouTube TV app"
# access of cast/youtube_tv.js, signed in with a code on google.com/device; nothing to create (no Google app of your
# own, no API quota). The feed is the TV app's (youtube.com), kept 15 min by youtube_tv.js.


def yt_safe(fn, *args):
    try:
        return fn(*args)
    except (OSError, ValueError):
        return None   # channel closed or unreachable: the others remain


def yt_subscriptions():
    """"Subscriptions" row for /api/youtube: {authorized, pending, videos} (videos None: not connected, or the TV
    access unavailable)"""
    status = yt_account_status()
    videos = yt_tv("/subscriptions", timeout=30) if status["authorized"] else None
    return {**status, "videos": with_progress(videos) if isinstance(videos, list) else None}


def yt_account_status():
    """The account through the TV access: authorized, pending (code to type, or error), unavailable (youtube_tv.js
    not running)"""
    tv = yt_tv("/status", timeout=3)
    if not tv:
        return {"authorized": False, "pending": None, "unavailable": True}
    pending = tv.get("pending") or ({"error": tv["error"]} if tv.get("error") else None)
    return {"authorized": bool(tv.get("connected")), "pending": pending, "unavailable": False}


def yt_reload():
    """"Reload my subscriptions": the feed read again now"""
    if not yt_account_status()["authorized"]:
        raise ValueError(tr("YouTube account not connected."))
    if yt_tv("/subscriptions?fresh=1", timeout=30) is None:
        raise ValueError(tr("YouTube unreachable for now."))
