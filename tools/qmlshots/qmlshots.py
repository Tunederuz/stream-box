"""Stream Box: screenshots of the QML TV menu (qml/TvMenu.qml), without a box, mpv or GPU (Xvfb, Mesa).

Mocks the context properties of ui.py (box, pip, i18n with locales/fr.json), serves fixed JSON fixtures on
127.0.0.1:8080 (the remote.py API the menu calls), opens the menu in a 1920x1080 window and plays a scripted key
sequence through box.keyPressed, grabbing the window after each step. Also writes to console.log the Qt console
(warnings), the state of the menu after each step and the requests made. Meant to run in Docker (see run.sh):
    qmlshots.py shoot <qml dir> <out dir>      screenshots NNN-step.png + console.log
    qmlshots.py diff <dir A> <dir B>           pixel comparison of two sets of screenshots
"""
import datetime
import json
import re
import os
import shutil
import sys
import tempfile
import threading
import time
import zlib
import struct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WAIT = int(os.environ.get("QMLSHOTS_WAIT", "900"))   # ms after each step: animations and images done

# Key sequence: ("key", name), ("open",), ("power",), ("text", text, submit), ("video", bool), ("close",),
# ("pause", ms): nothing more than waiting (the live preview starts after a moment on a live streamer).
# A screenshot follows each step; the label names it. Each scene starts from a fresh opening (Live tab).


def keys(*names):
    return [("key", k) for k in " ".join(names).split()]


def scene(tab, *names):   # close, open, from the rail to the tab (index in TvMenu.tabs), then the keys
    return [("key", "home"), ("open",)] + keys("back", *(["down"] * tab), "right", *names)


STEPS = (
    [("open",)]                                                   # Live, focus on the watched streamer
    + keys("right right") + [("pause", 2000)]                     # live in the background (pink: the fake video)
    + keys("down down down down up up up up")                     # the grid scrolls
    + keys("up right right left down")                            # shortcuts (second stream)
    + keys("menu down back")                                      # streamer options
    + keys("left left up down")                                   # rail, "Home screen" entry
    + scene(1, "") + [("pause", 2000)]                            # Following: live in the background
    + keys("right down down down down ok back")                   # grid scrolls, options
    + scene(2, "right right ok")                                  # Replays: another streamer
    + keys("down right right right right down right up left left left ok back")   # rows, resume dialog
    + scene(3, "down right right")                                # YouTube: recommended for you
    + keys("down right right right right menu down back")         # subscriptions, options
    + keys("down down right up up up")                            # channel rows
    + keys("ok ok right ok down down down down down right ok")    # search keyboard, search "ab"
    + keys("right right right right right right ok ok")           # found channels, dialog, its videos
    + keys("down right down up up up up ok")                      # rows, keyboard again
    + [("text", "phone", False), ("text", "phone typed", True)]   # text typed on the phone
    + scene(4, "down right ok back down down right right right right down ok")   # Jellyfin: series
    + keys("right ok back up ok back")                            # episodes, dialog, keyboard closed
    + scene(5, "down right ok back down down right ok")           # Plex: rows, series, episodes
    + scene(6, "right down down left ok back")                    # History
    + scene(7, "down down down down down down down right down down down down down down down down")
    + keys("right down up up up up")                              # Settings: audio output, resolution
    + scene(8, "down ok") + [("pause", 300)] + keys("ok back")    # System: Jellyfin, servers found, Quick Connect code
    + keys("down ok ok back")                                     # Plex, sign-in by code (dialog)
    + keys("down ok down ok back")                                # YouTube account, sync dialog
    + keys("down right down down ok back down down down down ok down back")   # Bluetooth, developer mode
    + keys("down ok ok back down ok back down down down down ok down ok")     # install, backup, restart
    + [("key", "home"), ("video", True), ("open",)]               # over a video: veil only
    + keys("back down down back")
    + [("video", False), ("power",)] + keys("down back")          # "Box" dialog alone
)


def png(rgb):
    """Solid 32x18 PNG of an RRGGBB color (thumbnails, avatars)"""
    w, h = 32, 18
    raw = b"".join(b"\0" + bytes.fromhex(rgb) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def dates(v):
    """"@-3d" in the fixtures: date 3 days ago (and 2 hours), so that "3 d ago" stays the same from day to day"""
    if isinstance(v, dict):
        return {k: dates(x) for k, x in v.items()}
    if isinstance(v, list):
        return [dates(x) for x in v]
    m = re.match(r"^@-(\d+)d$", v) if isinstance(v, str) else None
    if m:
        t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=int(m.group(1)), hours=2)
        return t.strftime("%Y-%m-%dT%H:%M:%SZ")
    return v


def serve(fixtures, log):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, body, ctype="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:   # image request cancelled by Qt
                pass

        def do_GET(self):
            path = urlparse(self.path).path
            if path.startswith("/img/"):
                log.append("GET " + self.path)
                return self.reply(png(path[5:11]), "image/png")
            if path in fixtures:
                log.append("GET " + self.path)
                return self.reply(json.dumps(fixtures[path], default=str).encode())
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            log.append("POST %s %s" % (self.path, self.rfile.read(n).decode()))
            self.reply(b'{"ok": true}')

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 8080), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def shoot(qml_dir, out):
    if os.environ.get("QMLSHOTS_DEBUG"):
        import faulthandler
        faulthandler.dump_traceback_later(60, exit=True)
    from PySide6.QtCore import (Property, QDate, QDateTime, QEventLoop, QTime, QObject, QTimer, QUrl, Signal, Slot, qInstallMessageHandler)
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import qmlRegisterType
    from PySide6.QtQuick import QQuickPaintedItem, QQuickView, QQuickWindow, QSGRendererInterface

    class Box(QObject):
        openRequested = Signal()
        closeRequested = Signal()
        keyPressed = Signal(str)
        textInput = Signal(str, bool)
        powerMenuRequested = Signal()
        ambientChanged = Signal()
        videoActiveChanged = Signal()
        homeChanged = Signal()

        def __init__(self):
            super().__init__()
            self._video = False
            self.calls = []
            self._ambient = json.dumps({"weather": {"temp": 14, "text": "Nuageux"},
                                        "qr": {"rows": fixtures["/api/qr"]["rows"], "url": "http://192.168.1.20:8080/"}})

        ambient = Property(str, lambda self: self._ambient, notify=ambientChanged)
        ambientOn = Property(bool, lambda self: False, notify=homeChanged)
        statusText = Property(str, lambda self: "", notify=homeChanged)
        qrMode = Property(str, lambda self: "always", notify=homeChanged)
        videoActive = Property(bool, lambda self: self._video, notify=videoActiveChanged)

        def set_video(self, v):
            self._video = v
            self.videoActiveChanged.emit()

        @Slot(bool)
        def setMenuOpen(self, v):
            self.calls.append("setMenuOpen %s" % v)

    class FakeVideo(QQuickPaintedItem):   # MpvVideo of ui.py (libmpv): a pink rectangle where the video would be
        whichChanged = Signal()

        def __init__(self, parent=None):
            super().__init__(parent)
            self._which = "main"

        which = Property(str, lambda self: self._which, lambda self, v: setattr(self, "_which", v), notify=whichChanged)

        def paint(self, painter):
            painter.fillRect(0, 0, int(self.width()), int(self.height()), QColor("#ff2fa8"))

    class LivePreview(QObject):   # livePreview of ui.py: "plays" at once
        changed = Signal()

        def __init__(self):
            super().__init__()
            self._ready = False

        ready = Property(bool, lambda self: self._ready, notify=changed)

        @Slot(str)
        def play(self, login):
            box.calls.append("livePreview.play " + login)
            self._ready = True
            self.changed.emit()

        @Slot()
        def stop(self):
            box.calls.append("livePreview.stop")
            self._ready = False
            self.changed.emit()

    class Pip(QObject):   # second stream running: shortcuts in Live
        changed = Signal()
        channel = Property(str, lambda self: "pipguy", notify=changed)
        layout = Property(str, lambda self: "pip", notify=changed)
        chatCorner = Property(str, lambda self: "bl", notify=changed)

        @Slot(str, str)
        def open(self, channel, layout):
            pass

        @Slot()
        def swap(self):
            pass

        @Slot()
        def close(self):
            pass

        @Slot(str)
        def setLayout(self, layout):
            pass

    class I18n(QObject):
        changed = Signal()

        def __init__(self, d):
            super().__init__()
            self._dict = d
        dict = Property("QVariantMap", lambda self: self._dict, notify=changed)
        lang = Property(str, lambda self: "fr", notify=changed)

    fixtures = dates(json.load(open(os.path.join(HERE, "fixtures.json"), encoding="utf-8")))
    posts = []
    serve(fixtures, posts)
    console = []

    def handler(mode, ctx, msg):
        console.append("%s %s" % (str(mode).split(".")[-1], msg))
    qInstallMessageHandler(handler)

    os.makedirs(out, exist_ok=True)
    root = tempfile.mkdtemp()
    shutil.copytree(qml_dir, os.path.join(root, "qml"))
    with open(os.path.join(root, "harness.qml"), "w") as f:
        f.write('import QtQuick\nimport "qml"\nRectangle {\n    width: 1920; height: 1080; color: "#203040"\n'
                '    TvMenu { objectName: "tvMenu" }\n}\n')

    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QGuiApplication(sys.argv[:1])   # noqa: F841  (kept referenced: Qt needs the application object alive)
    box = Box()
    pip = Pip()
    live_preview = LivePreview()
    qmlRegisterType(FakeVideo, "StreamBox", 1, 0, "MpvVideo")
    i18n = I18n(json.load(open(os.path.join(REPO, "locales", "fr.json"), encoding="utf-8")))
    view = QQuickView()
    view.rootContext().setContextProperty("box", box)
    view.rootContext().setContextProperty("pip", pip)
    view.rootContext().setContextProperty("livePreview", live_preview)
    view.rootContext().setContextProperty("i18n", i18n)
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(1920, 1080)
    view.setSource(QUrl.fromLocalFile(os.path.join(root, "harness.qml")))
    for e in view.errors():
        console.append("ERROR " + e.toString())
    view.show()

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()
    wait(1500)
    console.append("INFO graphics API %s" % view.rendererInterface().graphicsApi())
    steps = STEPS[:int(os.environ.get("QMLSHOTS_STEPS") or len(STEPS))]
    for i, step in enumerate(steps):
        if step[0] == "key":
            box.keyPressed.emit(step[1])
        elif step[0] == "open":
            box.openRequested.emit()
        elif step[0] == "power":
            box.powerMenuRequested.emit()
        elif step[0] == "close":
            box.closeRequested.emit()
        elif step[0] == "text":
            box.textInput.emit(step[1], step[2])
        elif step[0] == "video":
            box.set_video(step[1])
        elif step[0] == "pause":
            wait(step[1])
        t0 = time.monotonic()
        wait(WAIT)
        t1 = time.monotonic()
        # clock of the header: always 12:00 (the timer of the menu writes the real time every 10 s)
        menu = view.rootObject().findChild(QObject, "tvMenu")
        menu.setProperty("now", QDateTime(QDate(2026, 10, 26), QTime(12, 0)))
        img = view.grabWindow()
        if os.environ.get("QMLSHOTS_DEBUG"):
            print("step %d: wait %.2f s, grab %.2f s" % (i, t1 - t0, time.monotonic() - t1), flush=True)
        label = "-".join(str(s) for s in step).replace(" ", "_")
        img.save(os.path.join(out, "%03d-%s.png" % (i, label)))
        # state of the menu after the step (same keys, same state: compared with the console)
        state = {k: menu.property(k) for k in ("isOpen", "tab", "area", "kbOpen", "kbText", "mRow", "rpRow")}
        modal = menu.property("modal")
        state["modal"] = modal.property("title").toString() if hasattr(modal, "property") and modal.isObject() else None
        console.append("--- step %03d %s %s" % (i, label, json.dumps(state, ensure_ascii=False, default=str)))
    with open(os.path.join(out, "console.log"), "w") as f:
        f.write("\n".join(console + ["", "# requests (sorted: they come from several threads)"] + sorted(posts) + ["", "# box"] + box.calls) + "\n")
    print("%d screenshots in %s, %d console lines" % (len(steps), out, sum(1 for c in console if not c.startswith("---"))))


def diff(a, b):
    import numpy as np
    from PIL import Image
    names = sorted(n for n in os.listdir(a) if n.endswith(".png"))
    worst, bad = 0, 0
    for n in names:
        if not os.path.exists(os.path.join(b, n)):
            print("missing in B:", n)
            bad += 1
            continue
        x = np.asarray(Image.open(os.path.join(a, n)).convert("RGB"), dtype=np.int16)
        y = np.asarray(Image.open(os.path.join(b, n)).convert("RGB"), dtype=np.int16)
        if x.shape != y.shape:
            print("size differs:", n)
            bad += 1
            continue
        d = np.abs(x - y).max(axis=2)
        m, cnt = int(d.max()), int((d > 8).sum())
        worst = max(worst, m)
        if cnt:
            bad += 1
            ys, xs = np.nonzero(d > 8)
            print("%s: %d px differ (max %d) in x %d-%d, y %d-%d" % (n, cnt, m, xs.min(), xs.max(), ys.min(), ys.max()))
    print("%d frames compared, %d differ (more than 8/255 on a channel), max difference %d" % (len(names), bad, worst))
    return bad


if __name__ == "__main__":
    if sys.argv[1] == "shoot":
        shoot(os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]))
    elif sys.argv[1] == "diff":
        sys.exit(1 if diff(sys.argv[2], sys.argv[3]) else 0)
