"""Stream Box: the box as a machine: sleep and shutdown, power key lock, wake-up, SSH access and developer mode,
status (temperatures, processor, memory, network, services) and system updates. Standard library only.
"""
import functools, json, os, re, shutil, socket, subprocess, time, urllib.request

import settings  # settings.py: chosen player
from common import battery, lan_ip, mpv
from i18n import tr


def power(mode):
    """"suspend" or "poweroff". Allowed without a password for media by
    /etc/polkit-1/rules.d/50-stream-box.rules (sleep is also allowed by default for an active local session)"""
    r = subprocess.run(["systemctl", "suspend" if mode == "suspend" else "poweroff"],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        error = r.stderr.strip() or r.returncode
        raise ValueError(tr("Sleep refused: {error}", error=error) if mode == "suspend"
                         else tr("Shutdown refused: {error}", error=error))


def hold_power_key():
    """Power button (Bluetooth remote, case): logind would turn the box off by itself; this lock prevents it,
    and stream-box.lua applies the "Power button" setting (sleep or full shutdown). Allowed by default in the TV's
    session (remote.py is started by start.sh); refused elsewhere, and logind then keeps its behavior. Without
    pkill or systemd (tests, container), nothing to hold."""
    try:
        subprocess.run(["pkill", "-u", str(os.getuid()), "-f", "who=Stream Box bouton power"], capture_output=True)
        subprocess.Popen(["systemd-inhibit", "--what=handle-power-key", "--mode=block", "--who=Stream Box bouton power",
                          "--why=Power button: sleep or shutdown depending on the setting", "sleep", "infinity"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        print(f"remote.py: power button not held ({e})", flush=True)


wakes = 0   # wake-ups since boot: the TV menu asks again about a waiting update after each (update_prompt)


def resume_loop():
    """Wake-up after sleep: the connections (streamlink, video stream) are dead and the picture would stay
    frozen. logind signals PrepareForSleep(false) on wake-up (followed by gdbus); mpv then restarts playback."""
    global wakes
    while True:
        try:
            mon = subprocess.Popen(["gdbus", "monitor", "--system", "--dest", "org.freedesktop.login1",
                                    "--object-path", "/org/freedesktop/login1"], stdout=subprocess.PIPE, text=True)
            for line in mon.stdout:
                if "PrepareForSleep (false" in line:
                    wakes += 1
                    # Bluetooth dongle (mostly CSR clones) stuck on wake-up: the remote stays "connected" without
                    # its keys arriving. Restart it; the remote reconnects on the first key press
                    for args in (["power", "off"], ["power", "on"]):
                        try:
                            subprocess.run(["bluetoothctl", *args], capture_output=True, timeout=10)
                        except (OSError, subprocess.SubprocessError):
                            pass
                        time.sleep(2)
                    # Network back (NetworkManager resumes the connection within seconds): otherwise streamlink
                    # fails and the box thinks the streamer is offline, then retries 15 s later
                    for _ in range(60):
                        try:
                            socket.create_connection(("www.twitch.tv", 443), timeout=2).close()
                            break
                        except OSError:
                            time.sleep(1)
                    try:
                        mpv(["script-message", "streambox-resume"])
                    except OSError:
                        pass
            mon.wait()
        except OSError:
            pass
        time.sleep(5)


# SSH access (maintenance), turned on or off from the System menu: stream-box-ssh@enable|disable.service (root, polkit
# rule 54-stream-box-ssh.rules, ssh-access script), installed by the image and install.sh. On: password drawn by
# ssh-access, shown on the TV only (not to other devices on the network)
SSH_PASS_FILE = "/var/lib/stream-box/ssh-password"
SSH_UNIT = ("/usr/lib/systemd/system/stream-box-ssh@.service", "/etc/systemd/system/stream-box-ssh@.service")


def ssh_status(local=False):
    def systemctl(*args):
        return subprocess.run(["systemctl", *args, "sshd.service"], capture_output=True, text=True, timeout=10).stdout.strip()
    s = {"available": any(os.path.exists(p) for p in SSH_UNIT),
         "enabled": systemctl("is-enabled") == "enabled", "active": systemctl("is-active") == "active",
         "address": "media@" + lan_ip()}
    if local:
        try:
            with open(SSH_PASS_FILE) as f:
                s["password"] = f.read().strip()
        except OSError:
            s["password"] = None
    return s


def set_ssh(on):
    if not ssh_status()["available"]:
        raise ValueError(tr("SSH setting missing from this installation (run install.sh again)."))
    r = subprocess.run(["systemctl", "start", f"stream-box-ssh@{'enable' if on else 'disable'}.service"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise ValueError(tr("SSH: {error}", error=(r.stderr or r.stdout).strip() or r.returncode))


# Developer mode: passwordless sudo for media, and SSH (stream-box-dev@enable|disable.service, dev-mode script,
# polkit rule 55-stream-box-dev.rules). Without it, the box installed from the image has no root access
DEV_UNIT = ("/usr/lib/systemd/system/stream-box-dev@.service", "/etc/systemd/system/stream-box-dev@.service")
DEV_MARK = "/var/lib/stream-box/dev-mode"
LOCAL_ONLY = ("ssh", "dev")   # access settings: from the TV only (the menu goes through 127.0.0.1)


def dev_status():
    return {"available": any(os.path.exists(p) for p in DEV_UNIT), "enabled": os.path.exists(DEV_MARK)}


def set_dev(on):
    if not dev_status()["available"]:
        raise ValueError(tr("Developer mode missing from this installation (run install.sh again)."))
    r = subprocess.run(["systemctl", "start", f"stream-box-dev@{'enable' if on else 'disable'}.service"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise ValueError(tr("Developer mode: {error}", error=(r.stderr or r.stdout).strip() or r.returncode))


# Box status (TV Settings tab, companion app Settings → Status and updates): temperatures, processor, memory, disk, network, player, services,
# updates. Processor and network throughput are measured over an interval: polled every 5 s by a thread.

UPDATE_LOG = os.path.expanduser("~/.local/state/stream-box/update.log")
# System update (root, /usr/local/lib/stream-box/system-update: daily check, install when accepted, direct update);
# result and check in this file (readable by media)
SYSTEM_UPDATE = "/var/lib/stream-box/system-update.json"
health_rates = {"cpu": None, "rx": None, "tx": None}


def default_iface():
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if parts[1] == "00000000":
                    return parts[0]
    except OSError:
        pass
    return None


def read_int(path, default=None):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return default


def health_loop():
    prev = None
    while True:
        try:
            with open("/proc/stat") as f:
                cpu = [int(v) for v in f.readline().split()[1:]]
            iface = default_iface()
            rx = read_int(f"/sys/class/net/{iface}/statistics/rx_bytes", 0) if iface else 0
            tx = read_int(f"/sys/class/net/{iface}/statistics/tx_bytes", 0) if iface else 0
            now = time.time()
            if prev:
                busy, total = sum(cpu) - cpu[3] - cpu[4], sum(cpu)
                pbusy, ptotal = sum(prev[0]) - prev[0][3] - prev[0][4], sum(prev[0])
                dt = now - prev[3]
                health_rates.update(cpu=100 * (busy - pbusy) / max(1, total - ptotal),
                                    rx=(rx - prev[1]) * 8 / dt, tx=(tx - prev[2]) * 8 / dt)   # bits/s
            prev = (cpu, rx, tx, now)
        except OSError:
            pass
        time.sleep(5)


def temperatures():
    out = {}
    for h in sorted(os.listdir("/sys/class/hwmon")) if os.path.isdir("/sys/class/hwmon") else []:
        base = f"/sys/class/hwmon/{h}"
        try:
            name = open(f"{base}/name").read().strip()
        except OSError:
            continue
        t = read_int(f"{base}/temp1_input")
        if t is not None and name in ("coretemp", "k10temp", "zenpower", "nvme"):
            out["cpu" if name != "nvme" else "disk"] = round(t / 1000)
    return out


def user_systemctl(*args):
    env = {**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")}
    r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=10, env=env)
    return r.stdout.strip()


def last_update():
    """Last update from update.log: date and lines of that run"""
    try:
        with open(UPDATE_LOG, encoding="utf-8", errors="replace") as f:
            text = f.read()[-20000:]
    except OSError:
        return None
    runs = text.split("=== ")
    if len(runs) < 2:
        return None
    date, _, body = runs[-1].partition("\n")
    lines = [l for l in body.splitlines() if l.strip()]
    failed = any("échec" in l.lower() or "ÉCHEC" in l or "failed" in l.lower() for l in lines)   # old French logs too
    return {"date": date.strip(), "lines": lines[-12:], "ok": not failed}


def unit_state(unit):
    r = subprocess.run(["systemctl", "show", unit, "-p", "LoadState", "-p", "ActiveState"],
                       capture_output=True, text=True, timeout=10)
    return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)


@functools.cache
def single_slot():
    """The box's disk has one system partition (GPT type root-x86-64): the image flashed on a USB drive, no room for
    the next version next to the running one (system-update does nothing there: install the box on the PC)"""
    try:
        root = subprocess.run(["findmnt", "-no", "SOURCE", "/"], capture_output=True, text=True, timeout=5).stdout
        r = subprocess.run(["lsblk", "-no", "PKNAME", root.split("[")[0].strip()], capture_output=True, text=True, timeout=5)
        disk = r.stdout.split()[0]
        types = subprocess.run(["lsblk", "-nlo", "PARTTYPE", f"/dev/{disk}"], capture_output=True, text=True,
                               timeout=5).stdout.split()
    except (OSError, subprocess.SubprocessError, IndexError):
        return False
    return [t.lower() for t in types].count("4f68bce3-e8cd-4db1-96e7-fbcaf984b709") == 1


def system_update():
    """System update (image only): None without it; otherwise running (installing), checking (daily check, "Check for
    updates"), the version of the running system (os-release IMAGE_VERSION: an A/B box restarted onto a new one since
    the last result), the last result (version, ok, message, code, restart: now | pending | no, kind: ab | files |
    direct, new; available and checked: the daily check), offered: the newer release to offer, "" when none, and usb:
    the image running from a USB drive, which gets no system update"""
    props = unit_state("stream-box-system-update.service")
    if props.get("LoadState") != "loaded":
        return None
    try:
        with open(SYSTEM_UPDATE, encoding="utf-8") as f:
            last = json.load(f)
    except (OSError, ValueError):
        last = None
    version = None
    try:
        with open("/usr/lib/os-release", encoding="utf-8") as f:
            version = next((l.split("=", 1)[1].strip().strip('"') for l in f if l.startswith("IMAGE_VERSION=")), None)
    except OSError:
        pass
    running = props.get("ActiveState") == "activating"
    last_ = last or {}
    have = version or (last_.get("version") or "").lstrip("v").split("+")[0]
    pending_new = last_.get("new") if last_.get("restart") == "pending" else ""
    available = last_.get("available") or ""
    offered = available if available and available not in (have, pending_new) and not running else ""
    return {"running": running, "direct": running and last_.get("run") == "direct",   # direct: "Direct update (source)"
            "checking": unit_state("stream-box-update-check.service").get("ActiveState") == "activating",
            "last": last, "version": version, "offered": offered, "usb": bool(version) and single_slot()}


def health():
    with open("/proc/meminfo") as f:
        mem = {k: int(v.split()[0]) for k, v in (l.split(":", 1) for l in f)}
    # Disk: the data partition (settings, history, local update images) on an A/B box; the system partition aside
    disk = shutil.disk_usage("/data" if os.path.ismount("/data") else os.path.expanduser("~"))
    root = shutil.disk_usage("/")
    with open("/proc/uptime") as f:
        uptime = float(f.read().split()[0])
    iface = default_iface()
    try:
        hwdec, drops, fps, width, height, vo = mpv(
            ["get_property", "hwdec-current"], ["get_property", "frame-drop-count"],
            ["get_property", "estimated-vf-fps"], ["get_property", "video-params/w"],
            ["get_property", "video-params/h"], ["get_property", "current-vo"])
    except OSError:
        hwdec = drops = fps = width = height = vo = None
    services = {}
    for unit, label in (("stream-box-mqtt.service", "mqtt"), ("stream-box-pot.service", "youtube_tokens")):
        try:
            services[label] = user_systemctl("is-active", unit) or tr("unknown")
        except (OSError, subprocess.SubprocessError):
            services[label] = tr("unknown")
    try:   # dependencies (update.sh, every day without a word)
        props = dict(l.split("=", 1) for l in user_systemctl(
            "show", "stream-box-update.service", "-p", "ActiveState").splitlines() if "=" in l)
    except (OSError, subprocess.SubprocessError):
        props = {}
    return {
        "battery": battery(),   # None without one (a mini PC)
        "temps": temperatures(), "cpu": health_rates["cpu"], "load": os.getloadavg()[0], "cores": os.cpu_count(),
        "memory": {"total": mem.get("MemTotal", 0) * 1024, "available": mem.get("MemAvailable", 0) * 1024},
        "disk": {"total": disk.total, "free": disk.free,
                 "system": {"total": root.total, "free": root.free} if os.path.ismount("/data") else None},
        "uptime": uptime,
        "network": {"iface": iface, "speed": read_int(f"/sys/class/net/{iface}/speed") if iface else None,
                    "rx": health_rates["rx"], "tx": health_rates["tx"]},
        "player": {"choice": settings.player_choice(), "running": "qt" if vo == "libmpv" else "mpv", "hwdec": hwdec,
                   "dropped": drops, "fps": fps, "size": f"{width}x{height}" if width else None},
        "services": services,
        # running, last: the dependencies (update.sh); system: the box's system (releases)
        "update": {"running": props.get("ActiveState") == "activating", "last": last_update(),
                   "system": system_update(), "dev": dev_status()["enabled"]},
    }


UPDATE_MANUAL = os.path.expanduser("~/.local/state/stream-box/update-manual")
UPDATE_DIRECT = os.path.expanduser("~/.local/state/stream-box/update-direct")
UPDATE_DISMISSED = os.path.expanduser("~/.local/state/stream-box/update-dismissed")   # "Don't ask again": that update


def start_root(unit):
    r = subprocess.run(["systemctl", "start", "--no-block", unit], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise ValueError((r.stderr or r.stdout).strip() or tr("Couldn't start the update."))


BRANCHES_URL = "https://api.github.com/repos/Tunederuz/stream-box/branches?per_page=100"
branches_cache = {"at": 0.0, "list": None}


def branches():
    """Branches of the repository for the direct update (GitHub API, no account: kept 10 min), main first; ["main"]
    when GitHub is unreachable"""
    if branches_cache["list"] is None or time.time() - branches_cache["at"] > 600:
        try:
            req = urllib.request.Request(BRANCHES_URL, headers={"Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                names = [b["name"] for b in json.load(r) if isinstance(b, dict) and b.get("name")]
            branches_cache.update(at=time.time(), list=sorted(names, key=lambda n: (n != "main", n != "dev", n)))
        except (OSError, ValueError, KeyError):
            return branches_cache["list"] or ["main"]
    return branches_cache["list"]


def start_update(direct=False, branch="main"):
    """Install the newer release (the user accepted: TV menu question, Settings → Updates, companion app): marked as
    started by hand, so that system-update applies it at once when nothing plays. direct ("Direct update (source)",
    developer mode only): the code and system files of a branch (main by default), not the system"""
    if direct and not dev_status()["enabled"]:
        raise ValueError(tr("Direct update: developer mode only."))
    branch = (branch or "main").strip()
    if direct and not (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}", branch) and ".." not in branch):
        raise ValueError(tr("unknown branch"))
    if unit_state("stream-box-local-update.service").get("ActiveState") == "activating":   # (same slot; also locked)
        raise ValueError(tr("An update from a local image is running: try again once it is done."))
    os.makedirs(os.path.dirname(UPDATE_MANUAL), exist_ok=True)
    with open(UPDATE_DIRECT if direct else UPDATE_MANUAL, "w") as f:
        f.write(branch + "\n" if direct else str(time.time()))   # (direct: the branch, read by system-update)
    start_root("stream-box-system-update.service")


def check_update():
    """"Check for updates": the daily check, now (root, polkit rule 56)"""
    start_root("stream-box-update-check.service")


def update_deps():
    """"Update dependencies" (Settings → Advanced): update.sh now, as every day"""
    env = {**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")}
    r = subprocess.run(["systemctl", "--user", "start", "--no-block", "stream-box-update.service"],
                       capture_output=True, text=True, timeout=10, env=env)
    if r.returncode != 0:
        raise ValueError((r.stderr or r.stdout).strip() or tr("Couldn't start the update."))


def waiting_update():
    """(pending, last system-update.json, key): key names that update (A/B: its version; files: its date)"""
    s = system_update() or {}
    last = s.get("last") or {}
    pending = bool(last.get("ok") and last.get("restart") == "pending"
                   and not (last.get("kind") == "ab" and last.get("new") == s.get("version")))
    return pending, last, (last.get("new") if last.get("kind") == "ab" else last.get("date")) or ""


def update_prompt():
    """What the TV menu asks about at each start and wake-up: an update installed, waiting for a restart (pending: "restart
    to apply?"), or else a newer release found by the daily check (available: "update now?"). {pending, available,
    dismissed, id, new, kind}; id changes at each boot and wake-up (and with the release offered), the menu asks once
    per id, unless "Don't ask again" was chosen for that version (dismissed: a newer one asks again)"""
    pending, last, key = waiting_update()
    available = "" if pending else (system_update() or {}).get("offered") or ""
    key = key if pending else available
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            boot = f.read().strip()
    except OSError:
        boot = ""
    try:
        with open(UPDATE_DISMISSED) as f:
            dismissed = bool(key) and f.read().strip() == key
    except OSError:
        dismissed = False
    return {"pending": pending, "available": available, "dismissed": dismissed, "id": f"{boot}:{wakes}:{key}",
            "new": last.get("new") or "", "kind": last.get("kind") or ""}


def dismiss_update():
    """"Don't ask again" of that question: not asked again for this version (Settings → Updates still offers it)"""
    pending, _, key = waiting_update()
    key = key if pending else (system_update() or {}).get("offered") or ""
    if key:
        os.makedirs(os.path.dirname(UPDATE_DISMISSED), exist_ok=True)
        with open(UPDATE_DISMISSED, "w") as f:
            f.write(key)


def apply_update():
    """"Restart now" of that question: restart onto the new system (A/B) or the session (files), as root"""
    r = subprocess.run(["systemctl", "start", "--no-block", "stream-box-apply-update.service"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise ValueError((r.stderr or r.stdout).strip() or tr("Couldn't start the update."))
