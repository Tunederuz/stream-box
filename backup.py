"""Stream Box : sauvegarde et restauration des réglages et connexions, sans ligne de commande.

Menu Système de la TV → « Sauvegarde et restauration » : sauvegarde sur une clé USB, ou restauration d'une sauvegarde
trouvée dessus. Page web (Réglages → Système) : téléchargement du fichier sur le téléphone, et restauration d'un
fichier envoyé. Utilisé par remote.py (GET /api/backup, /api/backup/download ; POST /api/backup, /api/backup_restore).

Contenu, le même que backup.sh (archive au même format : install.sh --restore la reprend, et inversement) : liste des
streamers, réglages et historique de la box, comptes Twitch / YouTube, connexion Jellyfin, MQTT, réglages du son, plus
les Wi-Fi enregistrés (nom et mot de passe, recréés par NetworkManager). Pas les appairages Bluetooth (réservés à
root : backup.sh les garde). Ce sont des secrets : le fichier est à garder pour soi.

Clé USB : montée par udisks le temps de lire ou d'écrire (règle polkit pour media), démontée aussitôt : elle peut être
retirée dès la fin. Après une restauration, la box redémarre pour que tout reparte des fichiers remis.
"""
import io, json, os, re, socket, subprocess, tarfile, threading, time

import netsetup   # netsetup.py : nmcli (Wi-Fi enregistrés)

HOME = os.path.expanduser("~")
# Relatifs au dossier personnel ; dans l'archive : home/<utilisateur>/… comme backup.sh
PATHS = ("stream-box/streamers.txt", ".local/state/stream-box", ".config/stream-box", ".config/streamlink/config.twitch",
         ".config/jellyfin-mpv-shim", ".local/state/wireplumber")
SKIP = re.compile(r"(^|/)(fonts|scripts|offline)(/|$)|\.lock|\.bak$|(^|/)update\.log$|(^|/)before-restore\.tar\.gz$")
MANIFEST = "stream-box-backup.json"
WIFI = "stream-box-wifi.json"
NAME = re.compile(r"stream-box-backup-[\w.-]{1,60}\.tar\.gz")
SAFETY = os.path.join(HOME, ".local/state/stream-box/before-restore.tar.gz")   # réglages d'avant la dernière restauration
MAX_SIZE = 64 << 20
SHOWN = 4   # sauvegardes proposées par clé, les plus récentes

state = {"busy": None, "message": None}
lock = threading.Lock()
listing = {}   # (périphérique, uuid) → sauvegardes trouvées sur la clé
shown = {"text": None, "at": 0}   # dernier message : affiché une minute, puis la fenêtre revient à son titre


# Archive

def wifi_profiles():
    """Wi-Fi enregistrés dans NetworkManager (pas le point d'accès de configuration) : [{ssid, psk}]"""
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
            # Réseau protégé dont le mot de passe n'est pas lisible ici : pas recréé comme un réseau ouvert
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
    """Archive .tar.gz des réglages, en mémoire (moins d'un Mo)"""
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
    """Remet les fichiers d'une archive (de ce module ou de backup.sh) et ses Wi-Fi ; les réglages d'avant sont gardés
    dans SAFETY. Renvoie le nombre d'éléments remis ; ValueError si ce n'est pas une sauvegarde."""
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except (tarfile.TarError, EOFError, OSError):
        raise ValueError("Ce fichier n'est pas une sauvegarde de Stream Box.")
    with tar:
        members, wifi = [], []
        for m in tar.getmembers():
            if m.name == WIFI and m.isfile():
                try:
                    wifi = json.loads(tar.extractfile(m).read())
                except ValueError:
                    pass
                continue
            # home/<utilisateur de la box sauvegardée>/… → dossier personnel d'ici
            rel = re.match(r"home/[^/]+/(.+)$", m.name)
            rel = rel and rel.group(1)
            if not rel or SKIP.search(rel) or not (m.isfile() or m.isdir()) \
                    or not any(rel == p or rel.startswith(p + "/") for p in PATHS):
                continue
            m.name = f"{HOME.lstrip('/')}/{rel}"
            members.append(m)
        if not members:
            raise ValueError("Ce fichier n'est pas une sauvegarde de Stream Box.")
        os.makedirs(os.path.dirname(SAFETY), exist_ok=True)
        with open(os.open(SAFETY, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
            f.write(create())
        tar.extractall("/", members=members, filter="data")
        for m in members:   # dossiers : le filtre « data » ne garde pas leurs droits (700 pour ceux des secrets)
            if m.isdir():
                os.chmod("/" + m.name, m.mode & 0o755)
    restore_wifi(wifi)
    return len(members)


def restore_wifi(profiles):
    """Wi-Fi sauvegardés absents d'ici : profils NetworkManager recréés (connexion automatique à portée)"""
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
    """Redémarrage quelques secondes après la restauration : la TV et la page ont le temps d'afficher le message"""
    threading.Timer(4, lambda: subprocess.run(["systemctl", "reboot"], capture_output=True, timeout=10)).start()


def restore_upload(data):
    """Fichier envoyé par la page web"""
    if len(data) > MAX_SIZE:
        raise ValueError("Fichier trop gros pour une sauvegarde.")
    with lock:
        if state["busy"]:
            raise ValueError("Une sauvegarde ou une restauration est déjà en cours.")
        restore(data)
        state.update(busy="reboot", message="Sauvegarde restaurée : la box redémarre…")
    reboot_soon()


# Clés USB

def flag(v):
    return v in (True, 1, "1")


def usb_partitions():
    """Partitions lisibles des clés et disques USB (pas le disque de la box) : [{path, uuid, name, mountpoint}]"""
    r = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,RM,HOTPLUG,TRAN,TYPE,FSTYPE,UUID,MOUNTPOINT,MOUNTPOINTS,LABEL,SIZE,MODEL"],
                       capture_output=True, text=True, timeout=10)
    try:
        disks = json.loads(r.stdout or "{}").get("blockdevices") or []
    except ValueError:
        return []

    def mounts(d):   # tous les points de montage (un btrfs en sous-volumes en a plusieurs)
        return (d.get("mountpoints") or []) + [m for c in d.get("children") or [] for m in mounts(c)]
    out = []
    for d in disks:
        if d.get("type") != "disk" or not (d.get("tran") == "usb" or flag(d.get("rm")) or flag(d.get("hotplug"))):
            continue
        if any(m in ("/", "/boot", "/home", "/var/log") for m in mounts(d)):
            continue   # box démarrée sur une clé : son propre disque
        parts = d.get("children") or [d]   # clé formatée sans table de partitions
        for p in parts:
            if p.get("fstype") not in ("vfat", "exfat", "ntfs", "ntfs3", "ext4", "btrfs", "f2fs"):
                continue
            size = int(p.get("size") or 0)
            name = (p.get("label") or (d.get("model") or "").strip() or "Clé USB") + \
                   (f" ({size / 1e9:.0f} Go)" if size >= 1e9 else f" ({size / 1e6:.0f} Mo)" if size else "")
            out.append({"path": p["path"], "uuid": p.get("uuid") or "", "name": name, "mountpoint": p.get("mountpoint")})
    return out


def udisks(*args):
    r = subprocess.run(["udisksctl", *args, "--no-user-interaction"], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise OSError((r.stderr or r.stdout).strip() or f"udisksctl : code {r.returncode}")
    return r.stdout


class Mounted:
    """Clé montée le temps d'un bloc with (si elle ne l'était pas déjà), puis démontée"""
    def __init__(self, part):
        self.part, self.ours = part, False

    def __enter__(self):
        if self.part.get("mountpoint"):
            return self.part["mountpoint"]
        m = re.search(r" at (.+?)\.?$", udisks("mount", "-b", self.part["path"]).strip())
        if not m:
            raise OSError("clé USB non montée")
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
    """Sauvegardes à la racine de la clé, les plus récentes d'abord : [{name, date, size}]"""
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
    """Clés branchées et leurs sauvegardes (lues une fois par clé), travail en cours, dernier message"""
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
                print(f"backup.py : {p['path']} illisible : {e}", flush=True)
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
        raise ValueError("Clé USB introuvable : est-elle toujours branchée ?")
    return part


def start(job, busy, message):
    with lock:
        if state["busy"]:
            raise ValueError("Une sauvegarde ou une restauration est déjà en cours.")
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
                state["message"] = f"Sauvegarde enregistrée sur {part['name']} : tu peux retirer la clé."
            except (OSError, subprocess.SubprocessError) as e:
                state["message"] = f"Sauvegarde impossible sur {part['name']} : {e}"
            finally:
                listing.pop((part["path"], part["uuid"]), None)   # relue au prochain état
                state["busy"] = None
    start(run, "save", f"Sauvegarde sur {part['name']}…")


def restore_usb(path, name):
    if not NAME.fullmatch(name or ""):
        raise ValueError("sauvegarde inconnue")
    part = find_part(path)

    def run():
        with lock:
            try:
                with Mounted(part) as root:
                    with open(os.path.join(root, name), "rb") as f:
                        data = f.read(MAX_SIZE + 1)
                if len(data) > MAX_SIZE:
                    raise ValueError("Fichier trop gros pour une sauvegarde.")
                restore(data)
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                state.update(busy=None, message=f"Restauration impossible : {e}")
                return
            state.update(busy="reboot", message="Sauvegarde restaurée : la box redémarre…")
        reboot_soon()
    start(run, "restore", "Restauration…")
