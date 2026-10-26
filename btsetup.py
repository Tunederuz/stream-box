"""Stream Box: Bluetooth remotes and gamepads (bluetoothctl): list, scan, pairing, unpairing.

Used by remote.py (GET / POST /api/bluetooth), itself driven by the TV System menu. Pairing is done without a code
(NoInputNoOutput agent: "Just Works" remotes, gamepads, keyboards), then the device is marked as trusted (it reconnects
on its own) and connected.
"""
import os, re, subprocess, threading

from i18n import tr

SCAN_SECONDS = 20
# Scan or pairing in progress: btagent.py (permanent agent) then also accepts unknown devices
PAIRING_FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "stream-box-bt-pairing")
state = {"scanning": False, "busy": None, "message": None, "found": {}}   # found: address -> name seen during the scan
lock = threading.Lock()


def ctl(*args, timeout=15):
    r = subprocess.run(["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout)
    return re.sub(r"\x1b\[[0-9;]*m", "", r.stdout), r.returncode


def device_list(*filt):
    out, _ = ctl("devices", *filt)
    return [(m.group(1), m.group(2).strip()) for m in re.finditer(r"^Device ([0-9A-F:]{17}) (.*)$", out, re.M)]


def info(mac):
    out, _ = ctl("info", mac)
    get = lambda k: (re.search(rf"^\s*{k}: (.*)$", out, re.M) or [None, ""])[1].strip()
    return {"name": get("Name") or get("Alias") or mac, "icon": get("Icon"), "paired": get("Paired") == "yes",
            "connected": get("Connected") == "yes", "trusted": get("Trusted") == "yes"}


def is_input(icon):
    return icon.startswith("input") or icon in ("", "unknown")   # remotes often have no icon


def status():
    paired = []
    for mac, _ in device_list("Paired"):
        i = info(mac)
        paired.append({"mac": mac, "name": i["name"], "connected": i["connected"], "icon": i["icon"]})
    known = {d["mac"] for d in paired}
    found = []
    for mac, name in state["found"].items():
        if mac in known:
            continue
        i = info(mac)
        # Devices without a real name (address shown as the name): left out, the list is full of them
        if re.fullmatch(r"[0-9A-F-]{17}", i["name"].replace(":", "-")):
            continue
        found.append({"mac": mac, "name": i["name"], "icon": i["icon"], "input": is_input(i["icon"])})
    found.sort(key=lambda d: (not d["input"], d["name"].lower()))
    return {"paired": paired, "found": found, "scanning": state["scanning"], "busy": state["busy"],
            "message": state["message"]}


def open_pairing():
    with open(PAIRING_FLAG, "w"):
        pass


def scan():
    """SCAN_SECONDS-second scan in the background; the devices seen are added to found"""
    if state["scanning"]:
        return
    open_pairing()
    state.update(scanning=True, message=None, found={})
    ctl("power", "on")

    def run():
        try:
            before = {mac for mac, _ in device_list()}
            ctl("--timeout", str(SCAN_SECONDS), "scan", "on", timeout=SCAN_SECONDS + 10)
            state["found"] = {mac: name for mac, name in device_list() if mac not in before or not info(mac)["paired"]}
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            state["scanning"] = False
    threading.Thread(target=run, daemon=True).start()


def pair(mac):
    if not re.fullmatch(r"[0-9A-F:]{17}", mac):
        raise ValueError(tr("invalid address"))

    open_pairing()

    def run():
        with lock:
            name = info(mac)["name"]
            state.update(busy=mac, message=tr("Pairing {name}…", name=name))
            try:
                ctl("--agent", "NoInputNoOutput", "--timeout", "40", "pair", mac, timeout=50)
                # Only BlueZ's state counts: bluetoothctl can end without error while pairing did not succeed
                # (remote left pairing mode, USB receiver resetting along the way…)
                if not info(mac)["paired"]:
                    state["message"] = tr("Couldn't pair {name}: put it back in pairing mode and try again.", name=name)
                    return
                ctl("trust", mac)
                ctl("--timeout", "15", "connect", mac, timeout=25)
                state["message"] = (tr("{name} paired and connected.", name=name) if info(mac)["connected"] else
                                    tr("{name} paired: press one of its buttons to connect it.", name=name))
            except (OSError, subprocess.SubprocessError):
                state["message"] = tr("Couldn't pair {name}.", name=name)
            finally:
                state["busy"] = None
    threading.Thread(target=run, daemon=True).start()


def remove(mac):
    if not re.fullmatch(r"[0-9A-F:]{17}", mac):
        raise ValueError(tr("invalid address"))
    name = info(mac)["name"]
    ctl("remove", mac)
    state["message"] = tr("{name} unpaired.", name=name)
