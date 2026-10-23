#!/usr/bin/env python3
"""Stream Box : appli plein écran (Qt Quick) qui embarque mpv (libmpv).

Remplace la fenêtre de mpv dans la session cage : la vidéo est dessinée par libmpv dans la scène Qt Quick (OpenGL,
puce graphique), et les éléments d'interface en QML pourront se poser par-dessus avec de vraies animations. Le
lecteur garde tout ce qu'il faisait : mêmes options que la ligne de commande de mpv (passées telles quelles par
start.sh), scripts Lua, socket IPC (télécommande web, Jellyfin, Home Assistant). Les touches et la souris reçues par la
fenêtre sont transmises à mpv (keypress, mouse), là où stream-box.lua les attend.

Deux streams à la fois : un second lecteur libmpv (pip_player) avec son propre streamlink, dessiné en incrustation dans
un coin ou côte à côte avec le principal (ui.qml, transitions animées). Commandé par le menu QML (objet « pip ») et par
l'IPC (script-message streambox-pip <open|close|swap|layout> [chaîne] [pip|split], /api/pip de remote.py) ; état publié
dans user-data/streambox/pip. Son coupé : le son est celui du stream principal (Inverser échange les deux).

Le grand menu de la TV est en QML (qml/TvMenu.qml) : quand il se charge, tv_menu.lua n'est pas chargé ; le bouton Menu
(script-message streambox-tvmenu-open de stream-box.lua) l'ouvre, et tant qu'il est ouvert les touches lui vont, pas à
mpv. Il lit et agit par l'API de remote.py, comme la page web.

Lancé avec le Python du venv ui-venv (PySide6, python-mpv) : ui.py --input-ipc-server=… --script=… <autres options>
"""
import ctypes, faulthandler, json, locale, os, queue, re, signal, subprocess, sys, threading

from PySide6.QtCore import Property, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtOpenGL import QOpenGLFramebufferObject
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickFramebufferObject, QQuickView, QQuickWindow, QSGRendererInterface

import mpv

import chat_qt   # chat avec émotes (même dossier)

DIR = os.path.dirname(os.path.abspath(__file__))
CURSOR_HIDE_MS = 4000   # comme --cursor-autohide=4000 de mpv

# Touches Qt → noms de touches de mpv (ceux que stream-box.lua lie). Les touches sans nom chez Qt (OK et Menu de la
# télécommande Xiaomi) sont transmises par leur keysym, sous le nom que mpv leur donnait (voir key_name).
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

# Touches sans nom chez Qt, relevées sur la télécommande Xiaomi : keysym → nom que mpv leur donnait (stream-box.lua les lie)
SPECIAL_KEYSYMS = {0x1008ffa0: "0x21ffa0",   # OK
                   0x10081246: "0x2111a0"}   # Menu ≡

# Touches pour le grand menu, mêmes rôles que KEYS dans stream-box.lua
MENU_KEYS = {"UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right", "ENTER": "ok", "KP_ENTER": "ok",
             "0x21ffa0": "ok", "HOMEPAGE": "home", "GO_BACK": "back", "ESC": "back", "0x2111a0": "menu",
             "WWW": "homescreen", "PLAY": "corner", "PLAYPAUSE": "corner"}


def key_name(event):
    """Nom mpv de la touche, ou None pour l'ignorer."""
    name = KEYS.get(event.key())
    if name:
        return name
    text = event.text()
    if text and text.isprintable():
        return text
    # Touche spéciale sans nom chez mpv : il la nommait « 0x21 » suivi des 4 derniers chiffres de son keysym XF86
    # (OK de la télécommande Xiaomi : keysym 0x1008ffa0 = XF86Select → « 0x21ffa0 », que stream-box.lua lie)
    sym = event.nativeVirtualKey()
    if sym in SPECIAL_KEYSYMS:
        return SPECIAL_KEYSYMS[sym]
    if sym:
        name = f"0x{0x210000 | (sym & 0xffff):x}" if sym >> 16 == 0x1008 else f"0x{sym:x}"
        print(f"touche sans nom : keysym 0x{sym:x}, scancode {event.nativeScanCode()} → {name}", flush=True)
        return name
    return None


def parse_args(argv):
    """Options façon ligne de commande de mpv : (options avant initialisation, listes à compléter, fichiers)."""
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
            continue   # sans objet : c'est la fenêtre Qt qui est en plein écran
        elif key == "force-window":
            # Activé seulement une fois le rendu prêt (Bridge.ready) : passé au démarrage, mpv ne peut pas encore ouvrir
            # sa sortie vidéo et le désactive. Sans lui, rien ne se dessine quand aucune vidéo ne joue : écran
            # d'ambiance et chaîne hors ligne restaient figés sur la dernière image
            opts["__force_window"] = value if _ else "yes"
        else:
            opts[key] = value if _ else "yes"
    if scripts:
        opts["scripts"] = scripts   # assemblés dans main(), une fois connu le menu à utiliser
    return opts, appends, files


class Bridge(QObject):
    """Événements du fil de mpv → fil de Qt"""
    frame = Signal()
    shutdown = Signal()
    ready = Signal()   # contexte de rendu créé


def set_flag(name, value):
    """Booléen dans une propriété mpv (user-data) : python-mpv écrirait la chaîne « yes », que le chat et stream-box.lua
    ne prennent pas pour un vrai."""
    flag = ctypes.c_int(1 if value else 0)
    mpv._mpv_set_property(player.handle, name.encode(), mpv.MpvFormat.FLAG, ctypes.byref(flag))


class Box(QObject):
    """Ce que voit le QML (« box ») : ouverture du menu, touches, données de mpv utiles au menu"""
    openRequested = Signal()
    keyPressed = Signal(str)
    ambientChanged = Signal()
    videoActiveChanged = Signal()
    homeChanged = Signal()
    _ambient_in = Signal(str)        # depuis le fil de mpv
    _video_in = Signal(bool)
    _home_in = Signal(str, str)      # écran d'accueil : clé (ambient_on, status, qr), valeur en JSON

    def __init__(self):
        super().__init__()
        self.menu_open = False
        self._ambient, self._video = "{}", False
        self._home = {"ambient_on": False, "status": "", "qr": "always"}
        self._home_in.connect(self._set_home, Qt.QueuedConnection)
        self._ambient_in.connect(self._set_ambient, Qt.QueuedConnection)
        self._video_in.connect(self._set_video, Qt.QueuedConnection)

    def _set_ambient(self, value):
        if value != self._ambient:
            self._ambient = value
            self.ambientChanged.emit()

    def _set_home(self, key, value):
        self._home[key] = json.loads(value)
        self.homeChanged.emit()

    # Écran d'accueil (qml/AmbientScreen.qml) : affiché quand stream-box.lua le décide, avec son message d'état
    ambientOn = Property(bool, lambda self: bool(self._home["ambient_on"]), notify=homeChanged)
    statusText = Property(str, lambda self: self._home["status"] or "", notify=homeChanged)
    qrMode = Property(str, lambda self: self._home["qr"] or "always", notify=homeChanged)

    def _set_video(self, value):
        if value != self._video:
            self._video = value
            self.videoActiveChanged.emit()

    ambient = Property(str, lambda self: self._ambient, notify=ambientChanged)   # météo, QR code (JSON)
    videoActive = Property(bool, lambda self: self._video, notify=videoActiveChanged)

    @Slot(bool)
    def setMenuOpen(self, value):
        self.menu_open = value
        if chat:
            chat.set_menu_open(value)
        to_mpv(set_flag, "user-data/streambox/tvmenu", value)   # le chat se masque, la souris n'ouvre pas le petit menu


box = Box()


bridge = Bridge()
player = None   # créé dans main(), avant la fenêtre

# Appels à mpv depuis le fil de Qt : jamais en direct. Un appel synchrone peut attendre la sortie vidéo de mpv, qui
# attend le fil de rendu de Qt, lui-même bloqué par le fil principal : tout se fige (vu en relançant le lecteur, menu
# ouvert : socket IPC coupé, image figée). Un fil à part les exécute dans l'ordre.
mpv_calls = queue.Queue()


def mpv_worker():
    while True:
        fn, args = mpv_calls.get()
        try:
            fn(*args)
        except Exception as e:   # mpv arrêté, propriété refusée… : on continue
            print(f"appel à mpv refusé : {e}", flush=True)


def to_mpv(fn, *args):
    mpv_calls.put((fn, args))
# Tampons d'image donnés à Qt : PySide les libérerait sinon pendant que Qt s'en sert encore (plantage dans texture()).
# Qt les détruit lui-même quand la taille change ; on garde juste la référence Python.
framebuffers = []


def wayland_display():
    """Connexion Wayland à donner à libmpv pour le décodage matériel (VA-API) : sans elle, pas de VADisplay et
    décodage par le processeur. Connexion à part de celle de Qt, qui suffit à VA-API pour trouver la puce."""
    try:
        lib = ctypes.CDLL("libwayland-client.so.0")
        lib.wl_display_connect.restype = ctypes.c_void_p
        lib.wl_display_connect.argtypes = [ctypes.c_char_p]
        return lib.wl_display_connect(None) or None
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
        self.proc = egl_get_proc_address()   # gardé : mpv l'appelle depuis le C

    def createFramebufferObject(self, size):
        if self.ctx is None:   # contexte OpenGL de Qt actif ici, dans le fil de rendu
            params = {"opengl_init_params": {"get_proc_address": self.proc}}
            display = wayland_display()
            if display:
                params["wl_display"] = ctypes.c_void_p(display)
            main = self.item.which != "pip"
            self.ctx = mpv.MpvRenderContext(player if main else pip_player, "opengl", **params)
            self.ctx.update_cb = self.item.frameReady.emit
            if main:
                bridge.ready.emit()
        fbo = QOpenGLFramebufferObject(size)
        framebuffers.append(fbo)
        return fbo

    def render(self):
        # update() accuse réception de la notification de mpv ; sans attente de l'heure d'affichage de l'image : bloqué
        # là-dedans, le fil de rendu de Qt figeait tout au démarrage (une relance sur deux ou trois)
        self.ctx.update()
        fbo = self.framebufferObject()
        self.ctx.render(flip_y=False, block_for_target_time=False,
                        opengl_fbo={"fbo": fbo.handle(), "w": fbo.width(), "h": fbo.height()})
        self.ctx.report_swap()


class MpvVideo(QQuickFramebufferObject):
    """Vidéo d'un lecteur libmpv : which = « main » (par défaut) ou « pip » (second stream)"""
    frameReady = Signal()   # depuis mpv, n'importe quel fil

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


PIP_PORT = 34590   # streamlink du second stream (le principal prend 34501 à 34550, voir stream-box.lua)
pip_player = None  # second lecteur libmpv, créé dans main()


def set_node(name, value):
    """Valeur structurée (dict) dans une propriété mpv du lecteur principal"""
    player._set_property(name, value)


class Pip(QObject):
    """Second stream : streamlink à part, lecteur pip_player, disposition « pip » (incrustation) ou « split »"""
    changed = Signal()
    _request = Signal(str, str, str)   # depuis le fil de mpv (IPC) : action, chaîne, disposition
    _main = Signal(str, str, str)      # chaîne, mode et coin du chat du lecteur principal
    _idle = Signal()                   # le second lecteur n'a plus rien à lire

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
        # En incrustation, 720p suffit et ménage le réseau ; côte à côte, la meilleure qualité
        quality = "best" if self._layout == "split" else "720p60,720p,best"
        self.proc = subprocess.Popen(
            ["streamlink", "--twitch-low-latency", "--retry-streams", "30", "--player-external-http",
             "--player-external-http-interface", "127.0.0.1", "--player-external-http-port", str(PIP_PORT),
             f"twitch.tv/{name}", quality], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.retry.start(2500)   # le temps que streamlink ouvre son serveur
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
        """Échange les deux streams (et donc le son)"""
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
        # Écran d'accueil, vidéo, ou même streamer que le second : le second stream n'a plus lieu d'être
        if self._channel and (mode != "twitch" or channel == self._channel):
            self.close()

    def publish(self):
        self.changed.emit()
        to_mpv(set_node, "user-data/streambox/pip", {"channel": self._channel, "layout": self._layout})


pip = Pip()


class ChatBridge(QObject):
    """Chat avec émotes pour qml/ChatOverlay.qml : messages de chat_qt.py, réglages du lecteur principal"""
    changed = Signal()
    messagesChanged = Signal()
    _messages_in = Signal(str)     # depuis les fils de chat_qt
    _settings_in = Signal(str)     # depuis le fil de mpv (JSON des réglages)

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
    # Masqué : case décochée, vidéo ou écran d'accueil, grand menu ouvert (comme chat_overlay.py)
    visible = Property(bool, lambda self: bool(self.settings["chat_visible"]) and self.settings["mode"] == "twitch"
                       and not self.menu_open, notify=changed)


chat = None   # créé dans main(), avec l'application Qt


class View(QQuickView):
    """Fenêtre plein écran : transmet touches et souris à mpv, masque le curseur après 4 s sans mouvement."""

    def __init__(self):
        super().__init__()
        self.setResizeMode(QQuickView.SizeRootObjectToView)
        self.setColor(Qt.black)
        self.hide_cursor = QTimer(self, singleShot=True, interval=CURSOR_HIDE_MS)
        self.hide_cursor.timeout.connect(lambda: self.setCursor(QCursor(Qt.BlankCursor)))
        self.setCursor(QCursor(Qt.BlankCursor))

    def keyPressEvent(self, event):
        name = key_name(event)
        if not name:
            return
        if box.menu_open and name in MENU_KEYS:   # menu QML ouvert : la touche est pour lui (le volume reste à mpv)
            box.keyPressed.emit(MENU_KEYS[name])
            return
        # Répétition : un keypress par événement, comme mpv le fait pour une touche maintenue
        to_mpv(player.command, "keypress", name)

    def mouse_pos(self, event):
        ratio = self.devicePixelRatio()
        p = event.position()
        return int(p.x() * ratio), int(p.y() * ratio)

    def mouseMoveEvent(self, event):
        if box.menu_open:
            return
        self.setCursor(QCursor(Qt.ArrowCursor))
        self.hide_cursor.start()
        to_mpv(player.command, "mouse", *self.mouse_pos(event))

    def mousePressEvent(self, event):
        if box.menu_open:
            return
        x, y = self.mouse_pos(event)
        double = event.type() == event.Type.MouseButtonDblClick
        to_mpv(player.command, "mouse", x, y, 0, "double" if double else "single")

    mouseDoubleClickEvent = mousePressEvent


def main():
    global player
    # kill -USR1 <pid> : pile de chaque fil dans le journal (diagnostic d'un blocage)
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    opts, appends, files = parse_args(sys.argv[1:])
    force_window = opts.pop("__force_window", None)
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QGuiApplication(sys.argv[:1])
    locale.setlocale(locale.LC_NUMERIC, "C")   # exigé par libmpv, après Qt qui applique la locale du système
    qmlRegisterType(MpvVideo, "StreamBox", 1, 0, "MpvVideo")
    view = View()
    view.rootContext().setContextProperty("box", box)
    view.rootContext().setContextProperty("pip", pip)
    global chat
    chat = ChatBridge()
    view.rootContext().setContextProperty("chat", chat)
    view.setSource(QUrl.fromLocalFile(os.path.join(DIR, "ui.qml")))
    qml_menu = view.status() == QQuickView.Ready and view.rootObject().findChild(QObject, "tvMenu") is not None
    if not qml_menu:
        print("menu QML indisponible : menu de tv_menu.lua", [e.toString() for e in view.errors()], flush=True)
    scripts = opts.pop("scripts", [])
    if qml_menu:   # deux menus répondraient au bouton Menu
        scripts = [s for s in scripts if os.path.basename(s) != "tv_menu.lua"]
    if scripts:
        opts["scripts"] = ":".join(scripts)
    player = mpv.MPV(vo="libmpv", **{k.replace("-", "_"): v for k, v in opts.items()})
    global pip_player
    # Second stream : direct à faible latence comme le principal (petit tampon), sans son ni interface
    pip_player = mpv.MPV(vo="libmpv", hwdec=opts.get("hwdec", "auto-safe"), mute="yes", idle="yes", ytdl="no",
                         osd_level="0", input_default_bindings="no", cache="yes", demuxer_max_bytes="750KiB",
                         demuxer_max_back_bytes="0")
    pip_player.observe_property("idle-active", lambda _n, v: v and pip._idle.emit())
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

    def dec(v):
        return v.decode() if isinstance(v, bytes) else (v or "")
    player.register_message_handler(
        "streambox-pip", lambda action=b"", name=b"", layout=b"", *_: pip._request.emit(dec(action), dec(name), dec(layout)))
    if qml_menu:
        player.register_message_handler("streambox-tvmenu-open", lambda *_: box.openRequested.emit())
        # Touches envoyées par l'IPC (keypress → stream-box.lua → streambox-tvmenu-key) : tests, Home Assistant
        player.register_message_handler(
            "streambox-tvmenu-key", lambda k, *_: box.keyPressed.emit(k.decode() if isinstance(k, bytes) else k))
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
        # mpv quitté (commande quit par l'IPC…) : l'appli aussi, la boucle de player.sh la relance. Tout de suite, depuis
        # ce fil : juste après, python-mpv détruit sa connexion, ce qui attend la libération du contexte de rendu tenu
        # par le fil de rendu de Qt, et tout restait figé (socket IPC qui coupe les connexions, pas de relance).
        if pip.proc:
            pip.proc.terminate()
        os._exit(0)
    if force_window:
        bridge.ready.connect(lambda: to_mpv(player.command, "set", "force-window", force_window), Qt.QueuedConnection)
    if qml_menu:
        bridge.ready.connect(lambda: to_mpv(set_flag, "user-data/streambox/tvmenu", False), Qt.QueuedConnection)
        # Le chat est dessiné ici (avec émotes) : chat_overlay.py, qui le dessine en texte dans mpv, se tait
        bridge.ready.connect(lambda: to_mpv(player._set_property, "user-data/streambox/chat_ui", "qml"),
                             Qt.QueuedConnection)
    view.showFullScreen()
    threading.Thread(target=mpv_worker, daemon=True).start()
    for f in files:
        to_mpv(player.command, "loadfile", f, "append-play")
    code = app.exec()
    # Fenêtre fermée sans que mpv ait quitté (rare). Pas de player.terminate() : libmpv s'arrête net (abort, code 134)
    # si son contexte de rendu, tenu par le fil de rendu de Qt, existe encore.
    os._exit(code)


if __name__ == "__main__":
    main()
