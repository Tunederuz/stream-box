#!/usr/bin/env python3
"""Stream Box : appli plein écran (Qt Quick) qui embarque mpv (libmpv).

Remplace la fenêtre de mpv dans la session cage : la vidéo est dessinée par libmpv dans la scène Qt Quick (OpenGL,
puce graphique), et les éléments d'interface en QML pourront se poser par-dessus avec de vraies animations. Le
lecteur garde tout ce qu'il faisait : mêmes options que la ligne de commande de mpv (passées telles quelles par
start.sh), scripts Lua, socket IPC (télécommande web, Jellyfin, Home Assistant). Les touches et la souris reçues par la
fenêtre sont transmises à mpv (keypress, mouse), là où stream-box.lua les attend.

Le grand menu de la TV est en QML (qml/TvMenu.qml) : quand il se charge, tv_menu.lua n'est pas chargé ; le bouton Menu
(script-message streambox-tvmenu-open de stream-box.lua) l'ouvre, et tant qu'il est ouvert les touches lui vont, pas à
mpv. Il lit et agit par l'API de remote.py, comme la page web.

Lancé avec le Python du venv ui-venv (PySide6, python-mpv) : ui.py --input-ipc-server=… --script=… <autres options>
"""
import ctypes, faulthandler, json, locale, os, queue, signal, sys, threading

from PySide6.QtCore import Property, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtOpenGL import QOpenGLFramebufferObject
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickFramebufferObject, QQuickView, QQuickWindow, QSGRendererInterface

import mpv

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
    _ambient_in = Signal(str)        # depuis le fil de mpv
    _video_in = Signal(bool)

    def __init__(self):
        super().__init__()
        self.menu_open = False
        self._ambient, self._video = "{}", False
        self._ambient_in.connect(self._set_ambient, Qt.QueuedConnection)
        self._video_in.connect(self._set_video, Qt.QueuedConnection)

    def _set_ambient(self, value):
        if value != self._ambient:
            self._ambient = value
            self.ambientChanged.emit()

    def _set_video(self, value):
        if value != self._video:
            self._video = value
            self.videoActiveChanged.emit()

    ambient = Property(str, lambda self: self._ambient, notify=ambientChanged)   # météo, QR code (JSON)
    videoActive = Property(bool, lambda self: self._video, notify=videoActiveChanged)

    @Slot(bool)
    def setMenuOpen(self, value):
        self.menu_open = value
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
    def __init__(self):
        super().__init__()
        self.ctx = None
        self.proc = egl_get_proc_address()   # gardé : mpv l'appelle depuis le C

    def createFramebufferObject(self, size):
        if self.ctx is None:   # contexte OpenGL de Qt actif ici, dans le fil de rendu
            params = {"opengl_init_params": {"get_proc_address": self.proc}}
            display = wayland_display()
            if display:
                params["wl_display"] = ctypes.c_void_p(display)
            self.ctx = mpv.MpvRenderContext(player, "opengl", **params)
            self.ctx.update_cb = bridge.frame.emit
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
    def __init__(self, parent=None):
        super().__init__(parent)
        bridge.frame.connect(self.update, Qt.QueuedConnection)

    def createRenderer(self):
        return MpvRenderer()


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
    if qml_menu:
        player.register_message_handler("streambox-tvmenu-open", lambda *_: box.openRequested.emit())
        # Touches envoyées par l'IPC (keypress → stream-box.lua → streambox-tvmenu-key) : tests, Home Assistant
        player.register_message_handler(
            "streambox-tvmenu-key", lambda k, *_: box.keyPressed.emit(k.decode() if isinstance(k, bytes) else k))
        player.observe_property("user-data/streambox/ambient",
                                lambda _n, v: box._ambient_in.emit(json.dumps(v or {})))
        player.observe_property("video-params", lambda _n, v: box._video_in.emit(v is not None))
    for key, value in appends:
        player.command("change-list", key, "append", value)

    @player.event_callback("shutdown")
    def _(_event):   # mpv quitté (commande quit par l'IPC…) : l'appli aussi, start.sh le relance
        bridge.shutdown.emit()

    bridge.shutdown.connect(app.quit, Qt.QueuedConnection)
    if force_window:
        bridge.ready.connect(lambda: to_mpv(player.command, "set", "force-window", force_window), Qt.QueuedConnection)
    if qml_menu:
        bridge.ready.connect(lambda: to_mpv(set_flag, "user-data/streambox/tvmenu", False), Qt.QueuedConnection)
    view.showFullScreen()
    threading.Thread(target=mpv_worker, daemon=True).start()
    for f in files:
        to_mpv(player.command, "loadfile", f, "append-play")
    code = app.exec()
    # mpv a déjà quitté (événement shutdown). Pas de player.terminate() : libmpv s'arrête net (abort, code 134) si son
    # contexte de rendu, tenu par le fil de rendu de Qt, existe encore. Ni de ménage de Python : Qt a déjà détruit les
    # tampons d'image qu'il référence.
    os._exit(code)


if __name__ == "__main__":
    main()
