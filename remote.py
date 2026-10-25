#!/usr/bin/env python3
"""Stream Box : télécommande web pour téléphone (http://<box>:8080), qui pilote mpv via son socket IPC.

Les changements de streamer et de chat passent par les script-messages de stream-box.lua, pour que le menu
à l'écran, le chat et la page restent d'accord. Bibliothèque standard uniquement.

Compte Twitch : le jeton du site (cookie auth-token) est rangé dans la config Twitch de streamlink, que
streamlink lit tout seul. Twitch ne retire les pubs des abonnements qu'avec ce jeton-là.
"""
import calendar, datetime, hashlib, json, os, uuid, re, shutil, socket, subprocess, threading, time, urllib.error, urllib.parse, urllib.request, zoneinfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import display   # display.py, même dossier
import netsetup  # netsetup.py : point d'accès Wi-Fi de configuration
import audio     # audio.py : sortie son (HDMI branché, USB, Bluetooth, choix manuel)
import btsetup   # btsetup.py : télécommandes et manettes Bluetooth (appairage, dissociation)

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
PUBLISH_EVERY = 10   # secondes entre deux envois à mpv des données déjà connues : un mpv relancé les reçoit vite
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

live_now = {}   # pseudo -> {"title", "viewers", "game", "thumb"}, streamers en live seulement
avatars = {}    # pseudo -> photo de profil Twitch, pour la page (en live ou non)


def fetch_live(logins):
    query = ("query($l:[String!]){users(logins:$l){login profileImageURL(width:70) "
             "stream{title viewersCount createdAt game{displayName} previewImageURL(width:640,height:360)}}}")
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps({"query": query, "variables": {"l": logins}}).encode(),
        headers={"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        users = json.load(r)["data"]["users"]
    avatars.update({u["login"]: u["profileImageURL"] for u in users if u and u.get("profileImageURL")})
    # Miniature du live : même adresse d'une minute à l'autre, l'heure du relevé force le téléphone à la recharger
    return {u["login"]: {"title": u["stream"]["title"], "viewers": u["stream"]["viewersCount"],
                         "started": epoch(u["stream"]["createdAt"]) if u["stream"].get("createdAt") else None,
                         "game": (u["stream"].get("game") or {}).get("displayName"),
                         "thumb": f"{u['stream']['previewImageURL']}?t={int(time.time()) // LIVE_EVERY}"
                         if u["stream"].get("previewImageURL") else None}
            for u in users if u and u.get("stream")}


def live_loop():
    global live_now
    first, fetched = True, 0.0
    while True:
        went_live = []
        if time.time() - fetched >= LIVE_EVERY:
            fetched = time.time()
            try:
                previous, live_now = live_now, fetch_live(read_streamers())
                # Streamers qui viennent de lancer leur live (pas au premier relevé : ils étaient déjà en live)
                went_live = [] if first else [login for login in live_now if login not in previous]
                first = False
            except (OSError, ValueError, KeyError, TypeError):
                pass   # Twitch injoignable : on garde le dernier relevé
        try:
            mpv(["set_property", "user-data/streambox/live", live_now])
            for login in went_live:
                mpv(["script-message", "streambox-went-live", login])
        except OSError:
            pass
        time.sleep(PUBLISH_EVERY)


# Sondages et prédictions de la chaîne regardée, publiés dans user-data/streambox/polls pour l'encart de stream-box.lua.
# Twitch n'a plus d'abonnement en temps réel (PubSub) pour un simple spectateur : on relève, comme la page twitch.tv.

EVENTS_EVERY = 10    # secondes entre deux relevés, seulement pendant un direct avec l'encart activé
RESULT_FOR = 60      # secondes d'affichage du résultat d'un sondage ou d'une prédiction terminés
EVENTS_QUERY = (
    "query($l:String!){user(login:$l){"
    "viewablePoll{id title status startedAt durationSeconds totalVoters choices{id title votes{total}}} "
    "channel{activePredictionEvents{...p} lockedPredictionEvents{...p} "
    "resolvedPredictionEvents(first:1){edges{node{...p endedAt winningOutcome{id}}}}}}}"
    "fragment p on PredictionEvent{id title status createdAt predictionWindowSeconds "
    "outcomes{id title color totalPoints totalUsers}}")
# Avec le compte connecté : son pari en cours et son solde de points de chaîne (pour voter depuis la page)
EVENTS_SELF = "query($l:String!){user(login:$l){channel{self{communityPoints{balance}} " \
    "activePredictionEvents{id self{prediction{points outcome{id}}}} " \
    "lockedPredictionEvents{id self{prediction{points outcome{id}}}}}}}"
events_now = {"channel": None, "at": 0.0, "data": {"poll": None, "prediction": None}}   # dernier relevé
poll_votes = {}   # id du sondage → choix voté depuis la box (Twitch ne le redonne pas)


def epoch(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def fetch_events(login, seen):
    """{"poll", "prediction"} de la chaîne, chacun None s'il n'y a rien à montrer. seen : id → heure où l'on a vu le
    sondage terminé (Twitch ne donne pas cette heure-là), pour n'afficher son résultat que RESULT_FOR secondes."""
    user = twitch_gql(EVENTS_QUERY, {"l": login}).get("user") or {}
    now, out = time.time(), {"poll": None, "prediction": None}
    p = user.get("viewablePoll")
    if p and p.get("status") in ("ACTIVE", "COMPLETED", "TERMINATED"):
        ended = p["status"] != "ACTIVE"
        if not ended or now - seen.setdefault(p["id"], now) < RESULT_FOR:
            out["poll"] = {"id": p["id"], "title": p["title"], "ended": ended, "voters": p.get("totalVoters") or 0,
                           "ends_at": epoch(p["startedAt"]) + (p.get("durationSeconds") or 0),
                           "mine": poll_votes.get(p["id"]),
                           "choices": [{"id": c["id"], "title": c["title"],
                                        "votes": (c.get("votes") or {}).get("total") or 0}
                                       for c in p.get("choices") or []]}
    channel = user.get("channel") or {}
    events = (channel.get("activePredictionEvents") or []) + (channel.get("lockedPredictionEvents") or [])
    resolved = [e["node"] for e in (channel.get("resolvedPredictionEvents") or {}).get("edges") or []]
    if not events and resolved and resolved[0].get("endedAt") and now - epoch(resolved[0]["endedAt"]) < RESULT_FOR:
        events = resolved
    if events:
        e = events[0]
        winner = (e.get("winningOutcome") or {}).get("id")
        out["prediction"] = {"id": e["id"], "title": e["title"], "status": e["status"],
                             "ends_at": epoch(e["createdAt"]) + (e.get("predictionWindowSeconds") or 0),
                             "outcomes": [{"id": o["id"], "title": o["title"], "color": o.get("color"),
                                           "points": o.get("totalPoints") or 0, "users": o.get("totalUsers") or 0,
                                           "winner": o["id"] == winner}
                                          for o in e.get("outcomes") or []]}
    if read_token() and (out["poll"] or out["prediction"]):
        try:   # pari en cours et solde, seulement s'il y a de quoi voter
            ch = (twitch_gql(EVENTS_SELF, {"l": login}).get("user") or {}).get("channel") or {}
            out["balance"] = ((ch.get("self") or {}).get("communityPoints") or {}).get("balance")
            for ev in (ch.get("activePredictionEvents") or []) + (ch.get("lockedPredictionEvents") or []):
                mine = ((ev.get("self") or {}).get("prediction")) or None
                if out["prediction"] and ev["id"] == out["prediction"]["id"] and mine:
                    out["prediction"]["mine"] = {"outcome": (mine.get("outcome") or {}).get("id"), "points": mine.get("points")}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return out


def current_user_id():
    me = twitch_gql("{currentUser{id}}").get("currentUser")
    if not me:
        raise ValueError("Connecte ton compte Twitch (Réglages) pour voter.")
    return me["id"]


VOTE_ERRORS = {"POLL_NOT_FOUND": "Ce sondage est terminé.", "POLL_NOT_ACTIVE": "Ce sondage est terminé.",
               "INVALID_CHOICE_INDEX": "Choix inconnu.", "NOT_ENOUGH_POINTS": "Pas assez de points de chaîne.",
               "EVENT_NOT_ACTIVE": "Les paris sont fermés.", "EVENT_LOCKED": "Les paris sont fermés.",
               "NOT_FOUND": "Cette prédiction est terminée.", "MULTI_OUTCOME_PREDICTION": "Tu as déjà parié sur l'autre choix."}


def vote_poll(poll_id, choice_id):
    if not read_token():
        raise ValueError("Connecte ton compte Twitch (Réglages) pour voter.")
    d = twitch_gql("mutation($i:VoteInPollInput!){voteInPoll(input:$i){error{code}}}",
                   {"i": {"pollID": poll_id, "choiceID": choice_id, "userID": current_user_id(),
                          "voteID": uuid.uuid4().hex}})
    code = ((d.get("voteInPoll") or {}).get("error") or {}).get("code")
    if code:
        raise ValueError(VOTE_ERRORS.get(code, f"Twitch refuse le vote ({code})."))
    poll_votes[poll_id] = choice_id
    events_now["at"] = 0.0   # relevé à refaire


def predict(event_id, outcome_id, points):
    if not read_token():
        raise ValueError("Connecte ton compte Twitch (Réglages) pour parier.")
    if points < 1:
        raise ValueError("Nombre de points invalide.")
    d = twitch_gql("mutation($i:MakePredictionInput!){makePrediction(input:$i){error{code}}}",
                   {"i": {"eventID": event_id, "outcomeID": outcome_id, "points": points,
                          "transactionID": uuid.uuid4().hex}})
    code = ((d.get("makePrediction") or {}).get("error") or {}).get("code")
    if code:
        raise ValueError(VOTE_ERRORS.get(code, f"Twitch refuse le pari ({code})."))
    events_now["at"] = 0.0


def events_for_page():
    """Sondage et prédiction de la chaîne regardée, pour la page ; relevés ici si le relevé régulier ne tourne pas
    (encart désactivé), au plus toutes les EVENTS_EVERY secondes"""
    user = mpv(["get_property", "user-data/streambox"])[0] or {}
    login = user.get("channel") if user.get("mode") == "twitch" else None
    if not login:
        return {"channel": None, "poll": None, "prediction": None, "logged_in": bool(read_token())}
    if events_now["channel"] != login or time.time() - events_now["at"] > EVENTS_EVERY:
        events_now.update(channel=login, at=time.time(), data=fetch_events(login, {}))
    return {"channel": login, **events_now["data"], "logged_in": bool(read_token())}


def events_loop():
    seen, current = {}, None
    while True:
        data = {"poll": None, "prediction": None}
        try:
            user, playing = mpv(["get_property", "user-data/streambox"], ["get_property", "video-params"])
            user = user or {}
            login = user.get("channel")
            # Toute chaîne en direct (aussi une chaîne suivie ou un second stream inversé, hors de la liste)
            if user.get("mode") == "twitch" and user.get("events", True) and playing and login:
                if login != current:
                    seen, current = {}, login
                data = fetch_events(login, seen)
                events_now.update(channel=login, at=time.time(), data=data)
            mpv(["set_property", "user-data/streambox/polls", data])
        except (OSError, ValueError, KeyError, TypeError):
            pass   # mpv ou Twitch injoignable : on réessaie au prochain tour
        time.sleep(EVENTS_EVERY)


# Rediffusions et clips de la semaine d'un streamer, pour la page (cache de 5 min par streamer)

replays_cache = {}   # pseudo -> (heure, résultat)


def fetch_replays(login):
    query = ("query($l:String!){user(login:$l){"
             "videos(first:8,type:ARCHIVE,sort:TIME){edges{node{id title lengthSeconds createdAt "
             "previewThumbnailURL(width:320,height:180) self{viewingHistory{position}}}}} "
             "clips(first:6,criteria:{period:LAST_WEEK}){edges{node{slug title durationSeconds viewCount "
             "thumbnailURL}}}}}")
    user = twitch_gql(query, {"l": login})["user"] or {}
    vods = [{"title": n["title"], "date": n["createdAt"][:10], "seconds": n["lengthSeconds"],
             "thumb": n["previewThumbnailURL"], "url": f"https://www.twitch.tv/videos/{n['id']}",
             "position": (((n.get("self") or {}).get("viewingHistory") or {}).get("position"))}
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
    # Progression : celle de l'historique de la box si elle est plus récente que le relevé Twitch
    known = {e["key"]: e for e in read_history()}
    result = json.loads(json.dumps(cached[1]))
    for item in result["vods"] + result["clips"]:
        entry = known.get(media_key(item["url"])[0])
        if entry and entry.get("updated", 0) > cached[0] - 300:
            item["position"] = entry["position"]
        item["finished"] = finished(item.get("position") or 0, item.get("seconds"))
    return result


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
    return {"city": conf.get("city"), "temp": round(d["current"]["temperature_2m"]), "code": code,
            "text": next((t for codes, t in WEATHER if code in codes), ""),
            "min": round(d["daily"]["temperature_2m_min"][0]), "max": round(d["daily"]["temperature_2m_max"][0]),
            "rain": d["daily"]["precipitation_probability_max"][0]}


def fetch_schedule(logins, tz):
    """Prochains lives prévus de la liste (plannings Twitch), voir next_streams."""
    if not logins:
        return []
    query = ("query($l:[String!]){users(logins:$l){login channel{schedule{"
             "interruption{startAt endAt} segments{startAt endAt title isCancelled}}}}}")
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps({"query": query, "variables": {"l": logins}}).encode(),
        headers={"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        users = json.load(r)["data"]["users"]
    return next_streams(users, datetime.datetime.now(tz))


MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
          "décembre"]


def next_streams(users, now):
    """Prochain créneau de chaque streamer, du plus proche au plus lointain, puis les streamers en pause.

    Les plannings sont hebdomadaires : un créneau passé est reporté d'une semaine. Les créneaux annulés sont ignorés,
    et ceux qui tombent pendant une pause (« interruption » Twitch, les vacances du streamer) aussi ; un streamer en
    pause en ce moment est affiché « en pause jusqu'au … » au lieu d'un créneau.
    """
    tz = now.tzinfo

    def when(value):
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(tz)

    upcoming, paused = [], []
    for u in users:
        schedule = ((u or {}).get("channel") or {}).get("schedule") or {}
        pause = schedule.get("interruption") or {}
        pause = (when(pause["startAt"]), when(pause["endAt"])) if pause.get("startAt") and pause.get("endAt") else None
        if pause and pause[0] <= now < pause[1]:
            end = pause[1]
            paused.append({"login": u["login"], "when": f"en pause jusqu'au {'1er' if end.day == 1 else end.day} "
                                                        f"{MONTHS[end.month - 1]}", "title": ""})
            continue
        best = None
        for seg in schedule.get("segments") or []:
            if seg.get("isCancelled"):
                continue
            start = when(seg["startAt"])
            while start < now - datetime.timedelta(hours=1) or (pause and pause[0] <= start < pause[1]):
                start += datetime.timedelta(days=7)   # créneau passé, ou pendant la pause : la semaine suivante
            if not best or start < best[0]:
                best = (start, seg.get("title") or "")
        if best:
            upcoming.append((best[0], u["login"], best[1]))
    out = []
    for start, login, title in sorted(upcoming)[:4]:
        days = (start.date() - now.date()).days
        day = "aujourd'hui" if days == 0 else "demain" if days == 1 else DAYS[start.weekday()]
        if days >= 7:   # au-delà d'une semaine (après une pause), le jour seul serait trompeur
            day += f" {'1er' if start.day == 1 else start.day} {MONTHS[start.month - 1]}"
        out.append({"login": login, "when": f"{day} {start:%H:%M}", "title": title})
    return out + paused[:2]


# QR code de la télécommande, pour les invités (écran d'ambiance et menu de la TV). Adresse dans
# ~/.config/stream-box/remote-url (celle du reverse proxy HTTPS, par exemple), sinon http://<IP de la box>:8080.
# Le QR code est calculé par segno, dans le venv media, et publié comme lignes de « 0 » et « 1 ».

REMOTE_URL_FILE = os.path.join(COOKIES_DIR, "remote-url")
MEDIA_PYTHON = os.path.expanduser("~/.local/share/media-venv/bin/python")


def remote_url():
    try:
        with open(REMOTE_URL_FILE, encoding="utf-8") as f:
            url = f.read().strip()
        if re.match(r"https?://", url):
            return url
    except OSError:
        pass
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))   # rien n'est envoyé : sert seulement à connaître l'adresse de sortie
        return f"http://{s.getsockname()[0]}:{PORT}"


def custom_remote_url():
    try:
        with open(REMOTE_URL_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def set_remote_url(url):
    """Adresse de la télécommande montrée en QR code : nom de domaine (reverse proxy HTTPS…) ; vide = réseau local"""
    url = url.strip()
    if not url:
        try:
            os.remove(REMOTE_URL_FILE)
        except FileNotFoundError:
            pass
        return
    if not re.match(r"https?://[\w.-]+(:\d+)?(/\S*)?$", url):
        raise ValueError("Adresse attendue : https://… (ou http://…)")
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    with open(REMOTE_URL_FILE, "w", encoding="utf-8") as f:
        f.write(url + "\n")


qr_cache = {}   # adresse -> lignes du QR code


def qr_rows(text):
    if text not in qr_cache:
        try:
            r = subprocess.run([MEDIA_PYTHON, "-I", "-c", "import segno, sys\n"
                                "for row in segno.make(sys.argv[1], error='m', micro=False).matrix:\n"
                                "    print(''.join(str(int(bool(v))) for v in row))", text],
                               capture_output=True, text=True, timeout=20, check=True)
            qr_cache[text] = r.stdout.split()
        except (OSError, subprocess.SubprocessError):
            qr_cache[text] = None   # segno absent : pas de nouvel essai avant le prochain démarrage
    return qr_cache[text]


def remote_qr():
    url = remote_url()
    rows = qr_rows(url)
    return {"url": url, "rows": rows} if rows else None


def ambient_loop():
    data, fetched = {}, 0
    while True:
        try:
            data["qr"] = remote_qr()   # adresse relue à chaque tour : un changement se voit tout de suite
        except OSError:
            data["qr"] = None   # pas de réseau : pas d'adresse à montrer
        # Mode configuration (point d'accès Wi-Fi de la box) : QR code pour rejoindre son réseau, puis pour la page
        try:
            w = netsetup.status()
        except (OSError, subprocess.SubprocessError):
            w = {}
        h = w.get("hotspot")
        data["setup"] = {"ssid": h["ssid"], "password": h["password"], "url": h["url"],
                         "wifi_rows": qr_rows(f"WIFI:T:WPA;S:{h['ssid']};P:{h['password']};;"),
                         "url_rows": qr_rows(h["url"]), "error": w.get("error")} if h else (
                        {"connecting": w["connecting"]} if w.get("connecting") else None)
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
        try:
            mpv(["set_property", "user-data/streambox/ambient", data])
        except OSError:
            pass
        time.sleep(PUBLISH_EVERY)


# Images du menu de la TV (tv_menu.lua) : par-dessus la vidéo, mpv n'affiche que des images brutes (overlay-add, BGRA à
# alpha prémultiplié). On les télécharge, recadre et convertit avec ffmpeg, en cache dans /tmp. Seulement depuis les
# serveurs d'images de Twitch et de YouTube : l'adresse vient de la requête.

TV_IMAGE_DIR = "/tmp/stream-box-images"


def tv_image(src, width, height, round_, radius=0):
    """Image prête pour overlay-add : round_ = disque, sinon coins arrondis de radius pixels (0 : carrés)."""
    host = urllib.parse.urlsplit(src).hostname or ""
    jf_host = urllib.parse.urlsplit((jf_server() or {}).get("address", "")).hostname
    if not (host.endswith(".jtvnw.net") or host in ("i.ytimg.com", "clips-media-assets2.twitch.tv") or host == jf_host):
        raise ValueError("image refusée")
    width, height = max(8, min(1280, width)), max(8, min(1280, height))
    radius = max(0, min(radius, width // 2, height // 2))
    key = hashlib.sha1(f"{src}|{width}|{height}|{round_}|{radius}".encode()).hexdigest()[:24]
    path = os.path.join(TV_IMAGE_DIR, f"{key}.bgra")
    if not os.path.exists(path):
        os.makedirs(TV_IMAGE_DIR, exist_ok=True)
        with urllib.request.urlopen(src, timeout=10) as r:
            data = r.read(8_000_000)
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},format=rgba"
        # Bords adoucis : disque, ou coins arrondis (distance au centre du quart de cercle du coin le plus proche).
        # Alpha prémultiplié : les couleurs suivent l'opacité.
        alpha = None
        if round_:
            alpha = "clip(255*(W/2+0.5-hypot(X+0.5-W/2,Y+0.5-H/2)),0,255)"
        elif radius:
            r = radius
            alpha = (f"clip(255*({r}+0.5-hypot(max(0,max({r}-X-0.5,X+0.5-W+{r})),"
                     f"max(0,max({r}-Y-0.5,Y+0.5-H+{r})))),0,255)")
        if alpha:
            vf += (f",geq=a='{alpha}'"
                   ":r='r(X,Y)*alpha(X,Y)/255':g='g(X,Y)*alpha(X,Y)/255':b='b(X,Y)*alpha(X,Y)/255'")
        tmp = f"{path}.{threading.get_ident()}.tmp"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", "pipe:0", "-vf", vf, "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "bgra", tmp], input=data, capture_output=True, timeout=30, check=True)
        os.replace(tmp, path)
    return {"path": path, "w": width, "h": height}


# Aperçu de la TV pour la page, seulement quand la page le demande (bloc ouvert) : l'écran entier, écran d'ambiance et
# menus compris, capturé par grim via le protocole wlr-screencopy de cage. Faute de grim, capture de mpv (fenêtre, avec
# le chat et le menu), qui n'a rien à capturer quand aucune vidéo ne joue (la page affiche alors un texte).

PREVIEW_WIDTH = 960
preview_lock = threading.Lock()
preview_cache = {"at": 0.0, "data": None}


def preview():
    """JPEG de l'écran, ou None s'il n'y a pas d'image à capturer."""
    with preview_lock:   # une capture à la fois ; plusieurs téléphones se partagent la dernière pendant 1 s
        if time.time() - preview_cache["at"] < 1:
            return preview_cache["data"]
        data = None
        playing = mpv(["get_property", "video-params"])[0] is not None
        if shutil.which("grim"):
            try:
                width = mpv(["get_property", "osd-dimensions"])[0].get("w") or PREVIEW_WIDTH
                r = subprocess.run(["grim", "-t", "jpeg", "-q", "70", "-s", f"{min(1.0, PREVIEW_WIDTH / width):.3f}", "-"],
                                   capture_output=True, timeout=10, env=display.wlr_env())
                data = r.stdout if r.returncode == 0 and r.stdout else None
            except (OSError, subprocess.SubprocessError, AttributeError):
                data = None
            if data:
                preview_cache.update(at=time.time(), data=data)
                return data
        if playing:
            shot, small = "/tmp/stream-box-shot.jpg", "/tmp/stream-box-preview.jpg"
            for path in (shot, small):
                if os.path.exists(path):
                    os.remove(path)
            mpv(["screenshot-to-file", shot, "window"])
            for _ in range(30):   # mpv écrit le fichier après avoir répondu
                if os.path.exists(shot) and os.path.getsize(shot) > 0:
                    size = os.path.getsize(shot)
                    time.sleep(0.05)
                    if os.path.getsize(shot) == size:
                        break
                time.sleep(0.05)
            if os.path.exists(shot):
                try:
                    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", shot, "-vf", f"scale={PREVIEW_WIDTH}:-2",
                                    "-q:v", "5", small], timeout=10, check=True)
                    shot = small
                except (OSError, subprocess.SubprocessError):
                    pass   # sans ffmpeg : capture en taille réelle
                with open(shot, "rb") as f:
                    data = f.read()
        preview_cache.update(at=time.time(), data=data)
        return data


PLAYER_FILE = os.path.join(COOKIES_DIR, "player")   # « qt » : appli Qt qui embarque mpv (voir player.sh)


def player_choice():
    try:
        with open(PLAYER_FILE, encoding="utf-8") as f:
            return "qt" if f.readline().strip() == "qt" else "mpv"
    except OSError:
        return "mpv"


# Action du bouton d'arrêt de la télécommande web et de Home Assistant : « suspend » (mise en veille, réveil par le
# réseau) ou « poweroff » (arrêt complet, par défaut). Le menu de la TV a ses deux lignes, « Mettre en veille » et
# « Éteindre la box », qui ne dépendent pas de ce réglage. Lu aussi par mqtt_bridge.py.
POWER_ACTION_FILE = os.path.join(COOKIES_DIR, "power-action")


def power_action():
    try:
        with open(POWER_ACTION_FILE, encoding="utf-8") as f:
            return "suspend" if f.readline().strip() == "suspend" else "poweroff"
    except OSError:
        return "poweroff"


def set_power_action(mode):
    if mode not in ("suspend", "poweroff"):
        raise ValueError("action inconnue")
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    with open(POWER_ACTION_FILE, "w", encoding="utf-8") as f:
        f.write(mode + "\n")


def power(mode):
    """« suspend » ou « poweroff ». Autorisé sans mot de passe pour media par
    /etc/polkit-1/rules.d/50-stream-box.rules (la veille l'est aussi d'office pour une session locale active)"""
    r = subprocess.run(["systemctl", "suspend" if mode == "suspend" else "poweroff"],
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise ValueError(f"{'Mise en veille' if mode == 'suspend' else 'Extinction'} refusée : {r.stderr.strip() or r.returncode}")


def hold_power_key():
    """Bouton power (télécommande Bluetooth, boîtier) : logind éteindrait la box de lui-même ; ce verrou l'en empêche,
    et stream-box.lua applique le réglage « Bouton d'arrêt » (veille ou arrêt complet). Permis d'office dans la session
    de la TV (remote.py est lancé par start.sh) ; refusé ailleurs, et logind garde alors son comportement."""
    subprocess.run(["pkill", "-u", str(os.getuid()), "-f", "who=Stream Box bouton power"], capture_output=True)
    subprocess.Popen(["systemd-inhibit", "--what=handle-power-key", "--mode=block", "--who=Stream Box bouton power",
                      "--why=Bouton power : veille ou arrêt selon le réglage", "sleep", "infinity"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def resume_loop():
    """Réveil après une mise en veille : les connexions (streamlink, flux vidéo) sont mortes et l'image resterait
    figée. logind signale PrepareForSleep(false) au réveil (suivi par gdbus) ; mpv relance alors la lecture."""
    while True:
        try:
            mon = subprocess.Popen(["gdbus", "monitor", "--system", "--dest", "org.freedesktop.login1",
                                    "--object-path", "/org/freedesktop/login1"], stdout=subprocess.PIPE, text=True)
            for line in mon.stdout:
                if "PrepareForSleep (false" in line:
                    # Dongle Bluetooth (clones CSR surtout) bloqué au réveil : la télécommande reste « connectée » sans
                    # que ses touches arrivent. On le redémarre ; elle se reconnecte à la première touche
                    for args in (["power", "off"], ["power", "on"]):
                        try:
                            subprocess.run(["bluetoothctl", *args], capture_output=True, timeout=10)
                        except (OSError, subprocess.SubprocessError):
                            pass
                        time.sleep(2)
                    # Réseau revenu (NetworkManager reprend la connexion en quelques secondes) : sinon streamlink
                    # échoue et la box croit le streamer hors ligne, puis réessaie 15 s plus tard
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


keyboard = {}   # clavier de recherche du menu de la TV : {open, text, target, at}


def set_player(mode):
    """Choix du lecteur, appliqué tout de suite : on quitte le lecteur, la boucle de player.sh relance le bon"""
    if mode not in ("qt", "mpv"):
        raise ValueError("lecteur inconnu")
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    with open(PLAYER_FILE, "w", encoding="utf-8") as f:
        f.write(mode + "\n")
    mpv(["quit"])


def state():
    user, volume, mute, pause, video, title, position, duration, tracks, cache, vo, path = mpv(
        ["get_property", "user-data/streambox"], ["get_property", "volume"], ["get_property", "mute"],
        ["get_property", "pause"], ["get_property", "video-params"], ["get_property", "media-title"],
        ["get_property", "time-pos"], ["get_property", "duration"], ["get_property", "track-list"],
        ["get_property", "demuxer-cache-state"], ["get_property", "current-vo"], ["get_property", "path"])
    user = user or {}
    media = user.get("mode") == "media"
    # Direct : retard par rapport au bout de ce qui est gardé en mémoire (0 = en direct)
    ranges = (cache or {}).get("seekable-ranges") or []
    delay = max(0.0, ranges[0]["end"] - position) if ranges and position is not None and not media else None
    return {
        "streamers": read_streamers(), "channel": user.get("channel"), "avatars": avatars,
        "chat_visible": user.get("chat_visible", True), "corner": user.get("corner", "bl"),
        "chat_bg": user.get("chat_bg", 60), "chat_size": user.get("chat_size", 32),
        "sub_size": user.get("sub_size", 100), "sub_bg": user.get("sub_bg", 0),
        "auto_switch": user.get("auto_switch", True), "night": user.get("night", False),
        "events": user.get("events", True), "qr": user.get("qr", "always"),
        # Lecteur choisi, et celui qui tourne vraiment (mpv seul après plusieurs plantages de l'appli Qt)
        "player": player_choice(), "player_running": "qt" if vo == "libmpv" else "mpv", "power_action": power_action(),
        "remote_url": custom_remote_url(),
        # Clavier de recherche du menu de la TV ouvert (oublié au bout de 10 min, menu fermé entre-temps)
        "keyboard": keyboard if keyboard.get("open") and time.time() - keyboard.get("at", 0) < 600 else None,
        "pip": user.get("pip") or {"channel": "", "layout": ""},
        "volume": round(volume or 0), "mute": bool(mute), "pause": bool(pause), "playing": bool(video),
        "live": live_now, "mode": user.get("mode", "twitch"), "delay": delay, "title": title if media else None,
        "position": position if media else None, "duration": duration if media else None,
        # Type de la vidéo en cours (youtube, jellyfin, twitch-vod…) : le menu de la TV s'ouvre sur l'onglet qui va avec
        "media_kind": media_key(path)[1] if media and path else None,
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
    """Premier lien http(s) trouvé : les applis partagent souvent « titre + lien » dans le champ texte. Aussi
    « jellyfin:ID », le lien des vidéos Jellyfin dans l'historique."""
    for text in texts:
        match = re.search(r"https?://\S+|\bjellyfin:[0-9a-f]{32}\b", text or "")
        if match:
            return match.group(0)
    return None


# Historique et reprise de lecture des vidéos lancées depuis la télécommande (liens, YouTube, rediffusions et clips
# Twitch, Jellyfin : celui-ci garde sa propre progression, l'historique de la box ne sert qu'à le retrouver ; lien
# « jellyfin:ID », sans jeton). Les rediffusions Twitch sont synchronisées avec le compte connecté :
# position lue au lancement, écrite toutes les 30 s. Le reste n'est connu que de la box.

HISTORY_FILE = os.path.expanduser("~/.local/state/stream-box/history.json")
HISTORY_MAX = 60
RESUME_MIN = 30         # secondes : en dessous, on repart du début
FINISHED_LEFT = 30      # à moins de 30 s de la fin, ou au-delà de 95 %, la vidéo est vue
TWITCH_PUSH = 30        # secondes entre deux envois de la position à Twitch
history_lock = threading.Lock()
now_playing = {}        # vidéo lancée par play(), suivie par history_loop


def media_key(url):
    """(clé stable, type, identifiant) : une même vidéo garde la même clé quelle que soit la forme du lien."""
    m = re.fullmatch(r"jellyfin:([0-9a-f]{32})", url) or re.search(r"/Videos/([0-9a-f]{32})/", url)
    if m:
        return f"jellyfin:{m.group(1)}", "jellyfin", m.group(1)
    m = re.search(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/)|youtu\.be/)([\w-]{11})", url)
    if m:
        return f"youtube:{m.group(1)}", "youtube", m.group(1)
    m = re.search(r"twitch\.tv/videos/(\d+)", url)
    if m:
        return f"twitch-vod:{m.group(1)}", "twitch-vod", m.group(1)
    m = re.search(r"(?:clips\.twitch\.tv/|twitch\.tv/\w+/clip/)([\w-]+)", url)
    if m:
        return f"twitch-clip:{m.group(1)}", "twitch-clip", m.group(1)
    return url, "link", None


# YouTube : chaînes suivies (liste de la box, ~/.config/stream-box/youtube.json) et leurs dernières vidéos par le flux
# RSS public (sans clé d'API, 15 vidéos), recherche par yt-dlp (« ytsearch »). Caches : 20 min par flux, 10 min par
# recherche, pour solliciter YouTube le moins possible (il bloque vite une adresse IP trop curieuse).

YT_FILE = os.path.join(COOKIES_DIR, "youtube.json")
YT_FEED_CACHE = 1200
YT_FEED_RETRY = 600   # flux en échec (adresse limitée par YouTube…) : nouvel essai 10 min plus tard
YT_SEARCH_CACHE = 600
yt_feeds, yt_searches = {}, {}   # id de chaîne → (heure, vidéos) ; requête → (heure, résultats)
yt_lock = threading.Lock()
YTDLP = os.path.expanduser("~/.local/bin/yt-dlp")
# Défis JavaScript de YouTube : deno s'il est installé (install.sh), sinon le Node du système (image, sans deno)
YTDLP_JS = [] if os.path.exists(os.path.expanduser("~/.local/bin/deno")) else ["--js-runtimes", "node"]


def yt_channels():
    try:
        with open(YT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def yt_resolve(raw):
    """@nom, lien de chaîne ou identifiant UC… → {id, name, handle, avatar} (yt-dlp, une requête)"""
    raw = raw.strip()
    if re.fullmatch(r"UC[\w-]{22}", raw):
        url = f"https://www.youtube.com/channel/{raw}"
    elif re.fullmatch(r"@?[\w.-]{3,40}", raw):
        url = f"https://www.youtube.com/@{raw.lstrip('@')}"
    elif re.match(r"https?://(www\.|m\.)?youtube\.com/", raw):
        url = raw.split("?")[0]
    else:
        raise ValueError("Donne un @nom de chaîne YouTube ou le lien de la chaîne.")
    r = subprocess.run([YTDLP, "--flat-playlist", "-J", "--playlist-items", "0", "--no-warnings", url],
                       capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        raise ValueError("Chaîne YouTube introuvable.") from None
    if not d.get("channel_id"):
        raise ValueError("Chaîne YouTube introuvable.")
    avatar = next((t["url"] for t in d.get("thumbnails") or [] if "avatar" in str(t.get("id"))), None)
    return {"id": d["channel_id"], "name": d.get("channel") or d.get("uploader") or raw,
            "handle": d.get("uploader_id") or "", "avatar": avatar}


def edit_yt_channels(action, raw="", delta=0):
    with yt_lock:
        chans = yt_channels()
        if action == "add":
            # Chaîne des abonnements (id UC…) : déjà connue, sans requête à YouTube
            c = next((dict(x) for x in read_json_file(YT_SUBS_FILE).get("channels") or [] if x["id"] == raw), None) \
                or yt_resolve(raw)
            c.setdefault("handle", "")
            cache = read_json_file(YT_FEED_FILE)
            if (cache.get("channels") or {}).get(c["id"], {}).pop("checked", None) is not None:
                write_private_json(YT_FEED_FILE, cache)   # abonnement devenu favori : 15 vidéos au prochain tour
            if any(x["id"] == c["id"] for x in chans):
                raise ValueError(f"{c['name']} est déjà dans la liste.")
            chans.append(c)
        elif action == "remove":
            chans = [c for c in chans if c["id"] != raw]
        elif action == "move":
            i = next((n for n, c in enumerate(chans) if c["id"] == raw), None)
            j = (i if i is not None else 0) + delta
            if i is None or not 0 <= j < len(chans):
                raise ValueError("déplacement impossible")
            chans[i], chans[j] = chans[j], chans[i]
        else:
            raise ValueError("action inconnue")
        os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
        with open(YT_FILE, "w", encoding="utf-8") as f:
            json.dump(chans, f, ensure_ascii=False)


def yt_feed(channel_id):
    cached = yt_feeds.get(channel_id)
    if cached and time.time() - cached[0] < (YT_FEED_CACHE if cached[1] is not None else YT_FEED_RETRY):
        if cached[1] is None:
            raise OSError("flux injoignable (nouvel essai plus tard)")
        return cached[1]
    try:
        return yt_fetch_feed(channel_id)
    except (OSError, ValueError):
        yt_feeds[channel_id] = (time.time(), None)   # échec gardé : pas de nouvel essai à chaque ouverture du menu
        raise


def yt_fetch_feed(channel_id):
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
          "m": "http://search.yahoo.com/mrss/"}
    with urllib.request.urlopen(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}", timeout=10) as r:
        root = ET.fromstring(r.read())
    videos = []
    for e in root.findall("a:entry", ns):
        vid = e.findtext("yt:videoId", namespaces=ns)
        link = (e.find("a:link", ns).get("href") if e.find("a:link", ns) is not None else "") or ""
        if not vid or "/shorts/" in link:   # les Shorts (vidéos verticales d'une minute) n'ont rien à faire sur la TV
            continue
        stats = e.find("m:group/m:community/m:statistics", ns)
        videos.append({"id": vid, "title": e.findtext("a:title", namespaces=ns) or "",
                       "date": (e.findtext("a:published", namespaces=ns) or "")[:10],
                       "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                       "views": int(stats.get("views")) if stats is not None and stats.get("views") else None,
                       "url": f"https://www.youtube.com/watch?v={vid}"})
    yt_feeds[channel_id] = (time.time(), videos)
    return videos


def yt_meta(video_id):
    """(titre, durée) d'une vidéo : API Google si le compte est connecté (1 unité), sinon oEmbed (titre seul)"""
    try:
        token = yt_token()
        if token:
            items = yt_api("videos", token, part="snippet,contentDetails", id=video_id).get("items") or []
            if items:
                return items[0]["snippet"]["title"], iso_seconds(items[0]["contentDetails"].get("duration"))
    except (OSError, ValueError, KeyError):
        pass
    try:
        url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}")
        with urllib.request.urlopen(url, timeout=3) as r:
            return json.load(r).get("title"), None
    except (OSError, ValueError):
        return None, None


def with_progress(videos, known=None):
    """Position et « vu » d'après l'historique de la box ; vidéo vue ailleurs : pourcentage du compte YouTube (percent,
    indicatif : YouTube le met à jour avec retard)"""
    known = known if known is not None else {e["key"]: e for e in read_history()}
    remote = yt_tv_progress()
    out = []
    for v in videos:
        e = known.get(f"youtube:{v['id']}") or {}
        seconds = v.get("seconds") or e.get("duration")
        item = {**v, "position": e.get("position"), "seconds": seconds, "finished": bool(e.get("finished"))}
        pct = remote.get(v["id"])
        if not e and pct:
            item.update(percent=pct, finished=pct >= 95,
                        position=round(pct / 100 * seconds) if seconds else None)
        out.append(item)
    return out


# Progression du compte YouTube par l'accès « appli TV » (cast/youtube_tv.js, 127.0.0.1:8091) : la box garde ses
# positions (reprise exacte), les renvoie à YouTube (le téléphone reprend là où la TV s'arrête), et montre le
# pourcentage du compte pour les vidéos vues ailleurs.
YT_TV = "http://127.0.0.1:8091"
YT_TV_PUSH = 30   # secondes entre deux envois de la position
yt_tv_cache = {"at": 0.0, "data": {}}


def yt_tv(path, body=None, timeout=10):
    req = urllib.request.Request(YT_TV + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except (OSError, ValueError):
        return None


def yt_tv_progress():
    if time.time() - yt_tv_cache["at"] > 60:
        yt_tv_cache.update(at=time.time(), data=yt_tv("/progress", timeout=15) or {})
    return yt_tv_cache["data"]


def yt_tv_report(video_id, position, final=False):
    threading.Thread(target=yt_tv, args=("/report", {"id": video_id, "position": position, "final": final}),
                     daemon=True).start()


def yt_fav_videos(cache, channel_id):
    """Vidéos d'un favori d'après le relevé des abonnements (API Google), ou None s'il n'y est pas"""
    entry = (cache.get("channels") or {}).get(channel_id) or {}
    if "checked" not in entry or not read_json_file(YT_TOKEN_FILE).get("refresh_token"):
        return None
    details, out = cache.get("details") or {}, []
    for v in entry.get("videos") or []:
        det = details.get(v["id"]) or {}
        if det.get("gone") or det.get("upcoming"):
            continue
        out.append({"id": v["id"], "title": v["title"], "date": v["date"][:10], "thumb": v["thumb"], "url": v["url"],
                    "seconds": det.get("seconds"), "views": det.get("views")})
    return out


def youtube_home():
    """Favoris (une rangée par chaîne) et abonnements. Favoris abonnés : relevé des abonnements, sans requête à
    youtube.com ; les autres : flux RSS, lus en parallèle (yt_feed garde aussi les échecs)"""
    from concurrent.futures import ThreadPoolExecutor
    cache, chans = read_json_file(YT_FEED_FILE), yt_channels()
    videos = {c["id"]: yt_fav_videos(cache, c["id"]) for c in chans}
    rss = [c["id"] for c in chans if videos[c["id"]] is None]
    if rss:
        with ThreadPoolExecutor(8) as pool:
            videos.update(zip(rss, pool.map(lambda cid: yt_safe(yt_feed, cid), rss)))
    known = {e["key"]: e for e in read_history()}
    out = [{**c, "videos": with_progress(videos[c["id"]], known) if videos[c["id"]] is not None else None}
           for c in chans]   # flux injoignable : la chaîne reste affichée, sans vidéos
    try:
        subs = yt_subscriptions()
    except (OSError, ValueError, KeyError) as e:   # compte YouTube en panne : les chaînes de la liste restent
        print(f"remote.py : abonnements YouTube : {e}", flush=True)
        subs = None
    return {"channels": out, "subs": subs}


def yt_search(query):
    """Vidéos et chaînes trouvées : la même requête renvoie les chaînes dont le nom correspond bien"""
    query = " ".join(query.split())[:100]
    if not query:
        return {"results": [], "channels": []}
    cached = yt_searches.get(query.lower())
    if cached and time.time() - cached[0] < YT_SEARCH_CACHE:
        return yt_search_out(*cached[1:])
    # lang=fr : titres d'origine (sinon YouTube renvoie ses traductions automatiques en anglais)
    r = subprocess.run([YTDLP, "--flat-playlist", "-J", "--no-warnings", "--extractor-args", "youtube:lang=fr",
                        f"ytsearch20:{query}"],
                       capture_output=True, text=True, timeout=60)
    try:
        entries = json.loads(r.stdout).get("entries") or []
    except ValueError:
        raise ValueError("Recherche YouTube impossible pour l'instant.") from None
    results, channels = [], []
    for e in entries:
        if re.fullmatch(r"UC[\w-]{22}", e.get("id") or ""):
            thumbs = [t.get("url") or "" for t in e.get("thumbnails") or []]
            avatar = thumbs[-1] if thumbs else ""
            channels.append({"id": e["id"], "name": e.get("title") or e.get("channel") or "",
                             "handle": e.get("uploader_id") or "", "followers": e.get("channel_follower_count"),
                             "avatar": "https:" + avatar if avatar.startswith("//") else avatar or None})
            continue
        # Sinon des vidéos seulement (les playlists, aux identifiants plus longs, sont écartées)
        if not re.fullmatch(r"[\w-]{11}", e.get("id") or "") or e.get("live_status") == "is_upcoming":
            continue
        results.append({"id": e["id"], "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
                        "seconds": e.get("duration"), "views": e.get("view_count"),
                        "thumb": f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg",
                        "url": f"https://www.youtube.com/watch?v={e['id']}"})
    yt_searches[query.lower()] = (time.time(), results, channels)
    return yt_search_out(results, channels)


def yt_search_out(results, channels):
    saved = {c["id"] for c in yt_channels()}
    return {"results": with_progress(results), "channels": [{**c, "saved": c["id"] in saved} for c in channels]}


def yt_channel_videos(channel_id):
    """Dernières vidéos d'une chaîne trouvée par la recherche, qu'elle soit dans la liste ou non"""
    if not re.fullmatch(r"UC[\w-]{22}", channel_id):
        raise ValueError("chaîne invalide")
    try:
        videos = with_progress(yt_feed(channel_id))
    except OSError:
        raise ValueError("YouTube injoignable pour l'instant.") from None
    return {"id": channel_id, "videos": videos, "saved": any(c["id"] == channel_id for c in yt_channels())}


# Jellyfin : bibliothèque du serveur déjà associé à jellyfin-mpv-shim (« Lire sur… »), avec ses identifiants
# (~/.config/jellyfin-mpv-shim/users.json : adresse, UserId, AccessToken ; rien à configurer de plus). La box lit
# « Reprendre », « Prochains épisodes », les ajouts récents par bibliothèque, cherche, et renvoie la progression au
# serveur pendant la lecture (Sessions/Playing, /Progress, /Stopped) : « vu » et la reprise suivent partout.

JF_USERS = os.path.expanduser("~/.config/jellyfin-mpv-shim/users.json")
JF_CACHE = 30
jf_cache = {}


def jf_server():
    try:
        with open(JF_USERS, encoding="utf-8") as f:
            d = json.load(f)
        users = d["users"]
        s = next((u for u in users if u.get("id") == d.get("active")), users[0])["credentials"][0]
        return {"address": s["address"].rstrip("/"), "user": s["UserId"], "token": s["AccessToken"], "name": s.get("Name") or ""}
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def jf_api(path, body=None, params=None):
    srv = jf_server()
    if not srv:
        raise ValueError("Jellyfin n'est pas associé à la box.")
    url = srv["address"] + path.replace("{user}", srv["user"])
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f'MediaBrowser Token="{srv["token"]}"',
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = r.read()
    return json.loads(data) if data else None


def jf_item(i):
    """Élément Jellyfin → carte : titre, ligne d'infos, image paysage, durée, position, vu"""
    srv = jf_server() or {"address": ""}
    img = lambda item_id, kind: f"{srv['address']}/Items/{item_id}/Images/{kind}?fillWidth=480&quality=85"
    kind, tags = i.get("Type"), i.get("ImageTags") or {}
    if kind == "Episode" and tags.get("Primary"):
        thumb = img(i["Id"], "Primary")
    elif tags.get("Thumb"):
        thumb = img(i["Id"], "Thumb")
    elif i.get("BackdropImageTags"):
        thumb = img(i["Id"], "Backdrop/0")
    elif i.get("ParentThumbItemId"):
        thumb = img(i["ParentThumbItemId"], "Thumb")
    elif i.get("ParentBackdropItemId"):
        thumb = img(i["ParentBackdropItemId"], "Backdrop/0")
    else:
        thumb = img(i["Id"], "Primary")
    ud = i.get("UserData") or {}
    out = {"id": i["Id"], "type": kind, "title": i.get("Name") or "", "thumb": thumb,
           "seconds": int((i.get("RunTimeTicks") or 0) / 1e7) or None,
           "position": int((ud.get("PlaybackPositionTicks") or 0) / 1e7), "finished": bool(ud.get("Played")),
           "year": i.get("ProductionYear")}
    if kind == "Episode":
        out["title"] = i.get("SeriesName") or out["title"]
        out["episode"] = (f"S{i.get('ParentIndexNumber') or 0}·E{i.get('IndexNumber') or 0} · " if i.get("IndexNumber") else "") + (i.get("Name") or "")
        out["series"] = i.get("SeriesId")
    elif kind == "Season":   # ajouts récents d'une série, regroupés par saison
        out.update(title=i.get("SeriesName") or out["title"], episode=i.get("Name") or "", series=i.get("SeriesId"))
    elif kind == "Series":
        out.update(series=i["Id"], unplayed=ud.get("UnplayedItemCount"))
    return out


JF_FIELDS = {"Fields": "UserData,RunTimeTicks,ProductionYear", "EnableImageTypes": "Primary,Thumb,Backdrop"}


def jellyfin_home():
    cached = jf_cache.get("home")
    if cached and time.time() - cached[0] < JF_CACHE:
        return cached[1]
    srv = jf_server()
    if not srv:
        return {"configured": False}
    resume = jf_api("/Users/{user}/Items/Resume", params={"Limit": 16, "MediaTypes": "Video", **JF_FIELDS})["Items"]
    nextup = jf_api("/Shows/NextUp", params={"UserId": srv["user"], "Limit": 16, **JF_FIELDS})["Items"]
    libraries = []
    for v in jf_api("/Users/{user}/Views")["Items"]:
        if v.get("CollectionType") not in ("movies", "tvshows", "homevideos", None):
            continue
        latest = jf_api("/Users/{user}/Items/Latest", params={"ParentId": v["Id"], "Limit": 16, **JF_FIELDS})
        libraries.append({"id": v["Id"], "name": v.get("Name") or "", "items": [jf_item(i) for i in latest]})
    home = {"configured": True, "server": srv["name"], "resume": [jf_item(i) for i in resume],
            "nextup": [jf_item(i) for i in nextup], "libraries": libraries}
    jf_cache["home"] = (time.time(), home)
    return home


def jellyfin_search(query):
    query = " ".join(query.split())[:100]
    if not query:
        return []
    items = jf_api("/Users/{user}/Items", params={"searchTerm": query, "IncludeItemTypes": "Movie,Series,Episode",
                                                  "Recursive": "true", "Limit": 30, **JF_FIELDS})["Items"]
    return [jf_item(i) for i in items]


def jellyfin_series(series_id):
    """Épisodes d'une série, et l'index du premier pas encore vu (là où placer le focus)"""
    if not re.fullmatch(r"[0-9a-f]{32}", series_id):
        raise ValueError("série invalide")
    srv = jf_server()
    eps = [jf_item(i) for i in jf_api(f"/Shows/{series_id}/Episodes", params={"UserId": srv["user"], **JF_FIELDS})["Items"]]
    first = next((n for n, e in enumerate(eps) if not e["finished"]), 0)
    return {"id": series_id, "episodes": eps, "first": first}


def jellyfin_play(item_id, from_start=False):
    if not re.fullmatch(r"[0-9a-f]{32}", item_id):
        raise ValueError("élément invalide")
    srv = jf_server()
    raw = jf_api(f"/Users/{{user}}/Items/{item_id}")
    i = jf_item(raw)
    if i["type"] == "Series":
        raise ValueError("Choisis un épisode.")
    title = f"{i['title']} · {i['episode']}" if i.get("episode") else i["title"]
    start = 0 if from_start or i["position"] < RESUME_MIN or i["finished"] else i["position"]
    url = f"{srv['address']}/Videos/{item_id}/stream?static=true&api_key={srv['token']}"
    now_playing.clear()
    now_playing.update(key=f"jellyfin:{item_id}", url=url, link=f"jellyfin:{item_id}", kind="jellyfin", ident=item_id,
                       title=title, thumb=i["thumb"], position=start)
    mpv(["script-message", "streambox-play", url, str(start), title, i["thumb"] or ""])
    mpv(["set_property", "user-data/streambox/storyboard", {}])
    # Barre de lecture et écran de pause : série, épisode, année, résumé ; épisode suivant pour la carte de fin
    mpv(["set_property", "user-data/streambox/meta",
         {"source": "jellyfin", "series": raw.get("SeriesName") or "", "episode": i.get("episode") or "",
          "year": raw.get("ProductionYear") or "", "rating": raw.get("CommunityRating") or 0,
          "overview": (raw.get("Overview") or "")[:600]}])
    nxt = {}
    if i["type"] == "Episode" and raw.get("SeriesId"):
        try:
            eps = jf_api(f"/Shows/{raw['SeriesId']}/Episodes",
                         params={"UserId": srv["user"], "AdjacentTo": item_id, **JF_FIELDS})["Items"]
            ids = [e["Id"] for e in eps]
            if item_id in ids and ids.index(item_id) + 1 < len(eps):
                n = jf_item(eps[ids.index(item_id) + 1])
                nxt = {"id": n["id"], "of": item_id, "title": n["title"], "episode": n.get("episode") or "", "thumb": n["thumb"]}
        except (OSError, ValueError, KeyError):
            pass
    mpv(["set_property", "user-data/streambox/next_up", nxt])
    jf_cache.pop("home", None)
    record(dict(now_playing), start, i["seconds"])
    jf_report("", item_id, start)
    # Sous-titres à part (fichiers .srt… à côté de la vidéo) : absents du flux direct, ajoutés à mpv une fois la vidéo
    # ouverte ; ceux intégrés au fichier y sont déjà
    source = (raw.get("MediaSources") or [{}])[0]
    external = [m for m in source.get("MediaStreams") or [] if m.get("Type") == "Subtitle" and m.get("IsExternal")]
    if external:
        threading.Thread(target=jf_add_subtitles, args=(url, item_id, source["Id"], external, srv), daemon=True).start()


def jf_add_subtitles(url, item_id, source_id, streams, srv):
    for _ in range(30):   # jusqu'à 15 s pour que la vidéo s'ouvre
        time.sleep(0.5)
        try:
            path, loaded = mpv(["get_property", "path"], ["get_property", "duration"])
        except (OSError, ValueError):
            continue
        if path == url and loaded:
            break
    else:
        return
    for m in streams:
        ext = "ass" if m.get("Codec") in ("ass", "ssa") else "srt"
        sub = f"{srv['address']}/Videos/{item_id}/{source_id}/Subtitles/{m['Index']}/Stream.{ext}?api_key={srv['token']}"
        try:
            mpv(["sub-add", sub, "auto", m.get("Title") or m.get("DisplayTitle") or "", m.get("Language") or ""])
        except (OSError, ValueError):
            pass


def jf_report(what, item_id, position, paused=False):
    """Progression vers le serveur : what = "" (début), "/Progress" ou "/Stopped" """
    try:
        jf_api(f"/Sessions/Playing{what}", {"ItemId": item_id, "PositionTicks": int(position * 1e7), "IsPaused": paused,
                                            "CanSeek": True, "PlayMethod": "DirectStream"})
    except (OSError, ValueError):
        pass
    if what == "/Stopped":
        jf_cache.pop("home", None)


def finished(position, duration):
    return bool(duration) and (position >= duration - FINISHED_LEFT or position >= 0.95 * duration)


def read_history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def write_history(entries):
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries[:HISTORY_MAX], f, ensure_ascii=False)
    os.replace(tmp, HISTORY_FILE)


def record(video, position, duration, title=None):
    """Met la vidéo en tête de l'historique avec sa position."""
    with history_lock:
        entries = [e for e in read_history() if e["key"] != video["key"]]
        entry = {"key": video["key"], "url": video.get("link") or video["url"], "kind": video["kind"],
                 "title": title or video.get("title") or video["url"], "thumb": video.get("thumb"),
                 "position": int(position or 0), "duration": int(duration or 0), "updated": time.time()}
        entry["finished"] = finished(entry["position"], entry["duration"])
        write_history([entry] + entries)


def twitch_gql(query, variables=None):
    """Requête GQL Twitch, avec le compte connecté s'il y en a un."""
    headers = {"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"}
    token = read_token()
    if token:
        headers["Authorization"] = f"OAuth {token}"
    req = urllib.request.Request("https://gql.twitch.tv/gql",
                                 data=json.dumps({"query": query, "variables": variables or {}}).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["data"]


def twitch_save_position(video_id, position):
    if not read_token():
        return
    me = twitch_gql("{currentUser{id}}").get("currentUser")
    if me:
        twitch_gql("mutation($i:UpdateUserViewedVideoInput!){updateUserViewedVideo(input:$i){video{id}}}",
                   {"i": {"userID": me["id"], "videoID": video_id, "videoType": "VOD", "position": int(position)}})


# Aperçu des vidéos YouTube sur la barre de lecture (appli Qt) : planche de miniatures (« storyboard ») donnée par
# yt-dlp, publiée dans user-data/streambox/storyboard. Chaque image de la planche est une grille rows × columns de
# miniatures couvrant « duration » secondes.

def fetch_storyboard(url, ident):
    try:
        r = subprocess.run([YTDLP, *YTDLP_JS, "-J", "--no-warnings", "--skip-download",
                            "--no-playlist", url], capture_output=True, text=True, timeout=90)
        info = json.loads(r.stdout or "{}")
        if now_playing.get("ident") == ident:   # infos de la barre de lecture et de l'écran de pause
            d = info.get("upload_date") or ""
            mpv(["set_property", "user-data/streambox/meta",
                 {"source": "youtube", "channel": info.get("channel") or info.get("uploader") or "",
                  "date": f"{d[6:8]}/{d[4:6]}/{d[:4]}" if len(d) == 8 else "",
                  "views": info.get("view_count") or 0, "overview": (info.get("description") or "")[:600]}])
        boards = [f for f in info.get("formats") or [] if f.get("format_note") == "storyboard" and f.get("fragments")]
        if not boards:
            return
        b = max(boards, key=lambda f: f.get("width") or 0)
        board = {"id": ident, "width": b["width"], "height": b["height"], "rows": b.get("rows") or 1,
                 "columns": b.get("columns") or 1,
                 "fragments": [{"url": f["url"], "duration": f.get("duration") or 0} for f in b["fragments"]]}
        if now_playing.get("ident") == ident:   # toujours la même vidéo
            mpv(["set_property", "user-data/streambox/storyboard", board])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        pass


def play(url, from_start=False, title=None, thumb=None, at=None):
    """title, thumb : connus de la page ou du menu qui lance la vidéo (écran de chargement, historique) ;
    at : position imposée (cast depuis l'appli YouTube), sinon reprise d'après l'historique"""
    if re.fullmatch(r"jellyfin:[0-9a-f]{32}", url or ""):   # depuis l'historique
        return jellyfin_play(url.split(":")[1], from_start)
    if not url or not re.match(r"https?://", url):
        raise ValueError("Ce n'est pas un lien http(s).")
    key, kind, ident = media_key(url)
    entry = next((e for e in read_history() if e["key"] == key), None) or {}
    video = {"key": key, "url": url, "kind": kind, "ident": ident, "title": entry.get("title") or title,
             "thumb": entry.get("thumb") or thumb or (f"https://i.ytimg.com/vi/{ident}/mqdefault.jpg" if kind == "youtube" else None)}
    position, updated, duration = entry.get("position", 0), entry.get("updated", 0), entry.get("duration", 0)
    if kind == "youtube" and not video["title"]:   # vidéo castée depuis l'appli YouTube : seul son identifiant est connu
        video["title"], duration = yt_meta(ident)
        duration = duration or 0
    if kind == "youtube" and position < RESUME_MIN and not from_start and at is None:
        pct = yt_tv_progress().get(ident) or 0   # vue ailleurs (téléphone…) : reprise au pourcentage du compte
        if 3 <= pct < 95:
            duration = duration or yt_meta(ident)[1] or 0
            position = int(pct / 100 * duration)
    try:   # Twitch : titre, vignette, durée et position enregistrée sur le compte
        if kind == "twitch-vod":
            v = twitch_gql("query($id:ID!){video(id:$id){title lengthSeconds previewThumbnailURL(width:320,height:180) "
                           "self{viewingHistory{position updatedAt}}}}", {"id": ident}).get("video") or {}
            video.update(title=v.get("title") or video["title"], thumb=v.get("previewThumbnailURL") or video["thumb"])
            duration = v.get("lengthSeconds") or duration
            seen = (v.get("self") or {}).get("viewingHistory") or {}
            if seen.get("updatedAt"):
                at = datetime.datetime.fromisoformat(seen["updatedAt"].replace("Z", "+00:00")).timestamp()
                if at > updated:   # vu plus récemment ailleurs (site, appli) que sur la box
                    position = seen.get("position") or 0
        elif kind == "twitch-clip":
            c = twitch_gql("query($s:ID!){clip(slug:$s){title durationSeconds thumbnailURL}}", {"s": ident}).get("clip") or {}
            video.update(title=c.get("title") or video["title"], thumb=c.get("thumbnailURL") or video["thumb"])
            duration = c.get("durationSeconds") or duration
    except (OSError, ValueError, KeyError):
        pass   # Twitch injoignable : on se contente de l'historique de la box
    start = 0 if from_start or position < RESUME_MIN or finished(position, duration) else int(position)
    if at is not None:
        start = max(0, int(at))
    now_playing.clear()
    now_playing.update(video, pushed=0.0, position=start)
    mpv(["script-message", "streambox-play", url, str(start), "", video.get("thumb") or "", video.get("title") or ""])
    record(video, start, duration)
    mpv(["set_property", "user-data/streambox/storyboard", {}])
    mpv(["set_property", "user-data/streambox/meta", {}])
    mpv(["set_property", "user-data/streambox/next_up", {}])
    if kind == "youtube":
        threading.Thread(target=fetch_storyboard, args=(url, ident), daemon=True).start()


shim_items = {}   # identifiant Jellyfin → carte (titre, image), pour l'historique des lectures du shim


def shim_video():
    """Vidéo Jellyfin lancée par jellyfin-mpv-shim (« Lire sur… » depuis une appli Jellyfin), d'après le lien en
    lecture ; None sinon"""
    try:
        user, path = mpv(["get_property", "user-data/streambox"], ["get_property", "path"])
    except (OSError, ValueError):
        return None
    srv = jf_server()
    if (user or {}).get("mode") != "media" or not srv or not str(path or "").startswith(srv["address"]):
        return None
    key, kind, ident = media_key(path)
    if kind != "jellyfin":
        return None
    if ident not in shim_items:
        try:
            shim_items[ident] = jf_item(jf_api(f"/Users/{{user}}/Items/{ident}"))
        except (OSError, ValueError, KeyError):
            return None
    i = shim_items[ident]
    return {"key": key, "url": path, "link": key, "kind": kind, "ident": ident, "shim": True, "thumb": i["thumb"],
            "title": f"{i['title']} · {i['episode']}" if i.get("episode") else i["title"]}


def history_loop():
    """Toutes les 10 s, note la position de la vidéo lancée par play() ; l'envoie à Twitch pour une rediffusion."""
    while True:
        time.sleep(10)
        video = dict(now_playing) or shim_video()
        if not video:
            continue
        try:
            user, path, position, duration, title = mpv(
                ["get_property", "user-data/streambox"], ["get_property", "path"], ["get_property", "time-pos"],
                ["get_property", "duration"], ["get_property", "media-title"])
        except (OSError, ValueError):
            continue
        playing = (user or {}).get("mode") == "media" and path == video["url"]
        if video.get("shim"):   # lancé par « Lire sur… » : le shim rend compte au serveur, la box note l'historique
            if playing and isinstance(position, (int, float)):
                record(video, position, duration)
            continue
        if video["kind"] == "jellyfin":
            if playing and isinstance(position, (int, float)):
                paused = mpv(["get_property", "pause"])[0]
                jf_report("/Progress", video["ident"], position, bool(paused))
                record(video, position, duration)
                now_playing["position"] = position
            elif not playing:
                jf_report("/Stopped", video["ident"], video.get("position") or 0)
                if now_playing.get("key") == video["key"]:
                    now_playing.clear()
            continue
        if playing and isinstance(position, (int, float)):
            record(video, position, duration, title if title and title != video["url"] else None)
            now_playing["position"] = position
            if video["kind"] == "twitch-vod" and time.time() - video["pushed"] >= TWITCH_PUSH:
                try:
                    twitch_save_position(video["ident"], position)
                    now_playing["pushed"] = time.time()
                except (OSError, ValueError, KeyError):
                    pass
            if video["kind"] == "youtube" and time.time() - video["pushed"] >= YT_TV_PUSH:
                yt_tv_report(video["ident"], position)
                now_playing["pushed"] = time.time()
        elif not playing:   # vidéo terminée ou remplacée : dernière position envoyée à Twitch
            if video["kind"] == "twitch-vod" and video.get("position"):
                try:
                    twitch_save_position(video["ident"], video["position"])
                except (OSError, ValueError, KeyError):
                    pass
            if video["kind"] == "youtube" and video.get("position"):
                yt_tv_report(video["ident"], video["position"], final=True)
            if now_playing.get("key") == video["key"]:
                now_playing.clear()


def edit_history(action, key=""):
    with history_lock:
        entries = read_history()
        if action == "remove":
            entries = [e for e in entries if e["key"] != key]
        elif action == "clear":
            entries = []
        else:
            raise ValueError("action inconnue")
        write_history(entries)


# Chaînes suivies (onglet Suivis du menu de la TV). Twitch refuse cette liste au jeton du site (GQL : « service error »,
# Helix : il manque le droit user:read:follows) : il faut une appli Twitch à soi (dev.twitch.tv), de type Publique (sans
# secret) ou Confidentielle (avec secret), et une autorisation par code (« device code flow ») : la TV ou la page
# affichent un code à taper sur twitch.tv/activate. Config dans twitch-app.json ({"client_id", "client_secret"?}),
# jetons dans twitch-follows-token.json, tous deux en 600 dans ~/.config/stream-box.

TWITCH_APP_FILE = os.path.join(COOKIES_DIR, "twitch-app.json")
FOLLOWS_TOKEN_FILE = os.path.join(COOKIES_DIR, "twitch-follows-token.json")
FOLLOWS_SCOPE = "user:read:follows"
FOLLOWS_CACHE = 60   # secondes entre deux relevés de la liste
follows_lock = threading.Lock()
follows_pending = {}           # autorisation en cours : user_code, verification_uri, expires_at, error
follows_cache = {"at": 0.0, "data": None}


def read_json_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_private_json(path, data):
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def twitch_oauth(path, fields):
    """POST sur id.twitch.tv ; renvoie (code HTTP, réponse JSON)."""
    req = urllib.request.Request(f"https://id.twitch.tv/oauth2/{path}", data=urllib.parse.urlencode(fields).encode())
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {}


def app_fields():
    app = read_json_file(TWITCH_APP_FILE)
    if not app.get("client_id"):
        raise ValueError("aucune appli Twitch configurée")
    fields = {"client_id": app["client_id"]}
    if app.get("client_secret"):
        fields["client_secret"] = app["client_secret"]
    return fields


def save_follows_token(d):
    write_private_json(FOLLOWS_TOKEN_FILE, {"access_token": d["access_token"], "refresh_token": d.get("refresh_token"),
                                            "expires_at": time.time() + int(d.get("expires_in") or 3600)})


def follows_poll(device_code, interval, expires_at):
    """Attend que l'utilisateur tape le code sur twitch.tv/activate (fil séparé)."""
    while time.time() < expires_at:
        time.sleep(interval)
        try:
            code, d = twitch_oauth("token", {**app_fields(), "scopes": FOLLOWS_SCOPE, "device_code": device_code,
                                              "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        except (OSError, ValueError):
            continue
        if code == 200 and d.get("access_token"):
            save_follows_token(d)
            with follows_lock:
                follows_pending.clear()
                follows_cache.update(at=0.0, data=None)
            return
        message = d.get("message", "")
        if message == "slow_down":
            interval += 5
        elif message != "authorization_pending":
            with follows_lock:
                follows_pending.update(error=message or f"refus de Twitch ({code})")
            return
    with follows_lock:
        follows_pending.update(error="code expiré")


def follows_start():
    code, d = twitch_oauth("device", {"client_id": app_fields()["client_id"], "scopes": FOLLOWS_SCOPE})
    if code != 200 or not d.get("device_code"):
        raise ValueError(f"Twitch refuse l'appli : {d.get('message') or code} (vérifie le Client ID)")
    expires_at = time.time() + int(d.get("expires_in") or 1800)
    with follows_lock:
        follows_pending.clear()
        follows_pending.update(user_code=d["user_code"], verification_uri=d["verification_uri"], expires_at=expires_at)
    threading.Thread(target=follows_poll, args=(d["device_code"], int(d.get("interval") or 5), expires_at),
                     daemon=True).start()


def follows_token():
    """Jeton valide pour Helix, renouvelé si besoin ; None si la box n'est pas autorisée."""
    tok = read_json_file(FOLLOWS_TOKEN_FILE)
    if not tok.get("access_token"):
        return None
    if time.time() > tok.get("expires_at", 0) - 120:
        if not tok.get("refresh_token"):
            return None
        code, d = twitch_oauth("token", {**app_fields(), "grant_type": "refresh_token",
                                         "refresh_token": tok["refresh_token"]})
        if code != 200 or not d.get("access_token"):
            if code in (400, 401):   # autorisation retirée sur Twitch : il faudra recommencer
                os.remove(FOLLOWS_TOKEN_FILE)
            return None
        save_follows_token(d)
        tok = read_json_file(FOLLOWS_TOKEN_FILE)
    return tok["access_token"]


def helix(path, token):
    req = urllib.request.Request(f"https://api.twitch.tv/helix/{path}",
                                 headers={"Client-Id": app_fields()["client_id"], "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def fetch_follows(token):
    me = validate_helix(token)
    live = []
    for st in helix(f"streams/followed?user_id={me}&first=100", token).get("data", []):
        live.append({"login": st["user_login"], "title": st.get("title"), "viewers": st.get("viewer_count"),
                     "game": st.get("game_name"),
                     "thumb": (st.get("thumbnail_url") or "").replace("{width}", "640").replace("{height}", "360")
                     + f"?t={int(time.time()) // FOLLOWS_CACHE}"})
    logins, cursor = [], ""
    for _ in range(5):   # jusqu'à 500 chaînes suivies
        d = helix(f"channels/followed?user_id={me}&first=100" + (f"&after={cursor}" if cursor else ""), token)
        logins += [c["broadcaster_login"] for c in d.get("data", [])]
        cursor = (d.get("pagination") or {}).get("cursor")
        if not cursor:
            break
    avatars_map = {}
    for i in range(0, len(logins), 100):
        query = "&".join(f"login={urllib.parse.quote(l)}" for l in logins[i:i + 100])
        for u in helix(f"users?{query}", token).get("data", []):
            avatars_map[u["login"]] = u.get("profile_image_url")
    avatars.update({k: v for k, v in avatars_map.items() if v})
    live_logins = {c["login"] for c in live}
    for c in live:
        c["avatar"] = avatars_map.get(c["login"])
    offline = [{"login": l, "avatar": avatars_map.get(l)} for l in logins if l not in live_logins]
    return {"live": sorted(live, key=lambda c: -(c["viewers"] or 0)), "offline": offline}


def validate_helix(token):
    req = urllib.request.Request("https://id.twitch.tv/oauth2/validate", headers={"Authorization": f"OAuth {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["user_id"]


def follows_status():
    """État pour la page et le menu : appli configurée, autorisation en cours, liste."""
    app = read_json_file(TWITCH_APP_FILE)
    out = {"configured": bool(app.get("client_id")), "confidential": bool(app.get("client_secret")),
           "authorized": False, "pending": None, "live": [], "offline": []}
    with follows_lock:
        if follows_pending and follows_pending.get("expires_at", 0) > time.time():
            out["pending"] = {k: follows_pending.get(k) for k in ("user_code", "verification_uri", "error")}
    if not out["configured"]:
        return out
    token = follows_token()
    if not token:
        return out
    out["authorized"] = True
    with follows_lock:
        if follows_cache["data"] is None or time.time() - follows_cache["at"] > FOLLOWS_CACHE:
            follows_cache.update(at=time.time(), data=fetch_follows(token))
        out.update(follows_cache["data"])
    return out


def follows_logins():
    data = follows_cache["data"] or {}
    return {c["login"] for c in data.get("live", []) + data.get("offline", [])}


def set_twitch_app(client_id, client_secret):
    client_id = client_id.strip()
    if not re.fullmatch(r"[a-z0-9]{20,40}", client_id):
        raise ValueError("Ce n'est pas un Client ID Twitch (30 lettres et chiffres).")
    app = {"client_id": client_id}
    if client_secret.strip():
        app["client_secret"] = client_secret.strip()
    write_private_json(TWITCH_APP_FILE, app)
    for path in (FOLLOWS_TOKEN_FILE,):   # nouvelle appli : l'ancienne autorisation ne vaut plus
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    with follows_lock:
        follows_pending.clear()
        follows_cache.update(at=0.0, data=None)


def follows_logout():
    try:
        os.remove(FOLLOWS_TOKEN_FILE)
    except FileNotFoundError:
        pass
    with follows_lock:
        follows_cache.update(at=0.0, data=None)


# Compte YouTube (rangée « Abonnements » de l'onglet YouTube) : appli Google à soi (console.cloud.google.com, API
# YouTube Data v3, client « TV et appareils à saisie limitée »), autorisation par code sur google.com/device, lecture
# seule. Config dans youtube-app.json ({"client_id", "client_secret"}), jetons dans youtube-token.json, liste des
# abonnements dans youtube-subs.json, en 600 dans ~/.config/stream-box. Tout passe par l'API Google (googleapis.com),
# pas par youtube.com : rien ne s'ajoute aux requêtes qui font limiter l'adresse IP de la box. Quota de l'API : 10 000
# unités par jour ; abonnements relus une fois par jour (1 unité par 50), puis par chaîne 1 unité pour ses dernières
# vidéos (playlist « UULF… » : vidéos sans les Shorts) et 1 unité par 50 vidéos pour durées et vues. Chaque chaîne est
# relue à son rythme (YT_CHANNEL_RHYTHM, d'après l'âge de sa dernière vidéo : toutes les heures si elle a publié ces
# deux derniers jours, une fois par jour si elle se tait depuis un mois), par un tour toutes les minutes en
# arrière-plan (yt_subfeed_loop) ; relevés gardés dans youtube-subfeed.json (rien à refaire au redémarrage), unités
# comptées pour ne pas dépasser YT_DAILY_BUDGET par jour. L'onglet s'ouvre sur le dernier fil.

YT_APP_FILE = os.path.join(COOKIES_DIR, "youtube-app.json")
YT_TOKEN_FILE = os.path.join(COOKIES_DIR, "youtube-token.json")
YT_SUBS_FILE = os.path.join(COOKIES_DIR, "youtube-subs.json")
YT_FEED_FILE = os.path.join(COOKIES_DIR, "youtube-subfeed.json")
YT_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YT_SUBS_EVERY = 86400
YT_CHANNEL_RHYTHM = ((2 * 86400, 3600), (7 * 86400, 3 * 3600), (30 * 86400, 12 * 3600))   # (âge de la dernière vidéo, relecture)
YT_DAILY_BUDGET = 7000   # sur les 10 000 du quota : marge pour « Relire mes abonnements » et les essais
YT_SUBFEED_PER_CHANNEL = 4
YT_SUBFEED_MAX = 60
YT_FAV_VIDEOS = 15
yt_account_lock = threading.Lock()
yt_pending = {}                # autorisation en cours : user_code, verification_uri, expires_at, error
yt_subfeed = {"at": 0.0, "videos": None, "refreshing": False}
yt_units = {"day": "", "used": 0}  # unités du quota de l'API dépensées aujourd'hui


def google_oauth(path, fields):
    """POST sur oauth2.googleapis.com ; renvoie (code HTTP, réponse JSON)."""
    req = urllib.request.Request(f"https://oauth2.googleapis.com/{path}", data=urllib.parse.urlencode(fields).encode())
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {}


def yt_app():
    app = read_json_file(YT_APP_FILE)
    if not app.get("client_id") or not app.get("client_secret"):
        raise ValueError("aucune appli Google configurée")
    return app


def save_yt_token(d, refresh_token=None):
    write_private_json(YT_TOKEN_FILE, {"access_token": d["access_token"],
                                       "refresh_token": d.get("refresh_token") or refresh_token,
                                       "expires_at": time.time() + int(d.get("expires_in") or 3600)})


def yt_poll(device_code, interval, expires_at):
    """Attend que l'utilisateur tape le code sur google.com/device (fil séparé)."""
    while time.time() < expires_at:
        time.sleep(interval)
        try:
            app = yt_app()
            code, d = google_oauth("token", {"client_id": app["client_id"], "client_secret": app["client_secret"],
                                             "device_code": device_code,
                                             "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        except (OSError, ValueError):
            continue
        if code == 200 and d.get("access_token"):
            save_yt_token(d)
            with yt_account_lock:
                yt_pending.clear()
            yt_reset_subs(everything=True)   # peut-être un autre compte
            return
        error = d.get("error", "")
        if error == "slow_down":
            interval += 5
        elif error != "authorization_pending":
            with yt_account_lock:
                yt_pending.update(error={"access_denied": "accès refusé"}.get(error, error or f"refus de Google ({code})"))
            return
    with yt_account_lock:
        yt_pending.update(error="code expiré")


def yt_login():
    app = yt_app()
    code, d = google_oauth("device/code", {"client_id": app["client_id"], "scope": YT_SCOPE})
    if code != 200 or not d.get("device_code"):
        raise ValueError(f"Google refuse l'appli : {d.get('error_description') or d.get('error') or code}"
                         " (vérifie l'ID client et son type « TV et appareils à saisie limitée »)")
    expires_at = time.time() + int(d.get("expires_in") or 1800)
    with yt_account_lock:
        yt_pending.clear()
        yt_pending.update(user_code=d["user_code"], verification_uri=d.get("verification_url") or d.get("verification_uri"),
                          expires_at=expires_at)
    threading.Thread(target=yt_poll, args=(d["device_code"], int(d.get("interval") or 5), expires_at),
                     daemon=True).start()


def yt_token():
    """Jeton valide pour l'API YouTube, renouvelé si besoin ; None si la box n'est pas autorisée."""
    tok = read_json_file(YT_TOKEN_FILE)
    if not tok.get("access_token"):
        return None
    if time.time() > tok.get("expires_at", 0) - 120:
        if not tok.get("refresh_token"):
            return None
        app = yt_app()
        code, d = google_oauth("token", {"client_id": app["client_id"], "client_secret": app["client_secret"],
                                         "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
        if code != 200 or not d.get("access_token"):
            if code in (400, 401):   # autorisation retirée sur le compte Google : il faudra recommencer
                os.remove(YT_TOKEN_FILE)
            return None
        save_yt_token(d, tok["refresh_token"])
        tok = read_json_file(YT_TOKEN_FILE)
    return tok["access_token"]


def yt_api(path, token, **params):
    yt_count_units()
    req = urllib.request.Request(f"https://www.googleapis.com/youtube/v3/{path}?{urllib.parse.urlencode(params)}",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def yt_fetch_subs(token):
    """Chaînes abonnées du compte : [{id, name, avatar}] (jusqu'à 1000)"""
    subs, page = [], None
    for _ in range(20):
        d = yt_api("subscriptions", token, part="snippet", mine="true", maxResults=50, order="alphabetical",
                   **({"pageToken": page} if page else {}))
        for it in d.get("items", []):
            sn = it.get("snippet") or {}
            cid = (sn.get("resourceId") or {}).get("channelId")
            if cid:
                thumbs = sn.get("thumbnails") or {}
                subs.append({"id": cid, "name": sn.get("title") or cid,
                             "avatar": (thumbs.get("medium") or thumbs.get("default") or {}).get("url")})
        page = d.get("nextPageToken")
        if not page:
            break
    write_private_json(YT_SUBS_FILE, {"at": time.time(), "channels": subs})
    return subs


def iso_seconds(text):
    """« PT1H2M3S » → 3723"""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def yt_channel_uploads(channel, token, count=YT_SUBFEED_PER_CHANNEL):
    for prefix in ("UULF", "UU"):   # UULF : vidéos longues seulement (sans Shorts ni directs) ; UU : tout, en secours
        try:
            d = yt_api("playlistItems", token, part="snippet,contentDetails", maxResults=count,
                       playlistId=prefix + channel["id"][2:])
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
        out = []
        for it in d.get("items", []):
            sn, cd = it.get("snippet") or {}, it.get("contentDetails") or {}
            vid = cd.get("videoId")
            if vid:
                out.append({"id": vid, "title": sn.get("title") or "", "channel": channel["name"],
                            "channel_id": channel["id"], "avatar": channel.get("avatar"),
                            "date": cd.get("videoPublishedAt") or sn.get("publishedAt") or "",
                            "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                            "url": f"https://www.youtube.com/watch?v={vid}"})
        return out
    return []


def yt_quota_day():
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - 8 * 3600))   # le quota repart à minuit, heure du Pacifique


def yt_count_units(n=1):
    with yt_account_lock:
        if yt_units["day"] != yt_quota_day():
            yt_units.update(day=yt_quota_day(), used=0)
        yt_units["used"] += n


def yt_channel_every(entry):
    """Rythme de relecture d'une chaîne d'après sa dernière vidéo : souvent si elle publie souvent"""
    if not entry or "checked" not in entry:
        return 0
    dates = [v["date"] for v in entry.get("videos") or [] if v.get("date")]
    if not dates:
        return 86400
    try:
        age = time.time() - calendar.timegm(time.strptime(max(dates)[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return 86400
    for limit, every in YT_CHANNEL_RHYTHM:
        if age < limit:
            return every
    return 86400


def yt_build_feed(cache, token):
    """60 vidéos les plus récentes d'après les chaînes relues ; durées et vues relues au plus toutes les heures (aussi
    pour les vidéos des favoris, servies par yt_fav_videos)"""
    details = cache.setdefault("details", {})
    candidates = sorted((v for e in cache["channels"].values() for v in (e.get("videos") or [])[:YT_SUBFEED_PER_CHANNEL]),
                        key=lambda v: v["date"], reverse=True)[:YT_SUBFEED_MAX + 20]   # marge : directs à venir écartés
    favs = [v for c in yt_channels() for v in (cache["channels"].get(c["id"]) or {}).get("videos") or []]
    if token:
        stale = [v["id"] for v in candidates + favs if time.time() - (details.get(v["id"]) or {}).get("at", 0) > 3600]
        for i in range(0, len(stale), 50):
            ids = stale[i:i + 50]
            d = yt_api("videos", token, part="snippet,contentDetails,statistics", id=",".join(ids), maxResults=50)
            found = {it["id"]: it for it in d.get("items", [])}
            for vid in ids:
                it = found.get(vid)
                views = ((it or {}).get("statistics") or {}).get("viewCount")
                details[vid] = {"at": time.time(), "gone": it is None,
                                "upcoming": ((it or {}).get("snippet") or {}).get("liveBroadcastContent") == "upcoming",
                                "seconds": iso_seconds(((it or {}).get("contentDetails") or {}).get("duration")),
                                "views": int(views) if views else None}
    keep = {v["id"] for v in candidates + favs}
    cache["details"] = {k: v for k, v in details.items() if k in keep}
    out = []
    for v in candidates:
        det = details.get(v["id"]) or {}
        if det.get("gone") or det.get("upcoming"):
            continue   # supprimée, privée, ou direct pas encore commencé
        out.append({**v, "date": v["date"][:10], "seconds": det.get("seconds"), "views": det.get("views")})
    return out[:YT_SUBFEED_MAX]


def yt_refresh_subfeed():
    """Relit les chaînes dont c'est le tour (yt_channel_every), puis refait le fil si quelque chose a bougé"""
    from concurrent.futures import ThreadPoolExecutor
    try:
        token = yt_token()
        if not token:
            return
        cache = read_json_file(YT_FEED_FILE)
        cache.setdefault("channels", {})
        with yt_account_lock:   # unités déjà dépensées aujourd'hui avant un redémarrage
            saved = cache.get("units") or {}
            if not yt_units["day"] and saved.get("day") == yt_quota_day():
                yt_units.update(saved)
        listed = read_json_file(YT_SUBS_FILE)
        subs = listed.get("channels")
        if subs is None or time.time() - listed.get("at", 0) > YT_SUBS_EVERY:
            subs = yt_fetch_subs(token)
        cache["channels"] = {c["id"]: cache["channels"].get(c["id"], {}) for c in subs}   # désabonnements oubliés
        favs = {c["id"] for c in yt_channels()}   # favoris : 15 vidéos pour leur rangée (même coût)
        due = [c for c in subs if time.time() - cache["channels"][c["id"]].get("checked", 0) >= yt_channel_every(cache["channels"][c["id"]])
               or (c["id"] in favs and cache["channels"][c["id"]].get("count", 0) < YT_FAV_VIDEOS)]
        with yt_account_lock:
            left = YT_DAILY_BUDGET - (yt_units["used"] if yt_units["day"] == yt_quota_day() else 0)
        due = due[:max(0, left - 10)]   # quota du jour presque épuisé : la suite attend demain
        if due:
            with ThreadPoolExecutor(16) as pool:
                lists = list(pool.map(lambda c: yt_safe(yt_channel_uploads, c, token,
                                                        YT_FAV_VIDEOS if c["id"] in favs else YT_SUBFEED_PER_CHANNEL), due))
            for c, videos in zip(due, lists):
                entry = cache["channels"][c["id"]]
                entry["checked"] = time.time()
                entry["count"] = YT_FAV_VIDEOS if c["id"] in favs else YT_SUBFEED_PER_CHANNEL
                if videos is not None:   # injoignable : l'ancien relevé reste, nouvel essai au prochain tour
                    entry["videos"] = videos
        if due or yt_subfeed["videos"] is None or time.time() - yt_subfeed["at"] > 3600:
            videos = yt_build_feed(cache, token)
            cache["units"] = dict(yt_units)
            write_private_json(YT_FEED_FILE, cache)
            with yt_account_lock:
                yt_subfeed.update(at=time.time(), videos=videos)
        if due:
            print(f"remote.py : abonnements YouTube : {len(due)} chaînes relues, {yt_units['used']} unités aujourd'hui",
                  flush=True)
    except (OSError, ValueError) as e:
        print(f"remote.py : abonnements YouTube : {e}", flush=True)
        with yt_account_lock:
            if yt_subfeed["videos"] is None:
                yt_subfeed.update(at=time.time(), videos=[])
    finally:
        with yt_account_lock:
            yt_subfeed["refreshing"] = False


def yt_safe(fn, *args):
    try:
        return fn(*args)
    except (OSError, ValueError):
        return None   # chaîne fermée ou injoignable : les autres restent


def yt_reset_subs(everything=False):
    """Liste des abonnements relue au prochain tour ; everything : relevés des chaînes oubliés aussi (déconnexion)"""
    for path in (YT_SUBS_FILE, YT_FEED_FILE) if everything else (YT_SUBS_FILE,):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    with yt_account_lock:
        yt_subfeed.update(at=0.0, videos=None if everything else yt_subfeed["videos"])


def yt_start_refresh():
    """Lance un relevé s'il n'y en a pas déjà un ; renvoie True s'il faut le faire dans ce fil"""
    with yt_account_lock:
        if yt_subfeed["refreshing"]:
            return False
        yt_subfeed["refreshing"] = True
        return True


def yt_subfeed_loop():
    """Tour des chaînes toutes les minutes en arrière-plan (seules celles dont c'est le tour sont relues)"""
    while True:
        try:
            if read_json_file(YT_TOKEN_FILE).get("refresh_token") and yt_start_refresh():
                yt_refresh_subfeed()
        except Exception as e:   # le fil ne doit pas mourir
            print(f"remote.py : abonnements YouTube : {e}", flush=True)
        time.sleep(60)


def yt_subscriptions():
    """Rangée « Abonnements » pour /api/youtube : fil de yt_subfeed_loop ; le tout premier est attendu"""
    status = yt_account_status()
    if not status["authorized"]:
        return {**status, "videos": None}
    if yt_subfeed["videos"] is None:
        if yt_start_refresh():
            yt_refresh_subfeed()
        else:
            for _ in range(150):   # relevé en cours dans un autre fil
                if yt_subfeed["videos"] is not None:
                    break
                time.sleep(0.2)
    with yt_account_lock:
        videos = yt_subfeed["videos"]
    return {**status, "videos": with_progress(videos) if videos is not None else None}


def yt_account_status():
    app = read_json_file(YT_APP_FILE)
    out = {"configured": bool(app.get("client_id") and app.get("client_secret")), "authorized": False, "pending": None,
           "channels": None, "synced": None}
    with yt_account_lock:
        if yt_pending and yt_pending.get("expires_at", 0) > time.time():
            out["pending"] = {k: yt_pending.get(k) for k in ("user_code", "verification_uri", "error")}
    if not out["configured"]:
        return out
    try:
        out["authorized"] = bool(yt_token())
    except (OSError, ValueError):
        out["authorized"] = bool(read_json_file(YT_TOKEN_FILE).get("refresh_token"))   # Google injoignable : on y croit
    subs = read_json_file(YT_SUBS_FILE)
    if out["authorized"] and subs.get("channels") is not None:
        out["channels"], out["synced"] = len(subs["channels"]), int(subs.get("at") or 0)
    out["units_today"] = yt_units["used"] if yt_units["day"] == yt_quota_day() else 0
    out["tv"] = yt_tv("/status", timeout=3) or {"unavailable": True}   # progression (accès « appli TV »)
    return out


def set_yt_app(client_id, client_secret):
    client_id, client_secret = client_id.strip(), client_secret.strip()
    if not re.fullmatch(r"[\w-]+\.apps\.googleusercontent\.com", client_id):
        raise ValueError("Ce n'est pas un ID client Google (il finit par .apps.googleusercontent.com).")
    if not client_secret:
        raise ValueError("Il manque le code secret du client.")
    write_private_json(YT_APP_FILE, {"client_id": client_id, "client_secret": client_secret})
    yt_logout()   # nouvelle appli : l'ancienne autorisation ne vaut plus


def yt_logout():
    try:
        os.remove(YT_TOKEN_FILE)
    except FileNotFoundError:
        pass
    with yt_account_lock:
        yt_pending.clear()
    yt_reset_subs(everything=True)


# État de la box (page, Réglages → Système) : températures, processeur, mémoire, disque, réseau, lecteur, services,
# mises à jour. Le processeur et le débit réseau se mesurent sur un intervalle : relevés toutes les 5 s par un fil.

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
    """Dernière mise à jour d'après update.log : date et lignes de ce passage"""
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
    failed = any("échec" in l.lower() or "ÉCHEC" in l for l in lines)
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
            services[label] = user_systemctl("is-active", unit) or "inconnu"
        except (OSError, subprocess.SubprocessError):
            services[label] = "inconnu"
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
        "player": {"choice": player_choice(), "running": "qt" if vo == "libmpv" else "mpv", "hwdec": hwdec,
                   "dropped": drops, "fps": fps, "size": f"{width}x{height}" if width else None},
        "services": services,
        "update": {"running": props.get("ActiveState") == "activating", "next": next_run, "last": last_update()},
    }


def start_update():
    user_systemctl("start", "--no-block", "stream-box-update.service")


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
        # Streamer de la liste, ou chaîne suivie (onglet Suivis du menu de la TV)
        if body.get("name") not in read_streamers() and body.get("name") not in follows_logins():
            raise ValueError("streamer inconnu")
        mpv(["script-message", "streambox-channel", body["name"]])
    elif name == "chat":
        mpv(["script-message", "streambox-toggle-chat"])
    elif name == "corner":
        mpv(["script-message", "streambox-cycle-corner"])
    elif name == "resume_last":
        # Retour deux fois (stream-box.lua) : pendant un stream, dernière vidéo de l'historique, à sa position ; sur
        # l'écran d'accueil (or_stream), le plus récent du dernier stream et de cette vidéo
        entries = read_history()
        state = os.path.expanduser("~/.local/state/stream-box/")
        try:
            with open(state + "channel") as f:
                last_channel = f.read().strip()
            with open(state + "channel_at") as f:
                channel_at = float(f.read().strip() or 0)
        except (OSError, ValueError):
            last_channel, channel_at = "", 0
        if body.get("or_stream") and last_channel and (not entries or channel_at > entries[0].get("updated", 0)):
            mpv(["script-message", "streambox-channel", last_channel])
        elif entries:
            play(entries[0]["url"], title=entries[0].get("title"), thumb=entries[0].get("thumb"))
        else:
            raise ValueError("Pas encore de vidéo dans l'historique")
    elif name == "play":
        play(find_url(str(body.get("url", ""))), bool(body.get("from_start")),
             str(body.get("title") or "")[:200] or None, str(body.get("thumb") or "")[:500] or None,
             body.get("start") if isinstance(body.get("start"), (int, float)) else None)
    elif name == "history":
        edit_history(str(body.get("action", "")), str(body.get("key", "")))
    elif name == "twitch":
        mpv(["script-message", "streambox-twitch"])
    elif name == "home":
        mpv(["script-message", "streambox-home"])
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
    elif name == "auto_switch":
        mpv(["script-message", "streambox-auto-switch", "yes" if body.get("enabled") else "no"])
    elif name == "flag":
        # Réglages oui / non de stream-box.lua : mode nuit (son compressé), encart des sondages et prédictions
        if body.get("key") not in ("night", "events"):
            raise ValueError("réglage inconnu")
        mpv(["script-message", "streambox-flag", body["key"], "yes" if body.get("enabled") else "no"])
    elif name == "pip":
        # Second stream (appli Qt) : open <chaîne> [pip|split], close, swap, layout <pip|split>
        action = str(body.get("action", ""))
        if action not in ("open", "close", "swap", "layout"):
            raise ValueError("action inconnue")
        login = str(body.get("name", "")).strip().lower()
        if action == "open" and not re.fullmatch(r"[a-z0-9_]{2,25}", login):
            raise ValueError("chaîne invalide")
        mpv(["script-message", "streambox-pip", action, login, str(body.get("layout", "pip"))])
    elif name == "vote":
        vote_poll(str(body.get("poll", "")), str(body.get("choice", "")))
    elif name == "predict":
        predict(str(body.get("event", "")), str(body.get("outcome", "")), int(body.get("points", 0)))
    elif name == "player":
        set_player(str(body.get("mode", "")))
    elif name == "jellyfin_play":
        jellyfin_play(str(body.get("id", "")), bool(body.get("from_start")))
    elif name == "youtube_channels":
        edit_yt_channels(str(body.get("action", "")), str(body.get("channel", "")), int(body.get("delta", 0)))
    elif name == "update":
        start_update()
    elif name == "qr":
        # Affichage du QR code de la télécommande sur la TV
        if body.get("mode") not in ("always", "timed", "never"):
            raise ValueError("mode inconnu")
        mpv(["script-message", "streambox-qr", body["mode"]])
    elif name == "set":
        # Bornes et enregistrement gérés par stream-box.lua (set_number)
        if body.get("key") not in ("chat_bg", "chat_size", "sub_size", "sub_bg"):
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
    elif name == "follows_app":
        set_twitch_app(str(body.get("client_id", "")), str(body.get("client_secret", "")))
    elif name == "follows_login":
        follows_start()
    elif name == "follows_logout":
        follows_logout()
    elif name == "youtube_app":
        set_yt_app(str(body.get("client_id", "")), str(body.get("client_secret", "")))
    elif name == "youtube_login":
        yt_login()
    elif name == "youtube_logout":
        yt_logout()
    elif name == "youtube_tv_login":
        d = yt_tv("/login", {}, timeout=15)
        if not d or d.get("error"):
            raise ValueError(f"Connexion impossible : {(d or {}).get('error') or 'service cast arrêté'}")
    elif name == "youtube_tv_logout":
        yt_tv("/logout", {})
        yt_tv_cache.update(at=0.0, data={})
    elif name == "youtube_sync":
        yt_reset_subs()
    elif name == "poweroff":
        # mode : « suspend » (Mettre en veille), « full » (Éteindre la box, menu de la TV) ; sinon le réglage
        mode = str(body.get("mode") or "")
        power("suspend" if mode == "suspend" else "poweroff" if mode == "full" else power_action())
    elif name == "key":
        # Télécommande virtuelle de la page : mêmes touches que la télécommande Bluetooth (stream-box.lua, KEYS)
        # (la touche lecture de la télécommande Xiaomi change le coin du chat : ici, « Lecture » met en pause ou relance)
        # Action envoyée telle quelle à stream-box.lua (comme les touches lues par input.py)
        key = str(body.get("key", ""))
        if key == "playpause":
            mpv(["cycle", "pause"])
            return
        if key not in ("up", "down", "left", "right", "ok", "back", "home", "menu", "homescreen"):
            raise ValueError("touche inconnue")
        mpv(["script-message", "streambox-input", "VIRTUAL", key])
    elif name == "bluetooth":
        # Menu Système de la TV : {"action": "scan"}, {"action": "pair" | "remove", "mac"}
        what, mac = str(body.get("action", "")), str(body.get("mac", "")).upper()
        if what == "scan":
            btsetup.scan()
        elif what == "pair":
            btsetup.pair(mac)
        elif what == "remove":
            btsetup.remove(mac)
        else:
            raise ValueError("action inconnue")
    elif name == "keymap":
        # Touches de la télécommande : assistant d'apprentissage (stream-box.lua), ou retour aux touches par défaut
        what = str(body.get("action", ""))
        if what not in ("wizard", "reset"):
            raise ValueError("action inconnue")
        mpv(["script-message", "streambox-keymap-" + what])
    elif name == "audio":
        # Sortie son : « auto » ou l'identifiant d'une sortie de GET /api/audio
        audio.set_choice(str(body.get("output", "auto"))[:200])
    elif name == "keyboard":
        # Menu de la TV : clavier de recherche ouvert ou fermé (la page propose alors un champ de texte)
        keyboard.update(open=bool(body.get("open")), text=str(body.get("text", ""))[:80],
                        target=str(body.get("target", ""))[:20], at=time.time())
    elif name == "keyboard_input":
        # Page : texte du champ, envoyé au clavier du menu ; submit lance la recherche
        if not keyboard.get("open"):
            raise ValueError("Le clavier de la TV n'est plus ouvert.")
        text = str(body.get("text", ""))[:80]
        keyboard["text"] = text
        mpv(["script-message", "streambox-tvmenu-text", text, "1" if body.get("submit") else "0"])
        if body.get("submit"):
            keyboard["open"] = False
    elif name == "remote_url":
        set_remote_url(str(body.get("url", ""))[:300])
    elif name == "wifi":
        # {"action": "connect", "ssid", "password"} : rejoindre un réseau ; {"action": "hotspot"} : mode configuration
        if body.get("action") == "hotspot":
            netsetup.manual_hotspot()
        else:
            netsetup.connect(str(body.get("ssid", ""))[:64], str(body.get("password", ""))[:128])
    elif name == "reboot":
        # Autorisé à la session de la TV d'office, ailleurs par la règle polkit (login1.reboot*)
        r = subprocess.run(["systemctl", "reboot"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            raise ValueError(f"Redémarrage refusé : {r.stderr.strip() or r.returncode}")
    elif name == "power_action":
        set_power_action(str(body.get("mode", "")))
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
            elif self.path.split("?")[0] == "/api/preview":
                image = preview()
                if image:
                    self.send(200, image, "image/jpeg")
                else:
                    self.send_response(204)   # rien à capturer (écran d'ambiance)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
            elif self.path == "/api/history":
                self.send(200, read_history())
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
            elif self.path.startswith("/api/tvimage?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    self.send(200, tv_image(q.get("src", [""])[0], int(q.get("w", ["0"])[0]), int(q.get("h", ["0"])[0]),
                                            q.get("round", ["0"])[0] == "1", int(q.get("radius", ["0"])[0])))
                except (ValueError, subprocess.SubprocessError) as e:
                    self.send(400, {"error": str(e)})
            elif self.path == "/api/youtube":
                self.send(200, youtube_home())
            elif self.path.startswith("/api/youtube_search?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("q", [""])[0]
                try:
                    self.send(200, {"query": q, **yt_search(q)})
                except ValueError as e:
                    self.send(400, {"error": str(e)})
            elif self.path == "/api/jellyfin":
                try:
                    self.send(200, jellyfin_home())
                except (OSError, ValueError, KeyError) as e:
                    self.send(503, {"error": f"Jellyfin injoignable : {e}"})
            elif self.path.startswith("/api/jellyfin_search?") or self.path.startswith("/api/jellyfin_series?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    if self.path.startswith("/api/jellyfin_search?"):
                        query = q.get("q", [""])[0]
                        self.send(200, {"query": query, "results": jellyfin_search(query)})
                    else:
                        self.send(200, jellyfin_series(q.get("id", [""])[0]))
                except (OSError, ValueError, KeyError) as e:
                    self.send(400, {"error": str(e)})
            elif self.path.startswith("/api/youtube_channel?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("id", [""])[0]
                try:
                    self.send(200, yt_channel_videos(q))
                except ValueError as e:
                    self.send(400, {"error": str(e)})
            elif self.path == "/api/bluetooth":
                self.send(200, btsetup.status())
            elif self.path == "/api/audio":
                outs = audio.outputs()
                self.send(200, {"choice": audio.choice(), "current": audio.current(outs),
                                "outputs": [{"id": o["id"], "label": o["label"], "kind": o["kind"]} for o in outs]})
            elif self.path == "/api/wifi":
                self.send(200, netsetup.status())
            elif self.path == "/api/health":
                self.send(200, health())
            elif self.path == "/api/events":
                try:
                    self.send(200, events_for_page())
                except (OSError, ValueError, KeyError) as e:
                    self.send(503, {"error": f"Twitch injoignable : {e}"})
            elif self.path == "/api/youtube_channels":
                self.send(200, {"channels": yt_channels()})
            elif self.path == "/api/youtube_account":
                self.send(200, yt_account_status())
            elif self.path == "/api/follows":
                try:
                    self.send(200, follows_status())
                except (OSError, ValueError, KeyError) as e:
                    self.send(503, {"error": f"Twitch injoignable : {e}"})
            elif self.path.startswith("/api/qr?"):
                text = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("text", [""])[0]
                self.send(200, {"rows": qr_rows(text)})
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
threading.Thread(target=history_loop, daemon=True).start()
threading.Thread(target=events_loop, daemon=True).start()
threading.Thread(target=health_loop, daemon=True).start()
threading.Thread(target=resume_loop, daemon=True).start()
threading.Thread(target=netsetup.setup_loop, daemon=True).start()
threading.Thread(target=yt_subfeed_loop, daemon=True).start()
hold_power_key()
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
