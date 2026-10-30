"""Inlet: games streamed from a PC (Sunshine on the PC, Moonlight on the box), for the TV menu's "PC games" tab.
Standard library only; Moonlight itself is moonlight-qt's command line (moonlight pair / stream), its pairing
kept in its own settings (~/.config/Moonlight Game Streaming Project/); the list of games, their box art and closing a game go to
Sunshine directly, with the client certificate Moonlight made at pairing.

The PC: found on the network (mDNS, _nvstream._tcp, what Sunshine announces; otherwise the box's /24 tried on
Sunshine's port 47989), or the one already paired
(~/.config/stream-box/gamestream.json: {"host": "<address>"}). Pairing: the box picks a 4-digit code, shows it on the
TV, and waits in "moonlight pair" while it is typed in Sunshine's PIN page. While a game streams, the moonlight process
covers the screen; its PID is in GAMESTREAM_PID, so that input.py leaves the keys to it (a long press on Home ends
the stream).
"""
import concurrent.futures, html, json, os, random, re, shutil, socket, ssl, struct, subprocess, threading, time
import urllib.parse, urllib.request

from common import COOKIES_DIR, GAMESTREAM_PID, lan_ip, mpv
from i18n import tr

CONF = os.path.join(COOKIES_DIR, "gamestream.json")
MOONLIGHT = shutil.which("moonlight") or shutil.which("moonlight-qt")
APPS_CACHE = 60   # seconds: the list of games, asked again when the tab is opened after that
# Pairing: no window (moonlight-qt would open its own over the TV menu, full screen in cage)
QUIET = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
lock = threading.Lock()
state = {"pairing": None, "apps": None, "apps_at": 0, "apps_error": "", "found": [], "found_at": 0, "busy": False}
proc = {"stream": None, "pair": None}


def available():
    return bool(MOONLIGHT)


def read_conf():
    try:
        with open(CONF, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_conf(conf):
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    with open(CONF, "w", encoding="utf-8") as f:
        json.dump(conf, f)


def discover(timeout=1.5):
    """Addresses of the PCs announcing a game stream on the network (mDNS question for _nvstream._tcp.local, answered
    by Sunshine and by NVIDIA GameStream): the senders of the answers."""
    name = b"".join(bytes([len(p)]) + p for p in b"_nvstream._tcp.local".split(b".")) + b"\0"
    query = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0) + name + struct.pack(">HH", 12, 0x8001)   # PTR, unicast answer
    found = set()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.3)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        s.sendto(query, ("224.0.0.251", 5353))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, (addr, _) = s.recvfrom(4096)
            except socket.timeout:
                continue
            if b"_nvstream" in data:
                found.add(addr)
    except OSError:
        pass
    finally:
        s.close()
    return sorted(found)


def scan():
    """Without an mDNS answer (no Avahi on the PC, a firewall on port 5353): the addresses of the box's network
    (its /24) that have Sunshine's port 47989 open, tried all at once (about a second)"""
    try:
        prefix = lan_ip().rsplit(".", 1)[0]
    except OSError:
        return []

    def try_one(addr):
        try:
            with socket.create_connection((addr, 47989), timeout=0.6):
                return addr
        except OSError:
            return None
    with concurrent.futures.ThreadPoolExecutor(64) as pool:
        return [a for a in pool.map(try_one, (f"{prefix}.{i}" for i in range(1, 255))) if a]


def serverinfo(host):
    """Name and state of the PC (Sunshine's public page, no pairing needed): {name, playing} or None if unreachable"""
    try:
        with urllib.request.urlopen(f"http://{host}:47989/serverinfo", timeout=3) as r:
            xml = r.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    field = lambda tag: (re.search(f"<{tag}>(.*?)</{tag}>", xml) or [None, ""])[1]
    return {"name": field("hostname") or host, "playing": field("currentgame") not in ("", "0")}


MOONLIGHT_CONF = os.path.expanduser("~/.config/Moonlight Game Streaming Project/Moonlight.conf")
ART_DIR = os.path.expanduser("~/.cache/stream-box/gamestream")


def client_identity():
    """Moonlight's client certificate and key (created at pairing, in its settings: QSettings, @ByteArray(...) with
    escaped newlines), written as PEM files for ssl; with its uniqueid. None before any pairing."""
    try:
        with open(MOONLIGHT_CONF, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    values = {}
    for key in ("certificate", "key", "uniqueid"):
        m = re.search(rf'^{key}="?(?:@ByteArray\()?(.*?)\)?"?$', text, re.M)
        if m:
            values[key] = m.group(1).replace("\\n", "\n")
    if "certificate" not in values or "key" not in values:
        return None
    os.makedirs(ART_DIR, mode=0o700, exist_ok=True)
    paths = (os.path.join(ART_DIR, "client.crt"), os.path.join(ART_DIR, "client.key"))
    for path, value in zip(paths, (values["certificate"], values["key"])):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(value)
    return {"cert": paths[0], "key": paths[1], "uniqueid": values.get("uniqueid", "0123456789ABCDEF")}


def sunshine(host, path, **params):
    """A request to Sunshine's paired API (HTTPS 47984, Moonlight's client certificate): bytes, or None when the
    box isn't paired (Sunshine answers 401) or the PC is unreachable. Its own certificate is self-signed: not checked."""
    me = client_identity()
    if not me:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    ctx.load_cert_chain(me["cert"], me["key"])
    query = urllib.parse.urlencode({"uniqueid": me["uniqueid"], **params})
    try:
        with urllib.request.urlopen(f"https://{host}:47984/{path}?{query}", context=ctx, timeout=6) as r:
            return r.read()
    except (OSError, ValueError):
        return None


def load_apps(host):
    """Games of the paired PC (Sunshine's applist): [{name, id, art}], art served by the box (/api/gamestream_art).
    Not paired: None. (moonlight list is not used: moonlight-qt 6.2's hangs on an assertion once paired.)"""
    xml = sunshine(host, "applist")
    if xml is None or b'status_code="200"' not in xml:
        state["apps_error"] = "unpaired"
        return None
    apps = []
    for block in re.findall(rb"<App>(.*?)</App>", xml, re.S):
        field = lambda tag: (re.search(rb"<%s>(.*?)</%s>" % (tag, tag), block, re.S) or [None, b""])[1].decode("utf-8", "replace")
        name, app_id = html.unescape(field(b"AppTitle")), field(b"ID")
        if name and app_id.isdigit():
            apps.append({"name": name, "id": app_id, "art": f"http://127.0.0.1:8080/api/gamestream_art?id={app_id}"})
    state["apps_error"] = ""
    return apps


def art(app_id):
    """Box art of a game (PNG), asked once to Sunshine then kept in ~/.cache/stream-box/gamestream; None if missing"""
    if not str(app_id).isdigit():
        return None
    path = os.path.join(ART_DIR, f"{app_id}.png")
    if not os.path.exists(path):
        host = read_conf().get("host")
        data = sunshine(host, "appasset", appid=app_id, AssetType=2, AssetIdx=0) if host else None
        if not data:
            return None
        os.makedirs(ART_DIR, mode=0o700, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    with open(path, "rb") as f:
        return f.read()


def refresh(host):
    def work():
        apps = load_apps(host)
        with lock:
            state["apps"], state["apps_at"], state["busy"] = apps, time.time(), False
    state["busy"] = True
    threading.Thread(target=work, daemon=True).start()


def status():
    """GET /api/gamestream: the PC (found or paired), pairing in progress, its games, a stream running"""
    if not available():
        return {"available": False}
    conf = read_conf()
    if time.time() - state["found_at"] > 30 and not conf.get("host"):   # (looked for in the background: a few seconds)
        state["found_at"] = time.time()

        def look():
            state["found"] = discover() or scan()
        threading.Thread(target=look, daemon=True).start()
    host = conf.get("host") or (state["found"][0] if state["found"] else "")
    info = serverinfo(host) if host else None
    pairing = None
    p = proc["pair"]
    if p:
        code = p["proc"].poll()
        if code is None:
            pairing = {"pin": p["pin"], "page": f"https://{host}:47990/pin"}
        else:
            proc["pair"] = None
            if code == 0:
                write_conf({"host": p["host"]})
                state["apps_at"] = 0   # paired: list the games now
            else:
                pairing = {"error": tr("The pairing failed: try again, and type the code in Sunshine within a minute.")}
    if host and info and not state["busy"] and time.time() - state["apps_at"] > APPS_CACHE and not proc["pair"]:
        refresh(host)
    s = proc["stream"]
    return {"available": True, "host": host, "name": info["name"] if info else host, "online": bool(info),
            "playing": bool(info and info["playing"]), "paired": state["apps"] is not None,
            "loading": state["busy"] and state["apps"] is None, "apps": state["apps"] or [],
            "unpaired": state["apps_error"] == "unpaired", "pairing": pairing,
            "streaming": bool(s and s.poll() is None)}


def pair(body):
    """Starts "moonlight pair" with a code of our own, shown on the TV until it is typed in Sunshine"""
    host = read_conf().get("host") or (state["found"][0] if state["found"] else "")
    if not host:
        raise ValueError(tr("No PC with Sunshine found on the network"))
    if proc["pair"] and proc["pair"]["proc"].poll() is None:
        return
    pin = f"{random.randint(0, 9999):04d}"
    proc["pair"] = {"pin": pin, "host": host,
                    "proc": subprocess.Popen([MOONLIGHT, "pair", host, "--pin", pin], stdin=subprocess.DEVNULL,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=QUIET)}


def search(body):
    """Looks for the PC on the network again (Settings: "Search again")"""
    state["found_at"] = 0


def forget(body):
    """Forgets the PC (another one can then be chosen): its address, the list of games, the cached box art. The
    pairing stays in Moonlight's settings, so the same PC comes back paired."""
    try:
        os.remove(CONF)
    except OSError:
        pass
    for name in os.listdir(ART_DIR) if os.path.isdir(ART_DIR) else []:
        if name.endswith(".png"):
            os.remove(os.path.join(ART_DIR, name))
    state.update({"apps": None, "apps_at": 0, "apps_error": "", "found": [], "found_at": 0})


def pair_cancel(body):
    p = proc["pair"]
    if p and p["proc"].poll() is None:
        p["proc"].terminate()
    proc["pair"] = None


def launch(body):
    """Streams a game: the player stops (home screen behind), Moonlight takes the screen until the stream ends"""
    host, app = read_conf().get("host"), str(body.get("app") or "")
    if not host or not app:
        raise ValueError(tr("unknown game"))
    if proc["stream"] and proc["stream"].poll() is None:
        return
    mpv(["stop"])
    p = subprocess.Popen([MOONLIGHT, "stream", host, app], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=open("/tmp/stream-box-moonlight.log", "w"), start_new_session=True)
    proc["stream"] = p
    with open(GAMESTREAM_PID, "w") as f:
        f.write(str(p.pid))

    def wait():   # stream over: the keys go back to the menu
        p.wait()
        try:
            os.remove(GAMESTREAM_PID)
        except OSError:
            pass
        mpv(["script-message", "streambox-tvmenu-open"])
    threading.Thread(target=wait, daemon=True).start()


def stop(body):
    """Ends the stream (the game keeps running on the PC)"""
    p = proc["stream"]
    if p and p.poll() is None:
        p.terminate()


def quit_game(body):
    """Closes the game on the PC (Sunshine's cancel)"""
    host = read_conf().get("host")
    if host:
        threading.Thread(target=lambda: sunshine(host, "cancel"), daemon=True).start()
