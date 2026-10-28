"""Quick menu of the simplified version (mpv alone, without the Qt app): lists of text that stream-box.lua draws
(user-data/streambox/quickmenu: title, items {label, info, on, dim}, sel, note; {} when closed), built here from the
same functions as the TV menu. stream-box.lua sends the keys as "script-message streambox-qm open | close | key <name>",
received on a connection of its own to mpv's IPC (script messages reach the IPC clients as "client-message" events).

A screen is {title, build, items, sel}: build() returns its items, run in a thread (network) when the screen opens
and again after an action that changes it. An item is {label, info, on, dim, do}: do() returns a screen to open, or
None (the menu was closed, or a setting changed and the screen is rebuilt).
"""
import json, socket, threading, time

import actions    # actions.py: language, restart
import ambient    # ambient.py: companion app address
import audio      # audio.py: sound outputs
import display    # display.py: screen resolution
import history    # history.py: history file, resume thresholds
import i18n       # i18n.py: interface language
import jellyfin   # jellyfin.py: library, playback
import playback   # playback.py: links, history entries
import plex       # plex.py: library, playback
import settings   # settings.py: back to the full version
import system     # system.py: sleep, shutdown, system update
import twitch     # twitch.py: streamers, who is live, followed channels, replays
import youtube    # youtube.py: favorites, subscriptions
from common import MPV_SOCKET, mpv
from i18n import tr

CORNERS = {"tl": "↖ top left", "tr": "↗ top right", "br": "↘ bottom right", "bl": "↙ bottom left"}   # (stream-box.lua)
STATE = "user-data/streambox/quickmenu"
lock = threading.RLock()
stack = []   # open screens, the last one is shown
note = ""    # error of the last action, shown under the list


def item(label, do=None, info="", on=False, dim=False):
    return {"label": label, "do": do, "info": info, "on": on, "dim": dim}


def screen(title, build):
    return {"title": title, "build": build, "items": None, "sel": 0}


def clock(seconds):
    s = int(seconds or 0)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def viewers(n):
    n = int(n or 0)
    return (f"{n / 1000:.1f} k".replace(".", "," if i18n.language() == "fr" else ".") if n >= 1000 else str(n))


def resumable(position, duration, finished=False):
    return bool(position) and position >= history.RESUME_MIN and not finished and not history.finished(position, duration)


def send(*command):
    """Action of an item that changes a setting: the screen is then rebuilt"""
    mpv(list(command))


def player_state():
    try:
        return mpv(["get_property", "user-data/streambox"])[0] or {}
    except (OSError, ValueError):
        return {}


# Playback: the menu closes first (the TV shows the loading screen right away)

def play_url(url, title=None, thumb=None, from_start=False):
    return lambda: playing(lambda: playback.play(playback.find_url(url), from_start, title, thumb))


def playing(start):
    close()
    try:
        start()
    except (OSError, ValueError, KeyError) as e:
        mpv(["show-text", tr("Playback failed: {error}", error=e), 5000])
    return None


def choose(name, position, duration, finished, play, more=()):
    """A video: plays it, or asks resume / from the beginning when it was left midway"""
    if not resumable(position, duration, finished):
        return lambda: play(True)() if not more else screen(name, lambda: [
            item(tr("↺  Watch again") if finished else tr("▶  Play"), play(True)), *more])
    return lambda: screen(name, lambda: [
        item(tr("▶  Resume at {time}", time=clock(position)), play(False)),
        item(tr("↺  From the beginning"), play(True)), *more])


def video_items(videos, extra=lambda v: ""):
    """YouTube videos, replays, history: {title, url, thumb, seconds, position, finished}"""
    out = []
    for v in videos:
        dur = v.get("seconds") or v.get("duration") or 0
        info = " · ".join(x for x in (extra(v), clock(dur) if dur else "",
                                      "✓" if v.get("finished") else f"{round(100 * v['position'] / dur)} %"
                                      if dur and resumable(v.get("position"), dur) else "") if x)
        out.append(item(v.get("title") or v.get("url", ""), choose(
            v.get("title") or "", v.get("position"), dur, v.get("finished"),
            lambda from_start, v=v: play_url(v["url"], v.get("title"), v.get("thumb"), from_start)), info))
    return out or [item(tr("Nothing here"), dim=True)]


# Twitch

def live_screen():
    def build():
        st, live = player_state(), twitch.live_now
        out = []
        for login in twitch.read_streamers():
            info = live.get(login)
            out.append(item(login, lambda login=login: playing(lambda: mpv(["script-message", "streambox-channel", login])),
                            "● " + " · ".join(x for x in (viewers(info.get("viewers")), info.get("game") or "") if x)
                            if info else tr("Offline"),
                            on=st.get("mode") == "twitch" and st.get("channel") == login, dim=not info))
        out.sort(key=lambda i: i["dim"])   # live first, in the order of the list
        if not out:
            out.append(item(tr("The list is empty: add streamers from the companion app."), dim=True))
        out.append(item(tr("Chat"), lambda: send("script-message", "streambox-toggle-chat"),
                        tr("Shown") if st.get("chat_visible", True) else tr("Hidden")))
        out.append(item(tr("Chat corner"), lambda: send("script-message", "streambox-cycle-corner"),
                        tr(CORNERS.get(st.get("corner"), CORNERS["bl"]))))
        return out
    return screen(tr("Live"), build)


def follows_screen():
    def build():
        d = twitch.follows_status()
        out = [item(f["login"], lambda login=f["login"]: playing(lambda: mpv(["script-message", "streambox-channel", login])),
                    "● " + " · ".join(x for x in (viewers(f.get("viewers")), f.get("game") or "") if x))
               for f in d.get("live") or []]
        return out or [item(tr("No followed channel is live"), dim=True)]
    return screen(tr("Following"), build)


def replays_screen():
    def build():
        return [item(login, lambda login=login: screen(login, lambda: video_items(twitch.replays(login).get("vods") or [])))
                for login in twitch.read_streamers()] or [item(tr("Nothing here"), dim=True)]
    return screen(tr("Replays"), build)


# YouTube

def youtube_screen():
    def build():
        d = youtube.youtube_home()
        out = []
        rec = d.get("recommended") or []
        if rec:
            out.append(item(tr("Recommended for you"), lambda: screen(tr("Recommended for you"), lambda: video_items(
                rec, lambda v: v.get("channel") or "")), str(len(rec))))
        subs = d.get("subs") or {}
        if subs.get("videos"):
            out.append(item(tr("Subscriptions"), lambda: screen(tr("Subscriptions"), lambda: video_items(
                subs["videos"], lambda v: v.get("channel") or "")), str(len(subs["videos"]))))
        for c in d.get("channels") or []:
            out.append(item(c["name"], lambda c=c: screen(c["name"], lambda: video_items(c.get("videos") or [])),
                            str(len(c.get("videos") or []))))
        out.append(item(tr("Search: from the companion app"), dim=True))
        return out
    return screen("YouTube", build)


# Jellyfin and Plex: same card fields (jellyfin.py, plex.py)

LIBS = {"jellyfin": (jellyfin.jellyfin_home, jellyfin.jellyfin_series, jellyfin.jellyfin_play),
        "plex": (plex.plex_home, plex.plex_series, plex.plex_play)}


def lib_items(service, cards, series_id=None):
    _, series, play = LIBS[service]
    out = []
    for c in cards:
        name = f"{c['title']} · {c['episode']}" if c.get("episode") else c["title"]
        if c.get("type") in ("Series", "Season"):
            out.append(item(c["title"], lambda c=c: series_screen(service, c["series"], c["title"]), "☰"))
            continue
        more = [item(tr("☰  All episodes"), lambda c=c: series_screen(service, c["series"], c["title"]))] \
            if c.get("type") == "Episode" and c.get("series") and c["series"] != series_id else []
        info = " · ".join(x for x in (str(c.get("year") or "") if c.get("type") == "Movie" else "",
                                      clock(c["seconds"]) if c.get("seconds") else "",
                                      "✓" if c.get("finished") else "") if x)
        out.append(item(name, choose(name, c.get("position"), c.get("seconds"), c.get("finished"),
                                     lambda from_start, c=c: lambda: playing(lambda: play(c["id"], from_start)), more),
                        info))
    return out or [item(tr("Nothing here"), dim=True)]


def series_screen(service, series_id, title):
    s = screen(title, None)

    def build():
        d = LIBS[service][1](series_id)
        s["sel"] = d.get("first") or 0   # first episode not watched yet
        return lib_items(service, d.get("episodes") or [], series_id)
    s["build"] = build
    return s


def lib_screen(service, title):
    def build():
        d = LIBS[service][0]()
        rows = [(tr("Continue watching"), d.get("resume")), (tr("Next up"), d.get("nextup"))]
        rows += [(lib["name"], lib.get("items")) for lib in d.get("libraries") or []]
        return [item(name, lambda name=name, cards=cards: screen(name, lambda: lib_items(service, cards)), str(len(cards)))
                for name, cards in rows if cards] or [item(tr("Nothing here"), dim=True)]
    return screen(title, build)


# History, settings, system

def history_screen():
    def build():
        return video_items(history.read_history()[:100], lambda v: "Twitch" if (v.get("kind") or "").startswith("twitch")
                           else {"youtube": "YouTube", "jellyfin": "Jellyfin", "plex": "Plex"}.get(v.get("kind"), ""))
    return screen(tr("History"), build)


def pick(title, options, current, apply):
    """Settings with a list of values: options [(value, label)], the current one is marked"""
    def build():
        cur = current()
        def set_to(value):
            apply(value)   # (returns what it applied: not a screen)
        return [item(label, lambda value=value: set_to(value), on=value == cur) for value, label in options()]
    return lambda: screen(title, build)


def settings_screen():
    def sound():
        outs = audio.outputs()
        return item(tr("Sound output"), pick(tr("Sound output"),
                                             lambda: [("auto", tr("Automatic"))] + [(o["id"], o["label"]) for o in outs],
                                             audio.choice, audio.set_choice),
                    next((o["label"] for o in outs if o["id"] == audio.choice()), tr("Automatic")))

    def resolution():
        return item(tr("Screen resolution"), pick(tr("Screen resolution"),
                                                  lambda: [("auto", tr("Automatic"))] + [(m, m) for m in display.info()["modes"]],
                                                  lambda: display.info()["setting"], display.apply),
                    display.info().get("current") or "")

    def build():
        out = []
        for row in (sound, resolution):   # one failing (no sound server, no wlr-randr) leaves the others
            try:
                out.append(row())
            except (OSError, ValueError, KeyError) as e:
                out.append(item(tr("Unavailable: {error}", error=e), dim=True))
        st = player_state()
        return out + [
            item(tr("Language"), pick(tr("Language"), lambda: list(i18n.LANGUAGES.items()), i18n.language, set_language),
                 i18n.LANGUAGES.get(i18n.language(), "")),
            item(tr("Chat"), lambda: send("script-message", "streambox-toggle-chat"),
                 tr("Shown") if st.get("chat_visible", True) else tr("Hidden")),
        ]
    return screen(tr("Settings"), build)


def set_language(lang):
    actions.language({"lang": lang})   # (the titles of the screens already open stay in the previous one)


def power_screen():
    def act(fn):
        def run():
            close()
            try:
                fn()
            except (OSError, ValueError) as e:
                mpv(["show-text", str(e), 5000])
        return run
    # Restart and shut down ask a second OK (a screen of their own; Back cancels), as in the full TV menu
    def confirm(label, fn):
        return lambda: screen(label, lambda: [item(label, act(fn))])
    return screen(tr("Turn off or restart"), lambda: [
        item(tr("☾  Sleep"), act(lambda: system.power("suspend"))),
        item(tr("↻  Restart"), confirm(tr("↻  Restart"), lambda: actions.reboot({}))),
        item(tr("⏻  Shut down"), confirm(tr("⏻  Shut down"), lambda: system.power("poweroff"))),
    ])


def update_item():
    """System update, as in the TV menu's Settings → Updates: restart onto the version installed and waiting (a plain
    restart keeps the running one), install the release the daily check found, or check now"""
    s = system.system_update()
    if not s:
        return None
    pending, last, _ = system.waiting_update()

    def run(fn, text):
        def go():
            close()
            try:
                fn()
                mpv(["show-text", text, 5000])
            except (OSError, ValueError) as e:
                mpv(["show-text", str(e), 5000])
        return go
    if s.get("running") or s.get("checking"):
        return item(tr("Update in progress…") if s.get("running") else tr("Checking…"), dim=True)
    if pending:
        return item(tr("Restart to apply version {version}", version=last["new"]) if last.get("new") else
                    tr("Restart to apply the update"), run(system.apply_update, tr("Restarting…")))
    if s.get("offered"):
        return item(tr("Install version {version}", version=s["offered"]),
                    run(system.start_update, tr("Downloading version {version}. The box restarts by itself once it is installed (not during a video).",
                                                version=s["offered"])))
    if s.get("usb"):   # running from a USB stick: install it on the PC to get system updates (full version)
        return item(tr("Install on this PC to get updates"), dim=True)
    return item(tr("Check for updates"), run(system.check_update, tr("Checking…")),
                info="v" + s["version"] if s.get("version") else "")


def system_screen():
    def build():
        return [x for x in [
            update_item(),
            item(tr("Switch to the full version"), lambda: playing(lambda: settings.set_player("qt"))),
            item(tr("Turn off or restart"), power_screen),
            item(tr("Companion app"), info=ambient.remote_url() or "", dim=True),
        ] if x]
    return screen(tr("System"), build)


def root():
    def build():
        out = [item(tr("Live"), live_screen)]
        if twitch.follows_logins():
            out.append(item(tr("Following"), follows_screen))
        out += [item(tr("Replays"), replays_screen), item("YouTube", youtube_screen)]
        if jellyfin.jf_server():
            out.append(item("Jellyfin", lambda: lib_screen("jellyfin", "Jellyfin")))
        if plex.px_config():
            out.append(item("Plex", lambda: lib_screen("plex", "Plex")))
        out += [item(tr("History"), history_screen),
                item(tr("⌂ Home screen"), lambda: playing(lambda: mpv(["script-message", "streambox-home"]))),
                item(tr("Settings"), settings_screen), item(tr("System"), system_screen)]
        return out
    return screen(tr("Menu"), build)


# State shown by stream-box.lua, keys

def publish():
    with lock:
        if not stack:
            data = {}
        else:
            s = stack[-1]
            items = s["items"] if s["items"] is not None else [item(tr("Loading…"), dim=True)]
            data = {"title": " › ".join(x["title"] for x in stack[1:]) or s["title"],
                    "items": [{k: i[k] for k in ("label", "info", "on", "dim")} for i in items],
                    "sel": s["sel"], "note": note}
    try:
        mpv(["set_property", STATE, data])
    except (OSError, ValueError):
        pass


def load(s):
    """Builds a screen's items (network: in a thread); the screen may have been closed in the meantime"""
    try:
        items = s["build"]()
    except Exception as e:   # whatever a service raises, the menu stays usable
        items = [item(tr("Unavailable: {error}", error=e), dim=True)]
    with lock:
        s["items"] = items
        s["sel"] = max(0, min(s["sel"], len(items) - 1))
        if s is not (stack[-1] if stack else None):
            return
    publish()


def push(s):
    with lock:
        stack.append(s)
    publish()
    threading.Thread(target=load, args=(s,), daemon=True).start()


def close():
    with lock:
        stack.clear()
    publish()


def activate(it):
    global note
    note = ""
    try:
        result = it["do"]()
    except (OSError, ValueError, KeyError) as e:
        note = str(e)
        return publish()
    if isinstance(result, dict):
        push(result)
    elif stack:   # a setting changed: the screen shows it
        load(stack[-1])


def key(name):
    with lock:
        if not stack:
            return
        s = stack[-1]
        items = s["items"] or []
        if name in ("up", "down") and items:
            s["sel"] = (s["sel"] + (1 if name == "down" else -1)) % len(items)
        elif name in ("ok", "right") and s["sel"] < len(items) and items[s["sel"]]["do"]:
            it = items[s["sel"]]
            threading.Thread(target=activate, args=(it,), daemon=True).start()
            return
        elif name in ("back", "left"):
            stack.pop()
            if stack:
                threading.Thread(target=load, args=(stack[-1],), daemon=True).start()   # up to date (positions…)
        elif name in ("home", "menu"):
            stack.clear()
        else:
            return
    publish()


def on_message(args):
    global note
    if not args or args[0] != "streambox-qm":
        return
    if args[1:2] == ["open"]:
        note = ""
        with lock:
            stack.clear()
        push(root())
    elif args[1:2] == ["close"]:
        close()
    elif args[1:2] == ["key"] and len(args) > 2:
        key(args[2])


def listen_loop():
    """Connection of its own to mpv: the script messages of stream-box.lua (mpv restarted: reconnects)"""
    while True:
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.connect(MPV_SOCKET)
                with lock:
                    stack.clear()   # new player: nothing open
                buf = b""
                while True:
                    data = s.recv(65536)
                    if not data:
                        break
                    *lines, buf = (buf + data).split(b"\n")
                    for line in lines:
                        msg = json.loads(line)
                        if msg.get("event") == "client-message":
                            on_message(msg.get("args") or [])
        except (OSError, ValueError):
            pass
        time.sleep(2)
