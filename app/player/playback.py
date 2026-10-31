"""Inlet: playback of the videos started from the companion app and the TV menu (links, YouTube, Twitch replays
and clips, Jellyfin, Plex), and the history loop that records their position and sends it back to Twitch, YouTube,
Jellyfin and Plex. Standard library only.
"""
import datetime, re, time

import addons    # addons/: the integrations (YouTube, Jellyfin, Plex…): their links, their videos, progress reports
import history   # history.py: history file and the video being played
import twitch    # twitch.py: replays and clips (GQL), position saved on the account
from common import mpv
from i18n import tr


def find_url(*texts):
    """First http(s) link found: apps often share "title + link" in the text field. Also
    "jellyfin:ID" and "plex:ID", the links of Jellyfin and Plex videos in the history."""
    for text in texts:
        match = re.search(r"https?://\S+|\bjellyfin:[0-9a-f]{32}\b|\bplex:\d{1,10}\b", text or "")
        if match:
            return match.group(0)
    return None


TWITCH_PUSH = 30        # seconds between two position sends to Twitch


def play(url, from_start=False, title=None, thumb=None, at=None):
    """title, thumb: known by the page or menu starting the video (loading screen, history);
    at: forced position (cast from the YouTube app), otherwise resume from the history"""
    if addons.play_link(url, from_start):   # a link of an addon, from the history (jellyfin:<id>, plex:<id>)
        return
    if not url or not re.match(r"https?://", url):
        raise ValueError(tr("This is not an http(s) link."))
    key, kind, ident = history.media_key(url)
    entry = next((e for e in history.read_history() if e["key"] == key), None) or {}
    video = {"key": key, "url": url, "kind": kind, "ident": ident, "title": entry.get("title") or title,
             "thumb": entry.get("thumb") or thumb}
    position, updated, duration = entry.get("position", 0), entry.get("updated", 0), entry.get("duration", 0)
    addon = addons.for_kind(kind)
    if addon and addon.prepare:   # (YouTube: title of a cast video, the account's progress)
        position, duration = addon.prepare(video, position, duration, from_start, at)
    try:   # Twitch: title, thumbnail, duration and position saved on the account
        if kind == "twitch-vod":
            v = twitch.twitch_gql("query($id:ID!){video(id:$id){title lengthSeconds "
                                  "previewThumbnailURL(width:320,height:180) self{viewingHistory{position updatedAt}}}}",
                                  {"id": ident}).get("video") or {}
            video.update(title=v.get("title") or video["title"], thumb=v.get("previewThumbnailURL") or video["thumb"])
            duration = v.get("lengthSeconds") or duration
            seen = (v.get("self") or {}).get("viewingHistory") or {}
            if seen.get("updatedAt"):
                seen_at = datetime.datetime.fromisoformat(seen["updatedAt"].replace("Z", "+00:00")).timestamp()
                if seen_at > updated:   # watched more recently elsewhere (site, app) than on the box
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
    mpv(["set_property", "user-data/streambox/rating", {}])
    mpv(["set_property", "user-data/streambox/comments", {}])
    if addon and addon.started:
        addon.started(video)


def history_loop():
    """Every 10 s, records the position of the video started by play(); sends it to Twitch for a replay."""
    while True:
        time.sleep(10)
        history.flush()   # positions kept in memory on a USB drive (history.WRITE_EVERY)
        video = dict(history.now_playing) or addons.outside_video()
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
        addon = addons.for_kind(video["kind"])
        if addon and addon.report:   # a video an addon plays itself (Jellyfin, Plex): its server follows
            if playing and isinstance(position, (int, float)):
                paused = mpv(["get_property", "pause"])[0]
                addon.report(video, position, duration, bool(paused), False)
                history.record(video, position, duration)
                history.now_playing.update(position=position, duration=duration)
            elif not playing:
                addon.report(video, None, None, False, True)
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
            if addon and addon.progress and time.time() - video["pushed"] >= addon.progress_every:
                addon.progress(video, position, False)   # (YouTube: the position to the account)
                history.now_playing["pushed"] = time.time()
        elif not playing:   # video finished or replaced: last position sent to Twitch
            if video["kind"] == "twitch-vod" and video.get("position"):
                try:
                    twitch.twitch_save_position(video["ident"], video["position"])
                except (OSError, ValueError, KeyError):
                    pass
            if addon and addon.progress and video.get("position"):
                addon.progress(video, video["position"], True)
            if history.now_playing.get("key") == video["key"]:
                history.now_playing.clear()
