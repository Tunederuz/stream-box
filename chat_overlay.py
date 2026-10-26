#!/usr/bin/env python3
"""Stream Box: shows the Twitch chat as an overlay in mpv, through its IPC socket.

The channel and the display corner come from mpv (user-data/streambox/* properties, set
by stream-box.lua): switching streamer in the menu switches the chat too.
"""
import json, random, select, socket, ssl, threading, time
from collections import deque

MPV_SOCKET = "/tmp/stream-box-mpv.sock"
MAX_MESSAGES = 10
LIFETIME = 45      # seconds before a message disappears
MAX_CHARS = 90     # truncates walls of text
BG_PADDING = 14    # background margin around the text, in 1920x1080 pixels
BOUNDS_REQUEST = 42   # request_id of the text measurement, to recognize its reply
# ASS anchoring and position of each corner, in 1920x1080 coordinates
CORNERS = {
    "tl": "\\an7\\pos(40,40)",
    "tr": "\\an9\\pos(1880,40)",
    "br": "\\an3\\pos(1880,1040)",
    "bl": "\\an1\\pos(40,1040)",
}

messages = deque(maxlen=MAX_MESSAGES)
lock = threading.Lock()
# Updated by mpv (user-data/streambox/*). chat_bg: background opacity in %; chat_size: text size
# tvmenu: big TV menu open (tv_menu.lua), the chat would go over it
# chat_ui: "qml" when the Qt app (ui.py) draws the chat itself, with emotes
state = {"channel": None, "corner": "bl", "chat_visible": True, "chat_bg": 60, "chat_size": 32, "mode": "twitch",
         "tvmenu": False, "chat_ui": None}


def parse_tags(raw):
    return dict(p.split("=", 1) for p in raw.split(";") if "=" in p)


def ass_escape(text):
    # Same escaping as mpv's built-in scripts
    return text.replace("\\", "\\\ufeff").replace("{", "\\{").replace("\n", " ")


def ass_color(hex_color):
    """#RRGGBB -> &HBBGGRR& (ASS is in BGR); usernames too dark -> lavender."""
    if not (hex_color and len(hex_color) == 7):
        hex_color = "#C9B8FF"
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    if 0.299 * r + 0.587 * g + 0.114 * b < 90:
        r, g, b = 0xC9, 0xB8, 0xFF
    return f"&H{b:02X}{g:02X}{r:02X}&"


def handle(line):
    tags, rest, prefix = {}, line, ""
    if rest.startswith("@"):
        raw, rest = rest[1:].split(" ", 1)
        tags = parse_tags(raw)
    if rest.startswith(":"):
        prefix, rest = rest[1:].split(" ", 1)
    head, _, trailing = rest.partition(" :")
    command = head.split(" ")[0]

    with lock:
        if command == "PRIVMSG":
            text = trailing
            if text.startswith("\x01ACTION ") and text.endswith("\x01"):
                text = text[8:-1]
            if len(text) > MAX_CHARS:
                text = text[:MAX_CHARS] + "…"
            messages.append({
                "t": time.time(), "id": tags.get("id"), "user": tags.get("user-id"),
                "name": tags.get("display-name") or prefix.split("!")[0],
                "color": ass_color(tags.get("color")), "text": text,
            })
        elif command == "CLEARMSG":
            target = tags.get("target-msg-id")
            for m in [m for m in messages if m["id"] == target]:
                messages.remove(m)
        elif command == "CLEARCHAT":
            target = tags.get("target-user-id")
            for m in [m for m in messages if not target or m["user"] == target]:
                messages.remove(m)


def render():
    now = time.time()
    with lock:
        while messages and now - messages[0]["t"] > LIFETIME:
            messages.popleft()
        lines = [
            f"{{\\c{m['color']}\\b1}}{ass_escape(m['name'])}{{\\b0\\c&HFFFFFF&}}  {ass_escape(m['text'])}"
            for m in messages
        ]
    if not state["chat_visible"] or state["mode"] != "twitch" or state["tvmenu"] or state["chat_ui"] == "qml":
        return ""
    # Block anchored in the chosen corner, dark outline to stay readable on the video
    style = "{" + CORNERS.get(state["corner"], CORNERS["bl"]) + f"\\fs{state['chat_size']}\\bord2.5\\shad0\\3c&H000000&\\3a&H30&}}"
    return style + "\\N".join(lines) if lines else ""


def irc_loop():
    ctx = ssl.create_default_context()
    while True:
        channel = state["channel"]
        if not channel:
            time.sleep(1)
            continue
        try:
            raw = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=10)
            with ctx.wrap_socket(raw, server_hostname="irc.chat.twitch.tv") as s:
                nick = f"justinfan{random.randint(1000, 80000)}"  # anonymous connection, read-only
                s.sendall(f"CAP REQ :twitch.tv/tags twitch.tv/commands\r\nNICK {nick}\r\nJOIN #{channel}\r\n".encode())
                s.settimeout(1)   # to notice a channel change quickly
                buf, last_data = b"", time.time()
                while state["channel"] == channel:
                    try:
                        data = s.recv(65536)
                    except TimeoutError:
                        if time.time() - last_data > 360:   # Twitch sends a PING every ~5 min
                            raise OSError("no news from the server")
                        continue
                    if not data:
                        raise OSError("connection closed")
                    last_data = time.time()
                    *lines, buf = (buf + data).split(b"\r\n")
                    for line in lines:
                        line = line.decode("utf-8", "replace")
                        if line.startswith("PING"):
                            s.sendall(line.replace("PING", "PONG", 1).encode() + b"\r\n")
                        elif line:
                            handle(line)
        except OSError:
            time.sleep(5)


def on_mpv_message(msg):
    if msg.get("event") != "property-change" or msg.get("data") is None:
        return
    key = msg["name"].rsplit("/", 1)[1]
    if key == "channel" and msg["data"] != state["channel"]:
        with lock:
            messages.clear()
    state[key] = msg["data"]


def overlay(overlay_id, data, request_id=0, **options):
    cmd = {"name": "osd-overlay", "id": overlay_id, "format": "ass-events", "data": data,
           "res_x": 1920, "res_y": 1080, **options}
    return (json.dumps({"command": cmd, "request_id": request_id}) + "\n").encode()


def background(bounds):
    """Semi-transparent black rectangle around the text (bounds returned by mpv, in 1920x1080 coordinates)."""
    if not bounds or "x0" not in bounds or state["chat_bg"] <= 0:
        return ""
    alpha = round(255 * (1 - state["chat_bg"] / 100))   # ASS: 00 = opaque, FF = transparent
    x0, y0 = bounds["x0"] - BG_PADDING, bounds["y0"] - BG_PADDING
    w, h = bounds["x1"] - bounds["x0"] + 2 * BG_PADDING, bounds["y1"] - bounds["y0"] + 2 * BG_PADDING
    return (f"{{\\an7\\pos({x0},{y0})\\bord0\\shad0\\1c&H000000&\\1a&H{alpha:02X}&\\p1}}"
            f"m 0 0 l {w} 0 {w} {h} 0 {h}{{\\p0}}")


def mpv_loop():
    # The connection must stay open: mpv removes the overlay when the client disconnects
    while True:
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.connect(MPV_SOCKET)
                # New player: these settings are only published by the Qt app and the big menu, start from scratch
                state.update(chat_ui=None, tvmenu=False)
                for i, prop in enumerate(("user-data/streambox/channel", "user-data/streambox/corner",
                                          "user-data/streambox/chat_visible", "user-data/streambox/chat_bg",
                                          "user-data/streambox/chat_size", "user-data/streambox/mode",
                                          "user-data/streambox/tvmenu", "user-data/streambox/chat_ui"), 1):
                    s.sendall((json.dumps({"command": ["observe_property", i, prop]}) + "\n").encode())
                buf, sent = b"", None

                def read():
                    nonlocal buf
                    data = s.recv(65536)
                    if not data:
                        raise OSError("mpv closed")
                    *lines, buf = (buf + data).split(b"\n")
                    return [json.loads(line) for line in lines]

                while True:
                    if select.select([s], [], [], 0.25)[0]:
                        for msg in read():
                            on_mpv_message(msg)
                    data = render()
                    if (data, state["chat_bg"]) != sent:
                        # The text is first rendered hidden to know its size, then the background is
                        # drawn below (lower z) and the text on top
                        bounds = None
                        if data:
                            s.sendall(overlay(1, data, BOUNDS_REQUEST, hidden=True, compute_bounds=True))
                            while bounds is None:
                                for msg in read():
                                    if msg.get("request_id") == BOUNDS_REQUEST and "event" not in msg:
                                        bounds = msg.get("data") or {}
                                    else:
                                        on_mpv_message(msg)
                        s.sendall(overlay(2, background(bounds), z=0))
                        s.sendall(overlay(1, data, z=1))
                        sent = (data, state["chat_bg"])
        except (OSError, ValueError):
            time.sleep(2)   # mpv not started yet, or restarted by start.sh


threading.Thread(target=irc_loop, daemon=True).start()
mpv_loop()
