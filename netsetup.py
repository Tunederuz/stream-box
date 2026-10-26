"""Stream Box: network setup mode (Wi-Fi), through NetworkManager (nmcli).

With no network at boot and a Wi-Fi card, the box creates its own hotspot ("Stream Box XXXX", password shown on the TV
with a QR code): the phone connects to it, opens the companion app (http://10.42.0.1:8080) and picks the home Wi-Fi.
On Ethernet, nothing to do. Used by remote.py (setup_loop loop, /api/wifi API).
Permissions: NetworkManager allows the active local session (remote.py runs in the TV session); the image adds a polkit
rule for media.
"""
import json, os, random, string, subprocess, threading, time

from i18n import tr

HOTSPOT_CON = "stream-box-setup"            # NetworkManager connection of the hotspot
HOTSPOT_URL = "http://10.42.0.1:8080/"       # box address on its hotspot (NetworkManager shared network)
CONF = os.path.expanduser("~/.config/stream-box/hotspot.json")
START_AFTER = 25                              # seconds after boot before deciding (DHCP, known Wi-Fi…)
OFFLINE_GRACE = 60                            # saved Wi-Fi lost: NetworkManager retries on its own during this time
RETRY_EVERY = 180                             # hotspot with no phone connected: retry the saved Wi-Fi

lock = threading.Lock()
state = {"connecting": None, "error": None, "networks": [], "scanned": 0, "manual_until": 0}


def nmcli(*args, timeout=20):
    r = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"nmcli {args[0]}: code {r.returncode}")
    return r.stdout


def split(line):
    """nmcli -t line: fields separated by ":", "\\:" for a colon inside a value"""
    out, cur, i = [], "", 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            cur += line[i + 1]
            i += 2
            continue
        if line[i] == ":":
            out.append(cur)
            cur = ""
        else:
            cur += line[i]
        i += 1
    return out + [cur]


def wifi_device():
    """The box's Wi-Fi card, always the same one: the hotspot's if it is running, otherwise the first by name, skipping
    a card already used as a hotspot for something else (two cards: tests, connection sharing)"""
    try:
        devs = sorted(split(l)[0] for l in nmcli("-t", "-f", "DEVICE,TYPE", "device").splitlines() if split(l)[1] == "wifi")
        acts = active()
        for name, _, dev in acts:
            if name == HOTSPOT_CON and dev in devs:
                return dev
        for dev in devs:
            other = next((name for name, kind, d in acts if d == dev and kind.endswith("wireless")), None)
            if other and nmcli("-g", "802-11-wireless.mode", "connection", "show", other).strip() == "ap":
                continue
            return dev
    except (OSError, RuntimeError, subprocess.SubprocessError, IndexError):
        pass
    return None


def active():
    """Active connections: [(name, type, device)]"""
    try:
        return [tuple(split(l)[:3]) for l in nmcli("-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active").splitlines()]
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return []


def online():
    """Home network: an active Ethernet or Wi-Fi connection, other than the hotspot"""
    return any(name != HOTSPOT_CON and (kind.endswith("ethernet") or kind.endswith("wireless")) for name, kind, _ in active())


def saved_wifi():
    """Saved home Wi-Fi (NetworkManager profile), other than the hotspot"""
    try:
        return any(split(l)[1].endswith("wireless") and split(l)[0] != HOTSPOT_CON
                   for l in nmcli("-t", "-f", "NAME,TYPE", "connection", "show").splitlines())
    except (OSError, RuntimeError, subprocess.SubprocessError, IndexError):
        return False


def clients(dev):
    """Devices connected to the hotspot"""
    try:
        r = subprocess.run(["iw", "dev", dev, "station", "dump"], capture_output=True, text=True, timeout=5)
        return r.stdout.count("Station ")
    except (OSError, subprocess.SubprocessError):
        return 0


def hotspot_on():
    return any(name == HOTSPOT_CON for name, _, _ in active())


def hotspot_conf():
    """Hotspot name and password: drawn once, kept (the QR code on the TV doesn't change)"""
    try:
        with open(CONF, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("ssid") and len(c.get("password", "")) >= 8:
            return c
    except (OSError, ValueError):
        pass
    c = {"ssid": "Stream Box " + "".join(random.choices(string.ascii_uppercase + string.digits, k=4)),
         "password": "".join(random.choices("abcdefghjkmnpqrstuvwxyz23456789", k=10))}
    os.makedirs(os.path.dirname(CONF), mode=0o700, exist_ok=True)
    with open(CONF, "w", encoding="utf-8") as f:
        json.dump(c, f)
    os.chmod(CONF, 0o600)
    return c


def scan(dev):
    """Visible networks, strongest to weakest (one per name). Impossible while the hotspot runs on many cards: the
    list is taken just before creating it, and kept."""
    try:
        seen = {}
        for line in nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", dev, "--rescan", "yes",
                          timeout=30).splitlines():
            ssid, signal, security = (split(line) + ["", "", ""])[:3]
            if ssid and ssid != hotspot_conf()["ssid"] and int(signal or 0) > seen.get(ssid, {}).get("signal", -1):
                seen[ssid] = {"ssid": ssid, "signal": int(signal or 0), "secure": bool(security and security != "--")}
        if seen:
            state["networks"] = sorted(seen.values(), key=lambda n: -n["signal"])
            state["scanned"] = time.time()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        pass


def start_hotspot(dev):
    c = hotspot_conf()
    scan(dev)
    try:   # a single profile (nmcli creates a new one each time)
        while True:
            nmcli("connection", "delete", HOTSPOT_CON)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass
    nmcli("device", "wifi", "hotspot", "ifname", dev, "con-name", HOTSPOT_CON, "ssid", c["ssid"],
          "band", "bg", "password", c["password"], timeout=40)


def stop_hotspot():
    try:
        nmcli("connection", "down", HOTSPOT_CON)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass


def connect(ssid, password):
    """In the background: the hotspot stops (a single radio), the box joins ssid; on failure, the hotspot comes back
    and the error is kept for the page."""
    dev = wifi_device()
    if not dev:
        raise ValueError(tr("No Wi-Fi card on this box."))
    if not ssid:
        raise ValueError(tr("Pick a network."))

    def run():
        with lock:
            state.update(connecting=ssid, error=None)
            stop_hotspot()
            time.sleep(2)
            try:
                # The card leaves hotspot mode with no network list: scan again, until ssid shows up
                for _ in range(6):
                    scan(dev)
                    if any(n["ssid"] == ssid for n in state["networks"]):
                        break
                    time.sleep(3)
                args = ["device", "wifi", "connect", ssid, "ifname", dev] + (["password", password] if password else [])
                nmcli(*args, timeout=60)
            except (OSError, RuntimeError, subprocess.SubprocessError) as e:
                msg = str(e)
                why = (tr("wrong password?") if "psk" in msg or "ecret" in msg or "activation failed" in msg
                       else tr("network not found (too far?)") if "found" in msg else msg[:160])
                state["error"] = tr("Couldn't connect to \"{ssid}\": {reason}", ssid=ssid, reason=why)
                try:
                    nmcli("connection", "delete", ssid)   # profile created but unusable (wrong password…)
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    pass
                try:
                    start_hotspot(dev)
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    pass
            finally:
                state["connecting"] = None
    threading.Thread(target=run, daemon=True).start()


def status():
    dev = wifi_device()
    acts = active()
    # Home network: Ethernet, or Wi-Fi on the box's card
    home = next(((n, k) for n, k, d in acts if n != HOTSPOT_CON and (k.endswith("ethernet") or (k.endswith("wireless") and d == dev))), None)
    hot = any(n == HOTSPOT_CON for n, _, _ in acts)
    return {"device": dev, "mode": "hotspot" if hot else "connected" if home else "none",
            "network": home[0] if home else None, "wired": bool(home and home[1].endswith("ethernet")),
            "hotspot": dict(hotspot_conf(), url=HOTSPOT_URL) if hot else None,
            "networks": state["networks"], "connecting": state["connecting"], "error": state["error"]}


def setup_loop():
    """At boot, then every 10 s: with no network and a Wi-Fi card, setup hotspot; when there is a network again (cable
    plugged in…), it stops. Recovery at any time: a saved Wi-Fi that gets lost (router restarted, password changed…)
    gives NetworkManager OFFLINE_GRACE seconds to find it again, then the hotspot comes back; with no phone on it, it
    steps aside every RETRY_EVERY seconds to retry the saved Wi-Fi (a single radio: no network scan while the hotspot
    runs)."""
    time.sleep(START_AFTER)
    offline_since, hotspot_since = None, None
    while True:
        try:
            if not state["connecting"] and not lock.locked():
                dev = wifi_device()
                up, hot = online(), hotspot_on()
                offline_since = None if up or hot else (offline_since or time.time())
                hotspot_since = (hotspot_since or time.time()) if hot else None
                if dev and not up and not hot:
                    if not saved_wifi() or time.time() - offline_since >= OFFLINE_GRACE:
                        start_hotspot(dev)
                        state["started"] = hotspot_since = time.time()
                elif hot and up and time.time() > state["manual_until"]:
                    stop_hotspot()
                elif (hot and time.time() > state["manual_until"] and saved_wifi() and not clients(dev)
                      and time.time() - hotspot_since >= RETRY_EVERY):
                    stop_hotspot()   # NetworkManager retries the saved Wi-Fi; otherwise back to the hotspot
                    offline_since = time.time() - OFFLINE_GRACE + 45
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            state["error"] = tr("Couldn't start the hotspot: {error}", error=str(e)[:160])
        time.sleep(10)


def manual_hotspot():
    """TV menu "Change Wi-Fi network": hotspot right away, even with a network"""
    dev = wifi_device()
    if not dev:
        raise ValueError(tr("No Wi-Fi card on this box."))
    state["manual_until"] = time.time() + 900   # kept 15 min even if Ethernet is plugged in
    def run():
        with lock:
            for name, kind, d in active():
                if d == dev and name != HOTSPOT_CON:
                    try:
                        nmcli("connection", "down", name)
                    except (OSError, RuntimeError, subprocess.SubprocessError):
                        pass
            try:
                start_hotspot(dev)
            except (OSError, RuntimeError, subprocess.SubprocessError) as e:
                state["error"] = tr("Couldn't start the hotspot: {error}", error=str(e)[:160])
    threading.Thread(target=run, daemon=True).start()
