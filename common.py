"""Stream Box: what the companion app's modules (remote.py and the modules it imports) share: port, paths, mpv's
IPC socket, private JSON files. Standard library only.
"""
import json, os, socket

PORT = 8080
MPV_SOCKET = "/tmp/stream-box-mpv.sock"
DIR = os.path.dirname(os.path.abspath(__file__))
# Box settings and tokens (700: also protects the files that yt-dlp rewrites as 644, see twitch.py)
COOKIES_DIR = os.path.expanduser("~/.config/stream-box")
PUBLISH_EVERY = 10   # seconds between two sends of already known data to mpv: a restarted mpv gets them quickly


def mpv(*commands):
    """Sends commands to mpv; returns the data field of each reply, in order."""
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(2)
        s.connect(MPV_SOCKET)
        for i, cmd in enumerate(commands):
            s.sendall((json.dumps({"command": list(cmd), "request_id": i}) + "\n").encode())
        results, buf = {}, b""
        while len(results) < len(commands):
            data = s.recv(65536)
            if not data:
                raise OSError("mpv closed")
            *lines, buf = (buf + data).split(b"\n")
            for line in lines:
                msg = json.loads(line)
                if "event" not in msg and "request_id" in msg:
                    results[msg["request_id"]] = msg.get("data")
        return [results[i] for i in range(len(commands))]


def lan_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))   # nothing is sent: only used to learn the outgoing address
        return s.getsockname()[0]


def read_json_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_private_json(path, data):
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)
