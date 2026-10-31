"""Inlet: history and resume of the videos started from the companion app (history.json), and the video being
played (now_playing, shared with playback.py, the addons and youtube.py). Standard library only.
"""
import json, os, re, threading, time

from i18n import tr

# History and resume of videos started from the companion app (links, YouTube, Twitch replays and clips,
# Jellyfin and Plex: they keep their own progress, the box's history only serves to find them again; links
# "jellyfin:ID" and "plex:ID", without token). Twitch replays are synced with the connected account:
# position read at start, written every 30 s. The rest is known only to the box.

HISTORY_FILE = os.path.expanduser("~/.local/state/stream-box/history.json")
# System on a USB drive (marker of /usr/local/lib/stream-box/flash-mode): positions are written at most once a minute,
# kept in memory in between (history_loop flushes them); removals and clearing are written at once
USB_ROOT = os.path.exists("/run/stream-box/usb-root")
WRITE_EVERY = 60 if USB_ROOT else 0
pending = None          # entries not written yet
last_write = 0.0
HISTORY_MAX = 60
RESUME_MIN = 30         # seconds: below that, start from the beginning
FINISHED_LEFT = 30      # less than 30 s from the end, or beyond 95 %, the video is watched
history_lock = threading.Lock()
now_playing = {}        # video started by play(), tracked by history_loop


def media_key(url):
    """(stable key, kind, identifier): the same video keeps the same key whatever the link's form."""
    m = re.fullmatch(r"jellyfin:([0-9a-f]{32})", url) or re.search(r"/Videos/([0-9a-f]{32})/", url)
    if m:
        return f"jellyfin:{m.group(1)}", "jellyfin", m.group(1)
    m = re.fullmatch(r"plex:(\d{1,10})", url)
    if m:
        return f"plex:{m.group(1)}", "plex", m.group(1)
    m = re.search(r"/library/parts/(\d+)/", url)   # file of a Plex server (the item id is not in the link)
    if m:
        return f"plex-part:{m.group(1)}", "plex", None
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


def finished(position, duration):
    return bool(duration) and (position >= duration - FINISHED_LEFT or position >= 0.95 * duration)


def read_history():
    if pending is not None:
        return list(pending)
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def write_history(entries, now=False):
    global pending, last_write
    if not now and time.time() - last_write < WRITE_EVERY:
        pending = entries[:HISTORY_MAX]
        return
    pending, last_write = None, time.time()
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


def flush(force=False):
    """Writes the positions kept in memory once WRITE_EVERY has passed (history_loop, every 10 s), or at once (force:
    remote.py stopping)"""
    with history_lock:
        if pending is not None and (force or time.time() - last_write >= WRITE_EVERY):
            write_history(pending, now=True)


def edit_history(action, key=""):
    with history_lock:
        entries = read_history()
        if action == "remove":
            entries = [e for e in entries if e["key"] != key]
        elif action == "clear":
            entries = []
        else:
            raise ValueError(tr("unknown action"))
        write_history(entries, now=True)
