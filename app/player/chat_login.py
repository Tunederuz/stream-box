"""Inlet: how the chat readers (chat_qt.py, chat_overlay.py) log in to Twitch's chat. With the account connected
(its token, from streamlink's config) the account joins the channel's chat like on the website and shows among its
chatters; it stays read-only (nothing is ever sent but PONG). Without one, or refused by the chat: anonymously
(justinfanNNNN). Standard library only (chat_overlay.py runs on its own)."""
import json, os, random, re, urllib.request

CONFIG = os.path.expanduser("~/.config/streamlink/config.twitch")
REFUSED = "Login authentication failed"   # the chat's NOTICE for a token it does not take
known = {}   # token -> its login, or None once the chat refused it


def token():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            m = re.search(r"^twitch-api-header=Authorization=OAuth (\S+)", f.read(), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def login():
    """(the lines that log in, the token used or None)"""
    t = token()
    if t and t not in known:
        try:
            req = urllib.request.Request("https://id.twitch.tv/oauth2/validate", headers={"Authorization": "OAuth " + t})
            with urllib.request.urlopen(req, timeout=10) as r:
                known[t] = json.load(r).get("login")
        except (OSError, ValueError):
            pass   # (unreachable, or refused: anonymous this time, asked again at the next connection)
    if t and known.get(t):
        return f"PASS oauth:{t}\r\nNICK {known[t]}\r\n", t
    return f"NICK justinfan{random.randint(1000, 80000)}\r\n", None


def refused(t, line):
    """The chat refused the token (its NOTICE): anonymous from now on with that token; True if it is that line"""
    if t and REFUSED in line:
        known[t] = None
        return True
    return False
