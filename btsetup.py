"""Stream Box : télécommandes et manettes Bluetooth (bluetoothctl) : liste, recherche, appairage, dissociation.

Utilisé par remote.py (GET / POST /api/bluetooth), lui-même piloté par le menu Système de la TV. L'appairage se fait
sans code (agent NoInputNoOutput : télécommandes, manettes, claviers « Just Works »), puis l'appareil est marqué de
confiance (il se reconnecte seul) et connecté.
"""
import os, re, subprocess, threading

SCAN_SECONDS = 20
# Recherche ou appairage en cours : btagent.py (agent permanent) accepte alors aussi les appareils inconnus
PAIRING_FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "stream-box-bt-pairing")
state = {"scanning": False, "busy": None, "message": None, "found": {}}   # found : adresse -> nom vu à la recherche
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
    return icon.startswith("input") or icon in ("", "unknown")   # télécommandes souvent sans icône


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
        # Appareils sans vrai nom (adresse affichée en guise de nom) : écartés, la liste en est pleine
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
    """Recherche de SCAN_SECONDS secondes en arrière-plan ; les appareils vus s'ajoutent à found"""
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
        raise ValueError("adresse invalide")

    open_pairing()

    def run():
        with lock:
            name = info(mac)["name"]
            state.update(busy=mac, message=f"Appairage de {name}…")
            try:
                ctl("--agent", "NoInputNoOutput", "--timeout", "40", "pair", mac, timeout=50)
                # Seul l'état de BlueZ fait foi : bluetoothctl peut finir sans erreur sans que l'appairage ait abouti
                # (télécommande sortie du mode appairage, récepteur USB qui se réinitialise en route…)
                if not info(mac)["paired"]:
                    state["message"] = f"Appairage de {name} impossible : remets-le en mode appairage et réessaie."
                    return
                ctl("trust", mac)
                ctl("--timeout", "15", "connect", mac, timeout=25)
                state["message"] = f"{name} appairé" + (" et connecté." if info(mac)["connected"] else
                                                         " : appuie sur une de ses touches pour le connecter.")
            except (OSError, subprocess.SubprocessError):
                state["message"] = f"Appairage de {name} impossible."
            finally:
                state["busy"] = None
    threading.Thread(target=run, daemon=True).start()


def remove(mac):
    if not re.fullmatch(r"[0-9A-F:]{17}", mac):
        raise ValueError("adresse invalide")
    name = info(mac)["name"]
    ctl("remove", mac)
    state["message"] = f"{name} dissocié."
