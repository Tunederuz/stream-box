"""Stream Box: backup and restore of settings and connections, without a command line.

TV System menu → "Backup and restore": backup to a USB drive, or restore of a backup found on it. Companion app
(Settings → System): download of the file to the phone, and restore of an uploaded file. Used by remote.py
(GET /api/backup, /api/backup/download; POST /api/backup, /api/backup_restore).

Contents, the same as backup.sh (archive in the same format: install.sh --restore takes it, and vice versa): streamer
list, box settings and history, Twitch / YouTube accounts, Jellyfin connection, MQTT, sound settings, plus the saved
Wi-Fi networks (name and password, recreated by NetworkManager). Not the Bluetooth pairings (root only: backup.sh
keeps them). These are secrets: the file is for your eyes only.

USB drive: mounted by udisks while reading or writing (polkit rule for media), unmounted right after: it can be
removed as soon as it's done. After a restore, the box reboots so that everything starts again from the restored files.
"""
import io, json, os, re, socket, subprocess, tarfile, threading, time

import netsetup   # netsetup.py: nmcli (saved Wi-Fi networks)
from i18n import tr

HOME = os.path.expanduser("~")
# Relative to the home directory; in the archive: home/<user>/… like backup.sh
PATHS = (".local/state/stream-box", ".config/stream-box", ".config/streamlink/config.twitch",
         ".config/jellyfin-mpv-shim", ".local/state/wireplumber")
# Also restored: the streamer list of older backups, next to the code (twitch.py moves it into the settings)
RESTORED = PATHS + ("stream-box/streamers.txt",)
SKIP = re.compile(r"(^|/)(fonts|scripts|offline)(/|$)|\.lock|\.bak$|(^|/)update\.log$|(^|/)before-restore\.tar\.gz$")
MANIFEST = "stream-box-backup.json"
WIFI = "stream-box-wifi.json"
NAME = re.compile(r"stream-box-backup-[\w.-]{1,60}\.tar\.gz")
SAFETY = os.path.join(HOME, ".local/state/stream-box/before-restore.tar.gz")
SETUP_DONE = os.path.join(HOME, ".config/stream-box/setup-done")   # restored: no more first-time setup   # settings from before the last restore
MAX_SIZE = 64 << 20
SHOWN = 4   # backups offered per drive, the most recent

state = {"busy": None, "message": None}
lock = threading.Lock()
listing = {}   # (device, uuid) → backups found on the drive
shown = {"text": None, "at": 0}   # last message: shown for a minute, then the window goes back to its title


# Archive

def wifi_profiles():
    """Wi-Fi networks saved in NetworkManager (not the setup hotspot): [{ssid, psk}]"""
    out = []
    try:
        for line in netsetup.nmcli("-t", "-f", "NAME,TYPE", "connection", "show").splitlines():
            name, kind = netsetup.split(line)[:2]
            if not kind.endswith("wireless") or name == netsetup.HOTSPOT_CON:
                continue
            get = lambda f: netsetup.nmcli("-s", "-g", f, "connection", "show", name).strip()
            if get("802-11-wireless.mode") == "ap":
                continue
            ssid, psk = get("802-11-wireless.ssid"), get("802-11-wireless-security.psk")
            # Protected network whose password can't be read here: not recreated as an open network
            if ssid and (psk or not get("802-11-wireless-security.key-mgmt")):
                out.append({"ssid": ssid, "psk": psk})
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        pass
    return out


def add_json(tar, name, data):
    raw = json.dumps(data, ensure_ascii=False, indent=1).encode()
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.mode = len(raw), int(time.time()), 0o600
    tar.addfile(info, io.BytesIO(raw))


def create():
    """Settings .tar.gz archive, in memory (less than a MB)"""
    buf = io.BytesIO()
    home = HOME.lstrip("/")
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        add_json(tar, MANIFEST, {"version": 1, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "host": socket.gethostname()})
        wifi = wifi_profiles()
        if wifi:
            add_json(tar, WIFI, wifi)
        for p in PATHS:
            if os.path.exists(os.path.join(HOME, p)):
                tar.add(os.path.join(HOME, p), arcname=f"{home}/{p}",
                        filter=lambda m: None if SKIP.search(m.name) or not (m.isfile() or m.isdir()) else m)
    return buf.getvalue()


def file_name():
    return time.strftime("stream-box-backup-%Y-%m-%d-%H%M.tar.gz")


def restore(data):
    """Puts back the files of an archive (from this module or from backup.sh) and its Wi-Fi networks; the previous
    settings are kept in SAFETY. Returns the number of restored items; ValueError if it isn't a backup."""
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except (tarfile.TarError, EOFError, OSError):
        raise ValueError(tr("This file is not a Stream Box backup."))
    with tar:
        members, wifi = [], []
        for m in tar.getmembers():
            if m.name == WIFI and m.isfile():
                try:
                    wifi = json.loads(tar.extractfile(m).read())
                except ValueError:
                    pass
                continue
            # home/<user of the backed-up box>/… → home directory here
            rel = re.match(r"home/[^/]+/(.+)$", m.name)
            rel = rel and rel.group(1)
            if not rel or SKIP.search(rel) or not (m.isfile() or m.isdir()) \
                    or not any(rel == p or rel.startswith(p + "/") for p in RESTORED):
                continue
            m.name = f"{HOME.lstrip('/')}/{rel}"
            members.append(m)
        if not members:
            raise ValueError(tr("This file is not a Stream Box backup."))
        os.makedirs(os.path.dirname(SAFETY), exist_ok=True)
        with open(os.open(SAFETY, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
            f.write(create())
        tar.extractall("/", members=members, filter="data")
        for m in members:   # directories: the "data" filter doesn't keep their permissions (700 for the secret ones)
            if m.isdir():
                os.chmod("/" + m.name, m.mode & 0o755)
    open(SETUP_DONE, "a").close()
    restore_wifi(wifi)
    return len(members)


def restore_wifi(profiles):
    """Backed-up Wi-Fi networks missing here: NetworkManager profiles recreated (automatic connection when in range)"""
    if not profiles or not netsetup.wifi_device():
        return
    try:
        known = set()
        for line in netsetup.nmcli("-t", "-f", "NAME,TYPE", "connection", "show").splitlines():
            name, kind = netsetup.split(line)[:2]
            if kind.endswith("wireless"):
                known.add(netsetup.nmcli("-g", "802-11-wireless.ssid", "connection", "show", name).strip())
        for p in profiles:
            ssid, psk = str(p.get("ssid", ""))[:64], str(p.get("psk", ""))[:128]
            if ssid and ssid not in known:
                sec = ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", psk] if psk else []
                netsetup.nmcli("connection", "add", "type", "wifi", "con-name", ssid, "ifname", "*", "ssid", ssid, *sec)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass


def reboot_soon():
    """Reboot a few seconds after the restore: the TV and the page have time to show the message"""
    threading.Timer(4, lambda: subprocess.run(["systemctl", "reboot"], capture_output=True, timeout=10)).start()


def restore_upload(data):
    """File uploaded from the companion app"""
    if len(data) > MAX_SIZE:
        raise ValueError(tr("File too large for a backup."))
    with lock:
        if state["busy"]:
            raise ValueError(tr("A backup or a restore is already in progress."))
        restore(data)
        state.update(busy="reboot", message=tr("Backup restored: the box is restarting…"))
    reboot_soon()


# USB drives

def flag(v):
    return v in (True, 1, "1")


def usb_partitions():
    """Readable partitions of USB drives and disks (not the box's own disk): [{path, uuid, name, mountpoint}]"""
    r = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,RM,HOTPLUG,TRAN,TYPE,FSTYPE,UUID,MOUNTPOINT,MOUNTPOINTS,LABEL,SIZE,MODEL"],
                       capture_output=True, text=True, timeout=10)
    try:
        disks = json.loads(r.stdout or "{}").get("blockdevices") or []
    except ValueError:
        return []

    def mounts(d):   # all mount points (a btrfs with subvolumes has several)
        return (d.get("mountpoints") or []) + [m for c in d.get("children") or [] for m in mounts(c)]
    out = []
    for d in disks:
        if d.get("type") != "disk" or not (d.get("tran") == "usb" or flag(d.get("rm")) or flag(d.get("hotplug"))):
            continue
        if any(m in ("/", "/boot", "/home", "/var/log") for m in mounts(d)):
            continue   # box booted from a USB drive: its own disk
        parts = d.get("children") or [d]   # drive formatted without a partition table
        for p in parts:
            if p.get("fstype") not in ("vfat", "exfat", "ntfs", "ntfs3", "ext4", "btrfs", "f2fs"):
                continue
            size = int(p.get("size") or 0)
            name = (p.get("label") or (d.get("model") or "").strip() or tr("USB drive")) + \
                   (" (" + tr("{size} GB", size=f"{size / 1e9:.0f}") + ")" if size >= 1e9 else
                    " (" + tr("{size} MB", size=f"{size / 1e6:.0f}") + ")" if size else "")
            out.append({"path": p["path"], "uuid": p.get("uuid") or "", "name": name, "mountpoint": p.get("mountpoint")})
    return out


def udisks(*args):
    r = subprocess.run(["udisksctl", *args, "--no-user-interaction"], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise OSError((r.stderr or r.stdout).strip() or f"udisksctl: code {r.returncode}")
    return r.stdout


class Mounted:
    """Drive mounted for the duration of a with block (if it wasn't already), then unmounted"""
    def __init__(self, part):
        self.part, self.ours = part, False

    def __enter__(self):
        if self.part.get("mountpoint"):
            return self.part["mountpoint"]
        m = re.search(r" at (.+?)\.?$", udisks("mount", "-b", self.part["path"]).strip())
        if not m:
            raise OSError(tr("USB drive not mounted"))
        self.ours = True
        return m.group(1)

    def __exit__(self, *exc):
        if self.ours:
            subprocess.run(["sync"], timeout=60)
            try:
                udisks("unmount", "-b", self.part["path"])
            except (OSError, subprocess.SubprocessError):
                time.sleep(2)
                udisks("unmount", "-b", self.part["path"])


def backups_on(part):
    """Backups at the root of the drive, most recent first: [{name, date, size}]"""
    found = []
    with Mounted(part) as root:
        for entry in os.scandir(root):
            if entry.is_file() and NAME.fullmatch(entry.name):
                m = re.search(r"(\d{4})-(\d\d)-(\d\d)-(\d\d)(\d\d)", entry.name)
                date = f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}" if m else \
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.stat().st_mtime))
                found.append({"name": entry.name, "date": date, "size": entry.stat().st_size})
    return sorted(found, key=lambda b: b["date"], reverse=True)[:SHOWN]


def status():
    """Plugged-in drives and their backups (read once per drive), job in progress, last message"""
    parts = usb_partitions()
    keys = {(p["path"], p["uuid"]) for p in parts}
    for k in list(listing):
        if k not in keys:
            listing.pop(k)
    usb = []
    for p in parts:
        k = (p["path"], p["uuid"])
        if k not in listing and not state["busy"] and lock.acquire(blocking=False):
            try:
                listing[k] = backups_on(p)
            except (OSError, subprocess.SubprocessError) as e:
                listing[k] = None
                print(f"backup.py: {p['path']} unreadable: {e}", flush=True)
            finally:
                lock.release()
        usb.append({"path": p["path"], "name": p["name"], "backups": listing.get(k) or [],
                    "readable": listing.get(k, []) is not None})
    if state["message"] != shown["text"]:
        shown.update(text=state["message"], at=time.time())
    message = state["message"] if state["busy"] or time.time() - shown["at"] < 60 else None
    return {"usb": usb, "busy": state["busy"], "message": message}


def find_part(path):
    part = next((p for p in usb_partitions() if p["path"] == path), None)
    if not part:
        raise ValueError(tr("USB drive not found: is it still plugged in?"))
    return part


def start(job, busy, message):
    with lock:
        if state["busy"]:
            raise ValueError(tr("A backup or a restore is already in progress."))
        state.update(busy=busy, message=message)
    threading.Thread(target=job, daemon=True).start()


def save_usb(path):
    part = find_part(path)

    def run():
        with lock:
            try:
                data, name = create(), file_name()
                with Mounted(part) as root:
                    tmp = os.path.join(root, name + ".part")
                    with open(tmp, "wb") as f:
                        f.write(data)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp, os.path.join(root, name))
                state["message"] = tr("Backup saved to {drive}: you can remove the drive.", drive=part["name"])
            except (OSError, subprocess.SubprocessError) as e:
                state["message"] = tr("Couldn't back up to {drive}: {error}", drive=part["name"], error=e)
            finally:
                listing.pop((part["path"], part["uuid"]), None)   # read again at the next status
                state["busy"] = None
    start(run, "save", tr("Backing up to {drive}…", drive=part["name"]))


def restore_usb(path, name):
    if not NAME.fullmatch(name or ""):
        raise ValueError(tr("unknown backup"))
    part = find_part(path)

    def run():
        with lock:
            try:
                with Mounted(part) as root:
                    with open(os.path.join(root, name), "rb") as f:
                        data = f.read(MAX_SIZE + 1)
                if len(data) > MAX_SIZE:
                    raise ValueError(tr("File too large for a backup."))
                restore(data)
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                state.update(busy=None, message=tr("Couldn't restore: {error}", error=e))
                return
            state.update(busy="reboot", message=tr("Backup restored: the box is restarting…"))
        reboot_soon()
    start(run, "restore", tr("Restoring…"))
