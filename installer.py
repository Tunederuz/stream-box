"""Stream Box: installation to an internal disk, from the box running on a USB drive (disk image, image/).

TV System menu → "Install on this PC": disk choice, confirmation, progress. The work is done by root
(/usr/local/lib/stream-box/install-to-disk, started by stream-box-install@<disk>.service; polkit rule
53-stream-box-install.rules: media can only start that service), which writes its state to
/run/stream-box-install.json. Used by remote.py (GET /api/install, POST /api/install {disk}).

Offered only when the box booted from a USB drive (or a removable disk) and the image has the installer; disks
offered: internal, 16 GB at least, other than the box's own.
"""
import json, os, re, subprocess

from i18n import tr

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
    """Mount points of a disk and its partitions (all of them: a btrfs with subvolumes has several)"""
    return (d.get("mountpoints") or []) + [m for c in d.get("children") or [] for m in mounts(c)]


def raid_mode():
    """Intel disk controller in RAID mode (RST): an NVMe SSD behind it is hidden from Arch's kernel ("remapped NVMe"),
    the BIOS must be switched to AHCI (Dell: SATA Operation → AHCI)"""
    try:
        for dev in os.listdir("/sys/bus/pci/devices"):
            with open(f"/sys/bus/pci/devices/{dev}/class") as f:
                if f.read().strip() == "0x010400":
                    return True
    except OSError:
        pass
    return False


def status():
    """{available, live, disks: [{name, label, size, data}], raid_mode, progress}"""
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
        # What it holds, to say so before erasing (Windows, Linux…)
        labels = [p.get("label") or p.get("fstype") for p in parts if p.get("fstype")]
        found.append({"name": d["name"], "label": f"{model} · " + tr("{size} GB", size=f"{size / 1e9:.0f}"), "size": size,
                      "data": ", ".join(dict.fromkeys(l for l in labels if l))[:60] or (len(parts) and tr("data")) or ""})
    try:
        with open(STATUS) as f:
            progress = json.load(f)
    except (OSError, ValueError):
        progress = None
    if isinstance(progress, dict):   # step and error are written in English by the root script: translated here
        if progress.get("step"):
            progress["step"] = tr(progress["step"])
        error = progress.get("error")
        if error:
            m = re.match(r"error during: (.*)$", error)
            progress["error"] = tr("error during: {step}", step=tr(m.group(1))) if m else tr(error)
    return {"available": live and os.path.exists(SCRIPT), "live": live, "disks": found,
            "raid_mode": not found and raid_mode(), "progress": progress}


def start(name):
    s = status()
    if not s["available"]:
        raise ValueError(tr("The installation must be started from the box booted on its USB drive."))
    if (s["progress"] or {}).get("state") == "running":
        raise ValueError(tr("Installation already in progress."))
    if name not in [d["name"] for d in s["disks"]]:
        raise ValueError(tr("Unknown disk."))
    r = subprocess.run(["systemctl", "start", "--no-block", f"stream-box-install@{name}.service"],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise ValueError(tr("Installation refused: {error}", error=(r.stderr or r.stdout).strip() or r.returncode))
