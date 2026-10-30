"""Inlet: games streamed from a PC (Sunshine on the PC, Moonlight on the box), for the TV menu's "PC games" tab.
Standard library only; Moonlight itself is moonlight-qt's command line (moonlight pair / list / stream / quit), its
pairing kept in its own settings (~/.config/Moonlight Game Streaming Project/).

The PC: found on the network (mDNS, _nvstream._tcp, what Sunshine announces; otherwise the box's /24 tried on
Sunshine's port 47989), or the one already paired
(~/.config/stream-box/gamestream.json: {"host": "<address>"}). Pairing: the box picks a 4-digit code, shows it on the
TV, and waits in "moonlight pair" while it is typed in Sunshine's PIN page. While a game streams, the moonlight process
covers the screen; its PID is in GAMESTREAM_PID, so that input.py leaves the keys to it (a long press on Home ends
the stream).
"""
import concurrent.futures, csv, io, json, os, random, re, shutil, socket, struct, subprocess, threading, time
import urllib.request

from common import COOKIES_DIR, GAMESTREAM_PID, lan_ip, mpv
from i18n import tr

CONF = os.path.join(COOKIES_DIR, "gamestream.json")
MOONLIGHT = shutil.which("moonlight") or shutil.which("moonlight-qt")
APPS_CACHE = 60   # seconds: the list of games, asked again when the tab is opened after that
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


def run(args, timeout=30):
    return subprocess.run([MOONLIGHT, *args], capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL)


def load_apps(host):
    """Games of the paired PC (moonlight list --csv): [{name, art}], art a local file (Moonlight's box art cache) or
    empty. Not paired: None, and the reason in state["apps_error"]."""
    try:
        r = run(["list", host, "--csv"])
    except (OSError, subprocess.SubprocessError) as e:
        state["apps_error"] = str(e)
        return None
    if r.returncode != 0:
        state["apps_error"] = "unpaired" if "not been paired" in (r.stdout + r.stderr) else (r.stderr.strip() or "error")
        return None
    rows = [line for line in r.stdout.splitlines() if line.startswith('"')]
    apps = []
    for row in csv.reader(io.StringIO("\n".join(rows)), skipinitialspace=True):
        if len(row) >= 7 and row[4] != "true":   # (hidden apps left out)
            art = row[6] if row[6].startswith("file:") else ""
            apps.append({"name": row[0], "art": art})
    state["apps_error"] = ""
    return apps


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
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)}


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
    """Closes the game on the PC"""
    host = read_conf().get("host")
    if host:
        threading.Thread(target=lambda: run(["quit", host], timeout=20), daemon=True).start()
