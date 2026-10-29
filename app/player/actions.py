"""Stream Box: actions of the companion app API (POST /api/<name> with a JSON body), also used by the TV menu, ui.py and
mqtt_bridge.py. One small handler per action in ACTIONS; a refused request raises ValueError (HTTP 400). Standard
library only.
"""
import re, subprocess, time

import ambient    # ambient.py: remote URL, first setup
import history    # history.py: history edits
import i18n       # i18n.py: interface language (locales/<lang>.json), tr()
import jellyfin   # jellyfin.py: Jellyfin playback
import playback   # playback.py: videos started from a link
import plex       # plex.py: Plex server, playback
import settings   # settings.py: player, power button, background
import twitch     # twitch.py: streamers, polls and predictions, account, followed channels
import youtube    # youtube.py: channels, account, "TV app" access
from common import mpv
from i18n import tr
# The box's system part (sound output, backup, Bluetooth, resolution, installation, local update, Wi-Fi, power, SSH,
# developer mode, updates): None in the Stream Player, whose actions below are then unknown
from sysparts import SYSTEM, audio, backup, btsetup, display, installer, localupdate, netsetup, system

keyboard = {}   # TV menu search keyboard: {open, text, target, at}


def channel(body):
    # Streamer from the list, or followed channel (Following tab of the TV menu)
    if body.get("name") not in twitch.read_streamers() and body.get("name") not in twitch.follows_logins():
        raise ValueError(tr("unknown streamer"))
    mpv(["script-message", "streambox-channel", body["name"]])


def play_url(body):
    playback.play(playback.find_url(str(body.get("url", ""))), bool(body.get("from_start")),
                  str(body.get("title") or "")[:200] or None, str(body.get("thumb") or "")[:500] or None,
                  body.get("start") if isinstance(body.get("start"), (int, float)) else None)


def live_seek(body):
    target = body.get("delta")
    arg = "live" if target == "live" else str(max(-600, min(600, int(target or 0))))
    mpv(["script-message", "streambox-live-seek", arg])


def flag(body):
    # Yes / no settings of stream-box.lua: night mode (compressed sound), polls and predictions panel
    if body.get("key") not in ("night", "events"):
        raise ValueError(tr("unknown setting"))
    mpv(["script-message", "streambox-flag", body["key"], "yes" if body.get("enabled") else "no"])


def pip(body):
    # Second stream (Qt app): open <channel> [pip|split], close, swap, layout <pip|split>
    action = str(body.get("action", ""))
    if action not in ("open", "close", "swap", "layout"):
        raise ValueError(tr("unknown action"))
    login = str(body.get("name", "")).strip().lower()
    if action == "open" and not re.fullmatch(r"[a-z0-9_]{2,25}", login):
        raise ValueError(tr("invalid channel"))
    mpv(["script-message", "streambox-pip", action, login, str(body.get("layout", "pip"))])


def qr(body):
    # Display of the companion app QR code on the TV
    if body.get("mode") not in ("always", "timed", "never"):
        raise ValueError(tr("unknown mode"))
    mpv(["script-message", "streambox-qr", body["mode"]])


def set_number(body):
    # Bounds and saving handled by stream-box.lua (set_number)
    if body.get("key") not in ("chat_bg", "chat_size", "sub_size", "sub_bg"):
        raise ValueError(tr("unknown setting"))
    mpv(["script-message", "streambox-set", body["key"], str(int(body.get("value", 0)))])


def youtube_login(body):
    """YouTube account (subscriptions, recommendations, progress): a code to type on google.com/device"""
    d = youtube.yt_tv("/login", {}, timeout=15)
    if not d or d.get("error"):
        raise ValueError(tr("Unable to connect: {error}",
                            error=(d or {}).get("error") or tr("cast service stopped")))


def youtube_logout(body):
    youtube.yt_tv("/logout", {})
    youtube.yt_tv_cache.update(at=0.0, data={})


def poweroff(body):
    # mode: "suspend" (Sleep), "full" (Turn off the box, TV menu); otherwise the setting
    mode = str(body.get("mode") or "")
    system.power("suspend" if mode == "suspend" else "poweroff" if mode == "full" else settings.power_action())


def key(body):
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


def bluetooth(body):
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


def language(body):
    # Interface language (companion app, TV): {"lang": "en" | "fr" …}; the TV reloads its texts right away
    i18n.set_language(str(body.get("lang", "")))
    mpv(["script-message", "streambox-language", i18n.language()])


def backup_usb(body):
    # TV System menu: {"action": "save_usb", "path"}, {"action": "restore_usb", "path", "name"}
    what, path = str(body.get("action", "")), str(body.get("path", ""))[:100]
    if what == "save_usb":
        backup.save_usb(path)
    elif what == "restore_usb":
        backup.restore_usb(path, str(body.get("name", ""))[:100])
    else:
        raise ValueError(tr("unknown action"))


def keymap(body):
    # Remote keys: learning wizard (stream-box.lua), or back to the default keys
    what = str(body.get("action", ""))
    if what not in ("wizard", "reset"):
        raise ValueError(tr("unknown action"))
    mpv(["script-message", "streambox-keymap-" + what])


def keyboard_state(body):
    # TV menu: search keyboard open or closed (the page then offers a text field)
    keyboard.update(open=bool(body.get("open")), text=str(body.get("text", ""))[:80],
                    target=str(body.get("target", ""))[:20], at=time.time())


def keyboard_input(body):
    # Page: text of the field, sent to the menu's keyboard; submit starts the search
    if not keyboard.get("open"):
        raise ValueError(tr("The TV keyboard is no longer open."))
    text = str(body.get("text", ""))[:80]
    keyboard["text"] = text
    mpv(["script-message", "streambox-tvmenu-text", text, "1" if body.get("submit") else "0"])
    if body.get("submit"):
        keyboard["open"] = False


def wifi(body):
    # {"action": "connect", "ssid", "password"}: join a network; {"action": "hotspot"}: setup mode
    if body.get("action") == "hotspot":
        netsetup.manual_hotspot()
    else:
        netsetup.connect(str(body.get("ssid", ""))[:64], str(body.get("password", ""))[:128])


def reboot(body):
    # Allowed by default for the TV session, elsewhere by the polkit rule (login1.reboot*)
    r = subprocess.run(["systemctl", "reboot"], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise ValueError(tr("Restart refused: {error}", error=r.stderr.strip() or r.returncode))


# Name in POST /api/<name> → handler(body)
ACTIONS = {
    "channel": channel,
    "chat": lambda body: mpv(["script-message", "streambox-toggle-chat"]),
    # the next corner clockwise, or {corner: tl | tr | br | bl}
    "corner": lambda body: mpv(["script-message", "streambox-cycle-corner"]
                               + ([body["corner"]] if body.get("corner") in ("tl", "tr", "br", "bl") else [])),
    "play": play_url,
    "history": lambda body: history.edit_history(str(body.get("action", "")), str(body.get("key", ""))),
    "twitch": lambda body: mpv(["script-message", "streambox-twitch"]),
    "home": lambda body: mpv(["script-message", "streambox-home"]),
    "streamers": lambda body: twitch.edit_streamers(str(body.get("action", "")), str(body.get("login", "")),
                                                    int(body.get("delta", 0))),
    "live_seek": live_seek,
    "auto_switch": lambda body: mpv(["script-message", "streambox-auto-switch",
                                     "yes" if body.get("enabled") else "no"]),
    "backdrop": settings.set_backdrop,   # {"base", "overlay", "color"} (one or more)
    "flag": flag,
    "pip": pip,
    "vote": lambda body: twitch.vote_poll(str(body.get("poll", "")), str(body.get("choice", ""))),
    "predict": lambda body: twitch.predict(str(body.get("event", "")), str(body.get("outcome", "")),
                                           int(body.get("points", 0))),
    "player": lambda body: settings.set_player(str(body.get("mode", ""))),
    "jellyfin_play": lambda body: jellyfin.jellyfin_play(str(body.get("id", "")), bool(body.get("from_start"))),
    "jellyfin_link": jellyfin.link_action,   # Quick Connect sign-in ({address}), cancel, forget the server
    "plex_play": lambda body: plex.plex_play(str(body.get("id", "")), bool(body.get("from_start"))),
    "plex": lambda body: plex.set_plex(str(body.get("address", "")), str(body.get("token", ""))),   # server (empty: forget)
    # Plex account by code (plex.tv/link): start, or give up
    "plex_link": lambda body: plex.link_cancel() if body.get("action") == "cancel" else plex.link_start(),
    "youtube_channels": lambda body: youtube.edit_yt_channels(str(body.get("action", "")),
                                                              str(body.get("channel", "")), int(body.get("delta", 0))),
    "qr": qr,
    "set": set_number,
    "volume": lambda body: mpv(["add", "volume", max(-20, min(20, int(body.get("delta", 0))))]),
    "mute": lambda body: mpv(["cycle", "mute"]),
    "pause": lambda body: mpv(["cycle", "pause"]),
    "login": lambda body: twitch.login(str(body.get("token", ""))),
    "logout": lambda body: twitch.logout(),
    "follows_app": lambda body: twitch.set_twitch_app(str(body.get("client_id", "")),
                                                      str(body.get("client_secret", ""))),
    "follows_login": lambda body: twitch.follows_start(),
    "follows_logout": lambda body: twitch.follows_logout(),
    "youtube_login": youtube_login,
    "youtube_logout": youtube_logout,
    "youtube_sync": lambda body: youtube.yt_reload(),
    "key": key,
    "language": language,
    "setup": lambda body: ambient.finish_setup(),   # phone page: "Finish" of the first setup
    "keymap": keymap,
    "keyboard": keyboard_state,
    "keyboard_input": keyboard_input,
    "remote_url": lambda body: ambient.set_remote_url(str(body.get("url", ""))[:300]),
}
if SYSTEM:   # the box's system (the Stream Player leaves it to its OS: these actions are unknown there)
    ACTIONS.update({
        # direct: developer mode, from a branch (main by default)
        "update": lambda body: system.start_update(bool(body.get("direct")), str(body.get("branch") or "main")),
        "update_check": lambda body: system.check_update(),   # "Check for updates"
        "update_deps": lambda body: system.update_deps(),   # "Update dependencies" (Settings → Advanced)
        "apply_update": lambda body: system.apply_update(),   # "Restart now" for an update waiting for the user
        "dismiss_update": lambda body: system.dismiss_update(),   # "Don't ask again" (for that update)
        "display": lambda body: display.apply(str(body.get("mode", "auto"))),
        "poweroff": poweroff,
        "bluetooth": bluetooth,
        "ssh": lambda body: system.set_ssh(bool(body.get("enabled"))),
        "dev": lambda body: system.set_dev(bool(body.get("enabled"))),
        # TV System menu: {"disk": "nvme0n1"}; the disk is entirely erased
        "install": lambda body: installer.start(str(body.get("disk", ""))[:32]),
        "backup": backup_usb,
        # System update from a local image: {"action": "usb", "path", "name"} (copied from the drive, then installed), or
        # {"action": "start"} once the companion app sent the files
        "local_update": lambda body: localupdate.from_usb(str(body.get("path", ""))[:100], str(body.get("name", ""))[:120])
                        if body.get("action") == "usb" else localupdate.start(),
        # Sound output: "auto" or the identifier of an output from GET /api/audio
        "audio": lambda body: audio.set_choice(str(body.get("output", "auto"))[:200]),
        "wifi": wifi,
        "reboot": reboot,
        "power_action": lambda body: settings.set_power_action(str(body.get("mode", ""))),
    })


def action(name, body):
    handler = ACTIONS.get(name)
    if not handler:
        raise ValueError(tr("unknown action"))
    handler(body)
