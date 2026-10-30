"""Inlet: HTTP server of the companion app (http://<box>:8080): the page and its PWA files, the locale files, the
GET routes of the API (state, lists, status) and POST /api/<action> (actions.py). Standard library only.
"""
import json, os, time, urllib.parse
from http.server import BaseHTTPRequestHandler

import actions    # actions.py: POST /api/<name>, TV menu keyboard
import ambient    # ambient.py: first setup, remote URL, QR codes
import history    # history.py: history file, kind of the current video
import i18n       # i18n.py: interface language (locales/<lang>.json), tr()
import images     # images.py: TV preview
import jellyfin   # jellyfin.py: library
import plex       # plex.py: library
import playback   # playback.py: videos shared from the phone
import settings   # settings.py: player, power button, background
import twitch     # twitch.py: streamers, live, polls, account, followed channels
import youtube    # youtube.py: channels, search, account, subtitles
import sysparts   # sysparts.py: the box's system part, absent from the Inlet app
from common import DIR, mpv
# (system part: sound outputs, backup, Bluetooth, resolution, installation, local update, Wi-Fi, status / SSH / dev mode)
from sysparts import SYSTEM, audio, backup, btsetup, display, installer, localupdate, netsetup, system
from i18n import tr

# Files served as is: the page and what is needed to install it as an app (PWA)
STATIC = {
    "/": ("web/remote.html", "text/html; charset=utf-8"),
    "/manifest.webmanifest": ("web/manifest.webmanifest", "application/manifest+json"),
    "/sw.js": ("web/sw.js", "text/javascript"),
    "/icon-192.png": ("web/icon-192.png", "image/png"),
    "/icon-512.png": ("web/icon-512.png", "image/png"),
    "/apple-touch-icon.png": ("web/icon-180.png", "image/png"),
}
# Translations (companion app, TV menu): /locales/<lang>.json
for _code in i18n.LANGUAGES:
    if _code != "en":
        STATIC[f"/locales/{_code}.json"] = (f"locales/{_code}.json", "application/json; charset=utf-8")


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
        "streamers": twitch.read_streamers(), "channel": user.get("channel"), "avatars": twitch.avatars,
        "chat_visible": user.get("chat_visible", True), "corner": user.get("corner", "bl"),
        "chat_bg": user.get("chat_bg", 60), "chat_size": user.get("chat_size", 32),
        "sub_size": user.get("sub_size", 100), "sub_bg": user.get("sub_bg", 0),
        "auto_switch": user.get("auto_switch", True), "night": user.get("night", False),
        "events": user.get("events", True), "qr": user.get("qr", "always"),
        # Chosen player, and the one actually running (mpv alone after several crashes of the Qt app)
        "backdrop": settings.backdrop(), "first_run": not ambient.setup_done(),
        "lang": i18n.language(), "languages": i18n.LANGUAGES,
        "player": settings.player_choice(), "player_running": "qt" if vo == "libmpv" else "mpv",
        "power_action": settings.power_action(),
        "remote_url": ambient.custom_remote_url(),
        # Video libraries connected to the box: their TV menu tab only shows when they are
        "libraries": {"jellyfin": jellyfin.jf_server() is not None, "plex": plex.px_config() is not None},
        "plex_server": (plex.px_config() or {}).get("address", ""),
        "jellyfin_server": (jellyfin.jf_server() or {}).get("address", ""),
        # TV menu search keyboard open (forgotten after 10 min, menu closed in the meantime)
        "keyboard": (actions.keyboard if actions.keyboard.get("open") and time.time() - actions.keyboard.get("at", 0) < 600
                     else None),
        "pip": user.get("pip") or {"channel": "", "layout": ""},
        "volume": round(volume or 0), "mute": bool(mute), "pause": bool(pause), "playing": bool(video),
        "live": twitch.live_now, "mode": user.get("mode", "twitch"), "delay": delay, "title": title if media else None,
        "position": position if media else None, "duration": duration if media else None,
        # Kind of the current video (youtube, jellyfin, twitch-vod…): the TV menu opens on the matching tab
        "media_kind": history.media_key(path)[1] if media and path else None,
        "subs": [{"id": t["id"], "name": t.get("title") or t.get("lang") or tr("Track {id}", id=t["id"]),
                  "selected": bool(t.get("selected"))}
                 for t in (tracks or []) if t.get("type") == "sub"] if media else [],
    }


def audio_status():
    outs = audio.outputs()
    return {"choice": audio.choice(), "current": audio.current(outs),
            "outputs": [{"id": o["id"], "label": o["label"], "kind": o["kind"]} for o in outs]}


# GET routes answered with JSON as is (exact path); the others, with parameters or their own errors, are in do_GET
JSON_ROUTES = {
    "/api/state": state,
    "/api/history": history.read_history,
    "/api/youtube": youtube.youtube_home,
    "/api/youtube_channels": lambda: {"channels": youtube.yt_channels()},
    "/api/youtube_account": youtube.yt_account_status,
    "/api/plex_link": plex.link_state,   # Plex server, and the sign-in code being waited for
    "/api/features": sysparts.features,   # what this installation has (system part or not)
}
if SYSTEM:   # the box's system (the Inlet app leaves it to its OS: these routes answer 404 there)
    JSON_ROUTES.update({
        "/api/bluetooth": btsetup.status,
        "/api/audio": audio_status,
        "/api/wifi": netsetup.status,
        "/api/health": system.health,
        "/api/dev": system.dev_status,
        "/api/install": installer.status,
        "/api/backup": backup.status,
        "/api/local_update": localupdate.status,   # system update from a local image: drives, copy, progress
        "/api/update_prompt": system.update_prompt,   # update to offer or to apply (the TV menu asks at start, wake-up)
    })


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
                url = playback.find_url(*(query.get(k, [""])[0] for k in ("url", "text", "title")))
                try:
                    playback.play(url)
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
                self.send(200, youtube.fetch_auto_subs(url).encode(), "application/x-subrip; charset=utf-8")
            elif self.path.split("?")[0] in STATIC:
                name, content_type = STATIC[self.path.split("?")[0]]
                with open(os.path.join(DIR, name), "rb") as f:
                    self.send(200, f.read(), content_type)
            elif self.path in JSON_ROUTES:
                self.send(200, JSON_ROUTES[self.path]())
            elif self.path.split("?")[0] == "/api/preview":
                image = images.preview()
                if image:
                    self.send(200, image, "image/jpeg")
                else:
                    self.send_response(204)   # nothing to capture (ambient screen)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
            elif self.path.startswith("/api/replays?"):
                login = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("login", [""])[0]
                try:
                    self.send(200, twitch.replays(login))
                except ValueError as e:
                    self.send(400, {"error": str(e)})
            elif SYSTEM and self.path == "/api/display":
                try:
                    self.send(200, display.info())
                except OSError as e:
                    self.send(503, {"error": str(e)})
            elif self.path.startswith("/api/youtube_search?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("q", [""])[0]
                try:
                    self.send(200, {"query": q, **youtube.yt_search(q)})
                except ValueError as e:
                    self.send(400, {"error": str(e)})
            elif self.path == "/api/jellyfin":
                try:
                    self.send(200, jellyfin.jellyfin_home())
                except (OSError, ValueError, KeyError) as e:
                    self.send(503, {"error": tr("Jellyfin unreachable: {error}", error=e)})
            elif self.path.startswith("/api/jellyfin_search?") or self.path.startswith("/api/jellyfin_series?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    if self.path.startswith("/api/jellyfin_search?"):
                        query = q.get("q", [""])[0]
                        self.send(200, {"query": query, "results": jellyfin.jellyfin_search(query)})
                    else:
                        self.send(200, jellyfin.jellyfin_series(q.get("id", [""])[0]))
                except (OSError, ValueError, KeyError) as e:
                    self.send(400, {"error": str(e)})
            elif self.path.split("?")[0] == "/api/jellyfin_link":
                # Jellyfin server, Quick Connect in progress; ?find=1: the servers that answer on the network
                self.send(200, jellyfin.link_state(find="find=1" in self.path))
            elif self.path == "/api/plex":
                try:
                    self.send(200, plex.plex_home())
                except (OSError, ValueError, KeyError) as e:
                    self.send(503, {"error": tr("Plex unreachable: {error}", error=e)})
            elif self.path.startswith("/api/plex_search?") or self.path.startswith("/api/plex_series?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    if self.path.startswith("/api/plex_search?"):
                        query = q.get("q", [""])[0]
                        self.send(200, {"query": query, "results": plex.plex_search(query)})
                    else:
                        self.send(200, plex.plex_series(q.get("id", [""])[0]))
                except (OSError, ValueError, KeyError) as e:
                    self.send(400, {"error": str(e)})
            elif self.path.startswith("/api/youtube_channel?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("id", [""])[0]
                try:
                    self.send(200, youtube.yt_channel_videos(q))
                except ValueError as e:
                    self.send(400, {"error": str(e)})
            elif SYSTEM and self.path == "/api/ssh":
                self.send(200, system.ssh_status(local=self.client_address[0] == "127.0.0.1"))
            elif SYSTEM and self.path.startswith("/api/backup/download"):
                # Companion app: backup file saved on the phone
                data = backup.create()
                self.send_response(200)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition", f'attachment; filename="{backup.file_name()}"')
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            elif self.path == "/api/events":
                try:
                    self.send(200, twitch.events_for_page())
                except (OSError, ValueError, KeyError) as e:
                    self.send(503, {"error": tr("Twitch unreachable: {error}", error=e)})
            elif self.path == "/api/follows":
                try:
                    self.send(200, twitch.follows_status())
                except (OSError, ValueError, KeyError) as e:
                    self.send(503, {"error": tr("Twitch unreachable: {error}", error=e)})
            elif self.path.startswith("/api/qr?"):
                text = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("text", [""])[0]
                self.send(200, {"rows": ambient.qr_rows(text)})
            elif SYSTEM and self.path == "/api/branches":   # direct update: the repository's branches
                self.send(200, {"branches": system.branches()})
            elif self.path == "/api/account":
                with twitch.account_lock:
                    self.send(200, dict(twitch.account))
            else:
                self.send(404, {"error": tr("not found")})
        except (OSError, ValueError) as e:
            self.send(503, {"error": tr("box unreachable: {error}", error=e)})

    def do_POST(self):
        if not self.path.startswith("/api/"):
            return self.send(404, {"error": tr("not found")})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if SYSTEM and self.path.startswith("/api/local_update_upload?"):   # companion app: a file of a local system update
                kind = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("file", [""])[0]
                localupdate.receive(kind, self.rfile, length)
                return self.send(200, {"ok": True})
            if SYSTEM and self.path == "/api/backup_restore":   # companion app: raw backup file, then restart
                if length > backup.MAX_SIZE:
                    raise ValueError(tr("File too large for a backup."))
                backup.restore_upload(self.rfile.read(length))
                return self.send(200, {"ok": True})
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            if SYSTEM and self.path[len("/api/"):] in system.LOCAL_ONLY and self.client_address[0] != "127.0.0.1":
                return self.send(403, {"error": tr("Access setting: only from the TV menu.")})
            actions.action(self.path[len("/api/"):], body)
            self.send(200, {"ok": True})
        except ValueError as e:
            self.send(400, {"error": str(e)})
        except OSError as e:
            self.send(503, {"error": tr("box unreachable: {error}", error=e)})

    def log_message(self, *args):
        pass   # no per-request log
