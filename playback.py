"""Stream Box: playback of the videos started from the companion app and the TV menu (links, YouTube, Twitch replays
and clips, Jellyfin), and the history loop that records their position and sends it back to Twitch, YouTube and
Jellyfin. Standard library only.
"""
import datetime, re, threading, time

import history   # history.py: history file and the video being played
import jellyfin  # jellyfin.py: Jellyfin videos and progress reports
import twitch    # twitch.py: replays and clips (GQL), position saved on the account
import youtube   # youtube.py: titles, storyboard, progress of the YouTube account
from common import mpv
from i18n import tr


def find_url(*texts):
    """First http(s) link found: apps often share "title + link" in the text field. Also
    "jellyfin:ID", the link of Jellyfin videos in the history."""
    for text in texts:
        match = re.search(r"https?://\S+|\bjellyfin:[0-9a-f]{32}\b", text or "")
        if match:
            return match.group(0)
    return None


TWITCH_PUSH = 30        # seconds between two position sends to Twitch


def play(url, from_start=False, title=None, thumb=None, at=None):
    """title, thumb: known by the page or menu starting the video (loading screen, history);
    at: forced position (cast from the YouTube app), otherwise resume from the history"""
    if re.fullmatch(r"jellyfin:[0-9a-f]{32}", url or ""):   # from the history
        return jellyfin.jellyfin_play(url.split(":")[1], from_start)
    if not url or not re.match(r"https?://", url):
        raise ValueError(tr("This is not an http(s) link."))
    key, kind, ident = history.media_key(url)
    entry = next((e for e in history.read_history() if e["key"] == key), None) or {}
    video = {"key": key, "url": url, "kind": kind, "ident": ident, "title": entry.get("title") or title,
             "thumb": entry.get("thumb") or thumb or (f"https://i.ytimg.com/vi/{ident}/mqdefault.jpg" if kind == "youtube" else None)}
    position, updated, duration = entry.get("position", 0), entry.get("updated", 0), entry.get("duration", 0)
    if kind == "youtube" and not video["title"]:   # video cast from the YouTube app: only its identifier is known
        video["title"], duration = youtube.yt_meta(ident)
        duration = duration or 0
    if kind == "youtube" and not from_start and at is None:
        # Watched further elsewhere (phone…): resume at the account's percentage, if beyond the box's position
        pct = youtube.yt_tv_progress().get(ident) or 0
        if 3 <= pct and (not duration or pct / 100 * duration > position + 30):
            duration = duration or youtube.yt_meta(ident)[1] or 0
            position = int(pct / 100 * duration)
    try:   # Twitch: title, thumbnail, duration and position saved on the account
        if kind == "twitch-vod":
            v = twitch.twitch_gql("query($id:ID!){video(id:$id){title lengthSeconds "
                                  "previewThumbnailURL(width:320,height:180) self{viewingHistory{position updatedAt}}}}",
                                  {"id": ident}).get("video") or {}
            video.update(title=v.get("title") or video["title"], thumb=v.get("previewThumbnailURL") or video["thumb"])
            duration = v.get("lengthSeconds") or duration
            seen = (v.get("self") or {}).get("viewingHistory") or {}
            if seen.get("updatedAt"):
                at = datetime.datetime.fromisoformat(seen["updatedAt"].replace("Z", "+00:00")).timestamp()
                if at > updated:   # watched more recently elsewhere (site, app) than on the box
                    position = seen.get("position") or 0
        elif kind == "twitch-clip":
            c = twitch.twitch_gql("query($s:ID!){clip(slug:$s){title durationSeconds thumbnailURL}}",
                                  {"s": ident}).get("clip") or {}
            video.update(title=c.get("title") or video["title"], thumb=c.get("thumbnailURL") or video["thumb"])
            duration = c.get("durationSeconds") or duration
    except (OSError, ValueError, KeyError):
        pass   # Twitch unreachable: make do with the box's history
    start = 0 if from_start or position < history.RESUME_MIN or history.finished(position, duration) else int(position)
    if at is not None:
        start = max(0, int(at))
    history.now_playing.clear()
    history.now_playing.update(video, pushed=0.0, position=start)
    mpv(["script-message", "streambox-play", url, str(start), "", video.get("thumb") or "", video.get("title") or ""])
    history.record(video, start, duration)
    mpv(["set_property", "user-data/streambox/storyboard", {}])
    mpv(["set_property", "user-data/streambox/meta", {}])
    mpv(["set_property", "user-data/streambox/next_up", {}])
    if kind == "youtube":
        threading.Thread(target=youtube.fetch_storyboard, args=(url, ident), daemon=True).start()


shim_items = {}   # Jellyfin identifier → card (title, image), for the history of the shim's playbacks


def shim_video():
    """Jellyfin video started by jellyfin-mpv-shim ("Play on…" from a Jellyfin app), from the link being
    played; None otherwise"""
    try:
        user, path = mpv(["get_property", "user-data/streambox"], ["get_property", "path"])
    except (OSError, ValueError):
        return None
    srv = jellyfin.jf_server()
    if (user or {}).get("mode") != "media" or not srv or not str(path or "").startswith(srv["address"]):
        return None
    key, kind, ident = history.media_key(path)
    if kind != "jellyfin":
        return None
    if ident not in shim_items:
        try:
            shim_items[ident] = jellyfin.jf_item(jellyfin.jf_api(f"/Users/{{user}}/Items/{ident}"))
        except (OSError, ValueError, KeyError):
            return None
    i = shim_items[ident]
    return {"key": key, "url": path, "link": key, "kind": kind, "ident": ident, "shim": True, "thumb": i["thumb"],
            "title": f"{i['title']} · {i['episode']}" if i.get("episode") else i["title"]}


def history_loop():
    """Every 10 s, records the position of the video started by play(); sends it to Twitch for a replay."""
    while True:
        time.sleep(10)
        video = dict(history.now_playing) or shim_video()
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
                history.record(video, position, duration)
            continue
        if video["kind"] == "jellyfin":
            if playing and isinstance(position, (int, float)):
                paused = mpv(["get_property", "pause"])[0]
                jellyfin.jf_report("/Progress", video["ident"], position, bool(paused))
                history.record(video, position, duration)
                history.now_playing["position"] = position
            elif not playing:
                jellyfin.jf_report("/Stopped", video["ident"], video.get("position") or 0)
                if history.now_playing.get("key") == video["key"]:
                    history.now_playing.clear()
            continue
        if playing and isinstance(position, (int, float)):
            history.record(video, position, duration, title if title and title != video["url"] else None)
            history.now_playing["position"] = position
            if video["kind"] == "twitch-vod" and time.time() - video["pushed"] >= TWITCH_PUSH:
                try:
                    twitch.twitch_save_position(video["ident"], position)
                    history.now_playing["pushed"] = time.time()
                except (OSError, ValueError, KeyError):
                    pass
            if video["kind"] == "youtube" and time.time() - video["pushed"] >= youtube.YT_TV_PUSH:
                youtube.yt_tv_report(video["ident"], position)
                history.now_playing["pushed"] = time.time()
        elif not playing:   # video finished or replaced: last position sent to Twitch
            if video["kind"] == "twitch-vod" and video.get("position"):
                try:
                    twitch.twitch_save_position(video["ident"], video["position"])
                except (OSError, ValueError, KeyError):
                    pass
            if video["kind"] == "youtube" and video.get("position"):
                youtube.yt_tv_report(video["ident"], video["position"], final=True)
            if history.now_playing.get("key") == video["key"]:
                history.now_playing.clear()
