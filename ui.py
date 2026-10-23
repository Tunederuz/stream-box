#!/usr/bin/env python3
"""Stream Box : appli plein écran (Qt Quick) qui embarque mpv (libmpv).

Remplace la fenêtre de mpv dans la session cage : la vidéo est dessinée par libmpv dans la scène Qt Quick (OpenGL,
puce graphique), et les éléments d'interface en QML pourront se poser par-dessus avec de vraies animations. Le
lecteur garde tout ce qu'il faisait : mêmes options que la ligne de commande de mpv (passées telles quelles par
start.sh), scripts Lua, socket IPC (télécommande web, Jellyfin, Home Assistant). Les touches et la souris reçues par la
fenêtre sont transmises à mpv (keypress, mouse), là où stream-box.lua les attend.

Lancé avec le Python du venv ui-venv (PySide6, python-mpv) : ui.py --input-ipc-server=… --script=… <autres options>
"""
import ctypes, locale, os, sys

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
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
        opts["scripts"] = ":".join(scripts)
    return opts, appends, files


class Bridge(QObject):
    """Événements du fil de mpv → fil de Qt"""
    frame = Signal()
    shutdown = Signal()
    ready = Signal()   # contexte de rendu créé


bridge = Bridge()
player = None   # créé dans main(), avant la fenêtre
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
        fbo = self.framebufferObject()
        self.ctx.render(flip_y=False, opengl_fbo={"fbo": fbo.handle(), "w": fbo.width(), "h": fbo.height()})
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
        if name:
            # Répétition : un keypress par événement, comme mpv le fait pour une touche maintenue
            player.command("keypress", name)

    def mouse_pos(self, event):
        ratio = self.devicePixelRatio()
        p = event.position()
        return int(p.x() * ratio), int(p.y() * ratio)

    def mouseMoveEvent(self, event):
        self.setCursor(QCursor(Qt.ArrowCursor))
        self.hide_cursor.start()
        player.command("mouse", *self.mouse_pos(event))

    def mousePressEvent(self, event):
        x, y = self.mouse_pos(event)
        double = event.type() == event.Type.MouseButtonDblClick
        player.command("mouse", x, y, 0, "double" if double else "single")

    mouseDoubleClickEvent = mousePressEvent


def main():
    global player
    opts, appends, files = parse_args(sys.argv[1:])
    force_window = opts.pop("__force_window", None)
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QGuiApplication(sys.argv[:1])
    locale.setlocale(locale.LC_NUMERIC, "C")   # exigé par libmpv, après Qt qui applique la locale du système
    player = mpv.MPV(vo="libmpv", **{k.replace("-", "_"): v for k, v in opts.items()})
    for key, value in appends:
        player.command("change-list", key, "append", value)

    @player.event_callback("shutdown")
    def _(_event):   # mpv quitté (commande quit par l'IPC…) : l'appli aussi, start.sh le relance
        bridge.shutdown.emit()

    bridge.shutdown.connect(app.quit, Qt.QueuedConnection)
    if force_window:
        bridge.ready.connect(lambda: player.command("set", "force-window", force_window), Qt.QueuedConnection)
    qmlRegisterType(MpvVideo, "StreamBox", 1, 0, "MpvVideo")
    view = View()
    view.setSource(QUrl.fromLocalFile(os.path.join(DIR, "ui.qml")))
    view.showFullScreen()
    for f in files:
        player.command("loadfile", f, "append-play")
    code = app.exec()
    player.terminate()
    os._exit(code)   # sans le ménage de Python : Qt a déjà détruit les tampons d'image qu'il référence


if __name__ == "__main__":
    main()
