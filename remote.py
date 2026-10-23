#!/usr/bin/env python3
"""Stream Box : télécommande web pour téléphone (http://<box>:8080), qui pilote mpv via son socket IPC.

Les changements de streamer et de chat passent par les script-messages de stream-box.lua, pour que le menu
à l'écran, le chat et la page restent d'accord. Bibliothèque standard uniquement.

Compte Twitch : le jeton du site (cookie auth-token) est rangé dans la config Twitch de streamlink, que
streamlink lit tout seul. Twitch ne retire les pubs des abonnements qu'avec ce jeton-là.
"""
import datetime, json, os, re, socket, subprocess, threading, time, urllib.error, urllib.parse, urllib.request, zoneinfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import display   # display.py, même dossier

PORT = 8080
MPV_SOCKET = "/tmp/stream-box-mpv.sock"
DIR = os.path.dirname(os.path.abspath(__file__))
STREAMERS_FILE = os.path.join(DIR, "streamers.txt")
TWITCH_CONFIG = os.path.expanduser("~/.config/streamlink/config.twitch")
TOKEN_PREFIX = "twitch-api-header=Authorization=OAuth "
# Le même jeton en cookie pour yt-dlp (VOD réservées aux abonnés). yt-dlp réécrit ce fichier en 644 à chaque
# lecture : c'est le dossier, en 700, qui le protège.
COOKIES_DIR = os.path.expanduser("~/.config/stream-box")
COOKIES_FILE = os.path.join(COOKIES_DIR, "twitch-cookies.txt")
CHECK_EVERY = 1800   # secondes entre deux vérifications du jeton auprès de Twitch
LIVE_EVERY = 60      # secondes entre deux relevés « qui est en live »
TWITCH_WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"   # celui du site twitch.tv, public (streamlink l'utilise aussi)
# Fichiers servis tels quels : la page et ce qu'il faut pour l'installer comme une appli (PWA)
STATIC = {
    "/": ("remote.html", "text/html; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/sw.js": ("sw.js", "text/javascript"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/apple-touch-icon.png": ("icon-180.png", "image/png"),
}


def read_streamers():
    # Mêmes règles que read_streamers() dans stream-box.lua
    names = []
    try:
        with open(STREAMERS_FILE, encoding="utf-8") as f:
            for line in f:
                name = line.split("#", 1)[0].strip().lower()
                for prefix in ("https://", "http://", "www.", "twitch.tv/"):
                    name = name.removeprefix(prefix)
                if name:
                    names.append(name)
    except OSError:
        pass
    return names


def mpv(*commands):
    """Envoie des commandes à mpv ; renvoie le champ data de chaque réponse, dans l'ordre."""
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(2)
        s.connect(MPV_SOCKET)
        for i, cmd in enumerate(commands):
            s.sendall((json.dumps({"command": list(cmd), "request_id": i}) + "\n").encode())
        results, buf = {}, b""
        while len(results) < len(commands):
            data = s.recv(65536)
            if not data:
                raise OSError("mpv fermé")
            *lines, buf = (buf + data).split(b"\n")
            for line in lines:
                msg = json.loads(line)
                if "event" not in msg and "request_id" in msg:
                    results[msg["request_id"]] = msg.get("data")
        return [results[i] for i in range(len(commands))]


# Qui est en live : relevé chaque minute pour toute la liste, publié dans user-data/streambox/live pour stream-box.lua
# (menu de la TV, bascule automatique) et renvoyé par /api/state

live_now = {}   # pseudo -> {"title", "viewers", "game"}, streamers en live seulement


def fetch_live(logins):
    query = "query($l:[String!]){users(logins:$l){login stream{title viewersCount game{displayName}}}}"
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps({"query": query, "variables": {"l": logins}}).encode(),
        headers={"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        users = json.load(r)["data"]["users"]
    return {u["login"]: {"title": u["stream"]["title"], "viewers": u["stream"]["viewersCount"],
                         "game": (u["stream"].get("game") or {}).get("displayName")}
            for u in users if u and u.get("stream")}


def live_loop():
    global live_now
    first = True
    while True:
        try:
            previous, live_now = live_now, fetch_live(read_streamers())
            mpv(["set_property", "user-data/streambox/live", live_now])
            # Streamers qui viennent de lancer leur live (pas au premier relevé : ils étaient déjà en live)
            for login in ([] if first else [l for l in live_now if l not in previous]):
                mpv(["script-message", "streambox-went-live", login])
            first = False
        except (OSError, ValueError, KeyError, TypeError):
            pass   # Twitch ou mpv injoignable : on garde le dernier relevé
        time.sleep(LIVE_EVERY)


# Rediffusions et clips de la semaine d'un streamer, pour la page (cache de 5 min par streamer)

replays_cache = {}   # pseudo -> (heure, résultat)


def fetch_replays(login):
    query = ("query($l:String!){user(login:$l){"
             "videos(first:8,type:ARCHIVE,sort:TIME){edges{node{id title lengthSeconds createdAt "
             "previewThumbnailURL(width:320,height:180)}}} "
             "clips(first:6,criteria:{period:LAST_WEEK}){edges{node{slug title durationSeconds viewCount "
             "thumbnailURL}}}}}")
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps({"query": query, "variables": {"l": login}}).encode(),
        headers={"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        user = json.load(r)["data"]["user"] or {}
    vods = [{"title": n["title"], "date": n["createdAt"][:10], "seconds": n["lengthSeconds"],
             "thumb": n["previewThumbnailURL"], "url": f"https://www.twitch.tv/videos/{n['id']}"}
            for n in (e["node"] for e in (user.get("videos") or {}).get("edges", []))]
    clips = [{"title": n["title"], "seconds": n["durationSeconds"], "views": n["viewCount"],
              "thumb": n["thumbnailURL"], "url": f"https://clips.twitch.tv/{n['slug']}"}
             for n in (e["node"] for e in (user.get("clips") or {}).get("edges", []))]
    return {"login": login, "vods": vods, "clips": clips}


def replays(login):
    if login not in read_streamers():
        raise ValueError("streamer inconnu")
    cached = replays_cache.get(login)
    if not cached or time.time() - cached[0] > 300:
        cached = (time.time(), fetch_replays(login))
        replays_cache[login] = cached
    return cached[1]


# Écran d'ambiance (dessiné par stream-box.lua quand rien ne joue) : météo et prochains lives prévus, publiés dans
# user-data/streambox/ambient. La météo vient d'Open-Meteo (sans compte) ; lieu dans ~/.config/stream-box/ambient.json :
# {"city": "...", "latitude": ..., "longitude": ..., "timezone": "Europe/..."} (sans ce fichier : pas de météo).

AMBIENT_FILE = os.path.join(COOKIES_DIR, "ambient.json")
AMBIENT_FETCH = 600   # secondes entre deux récupérations (météo, plannings)
WEATHER = [((0,), "Ciel dégagé"), ((1,), "Plutôt dégagé"), ((2,), "Partiellement nuageux"), ((3,), "Couvert"),
           ((45, 48), "Brouillard"), ((51, 53, 55), "Bruine"), ((56, 57), "Bruine verglaçante"), ((61,), "Pluie faible"),
           ((63,), "Pluie"), ((65,), "Forte pluie"), ((66, 67), "Pluie verglaçante"), ((71,), "Neige faible"),
           ((73,), "Neige"), ((75,), "Forte neige"), ((77,), "Grésil"), ((80, 81, 82), "Averses"),
           ((85, 86), "Averses de neige"), ((95,), "Orage"), ((96, 99), "Orage et grêle")]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def ambient_conf():
    try:
        with open(AMBIENT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def fetch_weather(conf):
    if "latitude" not in conf:
        return None
    query = urllib.parse.urlencode({
        "latitude": conf["latitude"], "longitude": conf["longitude"], "timezone": conf.get("timezone", "auto"),
        "current": "temperature_2m,weather_code", "forecast_days": 1,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=10) as r:
        d = json.load(r)
    code = d["current"]["weather_code"]
    return {"city": conf.get("city"), "temp": round(d["current"]["temperature_2m"]),
            "text": next((t for codes, t in WEATHER if code in codes), ""),
            "min": round(d["daily"]["temperature_2m_min"][0]), "max": round(d["daily"]["temperature_2m_max"][0]),
            "rain": d["daily"]["precipitation_probability_max"][0]}


def fetch_schedule(logins, tz):
    """Prochain créneau prévu de chaque streamer (plannings Twitch, hebdomadaires), du plus proche au plus lointain."""
    if not logins:
        return []
    query = "query($l:[String!]){users(logins:$l){login channel{schedule{segments{startAt endAt title}}}}}"
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps({"query": query, "variables": {"l": logins}}).encode(),
        headers={"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        users = json.load(r)["data"]["users"]
    now, upcoming = datetime.datetime.now(tz), []
    for u in users:
        best = None
        for seg in ((((u or {}).get("channel") or {}).get("schedule") or {}).get("segments") or []):
            start = datetime.datetime.fromisoformat(seg["startAt"].replace("Z", "+00:00")).astimezone(tz)
            while start < now - datetime.timedelta(hours=1):   # créneau passé : même heure la semaine suivante
                start += datetime.timedelta(days=7)
            if not best or start < best[0]:
                best = (start, seg.get("title") or "")
        if best:
            upcoming.append((best[0], u["login"], best[1]))
    out = []
    for start, login, title in sorted(upcoming)[:4]:
        days = (start.date() - now.date()).days
        day = "aujourd'hui" if days == 0 else "demain" if days == 1 else DAYS[start.weekday()]
        out.append({"login": login, "when": f"{day} {start:%H:%M}", "title": title})
    return out


def ambient_loop():
    data, fetched = {}, 0
    while True:
        if time.time() - fetched > AMBIENT_FETCH:
            conf = ambient_conf()
            try:
                tz = zoneinfo.ZoneInfo(conf["timezone"])
            except (KeyError, zoneinfo.ZoneInfoNotFoundError, ValueError):
                tz = datetime.datetime.now().astimezone().tzinfo   # fuseau du système
            for key, fetch in (("weather", lambda: fetch_weather(conf)),
                               ("schedule", lambda: fetch_schedule(read_streamers(), tz))):
                try:
                    data[key] = fetch()
                except (OSError, ValueError, KeyError, TypeError):
                    pass   # service injoignable : on garde la dernière valeur
            fetched = time.time()
        try:   # republié chaque minute : un mpv relancé le reçoit vite
            mpv(["set_property", "user-data/streambox/ambient", data])
        except OSError:
            pass
        time.sleep(60)


def state():
    user, volume, mute, pause, video, title, position, duration, tracks, cache = mpv(
        ["get_property", "user-data/streambox"], ["get_property", "volume"], ["get_property", "mute"],
        ["get_property", "pause"], ["get_property", "video-params"], ["get_property", "media-title"],
        ["get_property", "time-pos"], ["get_property", "duration"], ["get_property", "track-list"],
        ["get_property", "demuxer-cache-state"])
    user = user or {}
    media = user.get("mode") == "media"
    # Direct : retard par rapport au bout de ce qui est gardé en mémoire (0 = en direct)
    ranges = (cache or {}).get("seekable-ranges") or []
    delay = max(0.0, ranges[0]["end"] - position) if ranges and position is not None and not media else None
    return {
        "streamers": read_streamers(), "channel": user.get("channel"),
        "chat_visible": user.get("chat_visible", True), "corner": user.get("corner", "bl"),
        "chat_bg": user.get("chat_bg", 60), "chat_size": user.get("chat_size", 32),
        "volume": round(volume or 0), "mute": bool(mute), "pause": bool(pause), "playing": bool(video),
        "live": live_now, "mode": user.get("mode", "twitch"), "delay": delay, "title": title if media else None,
        "position": position if media else None, "duration": duration if media else None,
        "subs": [{"id": t["id"], "name": t.get("title") or t.get("lang") or f"Piste {t['id']}",
                  "selected": bool(t.get("selected"))}
                 for t in (tracks or []) if t.get("type") == "sub"] if media else [],
    }


SRT_CUE = re.compile(r"(\d+)\s*\n(\d\d:\d\d:\d\d,\d\d\d) --> (\d\d:\d\d:\d\d,\d\d\d)[^\n]*\n(.*?)(?:\n\s*\n|\Z)", re.S)


def fix_auto_subs(srt):
    """Sous-titres automatiques de YouTube : chaque réplique dure jusqu'au début de l'avant-dernière suivante, si
    bien que deux répliques sont toujours affichées et que l'ancienne semble ne jamais partir. On coupe chacune au
    début de la suivante."""
    def ms(t):
        h, m, rest = t.split(":")
        s, milli = rest.split(",")
        return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(milli)

    def stamp(v):
        return f"{v // 3600000:02d}:{v // 60000 % 60:02d}:{v // 1000 % 60:02d},{v % 1000:03d}"

    cues = [(ms(a), ms(b), text.strip()) for _, a, b, text in SRT_CUE.findall(srt.replace("\r\n", "\n"))]
    out = []
    for i, (start, end, text) in enumerate(cues):
        if i + 1 < len(cues):
            end = max(start + 1, min(end, cues[i + 1][0]))
        out.append(f"{i + 1}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
    return "\n".join(out)


def fetch_auto_subs(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ("www.youtube.com", "youtube.com"):
        raise ValueError("seuls les sous-titres de YouTube passent par ici")
    with urllib.request.urlopen(url, timeout=15) as r:
        text = r.read().decode("utf-8", "replace")
    return fix_auto_subs(text) if SRT_CUE.search(text) else text


# Liste des streamers modifiable depuis la page : ajout (après vérification sur Twitch) et suppression. Les lignes de
# commentaire de streamers.txt sont conservées.

def twitch_user(login):
    query = "query($l:String!){user(login:$l){login displayName}}"
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps({"query": query, "variables": {"l": login}}).encode(),
        headers={"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["data"]["user"]


def write_streamers(names):
    """Réécrit la liste dans l'ordre donné, en gardant les commentaires d'en-tête du fichier."""
    with open(STREAMERS_FILE, encoding="utf-8") as f:
        lines = f.readlines()
    header = []
    for line in lines:
        if line.split("#", 1)[0].strip():
            break
        header.append(line)
    tmp = STREAMERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(header + [name + "\n" for name in names])
    os.replace(tmp, STREAMERS_FILE)


def edit_streamers(action, raw, delta=0):
    login = raw.strip().lower().removeprefix("https://").removeprefix("www.").removeprefix("twitch.tv/").strip("/ @")
    if not re.fullmatch(r"[a-z0-9_]{3,25}", login):
        raise ValueError("Pseudo Twitch invalide (lettres, chiffres et _ seulement).")
    current = read_streamers()
    if action == "add":
        if login in current:
            raise ValueError(f"{login} est déjà dans la liste.")
        try:
            user = twitch_user(login)
        except OSError as e:
            raise ValueError(f"Impossible de vérifier sur Twitch ({e}).") from e
        if not user:
            raise ValueError(f"Aucune chaîne Twitch « {login} ».")
        with open(STREAMERS_FILE, "a", encoding="utf-8") as f:
            f.write(login + "\n")
        try:   # premier streamer d'une liste vide : on le lance
            if not mpv(["get_property", "user-data/streambox/channel"])[0]:
                mpv(["script-message", "streambox-channel", login])
        except OSError:
            pass
    elif action == "remove":
        if login not in current:
            raise ValueError(f"{login} n'est pas dans la liste.")
        if len(current) == 1:
            raise ValueError("Il faut garder au moins un streamer.")
        write_streamers([n for n in current if n != login])
    elif action == "move":
        if login not in current:
            raise ValueError(f"{login} n'est pas dans la liste.")
        i = current.index(login)
        j = max(0, min(len(current) - 1, i + (1 if delta > 0 else -1)))
        current[i], current[j] = current[j], current[i]
        write_streamers(current)
    else:
        raise ValueError("action inconnue")
    global live_now
    live_now = {k: v for k, v in live_now.items() if k in read_streamers()}


def find_url(*texts):
    """Premier lien http(s) trouvé : les applis partagent souvent « titre + lien » dans le champ texte."""
    for text in texts:
        match = re.search(r"https?://\S+", text or "")
        if match:
            return match.group(0)
    return None


def play(url):
    if not url or not re.match(r"https?://", url):
        raise ValueError("Ce n'est pas un lien http(s).")
    mpv(["script-message", "streambox-play", url])


# Compte Twitch

account = {"login": None, "expired": False}   # dernier résultat connu, pour ne pas interroger Twitch à chaque requête
account_lock = threading.Lock()


def read_token():
    try:
        with open(TWITCH_CONFIG, encoding="utf-8") as f:
            for line in f:
                if line.startswith(TOKEN_PREFIX):
                    return line[len(TOKEN_PREFIX):].strip()
    except OSError:
        pass
    return None


def write_cookies(token):
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    os.chmod(COOKIES_DIR, 0o700)
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        if token:
            f.write(f".twitch.tv\tTRUE\t/\tTRUE\t0\tauth-token\t{token}\n")


def write_token(token):
    write_cookies(token)
    if token is None:
        try:
            os.remove(TWITCH_CONFIG)
        except FileNotFoundError:
            pass
        return
    os.makedirs(os.path.dirname(TWITCH_CONFIG), exist_ok=True)
    tmp = TWITCH_CONFIG + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # lisible par media seulement
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(TOKEN_PREFIX + token + "\n")
    os.replace(tmp, TWITCH_CONFIG)


def validate(token):
    """Pseudo Twitch du jeton, ou None si Twitch le refuse. OSError si Twitch est injoignable."""
    req = urllib.request.Request("https://id.twitch.tv/oauth2/validate", headers={"Authorization": f"OAuth {token}"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.load(r).get("login")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return None
        raise OSError(f"Twitch a répondu {e.code}") from e


def restart_stream():
    # Relance streamlink sur la chaîne en cours, pour qu'il relise sa config
    try:
        channel = mpv(["get_property", "user-data/streambox/channel"])[0]
        if channel:
            mpv(["script-message", "streambox-channel", channel])
    except OSError:
        pass   # mpv pas lancé : il lira la config au démarrage


def check_account():
    """Revérifie le jeton enregistré. S'il ne marche plus, on le retire : un jeton refusé bloque la lecture."""
    token = read_token()
    if not token:
        with account_lock:
            account["login"] = None
        return
    try:
        login = validate(token)
    except OSError:
        return   # Twitch injoignable : on garde l'état connu
    with account_lock:
        account["login"] = login
        account["expired"] = login is None
    if login is None:
        write_token(None)
        restart_stream()


def account_loop():
    while True:
        check_account()
        time.sleep(CHECK_EVERY)


def login(raw):
    # Accepte la valeur du cookie telle quelle, entre guillemets ou précédée de « OAuth »
    token = raw.strip().strip("\"'").strip()
    token = re.sub(r"^(OAuth|Bearer)\s+", "", token, flags=re.I)
    if not re.fullmatch(r"[A-Za-z0-9]{20,64}", token):
        raise ValueError("Ça ne ressemble pas à un jeton Twitch : copie la valeur du cookie auth-token.")
    try:
        name = validate(token)
    except OSError as e:
        raise ValueError(f"Impossible de joindre Twitch pour vérifier le jeton ({e}).") from e
    if not name:
        raise ValueError("Twitch refuse ce jeton : il est expiré ou incomplet.")
    write_token(token)
    with account_lock:
        account.update(login=name, expired=False)
    restart_stream()


def logout():
    write_token(None)
    with account_lock:
        account.update(login=None, expired=False)
    restart_stream()


def action(name, body):
    if name == "channel":
        if body.get("name") not in read_streamers():
            raise ValueError("streamer inconnu")
        mpv(["script-message", "streambox-channel", body["name"]])
    elif name == "chat":
        mpv(["script-message", "streambox-toggle-chat"])
    elif name == "corner":
        mpv(["script-message", "streambox-cycle-corner"])
    elif name == "play":
        play(find_url(str(body.get("url", ""))))
    elif name == "twitch":
        mpv(["script-message", "streambox-twitch"])
    elif name == "sub":
        sid = body.get("id")
        mpv(["set_property", "sid", int(sid) if str(sid).isdigit() else "no"])
    elif name == "seek":
        mpv(["seek", max(-600, min(600, int(body.get("delta", 0))))])
    elif name == "streamers":
        edit_streamers(str(body.get("action", "")), str(body.get("login", "")), int(body.get("delta", 0)))
    elif name == "live_seek":
        target = body.get("delta")
        arg = "live" if target == "live" else str(max(-600, min(600, int(target or 0))))
        mpv(["script-message", "streambox-live-seek", arg])
    elif name == "seek_to":
        mpv(["seek", max(0.0, float(body.get("position", 0))), "absolute"])
    elif name == "set":
        # Bornes et enregistrement gérés par stream-box.lua (set_number)
        if body.get("key") not in ("chat_bg", "chat_size"):
            raise ValueError("réglage inconnu")
        mpv(["script-message", "streambox-set", body["key"], str(int(body.get("value", 0)))])
    elif name == "display":
        display.apply(str(body.get("mode", "auto")))
    elif name == "volume":
        mpv(["add", "volume", max(-20, min(20, int(body.get("delta", 0))))])
    elif name == "mute":
        mpv(["cycle", "mute"])
    elif name == "pause":
        mpv(["cycle", "pause"])
    elif name == "login":
        login(str(body.get("token", "")))
    elif name == "logout":
        logout()
    elif name == "poweroff":
        # Autorisé sans mot de passe pour media par /etc/polkit-1/rules.d/50-stream-box.rules
        r = subprocess.run(["systemctl", "poweroff"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            raise ValueError(f"Extinction refusée : {r.stderr.strip() or r.returncode}")
    else:
        raise ValueError("action inconnue")


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            if self.path.startswith("/share?"):
                # Cible de partage Android (share_target du manifeste) : on lance la vidéo puis on affiche la page
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                url = find_url(*(query.get(k, [""])[0] for k in ("url", "text", "title")))
                try:
                    play(url)
                    location = "/"
                except ValueError:
                    location = "/?partage=invalide"
                self.send_response(303)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif self.path.startswith("/subs?"):
                # Appelé par stream-box.lua (sub-add) pour les sous-titres automatiques de YouTube
                url = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("u", [""])[0]
                self.send(200, fetch_auto_subs(url).encode(), "application/x-subrip; charset=utf-8")
            elif self.path.split("?")[0] in STATIC:
                name, content_type = STATIC[self.path.split("?")[0]]
                with open(os.path.join(DIR, name), "rb") as f:
                    self.send(200, f.read(), content_type)
            elif self.path == "/api/state":
                self.send(200, state())
            elif self.path.startswith("/api/replays?"):
                login = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("login", [""])[0]
                try:
                    self.send(200, replays(login))
                except ValueError as e:
                    self.send(400, {"error": str(e)})
            elif self.path == "/api/display":
                try:
                    self.send(200, display.info())
                except OSError as e:
                    self.send(503, {"error": str(e)})
            elif self.path == "/api/account":
                with account_lock:
                    self.send(200, dict(account))
            else:
                self.send(404, {"error": "introuvable"})
        except (OSError, ValueError) as e:
            self.send(503, {"error": f"box injoignable : {e}"})

    def do_POST(self):
        if not self.path.startswith("/api/"):
            return self.send(404, {"error": "introuvable"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            action(self.path[len("/api/"):], body)
            self.send(200, {"ok": True})
        except ValueError as e:
            self.send(400, {"error": str(e)})
        except OSError as e:
            self.send(503, {"error": f"box injoignable : {e}"})

    def log_message(self, *args):
        pass   # pas de log par requête


write_cookies(read_token())   # au démarrage : cookies alignés sur le jeton enregistré
threading.Thread(target=account_loop, daemon=True).start()
threading.Thread(target=live_loop, daemon=True).start()
threading.Thread(target=ambient_loop, daemon=True).start()
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
