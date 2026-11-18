"""Inlet: Bluetooth remotes and gamepads (bluetoothctl): list, scan, pairing, unpairing.

Used by remote.py (GET / POST /api/bluetooth), itself driven by the TV System menu. Pairing is done without a code
(NoInputNoOutput agent: "Just Works" remotes, gamepads, keyboards), then the device is marked as trusted (it reconnects
on its own) and connected.

The scan (SCAN_SECONDS) reads bluetoothctl's events as they come: the devices show up in the TV dialog at once. Started
with auto (the TV), the first remote, gamepad or keyboard seen is paired by itself: an Xbox controller stays in pairing
mode only ~20 s. A device already paired but seen in the scan (paired again with a console or a PC since: its bond here
is lost) can be chosen too: its old pairing is removed first. Pairing: the scan stopped (some adapters don't connect
while scanning), "pair" given PAIR_SECONDS; failed: the device removed, looked for again, paired a second time.
"""
import os, re, subprocess, threading, time

from i18n import tr

SCAN_SECONDS = 60
PAIR_SECONDS = 30
FIND_AGAIN_SECONDS = 15   # before the second try (the device removed: BlueZ must see it again)
# Scan or pairing in progress: btagent.py (permanent agent) then also accepts unknown devices
PAIRING_FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "stream-box-bt-pairing")
MAC = r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}"
# found: address -> {name, icon, paired} seen during the scan; auto: the first input device seen gets paired
state = {"scanning": False, "busy": None, "message": None, "found": {}, "auto": False, "error": False}
scanner = {"proc": None}
lock = threading.Lock()


def ctl(*args, timeout=15):
    r = subprocess.run(["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout)
    return re.sub(r"\x1b\[[0-9;]*m", "", r.stdout), r.returncode


def device_list(*filt):
    out, _ = ctl("devices", *filt)
    return [(m.group(1), m.group(2).strip()) for m in re.finditer(rf"^Device ({MAC}) (.*)$", out, re.M)]


def info(mac):
    out, _ = ctl("info", mac)
    get = lambda k: (re.search(rf"^\s*{k}: (.*)$", out, re.M) or [None, ""])[1].strip()
    return {"name": get("Name") or get("Alias") or mac, "icon": get("Icon"), "paired": get("Paired") == "yes",
            "connected": get("Connected") == "yes", "trusted": get("Trusted") == "yes", "known": bool(out.strip())
            and "not available" not in out}


def is_input(icon):
    return icon.startswith("input") or icon in ("", "unknown")   # remotes often have no icon


def unnamed(name):
    return bool(re.fullmatch(r"[0-9A-F]{2}([-:][0-9A-F]{2}){5}", name))


def status():
    paired = []
    for mac, _ in device_list("Paired"):
        i = info(mac)
        paired.append({"mac": mac, "name": i["name"], "connected": i["connected"], "icon": i["icon"]})
    connected = {d["mac"] for d in paired if d["connected"]}
    found = []
    for mac, d in list(state["found"].items()):
        # Devices without a real name (address shown as the name): left out, the list is full of them (unless it says
        # it is a remote, a gamepad, a keyboard: its name may come later)
        if mac in connected or (unnamed(d["name"]) and not d["icon"].startswith("input")):
            continue
        found.append({"mac": mac, "name": d["name"], "icon": d["icon"], "input": is_input(d["icon"]),
                      "paired": d["paired"]})
    found.sort(key=lambda d: (not d["input"], d["name"].lower()))
    return {"paired": paired, "found": found, "scanning": state["scanning"], "busy": state["busy"],
            "message": state["message"], "error": state["error"], "auto": state["auto"]}


def open_pairing():
    with open(PAIRING_FLAG, "w"):
        pass


def parse(line, seen):
    """One line of "bluetoothctl scan on" (colours removed) into seen (address -> {name, icon}): the address of a
    device seen, or None. "[DEL] Device …": taken out of seen."""
    m = re.match(rf"^\[(NEW|CHG|DEL)\] Device ({MAC})(?: (.*))?$", line.strip())
    if not m:
        return None
    kind, mac, rest = m.group(1), m.group(2), (m.group(3) or "").strip()
    if kind == "DEL":
        seen.pop(mac, None)
        return None
    d = seen.setdefault(mac, {"name": mac, "icon": ""})
    if kind == "NEW":
        d["name"] = rest or mac
    else:
        k, _, v = rest.partition(": ")
        if k in ("Name", "Alias") and v and (k == "Name" or unnamed(d["name"])):
            d["name"] = v
        elif k == "Icon":
            d["icon"] = v
        elif k == "Connected" and v == "yes":
            return None   # (a paired device coming back on its own: not a scan result)
    return mac


def discover(seconds, on_seen):
    """bluetoothctl's scan for `seconds` in the background, each device seen given to on_seen(mac, seen) (from the
    reading thread); ended by stop_scan(). Returns the process."""
    stop_scan()
    proc = subprocess.Popen(["bluetoothctl", "--timeout", str(seconds), "scan", "on"], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True, errors="replace")
    scanner["proc"] = proc
    seen = {}

    def read():
        for line in proc.stdout:
            mac = parse(re.sub(r"\x1b\[[0-9;]*m|\r", "", line), seen)
            if mac:
                on_seen(mac, seen[mac])
        proc.wait()
    t = threading.Thread(target=read, daemon=True)
    t.start()
    return proc, t


def stop_scan():
    proc = scanner["proc"]
    scanner["proc"] = None
    if proc and proc.poll() is None:
        proc.terminate()   # (its discovery session ends with it)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def scan(auto=False):
    """SCAN_SECONDS-second scan in the background; the devices seen are added to found as they come. auto: the first
    remote, gamepad or keyboard seen is paired at once."""
    if state["scanning"] or state["busy"]:
        state["auto"] = state["auto"] or auto
        return
    open_pairing()
    state.update(scanning=True, message=None, error=False, found={}, auto=auto)
    ctl("power", "on")
    known = {}   # address -> its BlueZ state, asked once

    def on_seen(mac, d):
        if mac not in known:
            known[mac] = info(mac)
        i = known[mac]
        if i["connected"]:
            return
        icon = d["icon"] or i["icon"]
        name = d["name"] if not unnamed(d["name"]) else i["name"]
        state["found"][mac] = {"name": name, "icon": icon, "paired": i["paired"]}
        if state["auto"] and not state["busy"] and icon.startswith("input") and not unnamed(name):
            state["auto"] = False
            pair(mac)

    proc, reader = discover(SCAN_SECONDS, on_seen)

    def run():
        reader.join()
        if scanner["proc"] is proc:
            scanner["proc"] = None
        state["scanning"] = False
    threading.Thread(target=run, daemon=True).start()


def until(args, done, seconds):
    """bluetoothctl <args> in the background, given up to `seconds`, ended as soon as done() is true (checked every
    second): with --timeout, bluetoothctl stays for the whole duration even once the device is paired or connected,
    and the TV dialog with it"""
    proc = subprocess.Popen(["bluetoothctl", *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if done():
                return True
            if proc.poll() is not None:   # ended by itself (failure, or a bluetoothctl that returns once done)
                return done()
            time.sleep(1)
        return done()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def find_again(mac, seconds):
    """Scan until the device is seen again (removed from BlueZ, or forgotten since the scan), at most `seconds`"""
    event = threading.Event()
    proc, reader = discover(seconds, lambda m, d: m == mac and event.set())
    event.wait(seconds)
    stop_scan()
    return event.is_set()


def pair(mac):
    if not re.fullmatch(MAC, mac):
        raise ValueError(tr("invalid address"))

    open_pairing()
    name = (state["found"].get(mac) or {}).get("name") or mac
    state.update(busy=mac, message=tr("Pairing {name}…", name=name), error=False, auto=False)

    def run():
        with lock:
            try:
                stop_scan()
                i = info(mac)
                name_ = i["name"] if not unnamed(i["name"]) else name
                # Already paired here (then paired with a console or a PC: the bond is lost), or forgotten by BlueZ
                # since the scan: removed / looked for again first
                if i["paired"]:
                    ctl("remove", mac)
                    i = {"known": False}
                if not i["known"] and not find_again(mac, FIND_AGAIN_SECONDS):
                    state.update(message=tr("{name} is not in pairing mode any more: put it back in pairing mode and "
                                            "try again.", name=name_), error=True)
                    return
                ok = False
                for attempt in (1, 2):
                    # Only BlueZ's state counts: bluetoothctl can end without error while pairing did not succeed
                    # (device left pairing mode, USB receiver resetting along the way…)
                    ok = until(["--agent", "NoInputNoOutput", "--timeout", str(PAIR_SECONDS), "pair", mac],
                               lambda: info(mac)["paired"], PAIR_SECONDS)
                    if ok or attempt == 2:
                        break
                    state["message"] = tr("Pairing {name}: second try…", name=name_)
                    ctl("remove", mac)
                    if not find_again(mac, FIND_AGAIN_SECONDS):
                        break
                if not ok:
                    state.update(message=tr("Couldn't pair {name}: put it back in pairing mode and try again.",
                                            name=name_), error=True)
                    return
                ctl("trust", mac)
                state["message"] = tr("Connecting {name}…", name=name_)
                connected = until(["--timeout", "15", "connect", mac], lambda: info(mac)["connected"], 15)
                state["message"] = (tr("{name} paired and connected.", name=name_) if connected else
                                    tr("{name} paired: press one of its buttons to connect it.", name=name_))
                state["found"].pop(mac, None)
            except (OSError, subprocess.SubprocessError):
                state.update(message=tr("Couldn't pair {name}.", name=name), error=True)
            finally:
                state["busy"] = None
    threading.Thread(target=run, daemon=True).start()


def remove(mac):
    if not re.fullmatch(MAC, mac):
        raise ValueError(tr("invalid address"))
    name = info(mac)["name"]
    ctl("remove", mac)
    state["message"] = tr("{name} unpaired.", name=name)
