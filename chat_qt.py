"""Stream Box: Twitch chat with emotes for the Qt app (ui.py), shown in QML (qml/ChatOverlay.qml).

Same reading as chat_overlay.py (anonymous IRC, read-only), but each message is split into pieces: words and
emotes. Twitch emotes: positions given by the "emotes" tag of the message. 7TV, BTTV and FFZ emotes: by their name,
global lists loaded once, channel lists loaded as soon as the chat gives its id (ROOMSTATE).
Images are loaded and animated by Qt (GIF, WebP).

The player alone (mpv without the app) keeps chat_overlay.py, as text; when the app runs, it writes
user-data/streambox/chat_ui = "qml" and chat_overlay.py stays quiet.
"""
import json, random, socket, ssl, threading, time, urllib.request
from collections import deque

MAX_MESSAGES = 10
LIFETIME = 45      # seconds before a message disappears (like chat_overlay.py)
MAX_CHARS = 90     # truncates walls of text
TWITCH_EMOTE = "https://static-cdn.jtvnw.net/emoticons/v2/{}/default/dark/2.0"   # "default": animated if it is


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "stream-box"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def seventv(emotes):
    out = {}
    for e in emotes or []:
        host = ((e.get("data") or {}).get("host") or {}).get("url")
        if e.get("name") and host:
            out[e["name"]] = f"https:{host}/2x.webp"
    return out


def bttv(emotes):
    return {e["code"]: f"https://cdn.betterttv.net/emote/{e['id']}/2x" for e in emotes or [] if e.get("code")}


def ffz(emotes):
    return {e["code"]: (e.get("images") or {}).get("2x") or (e.get("images") or {}).get("1x")
            for e in emotes or [] if e.get("code") and e.get("images")}


def global_emotes():
    """Global emotes of the three services; an unreachable service is simply ignored"""
    out = {}
    for url, conv in (("https://api.betterttv.net/3/cached/frankerfacez/emotes/global", ffz),
                      ("https://api.betterttv.net/3/cached/emotes/global", bttv),
                      ("https://7tv.io/v3/emote-sets/global", lambda d: seventv(d.get("emotes")))):
        try:
            out.update(conv(fetch_json(url)))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
    return out


def channel_emotes(room_id):
    """Channel emotes; priority 7TV > BTTV > FFZ (the last ones override the first ones)"""
    out = {}
    try:
        out.update(ffz(fetch_json(f"https://api.betterttv.net/3/cached/frankerfacez/users/twitch/{room_id}")))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    try:
        d = fetch_json(f"https://api.betterttv.net/3/cached/users/twitch/{room_id}")
        out.update(bttv((d.get("sharedEmotes") or []) + (d.get("channelEmotes") or [])))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    try:
        d = fetch_json(f"https://7tv.io/v3/users/twitch/{room_id}")
        out.update(seventv(((d.get("emote_set") or {}).get("emotes"))))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return out


def color(hex_color):
    """Username color; colors too dark become lavender (unreadable on the video)"""
    if not (hex_color and len(hex_color) == 7):
        return "#c9b8ff"
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#c9b8ff" if 0.299 * r + 0.587 * g + 0.114 * b < 90 else hex_color


def parse_tags(raw):
    return dict(p.split("=", 1) for p in raw.split(";") if "=" in p)


class Chat:
    """Chat of the current channel; on_change(list of messages) called on each change, from another thread"""

    def __init__(self, on_change):
        self.on_change = on_change
        self.channel = None
        self.messages = deque(maxlen=MAX_MESSAGES)
        self.lock = threading.Lock()
        self.globals, self.local, self.room = {}, {}, None
        threading.Thread(target=self._load_globals, daemon=True).start()
        threading.Thread(target=self._irc_loop, daemon=True).start()
        threading.Thread(target=self._expire_loop, daemon=True).start()

    def set_channel(self, channel):
        if channel != self.channel:
            self.channel = channel
            with self.lock:
                self.messages.clear()
                self.local, self.room = {}, None
            self._publish()

    def _load_globals(self):
        while not self.globals:
            self.globals = global_emotes()
            if not self.globals:
                time.sleep(60)

    def _load_channel(self, room_id):
        emotes = channel_emotes(room_id)
        with self.lock:
            if self.room == room_id:
                self.local = emotes

    def _parts(self, text, emotes_tag):
        """Words and emotes: [{"t": "x", "v": word} | {"t": "e", "u": url, "n": name}]"""
        twitch = {}   # start position → (end, id)
        for spec in (emotes_tag or "").split("/"):
            if ":" not in spec:
                continue
            eid, ranges = spec.split(":", 1)
            for rng in ranges.split(","):
                if "-" in rng:
                    a, b = rng.split("-", 1)
                    if a.isdigit() and b.isdigit():
                        twitch[int(a)] = (int(b), eid)
        parts, i, word = [], 0, ""
        emotes = {**self.globals, **self.local}

        def flush():
            nonlocal word
            if word:
                url = emotes.get(word)
                parts.append({"t": "e", "u": url, "n": word} if url else {"t": "x", "v": word})
                word = ""
        while i < len(text):
            if i in twitch:
                flush()
                end, eid = twitch[i]
                parts.append({"t": "e", "u": TWITCH_EMOTE.format(eid), "n": text[i:end + 1]})
                i = end + 1
            elif text[i] == " ":
                flush()
                i += 1
            else:
                word += text[i]
                i += 1
        flush()
        return parts

    def _handle(self, line):
        tags, rest, prefix = {}, line, ""
        if rest.startswith("@"):
            raw, rest = rest[1:].split(" ", 1)
            tags = parse_tags(raw)
        if rest.startswith(":"):
            prefix, rest = rest[1:].split(" ", 1)
        head, _, trailing = rest.partition(" :")
        command = head.split(" ")[0]
        changed = False
        with self.lock:
            if command == "ROOMSTATE" and tags.get("room-id") and tags["room-id"] != self.room:
                self.room = tags["room-id"]
                threading.Thread(target=self._load_channel, args=(self.room,), daemon=True).start()
            elif command == "PRIVMSG":
                text = trailing
                if text.startswith("\x01ACTION ") and text.endswith("\x01"):
                    text = text[8:-1]
                cut = len(text) > MAX_CHARS
                parts = self._parts(text[:MAX_CHARS] if cut else text, tags.get("emotes"))
                if cut:
                    parts.append({"t": "x", "v": "…"})
                self.messages.append({"t": time.time(), "id": tags.get("id"), "user": tags.get("user-id"),
                                      "name": tags.get("display-name") or prefix.split("!")[0],
                                      "color": color(tags.get("color")), "parts": parts})
                changed = True
            elif command == "CLEARMSG":
                target = tags.get("target-msg-id")
                for m in [m for m in self.messages if m["id"] == target]:
                    self.messages.remove(m)
                    changed = True
            elif command == "CLEARCHAT":
                target = tags.get("target-user-id")
                for m in [m for m in self.messages if not target or m["user"] == target]:
                    self.messages.remove(m)
                    changed = True
        if changed:
            self._publish()

    def _publish(self):
        with self.lock:
            snapshot = [{k: m[k] for k in ("id", "name", "color", "parts")} for m in self.messages]
        self.on_change(snapshot)

    def _expire_loop(self):
        while True:
            time.sleep(2)
            now, changed = time.time(), False
            with self.lock:
                while self.messages and now - self.messages[0]["t"] > LIFETIME:
                    self.messages.popleft()
                    changed = True
            if changed:
                self._publish()

    def _irc_loop(self):
        ctx = ssl.create_default_context()
        while True:
            channel = self.channel
            if not channel:
                time.sleep(1)
                continue
            try:
                raw = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=10)
                with ctx.wrap_socket(raw, server_hostname="irc.chat.twitch.tv") as s:
                    nick = f"justinfan{random.randint(1000, 80000)}"   # anonymous connection, read-only
                    s.sendall(f"CAP REQ :twitch.tv/tags twitch.tv/commands\r\nNICK {nick}\r\nJOIN #{channel}\r\n".encode())
                    s.settimeout(1)   # to notice a channel change quickly
                    buf, last_data = b"", time.time()
                    while self.channel == channel:
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
                                self._handle(line)
            except OSError:
                time.sleep(5)
