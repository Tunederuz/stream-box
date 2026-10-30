#!/usr/bin/env python3
"""Owlink: full-screen app (Qt Quick) embedding mpv (libmpv).

Replaces the mpv window in the cage session: the video is drawn by libmpv in the Qt Quick scene (OpenGL,
GPU), and QML interface elements can sit on top of it with real animations. The
player keeps doing everything it did: same options as the mpv command line (passed as is by
start.sh), Lua scripts, IPC socket (companion app, Jellyfin, Home Assistant). Keys and mouse received by the
window are forwarded to mpv (keypress, mouse), where stream-box.lua expects them.

Two streams at once: a second libmpv player (pip_player) with its own streamlink, drawn as an inset in
a corner or side by side with the main one (ui.qml, animated transitions). Driven by the QML menu ("pip" object) and by
IPC (script-message streambox-pip <open|close|swap|layout> [channel] [pip|split], /api/pip of remote.py); state published
in user-data/streambox/pip. Sound muted: the sound is the main stream's (Swap exchanges the two).

Live preview: a third libmpv player (preview_player), muted, plays the live of the channel chosen in the TV menu's
Live or Following tab, in the menu's background ("livePreview" object, driven by qml/TvMenu.qml, through its own streamlink).

The big TV menu is in QML (qml/TvMenu.qml; if it fails to load, stream-box.lua opens its small menu): the Menu button
(script-message streambox-tvmenu-open from stream-box.lua) opens it, and while it is open keys go to it, not to
mpv. It reads and acts through the remote.py API, like the companion app.

Run with the Python of the ui-venv venv (PySide6, python-mpv): ui.py --input-ipc-server=… --script=… <other options>
"""
import ctypes, faulthandler, json, locale, os, queue, re, signal, subprocess, sys, threading, time

from PySide6.QtCore import Property, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtOpenGL import QOpenGLFramebufferObject
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickFramebufferObject, QQuickView, QQuickWindow, QSGRendererInterface

import mpv

import chat_qt   # chat with emotes (same folder)
import common    # common.py: built-in battery
from sysparts import SYSTEM   # False: the Owlink app (an app on an OS that runs itself)

DIR = os.path.dirname(os.path.abspath(__file__))
CURSOR_HIDE_MS = 4000   # like mpv's --cursor-autohide=4000
# Owlink app on a desktop: an ordinary window (F11: full screen). Full screen on the box and in SteamOS's Game mode
WINDOWED = not SYSTEM and os.environ.get("XDG_CURRENT_DESKTOP", "").lower() != "gamescope"

# Qt keys → mpv key names (those stream-box.lua binds). Keys with no name in Qt (OK and Menu of the
# Xiaomi remote control) are forwarded by their keysym, under the name mpv gave them (see key_name).
KEYS = {
    Qt.Key_Up: "UP", Qt.Key_Down: "DOWN", Qt.Key_Left: "LEFT", Qt.Key_Right: "RIGHT",
    Qt.Key_Return: "ENTER", Qt.Key_Enter: "KP_ENTER", Qt.Key_Escape: "ESC", Qt.Key_Space: "SPACE",
    Qt.Key_Back: "GO_BACK", Qt.Key_HomePage: "HOMEPAGE", Qt.Key_WWW: "WWW",
    Qt.Key_MediaPlay: "PLAY", Qt.Key_MediaPause: "PAUSE", Qt.Key_MediaTogglePlayPause: "PLAYPAUSE",
    Qt.Key_MediaStop: "STOP", Qt.Key_MediaNext: "NEXT", Qt.Key_MediaPrevious: "PREV",
    Qt.Key_VolumeUp: "VOLUME_UP", Qt.Key_VolumeDown: "VOLUME_DOWN", Qt.Key_VolumeMute: "MUTE",
    Qt.Key_Backspace: "BS", Qt.Key_Tab: "TAB", Qt.Key_PageUp: "PGUP", Qt.Key_PageDown: "PGDWN",
    Qt.Key_Home: "HOME", Qt.Key_End: "END",
}
for n in range(1, 13):
    KEYS[getattr(Qt, f"Key_F{n}")] = f"F{n}"

# Keys with no name in Qt, recorded on the Xiaomi remote control: keysym → name mpv gave them (stream-box.lua binds them)
SPECIAL_KEYSYMS = {0x1008ffa0: "0x21ffa0",   # OK
                   0x10081246: "0x2111a0"}   # Menu ≡

# Keys for the big menu, same roles as KEYS in stream-box.lua
MENU_KEYS = {"UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right", "ENTER": "ok", "KP_ENTER": "ok",
             "0x21ffa0": "ok", "HOMEPAGE": "home", "TAB": "home", "GO_BACK": "back", "ESC": "back", "0x2111a0": "menu",
             "WWW": "homescreen", "PLAY": "corner", "PLAYPAUSE": "corner"}


# Learned keys (wizard of the System menu, written by stream-box.lua): re-read when the file changes
KEYMAP_FILE = os.path.expanduser("~/.config/stream-box/keymap.json")
input_service = {"beat": 0}   # last "I'm running" from input.py (user-data/streambox/input)
keymap_cache = {"mtime": None, "map": {}}


def learned_keys():
    try:
        mtime = os.path.getmtime(KEYMAP_FILE)
    except OSError:
        return {}
    if mtime != keymap_cache["mtime"]:
        try:
            with open(KEYMAP_FILE, encoding="utf-8") as f:
                keymap_cache.update(mtime=mtime, map=json.load(f))
        except (OSError, ValueError):
            keymap_cache.update(mtime=mtime, map={})
    return keymap_cache["map"]


def key_name(event):
    """mpv name of the key, or None to ignore it."""
    name = KEYS.get(event.key())
    if name:
        return name
    text = event.text()
    if text and text.isprintable():
        return text
    # Special key with no name in mpv: it named it "0x21" followed by the last 4 digits of its XF86 keysym
    # (OK of the Xiaomi remote control: keysym 0x1008ffa0 = XF86Select → "0x21ffa0", which stream-box.lua binds)
    sym = event.nativeVirtualKey()
    if sym in SPECIAL_KEYSYMS:
        return SPECIAL_KEYSYMS[sym]
    if sym:
        name = f"0x{0x210000 | (sym & 0xffff):x}" if sym >> 16 == 0x1008 else f"0x{sym:x}"
        print(f"unnamed key: keysym 0x{sym:x}, scancode {event.nativeScanCode()} → {name}", flush=True)
        return name
    return None


def parse_args(argv):
    """mpv command-line style options: (options before initialization, lists to append to, files)."""
    opts, appends, files, scripts = {}, [], [], []
    for arg in argv:
        if not arg.startswith("--"):
            files.append(arg)
            continue
        key, _, value = arg[2:].partition("=")
        if key == "script":
            scripts.append(value)
        elif key.endswith("-append"):
            appends.append((key[:-len("-append")], value))
        elif key in ("fs", "fullscreen", "cursor-autohide"):
            continue   # not applicable: the Qt window is the one in full screen
        elif key == "force-window":
            # Enabled only once rendering is ready (Bridge.ready): passed at startup, mpv cannot open its video
            # output yet and disables it. Without it, nothing is drawn when no video is playing: home
            # screen and offline channel stayed frozen on the last frame
            opts["__force_window"] = value if _ else "yes"
        else:
            opts[key] = value if _ else "yes"
    if scripts:
        opts["scripts"] = scripts   # assembled in main(), once the menu to use is known
    return opts, appends, files


class Bridge(QObject):
    """Events from the mpv thread → Qt thread"""
    frame = Signal()
    shutdown = Signal()
    ready = Signal()   # render context created


def set_flag(name, value):
    """Boolean in an mpv property (user-data): python-mpv would write the string "yes", which the chat and stream-box.lua
    do not take as true."""
    flag = ctypes.c_int(1 if value else 0)
    mpv._mpv_set_property(player.handle, name.encode(), mpv.MpvFormat.FLAG, ctypes.byref(flag))


class Box(QObject):
    """What the QML sees ("box"): menu opening, keys, mpv data useful to the menu"""
    openRequested = Signal()
    closeRequested = Signal()      # video started from elsewhere (phone, Cast…), keys wizard: menu closed
    keyPressed = Signal(str)
    textInput = Signal(str, bool)
    keyTyped = Signal(str)   # computer keyboard while the search keyboard is open: a character, "\b" or "\n"
    powerMenuRequested = Signal()   # power held (stream-box.lua): "sleep, restart, shut down" window    # text typed on the phone for the menu keyboard (text, start the search)
    ambientChanged = Signal()
    videoActiveChanged = Signal()
    homeChanged = Signal()
    batteryChanged = Signal()
    _ambient_in = Signal(str)        # from the mpv thread
    _video_in = Signal(bool)
    _home_in = Signal(str, str)      # home screen: key (ambient_on, status, qr), value as JSON

    def __init__(self):
        super().__init__()
        self.menu_open = False
        self._ambient, self._video = "{}", False
        self._home = {"ambient_on": False, "status": "", "qr": "always"}
        self._home_in.connect(self._set_home, Qt.QueuedConnection)
        self._ambient_in.connect(self._set_ambient, Qt.QueuedConnection)
        self._video_in.connect(self._set_video, Qt.QueuedConnection)
        # Built-in battery (Steam Deck, laptop), read every 30 s: home screen and menu header; "" without one
        self._battery = ""
        self._battery_timer = None
        self._read_battery()

    def start(self):
        """Timers, once the Qt application exists (box is created at import, before it: a QTimer made then never
        fires, and the battery stayed at its value from the start of the session)"""
        self._battery_timer = QTimer(self, interval=30000)
        self._battery_timer.timeout.connect(self._read_battery)
        self._battery_timer.start()

    def _read_battery(self):
        b = common.battery()
        value = json.dumps(b) if b else ""
        if value != self._battery:
            self._battery = value
            self.batteryChanged.emit()

    battery = Property(str, lambda self: self._battery, notify=batteryChanged)   # {percent, charging} (JSON) or ""

    def _set_ambient(self, value):
        if value != self._ambient:
            self._ambient = value
            self.ambientChanged.emit()

    def _set_home(self, key, value):
        self._home[key] = json.loads(value)
        self.homeChanged.emit()

    # Home screen (qml/AmbientScreen.qml): shown when stream-box.lua decides so, with its status message
    ambientOn = Property(bool, lambda self: bool(self._home["ambient_on"]), notify=homeChanged)
    statusText = Property(str, lambda self: self._home["status"] or "", notify=homeChanged)
    qrMode = Property(str, lambda self: self._home["qr"] or "always", notify=homeChanged)

    def _set_video(self, value):
        if value != self._video:
            self._video = value
            self.videoActiveChanged.emit()

    ambient = Property(str, lambda self: self._ambient, notify=ambientChanged)   # weather, QR code (JSON)
    videoActive = Property(bool, lambda self: self._video, notify=videoActiveChanged)

    @Slot(bool)
    def setMenuOpen(self, value):
        self.menu_open = value
        if chat:
            chat.set_menu_open(value)
        to_mpv(set_flag, "user-data/streambox/tvmenu", value)   # the chat hides, the mouse does not open the small menu

    typing = False

    @Slot(bool)
    def setTyping(self, value):
        """The menu's search keyboard is open: the computer's keys type in it (View.keyPressEvent)."""
        self.typing = value

    @Slot()
    def quit(self):
        """Owlink app: "Quit" of the TV menu. mpv quits, the app with it (shutdown event below)."""
        to_mpv(lambda: player.command("quit"))


box = Box()


bridge = Bridge()
player = None   # created in main(), before the window

# Calls to mpv from the Qt thread: never directly. A synchronous call can wait for mpv's video output, which
# waits for Qt's render thread, itself blocked by the main thread: everything freezes (seen when restarting the player,
# menu open: IPC socket cut, frozen picture). A separate thread runs them in order.
mpv_calls = queue.Queue()


def mpv_worker():
    while True:
        fn, args = mpv_calls.get()
        try:
            fn(*args)
        except Exception as e:   # mpv stopped, property refused…: carry on
            print(f"mpv call refused: {e}", flush=True)


def to_mpv(fn, *args):
    mpv_calls.put((fn, args))
# Frame buffers given to Qt: otherwise PySide would free them while Qt still uses them (crash in texture()).
# Qt destroys them itself when the size changes; we just keep the Python reference.
framebuffers = []


def wayland_display():
    """Wayland connection to give libmpv for hardware decoding (VA-API): without it, no VADisplay and
    decoding on the CPU. A connection separate from Qt's, which is enough for VA-API to find the GPU."""
    try:
        lib = ctypes.CDLL("libwayland-client.so.0")
        lib.wl_display_connect.restype = ctypes.c_void_p
        lib.wl_display_connect.argtypes = [ctypes.c_char_p]
        return lib.wl_display_connect(None) or None
    except OSError:
        return None


def x11_display():
    """Same for an X11 session (Owlink app in SteamOS's Game mode: gamescope only offers X11)."""
    try:
        lib = ctypes.CDLL("libX11.so.6")
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        return lib.XOpenDisplay(None) or None
    except OSError:
        return None


def egl_get_proc_address():
    libegl = ctypes.CDLL("libEGL.so.1")
    libegl.eglGetProcAddress.restype = ctypes.c_void_p
    libegl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
    return mpv.MpvGlGetProcAddressFn(lambda _ctx, name: libegl.eglGetProcAddress(name))


class MpvRenderer(QQuickFramebufferObject.Renderer):
    def __init__(self, item):
        super().__init__()
        self.item = item
        self.ctx = None
        self.proc = egl_get_proc_address()   # kept: mpv calls it from C

    def createFramebufferObject(self, size):
        if self.ctx is None:   # Qt's OpenGL context active here, in the render thread
            params = {"opengl_init_params": {"get_proc_address": self.proc}}
            display = wayland_display()
            if display:
                params["wl_display"] = ctypes.c_void_p(display)
            elif os.environ.get("DISPLAY") and (display := x11_display()):
                params["x11_display"] = ctypes.c_void_p(display)
            main = self.item.which == "main"
            source = {"pip": pip_player, "preview": preview_player}.get(self.item.which, player)
            self.ctx = mpv.MpvRenderContext(source, "opengl", **params)
            self.ctx.update_cb = self.item.frameReady.emit
            if main:
                bridge.ready.emit()
        fbo = QOpenGLFramebufferObject(size)
        framebuffers.append(fbo)
        return fbo

    def render(self):
        # update() acknowledges mpv's notification; no waiting for the frame's display time: blocked
        # in there, Qt's render thread froze everything at startup (one restart out of two or three)
        self.ctx.update()
        fbo = self.framebufferObject()
        self.ctx.render(flip_y=False, block_for_target_time=False,
                        opengl_fbo={"fbo": fbo.handle(), "w": fbo.width(), "h": fbo.height()})
        self.ctx.report_swap()


class MpvVideo(QQuickFramebufferObject):
    """Video of a libmpv player: which = "main" (default), "pip" (second stream) or "preview" (card preview)"""
    frameReady = Signal()   # from mpv, any thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self._which = "main"
        self.frameReady.connect(self.update, Qt.QueuedConnection)

    def _get_which(self):
        return self._which

    def _set_which(self, value):
        self._which = value

    which = Property(str, _get_which, _set_which)

    def createRenderer(self):
        return MpvRenderer(self)


PIP_PORT = 34590   # streamlink of the second stream (the main one takes 34501 to 34550, see stream-box.lua)
pip_player = None  # second libmpv player, created in main()


def set_node(name, value):
    """Structured value (dict) in an mpv property of the main player"""
    player._set_property(name, value)


class Pip(QObject):
    """Second stream: separate streamlink, pip_player player, "pip" (inset) or "split" layout"""
    changed = Signal()
    _request = Signal(str, str, str)   # from the mpv thread (IPC): action, channel, layout
    _main = Signal(str, str, str)      # channel, mode and chat corner of the main player
    _idle = Signal()                   # the second player has nothing left to play

    def __init__(self):
        super().__init__()
        self._channel, self._layout, self._corner = "", "", "bl"
        self.main_channel, self.main_mode, self.proc = "", "", None
        self.retry = QTimer(self, singleShot=True, interval=3000)
        self.retry.timeout.connect(self.load)
        self._request.connect(self.handle, Qt.QueuedConnection)
        self._main.connect(self.on_main, Qt.QueuedConnection)
        self._idle.connect(lambda: self._channel and not self.retry.isActive() and self.retry.start(3000),
                           Qt.QueuedConnection)

    channel = Property(str, lambda self: self._channel, notify=changed)
    layout = Property(str, lambda self: self._layout, notify=changed)
    chatCorner = Property(str, lambda self: self._corner, notify=changed)

    def handle(self, action, name, layout):
        if action == "open":
            self.open(name, layout)
        elif action == "close":
            self.close()
        elif action == "swap":
            self.swap()
        elif action == "layout":
            self.setLayout(layout)

    @Slot(str, str)
    def open(self, name, layout):
        name = (name or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{2,25}", name) or name == self.main_channel or self.main_mode != "twitch":
            return
        self.stop_stream()
        self._channel, self._layout = name, layout if layout in ("pip", "split") else "pip"
        # As an inset, 720p is enough and spares the network; side by side, the best quality
        quality = "best" if self._layout == "split" else "720p60,720p,best"
        self.proc = subprocess.Popen(
            ["streamlink", "--twitch-low-latency", "--retry-streams", "30", "--player-external-http",
             "--player-external-http-interface", "127.0.0.1", "--player-external-http-port", str(PIP_PORT),
             f"twitch.tv/{name}", quality], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.retry.start(2500)   # time for streamlink to open its server
        self.publish()

    def load(self):
        if self._channel:
            to_mpv(pip_player.command, "loadfile", f"http://127.0.0.1:{PIP_PORT}/")

    def stop_stream(self):
        self.retry.stop()
        if self.proc:
            self.proc.terminate()
            self.proc = None
        to_mpv(pip_player.command, "stop")

    @Slot()
    def close(self):
        if not self._channel:
            return
        self.stop_stream()
        self._channel, self._layout = "", ""
        self.publish()

    @Slot()
    def swap(self):
        """Swaps the two streams (and so the sound)"""
        if not self._channel or not self.main_channel:
            return
        new_main, new_pip, layout = self._channel, self.main_channel, self._layout
        self.close()
        self.main_channel = new_main
        to_mpv(player.command, "script-message", "streambox-channel", new_main)
        self.open(new_pip, layout)

    @Slot(str)
    def setLayout(self, layout):
        if self._channel and layout in ("pip", "split") and layout != self._layout:
            self._layout = layout
            self.publish()

    def on_main(self, channel, mode, corner):
        self.main_channel, self.main_mode = channel, mode
        if corner != self._corner:
            self._corner = corner
            self.changed.emit()
        # Home screen, video, or same streamer as the second one: the second stream is no longer needed
        if self._channel and (mode != "twitch" or channel == self._channel):
            self.close()

    def publish(self):
        self.changed.emit()
        to_mpv(set_node, "user-data/streambox/pip", {"channel": self._channel, "layout": self._layout})


pip = Pip()

preview_player = None  # third libmpv player: muted live in the TV menu's background, created in main()


PREVIEW_PORT = 34591   # streamlink of the live previews


class LivePreview(QObject):
    """Muted live of the channel chosen in the TV menu's Live or Following tab, played in the menu's background
    (qml/TvMenu.qml, bgLive): "twitch:<login>" through its own streamlink, loaded in preview_player once served; ready once its first
    frame is there"""
    changed = Signal()
    _ready_in = Signal(bool)   # from the mpv thread

    def __init__(self):
        super().__init__()
        self._ready = False
        self._ready_in.connect(self._set_ready, Qt.QueuedConnection)
        self.proc = None
        self.idle = True   # preview_player has nothing loaded (written from the mpv thread)
        self.tries = 0
        self.retry = QTimer(self, interval=1500)   # until streamlink serves the live
        self.retry.timeout.connect(self.load_live)

    ready = Property(bool, lambda self: self._ready, notify=changed)

    def _set_ready(self, value):
        if value != self._ready:
            self._ready = value
            self.changed.emit()

    @Slot(str)
    def play(self, login):
        self.stop()
        if not re.fullmatch(r"[a-z0-9_]{2,25}", login):
            return
        self.proc = subprocess.Popen(
            ["streamlink", "--twitch-low-latency", "--player-external-http", "--player-external-http-interface",
             "127.0.0.1", "--player-external-http-port", str(PREVIEW_PORT), f"twitch.tv/{login}",
             "720p,720p60,480p,best"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.tries = 0
        self.retry.start()

    def load_live(self):
        self.tries += 1
        if self._ready or self.tries > 6 or not self.proc:   # playing, or streamlink never served it (offline…)
            self.retry.stop()
            return
        if not self.idle:   # a load is under way
            return
        to_mpv(preview_player.command, "loadfile", f"http://127.0.0.1:{PREVIEW_PORT}/")

    @Slot()
    def stop(self):
        self._set_ready(False)
        self.retry.stop()
        if self.proc:
            self.proc.terminate()
            self.proc = None
        to_mpv(preview_player.command, "stop")


live_preview = LivePreview()


class ChatBridge(QObject):
    """Chat with emotes for qml/ChatOverlay.qml: messages from chat_qt.py, settings of the main player"""
    changed = Signal()
    messagesChanged = Signal()
    _messages_in = Signal(str)     # from the chat_qt threads
    _settings_in = Signal(str)     # from the mpv thread (settings JSON)

    def __init__(self):
        super().__init__()
        self._messages = "[]"
        self.settings = {"channel": "", "mode": "", "corner": "bl", "chat_visible": True, "chat_bg": 60,
                         "chat_size": 32}
        self.menu_open = False
        self._messages_in.connect(self._set_messages, Qt.QueuedConnection)
        self._settings_in.connect(self._set_settings, Qt.QueuedConnection)
        self.chat = chat_qt.Chat(lambda msgs: self._messages_in.emit(json.dumps(msgs)))

    def _set_messages(self, value):
        self._messages = value
        self.messagesChanged.emit()

    def _set_settings(self, value):
        self.settings.update(json.loads(value))
        self.chat.set_channel(self.settings["channel"] or None)
        self.changed.emit()

    def set_menu_open(self, value):
        self.menu_open = value
        self.changed.emit()

    messages = Property(str, lambda self: self._messages, notify=messagesChanged)
    corner = Property(str, lambda self: self.settings["corner"] or "bl", notify=changed)
    bg = Property(int, lambda self: int(self.settings["chat_bg"] or 0), notify=changed)
    size = Property(int, lambda self: int(self.settings["chat_size"] or 32), notify=changed)
    # Hidden: box unchecked, video or home screen, big menu open (like chat_overlay.py)
    visible = Property(bool, lambda self: bool(self.settings["chat_visible"]) and self.settings["mode"] == "twitch"
                       and not self.menu_open, notify=changed)


chat = None   # created in main(), with the Qt application


class Osd(QObject):
    """Info bar and playback bar, live notification, polls box, subtitles choice (qml/InfoBar.qml,
    Toast.qml, PollsOverlay.qml, TracksPanel.qml). stream-box.lua decides when they show (user-data/streambox/bar, toast); the playback
    position is read here, from a separate thread, 4 times per second while the bar is visible."""
    changed = Signal()
    _in = Signal(str, str)   # from the mpv threads: key, JSON value

    def __init__(self):
        super().__init__()
        self.data = {"bar": False, "toast": {}, "polls": {}, "storyboard": {}, "playback": {}, "live": {}, "tracks": {}, "loading": {}, "learn": {}, "meta": {}, "controls": {}, "seekfx": {},
                     "next_card": {}, "notice": {}, "info": {},
                     "mode": "", "channel": "", "events": True}
        self._in.connect(self._set, Qt.QueuedConnection)
        self.wake = threading.Event()   # bar just shown: read the position at once (InfoBar waits for it to appear)

    def _set(self, key, value):
        self.data[key] = json.loads(value)
        if key == "bar" and self.data[key]:
            self.wake.set()
        self.changed.emit()

    def new_file(self, _name, _path):
        """Another file (or none): the playback state of the previous one is dropped, the bar never shows it (from mpv's
        thread). Not when the bar hides: it keeps its values while fading out"""
        self._in.emit("playback", "{}")

    def receive(self, key):
        return lambda _n, v: self._in.emit(key, json.dumps(v if v is not None else self.data[key]))

    def poll_loop(self):
        while True:
            self.wake.wait(0.25 if self.data["bar"] else 1)
            self.wake.clear()
            if not self.data["bar"]:
                continue
            try:
                get = player._get_property
                cache = get("demuxer-cache-state") or {}
                ranges = cache.get("seekable-ranges") or []
                state = {"pos": get("time-pos"), "duration": get("duration"), "pause": get("pause"),
                         "cached": get("demuxer-cache-time"), "title": get("media-title"), "path": get("path") or "",
                         "window": [ranges[0]["start"], ranges[0]["end"]] if ranges else None,
                         "chapters": [{"time": c.get("time", 0), "title": c.get("title") or ""}
                                      for c in get("chapter-list") or []], "chapter": get("chapter")}
            except Exception:   # nothing playing, mpv restarting…
                continue
            self._in.emit("playback", json.dumps(state))

    bar = Property(str, lambda self: json.dumps({k: self.data[k] for k in ("bar", "playback", "live", "mode", "channel")}),
                   notify=changed)
    toast = Property(str, lambda self: json.dumps(self.data["toast"] or {}), notify=changed)
    polls = Property(str, lambda self: json.dumps(self.data["polls"] or {}), notify=changed)
    storyboard = Property(str, lambda self: json.dumps(self.data["storyboard"] or {}), notify=changed)
    tracks = Property(str, lambda self: json.dumps(self.data["tracks"] or {}), notify=changed)   # TracksPanel.qml
    loading = Property(str, lambda self: json.dumps(self.data["loading"] or {}), notify=changed)   # LoadingOverlay.qml
    learn = Property(str, lambda self: json.dumps(self.data["learn"] or {}), notify=changed)   # KeyWizard.qml
    # Playback bar: video info, row of buttons, seek shown; "Next episode" card (NextUp.qml)
    meta = Property(str, lambda self: json.dumps(self.data["meta"] or {}), notify=changed)
    controls = Property(str, lambda self: json.dumps(self.data["controls"] or {}), notify=changed)
    seekfx = Property(str, lambda self: json.dumps(self.data["seekfx"] or {}), notify=changed)
    nextCard = Property(str, lambda self: json.dumps(self.data["next_card"] or {}), notify=changed)
    notice = Property(str, lambda self: json.dumps(self.data["notice"] or {}), notify=changed)   # Notice.qml
    info = Property(str, lambda self: json.dumps(self.data["info"] or {}), notify=changed)   # InfoPanel.qml
    eventsOn = Property(bool, lambda self: self.data["events"] is not False, notify=changed)


osd = Osd()


class I18n(QObject):
    """Interface language for QML (see i18n.py): `dict` maps English texts to the current language; QML texts call
    tr("English text"), which reads i18n.dict, so they update by themselves when the language changes
    (script-message streambox-language from remote.py)"""
    changed = Signal()
    _reload = Signal()   # from the mpv thread

    def __init__(self):
        super().__init__()
        self._dict, self._lang = {}, "en"
        self._reload.connect(self.load, Qt.QueuedConnection)
        self.load()

    def load(self):
        import i18n
        self._lang = i18n.language()
        self._dict = i18n.catalog(self._lang)
        self.changed.emit()

    dict = Property("QVariantMap", lambda self: self._dict, notify=changed)
    lang = Property(str, lambda self: self._lang, notify=changed)


tr_dict = I18n()


class View(QQuickView):
    """Full-screen window: forwards keys and mouse to mpv, hides the cursor after 4 s without movement."""

    def __init__(self):
        super().__init__()
        self.setResizeMode(QQuickView.SizeRootObjectToView)
        self.setColor(Qt.black)
        self.hide_cursor = QTimer(self, singleShot=True, interval=CURSOR_HIDE_MS)
        self.hide_cursor.timeout.connect(lambda: self.setCursor(QCursor(Qt.BlankCursor)))
        if not WINDOWED:
            self.setCursor(QCursor(Qt.BlankCursor))

    def keyPressEvent(self, event):
        if box.menu_open and box.typing:
            if event.key() == Qt.Key_Backspace:
                return box.keyTyped.emit("\b")
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                return box.keyTyped.emit("\n")
            if event.text() and event.text().isprintable():
                return box.keyTyped.emit(event.text())
        if WINDOWED and event.key() == Qt.Key_F11:
            self.showNormal() if self.visibility() == QQuickView.FullScreen else self.showFullScreen()
            return
        if time.time() - input_service["beat"] < 15:   # input.py reads the keys at the source: nothing to do here
            return
        name = key_name(event)
        if not name:
            return
        if (learned_keys().get(name) or MENU_KEYS.get(name)) == "power" or name in ("POWER", "0x21ff2a"):
            # power: separate press and release, for the long press (stream-box.lua: window after 1 s)
            if not event.isAutoRepeat():
                to_mpv(player.command, "keydown", name)
            return
        menu_key = learned_keys().get(name) or MENU_KEYS.get(name)
        if box.menu_open and menu_key and menu_key != "power":   # QML menu open: the key is for it
            box.keyPressed.emit(menu_key)
            return
        # Repeat: one keypress per event, as mpv does for a held key
        to_mpv(player.command, "keypress", name)

    def keyReleaseEvent(self, event):
        if time.time() - input_service["beat"] < 15 or event.isAutoRepeat():
            return
        name = key_name(event)
        if name and ((learned_keys().get(name) or MENU_KEYS.get(name)) == "power" or name in ("POWER", "0x21ff2a")):
            to_mpv(player.command, "keyup", name)

    def mouse_pos(self, event):
        ratio = self.devicePixelRatio()
        p = event.position()
        return int(p.x() * ratio), int(p.y() * ratio)

    def mouseMoveEvent(self, event):
        self.setCursor(QCursor(Qt.ArrowCursor))
        self.hide_cursor.start()
        if box.menu_open:   # the menu's clickable elements (qml/menu/Tap.qml)
            return super().mouseMoveEvent(event)
        to_mpv(player.command, "mouse", *self.mouse_pos(event))

    def mousePressEvent(self, event):
        if box.menu_open:
            return super().mousePressEvent(event)
        if not SYSTEM and event.button() == Qt.LeftButton:
            # Owlink app: a click opens the menu (no remote needed); a double click toggles full screen
            if WINDOWED and event.type() == event.Type.MouseButtonDblClick:
                self.showNormal() if self.visibility() == QQuickView.FullScreen else self.showFullScreen()
            else:
                box.openRequested.emit()
            return
        x, y = self.mouse_pos(event)
        double = event.type() == event.Type.MouseButtonDblClick
        to_mpv(player.command, "mouse", x, y, 0, "double" if double else "single")

    mouseDoubleClickEvent = mousePressEvent


def main():
    global player
    # kill -USR1 <pid>: stack of each thread in the journal (diagnosing a hang)
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    opts, appends, files = parse_args(sys.argv[1:])
    force_window = opts.pop("__force_window", None)
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    # Under X11, Qt's OpenGL through EGL (GLX by default): libmpv takes its functions from EGL (egl_get_proc_address)
    os.environ.setdefault("QT_XCB_GL_INTEGRATION", "xcb_egl")
    app = QGuiApplication(sys.argv[:1])
    locale.setlocale(locale.LC_NUMERIC, "C")   # required by libmpv, after Qt which applies the system locale
    qmlRegisterType(MpvVideo, "StreamBox", 1, 0, "MpvVideo")
    view = View()
    view.rootContext().setContextProperty("box", box)
    box.start()
    view.rootContext().setContextProperty("pip", pip)
    view.rootContext().setContextProperty("livePreview", live_preview)
    global chat
    chat = ChatBridge()
    view.rootContext().setContextProperty("chat", chat)
    view.rootContext().setContextProperty("osd", osd)
    view.rootContext().setContextProperty("i18n", tr_dict)
    view.setSource(QUrl.fromLocalFile(os.path.join(DIR, "ui.qml")))
    qml_menu = view.status() == QQuickView.Ready and view.rootObject().findChild(QObject, "tvMenu") is not None
    if not qml_menu:
        print("QML menu unavailable: small menu of stream-box.lua", [e.toString() for e in view.errors()], flush=True)
    scripts = opts.pop("scripts", [])
    if scripts:
        opts["scripts"] = ":".join(scripts)
    player = mpv.MPV(vo="libmpv", **{k.replace("-", "_"): v for k, v in opts.items()})
    global pip_player
    # Second stream: low-latency live like the main one (small buffer), without sound or interface
    pip_player = mpv.MPV(vo="libmpv", hwdec=opts.get("hwdec", "auto-safe"), mute="yes", idle="yes", ytdl="no",
                         osd_level="0", input_default_bindings="no", cache="yes", demuxer_max_bytes="750KiB",
                         demuxer_max_back_bytes="0")
    pip_player.observe_property("idle-active", lambda _n, v: v and pip._idle.emit())
    global preview_player
    # Live preview: no sound
    preview_player = mpv.MPV(vo="libmpv", hwdec=opts.get("hwdec", "auto-safe"), mute="yes", idle="yes", ytdl="no",
                             osd_level="0", input_default_bindings="no", cache="yes",
                             demuxer_max_bytes="20MiB", demuxer_max_back_bytes="0")
    preview_player.observe_property("video-params", lambda _n, v: live_preview._ready_in.emit(v is not None))
    preview_player.observe_property("idle-active", lambda _n, v: setattr(live_preview, "idle", bool(v)))
    main_state = {"channel": "", "mode": "", "corner": "bl"}

    def follow(key):
        def cb(_name, value):
            main_state[key] = value if isinstance(value, str) else ""
            pip._main.emit(main_state["channel"], main_state["mode"], main_state["corner"] or "bl")
        return cb
    for key in ("channel", "mode", "corner"):
        player.observe_property(f"user-data/streambox/{key}", follow(key))
    for key in ("channel", "mode", "corner", "chat_visible", "chat_bg", "chat_size"):
        player.observe_property(f"user-data/streambox/{key}",
                                lambda _n, v, key=key: v is not None and chat._settings_in.emit(json.dumps({key: v})))

    def input_beat(_n, v):
        m = re.match(r"evdev:(\d+)", v or "")
        input_service["beat"] = int(m.group(1)) if m else 0
    player.observe_property("user-data/streambox/input", input_beat)

    for key in ("bar", "toast", "polls", "storyboard", "live", "mode", "channel", "events", "tracks", "loading", "learn", "meta", "controls", "seekfx",
                "next_card", "notice", "info"):
        player.observe_property(f"user-data/streambox/{key}", osd.receive(key))
    player.observe_property("path", osd.new_file)
    threading.Thread(target=osd.poll_loop, daemon=True).start()

    def dec(v):
        return v.decode() if isinstance(v, bytes) else (v or "")
    player.register_message_handler(
        "streambox-pip", lambda action=b"", name=b"", layout=b"", *_: pip._request.emit(dec(action), dec(name), dec(layout)))
    if qml_menu:
        player.register_message_handler("streambox-tvmenu-open", lambda *_: box.openRequested.emit())
        player.register_message_handler("streambox-power-menu", lambda *_: box.powerMenuRequested.emit())
        player.register_message_handler("streambox-tvmenu-close", lambda *_: box.closeRequested.emit())
        player.register_message_handler("streambox-language", lambda *_: tr_dict._reload.emit())
        # Keys sent through IPC (keypress → stream-box.lua → streambox-tvmenu-key): tests, Home Assistant
        player.register_message_handler(
            "streambox-tvmenu-key", lambda k, *_: box.keyPressed.emit(k.decode() if isinstance(k, bytes) else k))
        # Menu keyboard held by the companion app (remote.py, /api/keyboard_input): whole text, and "1" to submit
        player.register_message_handler(
            "streambox-tvmenu-text", lambda t, submit="0", *_: box.textInput.emit(dec(t), dec(submit) == "1"))
        player.observe_property("user-data/streambox/ambient",
                                lambda _n, v: box._ambient_in.emit(json.dumps(v or {})))
        player.observe_property("video-params", lambda _n, v: box._video_in.emit(v is not None))
        for key in ("ambient_on", "status", "qr"):
            player.observe_property(f"user-data/streambox/{key}",
                                    lambda _n, v, key=key: v is not None and box._home_in.emit(key, json.dumps(v)))
    for key, value in appends:
        player.command("change-list", key, "append", value)

    @player.event_callback("shutdown")
    def _(_event):
        # mpv quit (quit command through IPC…): the app too, the player.sh loop restarts it. Right away, from
        # this thread: just after, python-mpv destroys its connection, which waits for the release of the render
        # context held by Qt's render thread, and everything stayed frozen (IPC socket dropping connections, no restart).
        if pip.proc:
            pip.proc.terminate()
        if live_preview.proc:
            live_preview.proc.terminate()
        os._exit(0)
    if force_window:
        bridge.ready.connect(lambda: to_mpv(player.command, "set", "force-window", force_window), Qt.QueuedConnection)
    if qml_menu:
        bridge.ready.connect(lambda: to_mpv(set_flag, "user-data/streambox/tvmenu", False), Qt.QueuedConnection)
        # The chat is drawn here (with emotes): chat_overlay.py, which draws it as text in mpv, stays quiet
        bridge.ready.connect(lambda: to_mpv(player._set_property, "user-data/streambox/chat_ui", "qml"),
                             Qt.QueuedConnection)
    else:   # no big menu: stream-box.lua opens its small menu instead
        bridge.ready.connect(lambda: to_mpv(player._set_property, "user-data/streambox/menu", "small"),
                             Qt.QueuedConnection)
    if WINDOWED:
        view.setTitle("Owlink")
        view.resize(1280, 720)
        view.show()
    else:
        view.showFullScreen()
    # Boot image from start.sh (mpv, same image as the Plymouth screen): removed once the app's first frame is
    # on screen (short delay: cage switches to the most recent window)
    def drop_splash():
        path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "stream-box-splash.pid")
        try:
            with open(path) as f:
                os.kill(int(f.read().strip()), signal.SIGTERM)
            os.remove(path)
        except (OSError, ValueError):
            pass
    first_frame = []
    def on_frame():
        if not first_frame:
            first_frame.append(True)
            QTimer.singleShot(300, drop_splash)
    view.frameSwapped.connect(on_frame)
    threading.Thread(target=mpv_worker, daemon=True).start()
    for f in files:
        to_mpv(player.command, "loadfile", f, "append-play")
    code = app.exec()
    # Window closed without mpv having quit (rare). No player.terminate(): libmpv stops dead (abort, code 134)
    # if its render context, held by Qt's render thread, still exists.
    os._exit(code)


if __name__ == "__main__":
    main()
