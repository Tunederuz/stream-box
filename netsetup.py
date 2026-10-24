"""Stream Box : mode configuration réseau (Wi-Fi), par NetworkManager (nmcli).

Sans réseau au démarrage et avec une carte Wi-Fi, la box crée son propre point d'accès (« Stream Box XXXX », mot de
passe affiché sur la TV avec un QR code) : le téléphone s'y connecte, ouvre la télécommande web (http://10.42.0.1:8080)
et choisit le Wi-Fi de la maison. En Ethernet, rien à faire. Utilisé par remote.py (boucle setup_loop, API /api/wifi).
Droits : NetworkManager autorise la session locale active (remote.py est lancé dans la session de la TV) ; l'image
ajoute une règle polkit pour media.
"""
import json, os, random, string, subprocess, threading, time

HOTSPOT_CON = "stream-box-setup"            # connexion NetworkManager du point d'accès
HOTSPOT_URL = "http://10.42.0.1:8080/"       # adresse de la box sur son point d'accès (réseau partagé de NetworkManager)
CONF = os.path.expanduser("~/.config/stream-box/hotspot.json")
START_AFTER = 25                              # secondes après le démarrage avant de se décider (DHCP, Wi-Fi connu…)
OFFLINE_GRACE = 60                            # Wi-Fi enregistré perdu : NetworkManager réessaie seul pendant ce temps
RETRY_EVERY = 180                             # point d'accès sans téléphone connecté : on réessaie le Wi-Fi enregistré

lock = threading.Lock()
state = {"connecting": None, "error": None, "networks": [], "scanned": 0, "manual_until": 0}


def nmcli(*args, timeout=20):
    r = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"nmcli {args[0]} : code {r.returncode}")
    return r.stdout


def split(line):
    """Ligne de nmcli -t : champs séparés par « : », « \\: » pour un deux-points dans une valeur"""
    out, cur, i = [], "", 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            cur += line[i + 1]
            i += 2
            continue
        if line[i] == ":":
            out.append(cur)
            cur = ""
        else:
            cur += line[i]
        i += 1
    return out + [cur]


def wifi_device():
    """Carte Wi-Fi de la box, toujours la même : celle du point d'accès s'il tourne, sinon la première par nom, en
    écartant une carte qui sert déjà de point d'accès à autre chose (deux cartes : tests, partage de connexion)"""
    try:
        devs = sorted(split(l)[0] for l in nmcli("-t", "-f", "DEVICE,TYPE", "device").splitlines() if split(l)[1] == "wifi")
        acts = active()
        for name, _, dev in acts:
            if name == HOTSPOT_CON and dev in devs:
                return dev
        for dev in devs:
            other = next((name for name, kind, d in acts if d == dev and kind.endswith("wireless")), None)
            if other and nmcli("-g", "802-11-wireless.mode", "connection", "show", other).strip() == "ap":
                continue
            return dev
    except (OSError, RuntimeError, subprocess.SubprocessError, IndexError):
        pass
    return None


def active():
    """Connexions actives : [(nom, type, appareil)]"""
    try:
        return [tuple(split(l)[:3]) for l in nmcli("-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active").splitlines()]
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return []


def online():
    """Réseau de la maison : une connexion Ethernet ou Wi-Fi active, autre que le point d'accès"""
    return any(name != HOTSPOT_CON and (kind.endswith("ethernet") or kind.endswith("wireless")) for name, kind, _ in active())


def saved_wifi():
    """Wi-Fi de la maison enregistré (profil NetworkManager), autre que le point d'accès"""
    try:
        return any(split(l)[1].endswith("wireless") and split(l)[0] != HOTSPOT_CON
                   for l in nmcli("-t", "-f", "NAME,TYPE", "connection", "show").splitlines())
    except (OSError, RuntimeError, subprocess.SubprocessError, IndexError):
        return False


def clients(dev):
    """Appareils connectés au point d'accès"""
    try:
        r = subprocess.run(["iw", "dev", dev, "station", "dump"], capture_output=True, text=True, timeout=5)
        return r.stdout.count("Station ")
    except (OSError, subprocess.SubprocessError):
        return 0


def hotspot_on():
    return any(name == HOTSPOT_CON for name, _, _ in active())


def hotspot_conf():
    """Nom et mot de passe du point d'accès : tirés une fois, gardés (le QR code de la TV ne change pas)"""
    try:
        with open(CONF, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("ssid") and len(c.get("password", "")) >= 8:
            return c
    except (OSError, ValueError):
        pass
    c = {"ssid": "Stream Box " + "".join(random.choices(string.ascii_uppercase + string.digits, k=4)),
         "password": "".join(random.choices("abcdefghjkmnpqrstuvwxyz23456789", k=10))}
    os.makedirs(os.path.dirname(CONF), mode=0o700, exist_ok=True)
    with open(CONF, "w", encoding="utf-8") as f:
        json.dump(c, f)
    os.chmod(CONF, 0o600)
    return c


def scan(dev):
    """Réseaux visibles, du plus fort au plus faible (un seul par nom). Impossible pendant le point d'accès sur
    beaucoup de cartes : la liste est relevée juste avant de le créer, et gardée."""
    try:
        seen = {}
        for line in nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", dev, "--rescan", "yes",
                          timeout=30).splitlines():
            ssid, signal, security = (split(line) + ["", "", ""])[:3]
            if ssid and ssid != hotspot_conf()["ssid"] and int(signal or 0) > seen.get(ssid, {}).get("signal", -1):
                seen[ssid] = {"ssid": ssid, "signal": int(signal or 0), "secure": bool(security and security != "--")}
        if seen:
            state["networks"] = sorted(seen.values(), key=lambda n: -n["signal"])
            state["scanned"] = time.time()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        pass


def start_hotspot(dev):
    c = hotspot_conf()
    scan(dev)
    try:   # un seul profil (nmcli en recrée un à chaque fois)
        while True:
            nmcli("connection", "delete", HOTSPOT_CON)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass
    nmcli("device", "wifi", "hotspot", "ifname", dev, "con-name", HOTSPOT_CON, "ssid", c["ssid"],
          "band", "bg", "password", c["password"], timeout=40)


def stop_hotspot():
    try:
        nmcli("connection", "down", HOTSPOT_CON)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass


def connect(ssid, password):
    """En arrière-plan : le point d'accès s'arrête (une seule radio), la box rejoint ssid ; en cas d'échec, le point
    d'accès revient et l'erreur est gardée pour la page."""
    dev = wifi_device()
    if not dev:
        raise ValueError("Pas de carte Wi-Fi sur cette box.")
    if not ssid:
        raise ValueError("Choisis un réseau.")

    def run():
        with lock:
            state.update(connecting=ssid, error=None)
            stop_hotspot()
            time.sleep(2)
            try:
                # La carte sort du mode point d'accès sans liste de réseaux : nouvelle recherche, jusqu'à voir ssid
                for _ in range(6):
                    scan(dev)
                    if any(n["ssid"] == ssid for n in state["networks"]):
                        break
                    time.sleep(3)
                args = ["device", "wifi", "connect", ssid, "ifname", dev] + (["password", password] if password else [])
                nmcli(*args, timeout=60)
            except (OSError, RuntimeError, subprocess.SubprocessError) as e:
                msg = str(e)
                why = ("mot de passe incorrect ?" if "psk" in msg or "ecret" in msg or "activation failed" in msg
                       else "réseau introuvable (trop loin ?)" if "found" in msg else msg[:160])
                state["error"] = f"Connexion à « {ssid} » impossible : {why}"
                try:
                    nmcli("connection", "delete", ssid)   # profil créé mais inutilisable (mauvais mot de passe…)
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    pass
                try:
                    start_hotspot(dev)
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    pass
            finally:
                state["connecting"] = None
    threading.Thread(target=run, daemon=True).start()


def status():
    dev = wifi_device()
    acts = active()
    # Réseau de la maison : Ethernet, ou Wi-Fi sur la carte de la box
    home = next(((n, k) for n, k, d in acts if n != HOTSPOT_CON and (k.endswith("ethernet") or (k.endswith("wireless") and d == dev))), None)
    hot = any(n == HOTSPOT_CON for n, _, _ in acts)
    return {"device": dev, "mode": "hotspot" if hot else "connected" if home else "none",
            "network": home[0] if home else None, "wired": bool(home and home[1].endswith("ethernet")),
            "hotspot": dict(hotspot_conf(), url=HOTSPOT_URL) if hot else None,
            "networks": state["networks"], "connecting": state["connecting"], "error": state["error"]}


def setup_loop():
    """Au démarrage, puis toutes les 10 s : sans réseau et avec une carte Wi-Fi, point d'accès de configuration ; s'il y
    a de nouveau un réseau (câble branché…), il s'arrête. Récupération à tout moment : un Wi-Fi enregistré qui se perd
    (box internet redémarrée, mot de passe changé…) laisse OFFLINE_GRACE secondes à NetworkManager pour le retrouver,
    puis le point d'accès revient ; sans téléphone dessus, il s'efface toutes les RETRY_EVERY secondes le temps de
    réessayer le Wi-Fi enregistré (une seule radio : pas de recherche de réseau pendant le point d'accès)."""
    time.sleep(START_AFTER)
    offline_since, hotspot_since = None, None
    while True:
        try:
            if not state["connecting"] and not lock.locked():
                dev = wifi_device()
                up, hot = online(), hotspot_on()
                offline_since = None if up or hot else (offline_since or time.time())
                hotspot_since = (hotspot_since or time.time()) if hot else None
                if dev and not up and not hot:
                    if not saved_wifi() or time.time() - offline_since >= OFFLINE_GRACE:
                        start_hotspot(dev)
                        state["started"] = hotspot_since = time.time()
                elif hot and up and time.time() > state["manual_until"]:
                    stop_hotspot()
                elif (hot and time.time() > state["manual_until"] and saved_wifi() and not clients(dev)
                      and time.time() - hotspot_since >= RETRY_EVERY):
                    stop_hotspot()   # NetworkManager réessaie le Wi-Fi enregistré ; sinon retour au point d'accès
                    offline_since = time.time() - OFFLINE_GRACE + 45
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            state["error"] = f"Point d'accès impossible : {str(e)[:160]}"
        time.sleep(10)


def manual_hotspot():
    """Menu de la TV « Changer de réseau Wi-Fi » : point d'accès tout de suite, même avec un réseau"""
    dev = wifi_device()
    if not dev:
        raise ValueError("Pas de carte Wi-Fi sur cette box.")
    state["manual_until"] = time.time() + 900   # gardé 15 min même si l'Ethernet est branché
    def run():
        with lock:
            for name, kind, d in active():
                if d == dev and name != HOTSPOT_CON:
                    try:
                        nmcli("connection", "down", name)
                    except (OSError, RuntimeError, subprocess.SubprocessError):
                        pass
            try:
                start_hotspot(dev)
            except (OSError, RuntimeError, subprocess.SubprocessError) as e:
                state["error"] = f"Point d'accès impossible : {str(e)[:160]}"
    threading.Thread(target=run, daemon=True).start()
