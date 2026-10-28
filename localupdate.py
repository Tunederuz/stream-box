"""Stream Box: system update from a local image, without the Internet (A/B boxes): the full disk image of a release
(stream-box.raw.xz, the one used to install), from a USB stick (TV System menu, companion app) or sent from the
companion app, with the release's SHA256SUMS and SHA256SUMS.gpg next to it (unsigned: developer mode only).

remote.py (media) puts the files in STAGE, on the data partition, then starts stream-box-local-update.service (root,
/usr/local/lib/stream-box/local-update: checks, writes the slot not in use, restarts); its progress is read from
/run/stream-box-local-update.json. Used by api.py (GET /api/local_update, POST /api/local_update_upload?file=…) and
actions.py (POST /api/local_update {action: usb | start}).
"""
import json, os, re, shutil, subprocess, threading

import backup     # backup.py: USB drives (listing, mounted for the time of a job)
import system     # system.py: developer mode
from i18n import tr

STAGE = os.path.expanduser("~/.local/state/stream-box/local-update")
JOB = "/run/stream-box-local-update.json"
FILES = {"image": "stream-box.raw.xz", "sums": "SHA256SUMS", "sig": "SHA256SUMS.gpg"}
IMAGE_NAME = re.compile(r"stream-box[\w.~+-]{0,80}\.raw\.xz")
MAX_SIZE = 4 << 30   # image (about 1.5 GB)
MARGIN = 700 << 20   # free space needed beyond the image: the ESP copied out of it, and some room

copying = {"name": None, "done": 0, "total": 0, "error": None}
lock = threading.Lock()
listing = {}   # (path, uuid) → images found on the drive


def available():
    """A/B box: the data partition mounted (/data) and two system partitions on the disk of /"""
    if not os.path.ismount("/data"):
        return False
    try:
        r = subprocess.run(["lsblk", "-J", "-o", "PKNAME,PARTTYPE,MOUNTPOINT"], capture_output=True, text=True, timeout=10)
        devs = json.loads(r.stdout).get("blockdevices") or []
        disk = next(d["pkname"] for d in devs if d.get("mountpoint") == "/")
        return sum(1 for d in devs if d.get("pkname") == disk
                   and (d.get("parttype") or "").lower() == "4f68bce3-e8cd-4db1-96e7-fbcaf984b709") >= 2
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
        return False


def images_on(part):
    """Images at the root of the drive: [{name, size, signed}] (signed: SHA256SUMS and SHA256SUMS.gpg next to it)"""
    with backup.Mounted(part) as root:
        names = set(os.listdir(root))
        signed = FILES["sums"] in names and FILES["sig"] in names
        return [{"name": n, "size": os.path.getsize(os.path.join(root, n)), "signed": signed}
                for n in sorted(names) if IMAGE_NAME.fullmatch(n) and os.path.isfile(os.path.join(root, n))]


def job():
    try:
        with open(JOB, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def status():
    """A/B box?, developer mode, copy in progress, root job's progress, images on the plugged-in drives"""
    usb = []
    if available():
        parts = backup.usb_partitions()
        keys = {(p["path"], p["uuid"]) for p in parts}
        for k in list(listing):
            if k not in keys:
                listing.pop(k)
        for p in parts:
            k = (p["path"], p["uuid"])
            if k not in listing and not copying["name"] and lock.acquire(blocking=False):
                try:
                    listing[k] = images_on(p)
                except (OSError, subprocess.SubprocessError):
                    listing[k] = []
                finally:
                    lock.release()
            if listing.get(k):
                usb.append({"path": p["path"], "drive": p["name"], "images": listing[k]})
    r = subprocess.run(["systemctl", "show", "-p", "ActiveState", "stream-box-local-update.service"],
                       capture_output=True, text=True, timeout=10)
    starting = r.stdout.strip() == "ActiveState=activating"
    busy = copying["name"] is not None or starting
    j = job()
    if starting and (j or {}).get("state") != "running":   # the previous run's result, until this one writes
        j = None
    return {"available": available(), "dev": system.dev_status()["enabled"], "busy": busy,
            "copy": dict(copying) if copying["name"] or copying["error"] else None, "job": j, "usb": usb}


def check_space(size):
    os.makedirs(STAGE, exist_ok=True)
    if shutil.disk_usage(STAGE).free < size + MARGIN:
        raise ValueError(tr("Not enough room on the box for the image ({size} GB needed).",
                            size=f"{(size + MARGIN) / 1e9:.1f}"))


def clear():
    os.makedirs(STAGE, exist_ok=True)
    for f in os.listdir(STAGE):
        os.remove(os.path.join(STAGE, f))


def start():
    """Files in place: the root job (it checks them, installs, restarts)"""
    if not os.path.isfile(os.path.join(STAGE, FILES["image"])):
        raise ValueError(tr("No image to install."))
    r = subprocess.run(["systemctl", "start", "--no-block", "stream-box-local-update.service"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise ValueError((r.stderr or r.stdout).strip() or tr("Couldn't start the update."))


def copy_file(src, name):
    tmp = os.path.join(STAGE, name + ".part")
    with open(src, "rb") as s, open(tmp, "wb") as d:
        while chunk := s.read(4 << 20):
            d.write(chunk)
            copying["done"] += len(chunk)
    os.replace(tmp, os.path.join(STAGE, name))


def from_usb(path, name):
    """Image chosen on a USB drive (with its signature files if there): copied to the box, then installed"""
    if not available():
        raise ValueError(tr("This box has no A/B layout: install it again from a 0.2.0 or later image."))
    if not IMAGE_NAME.fullmatch(name or ""):
        raise ValueError(tr("unknown image"))
    part = backup.find_part(path)
    if copying["name"]:
        raise ValueError(tr("An update is already in progress."))

    def run():
        with lock:
            copying.update(name=name, done=0, total=0, error=None)
            try:
                with backup.Mounted(part) as root:
                    src = {k: os.path.join(root, n) for k, n in (("image", name), ("sums", FILES["sums"]), ("sig", FILES["sig"]))
                           if os.path.isfile(os.path.join(root, n))}
                    copying["total"] = sum(os.path.getsize(p) for p in src.values())
                    check_space(copying["total"])
                    clear()
                    for k, p in src.items():
                        copy_file(p, FILES[k])
                start()
                copying.update(name=None)
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                copying.update(name=None, error=str(e))
    threading.Thread(target=run, daemon=True).start()


def receive(kind, stream, length):
    """File sent from the companion app (POST /api/local_update_upload?file=image|sums|sig, raw body), written as it
    arrives; the image first clears what an earlier upload left"""
    if kind not in FILES:
        raise ValueError(tr("unknown file"))
    if not available():
        raise ValueError(tr("This box has no A/B layout: install it again from a 0.2.0 or later image."))
    if length > (MAX_SIZE if kind == "image" else 1 << 20):
        raise ValueError(tr("File too large."))
    if kind == "image":
        check_space(length)
        clear()
        copying.update(name=FILES["image"], done=0, total=length, error=None)
    tmp = os.path.join(STAGE, FILES[kind] + ".part")
    try:
        with open(tmp, "wb") as f:
            left = length
            while left > 0:
                chunk = stream.read(min(4 << 20, left))
                if not chunk:
                    raise OSError(tr("File cut short."))
                f.write(chunk)
                left -= len(chunk)
                if kind == "image":
                    copying["done"] += len(chunk)
        os.replace(tmp, os.path.join(STAGE, FILES[kind]))
    except OSError as e:
        copying.update(error=str(e))
        raise
    finally:
        if kind == "image":
            copying["name"] = None
