"""Stream Box: the box as a machine: sleep and shutdown, power key lock, wake-up, SSH access and developer mode,
status (temperatures, processor, memory, network, services) and system updates. Standard library only.
"""
import os, shutil, socket, subprocess, time

import settings  # settings.py: chosen player
from common import lan_ip, mpv
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


def resume_loop():
    """Wake-up after sleep: the connections (streamlink, video stream) are dead and the picture would stay
    frozen. logind signals PrepareForSleep(false) on wake-up (followed by gdbus); mpv then restarts playback."""
    while True:
        try:
            mon = subprocess.Popen(["gdbus", "monitor", "--system", "--dest", "org.freedesktop.login1",
                                    "--object-path", "/org/freedesktop/login1"], stdout=subprocess.PIPE, text=True)
            for line in mon.stdout:
                if "PrepareForSleep (false" in line:
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


# Box status (page, Settings → System): temperatures, processor, memory, disk, network, player, services,
# updates. Processor and network throughput are measured over an interval: polled every 5 s by a thread.

UPDATE_LOG = os.path.expanduser("~/.local/state/stream-box/update.log")
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


def health():
    with open("/proc/meminfo") as f:
        mem = {k: int(v.split()[0]) for k, v in (l.split(":", 1) for l in f)}
    disk = shutil.disk_usage(os.path.expanduser("~"))
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
    try:
        props = dict(l.split("=", 1) for l in user_systemctl(
            "show", "stream-box-update.service", "-p", "ActiveState").splitlines() if "=" in l)
        timer = user_systemctl("show", "stream-box-update.timer", "-p", "NextElapseUSecRealtime")
        next_run = timer.split("=", 1)[1] if "=" in timer else ""
    except (OSError, subprocess.SubprocessError):
        props, next_run = {}, ""
    return {
        "temps": temperatures(), "cpu": health_rates["cpu"], "load": os.getloadavg()[0], "cores": os.cpu_count(),
        "memory": {"total": mem.get("MemTotal", 0) * 1024, "available": mem.get("MemAvailable", 0) * 1024},
        "disk": {"total": disk.total, "free": disk.free}, "uptime": uptime,
        "network": {"iface": iface, "speed": read_int(f"/sys/class/net/{iface}/speed") if iface else None,
                    "rx": health_rates["rx"], "tx": health_rates["tx"]},
        "player": {"choice": settings.player_choice(), "running": "qt" if vo == "libmpv" else "mpv", "hwdec": hwdec,
                   "dropped": drops, "fps": fps, "size": f"{width}x{height}" if width else None},
        "services": services,
        "update": {"running": props.get("ActiveState") == "activating", "next": next_run, "last": last_update()},
    }


def start_update():
    user_systemctl("start", "--no-block", "stream-box-update.service")
