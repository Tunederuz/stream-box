"""Stream Box : installation sur un disque interne, depuis la box qui tourne sur une clé USB (image disque, image/).

Menu Système de la TV → « Installer sur ce PC » : choix du disque, confirmation, progression. Le travail est fait par
root (/usr/local/lib/stream-box/install-to-disk, lancé par stream-box-install@<disque>.service ; règle polkit
53-stream-box-install.rules : media ne peut démarrer que ce service), qui écrit son état dans
/run/stream-box-install.json. Utilisé par remote.py (GET /api/install, POST /api/install {disk}).

Proposé seulement quand la box a démarré sur une clé USB (ou un disque amovible) et que l'image a l'installateur ;
disques proposés : internes, 16 Go au moins, autres que celui de la box.
"""
import json, os, re, subprocess

SCRIPT = "/usr/local/lib/stream-box/install-to-disk"
STATUS = "/run/stream-box-install.json"
MIN_SIZE = 16 * 1000 ** 3


def flag(v):
    return v in (True, 1, "1")


def disks():
    r = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,TYPE,RM,HOTPLUG,TRAN,SIZE,MODEL,MOUNTPOINTS,FSTYPE,LABEL"],
                       capture_output=True, text=True, timeout=10)
    try:
        return json.loads(r.stdout or "{}").get("blockdevices") or []
    except ValueError:
        return []


def mounts(d):
    """Points de montage d'un disque et de ses partitions (tous : un btrfs en sous-volumes en a plusieurs)"""
    return (d.get("mountpoints") or []) + [m for c in d.get("children") or [] for m in mounts(c)]


def status():
    """{available, live, disks: [{name, label, size, data}], progress}"""
    all_disks = disks()
    root = next((d for d in all_disks if "/" in mounts(d)), None)
    live = bool(root and (root.get("tran") == "usb" or flag(root.get("rm")) or flag(root.get("hotplug"))))
    found = []
    for d in all_disks:
        if d is root or d.get("type") != "disk" or d.get("tran") == "usb" or flag(d.get("rm")) \
                or re.match(r"(loop|zram|sr|ram)", d.get("name", "")) or int(d.get("size") or 0) < MIN_SIZE:
            continue
        size = int(d["size"])
        model = (d.get("model") or "").strip() or d["name"]
        parts = d.get("children") or []
        # Ce qu'il contient, pour le dire avant d'effacer (Windows, Linux…)
        labels = [p.get("label") or p.get("fstype") for p in parts if p.get("fstype")]
        found.append({"name": d["name"], "label": f"{model} · {size / 1e9:.0f} Go", "size": size,
                      "data": ", ".join(dict.fromkeys(l for l in labels if l))[:60] or (len(parts) and "données") or ""})
    try:
        with open(STATUS) as f:
            progress = json.load(f)
    except (OSError, ValueError):
        progress = None
    return {"available": live and os.path.exists(SCRIPT), "live": live, "disks": found, "progress": progress}


def start(name):
    s = status()
    if not s["available"]:
        raise ValueError("L'installation se lance depuis la box démarrée sur sa clé USB.")
    if (s["progress"] or {}).get("state") == "running":
        raise ValueError("Installation déjà en cours.")
    if name not in [d["name"] for d in s["disks"]]:
        raise ValueError("Disque inconnu.")
    r = subprocess.run(["systemctl", "start", "--no-block", f"stream-box-install@{name}.service"],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise ValueError(f"Installation refusée : {(r.stderr or r.stdout).strip() or r.returncode}")
