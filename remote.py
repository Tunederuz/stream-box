#!/usr/bin/env python3
"""Stream Box : télécommande web pour téléphone (http://<box>:8080), qui pilote mpv via son socket IPC.

Les changements de streamer et de chat passent par les script-messages de stream-box.lua, pour que le menu
à l'écran, le chat et la page restent d'accord. Bibliothèque standard uniquement.

Compte Twitch : le jeton du site (cookie auth-token) est rangé dans la config Twitch de streamlink, que
streamlink lit tout seul. Twitch ne retire les pubs des abonnements qu'avec ce jeton-là.
"""
import datetime, hashlib, json, os, uuid, re, shutil, socket, subprocess, threading, time, urllib.error, urllib.parse, urllib.request, zoneinfo
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
             "stream{title viewersCount game{displayName} previewImageURL(width:640,height:360)}}}")
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps({"query": query, "variables": {"l": logins}}).encode(),
        headers={"Client-ID": TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        users = json.load(r)["data"]["users"]
    avatars.update({u["login"]: u["profileImageURL"] for u in users if u and u.get("profileImageURL")})
    # Miniature du live : même adresse d'une minute à l'autre, l'heure du relevé force le téléphone à la recharger
    return {u["login"]: {"title": u["stream"]["title"], "viewers": u["stream"]["viewersCount"],
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
    if not (host.endswith(".jtvnw.net") or host in ("i.ytimg.com", "clips-media-assets2.twitch.tv")):
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


def set_player(mode):
    """Choix du lecteur, appliqué tout de suite : on quitte le lecteur, la boucle de player.sh relance le bon"""
    if mode not in ("qt", "mpv"):
        raise ValueError("lecteur inconnu")
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    with open(PLAYER_FILE, "w", encoding="utf-8") as f:
        f.write(mode + "\n")
    mpv(["quit"])


def state():
    user, volume, mute, pause, video, title, position, duration, tracks, cache, vo = mpv(
        ["get_property", "user-data/streambox"], ["get_property", "volume"], ["get_property", "mute"],
        ["get_property", "pause"], ["get_property", "video-params"], ["get_property", "media-title"],
        ["get_property", "time-pos"], ["get_property", "duration"], ["get_property", "track-list"],
        ["get_property", "demuxer-cache-state"], ["get_property", "current-vo"])
    user = user or {}
    media = user.get("mode") == "media"
    # Direct : retard par rapport au bout de ce qui est gardé en mémoire (0 = en direct)
    ranges = (cache or {}).get("seekable-ranges") or []
    delay = max(0.0, ranges[0]["end"] - position) if ranges and position is not None and not media else None
    return {
        "streamers": read_streamers(), "channel": user.get("channel"), "avatars": avatars,
        "chat_visible": user.get("chat_visible", True), "corner": user.get("corner", "bl"),
        "chat_bg": user.get("chat_bg", 60), "chat_size": user.get("chat_size", 32),
        "auto_switch": user.get("auto_switch", True), "night": user.get("night", False),
        "events": user.get("events", True), "qr": user.get("qr", "always"),
        # Lecteur choisi, et celui qui tourne vraiment (mpv seul après plusieurs plantages de l'appli Qt)
        "player": player_choice(), "player_running": "qt" if vo == "libmpv" else "mpv",
        "pip": user.get("pip") or {"channel": "", "layout": ""},
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


# Historique et reprise de lecture des vidéos lancées depuis la télécommande (liens, YouTube, rediffusions et clips
# Twitch ; Jellyfin gère sa propre progression). Les rediffusions Twitch sont synchronisées avec le compte connecté :
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
        entry = {"key": video["key"], "url": video["url"], "kind": video["kind"],
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


def play(url, from_start=False):
    if not url or not re.match(r"https?://", url):
        raise ValueError("Ce n'est pas un lien http(s).")
    key, kind, ident = media_key(url)
    entry = next((e for e in read_history() if e["key"] == key), None) or {}
    video = {"key": key, "url": url, "kind": kind, "ident": ident, "title": entry.get("title"),
             "thumb": entry.get("thumb") or (f"https://i.ytimg.com/vi/{ident}/mqdefault.jpg" if kind == "youtube" else None)}
    position, updated, duration = entry.get("position", 0), entry.get("updated", 0), entry.get("duration", 0)
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
    now_playing.clear()
    now_playing.update(video, pushed=0.0, position=start)
    mpv(["script-message", "streambox-play", url, str(start)])
    record(video, start, duration)


def history_loop():
    """Toutes les 10 s, note la position de la vidéo lancée par play() ; l'envoie à Twitch pour une rediffusion."""
    while True:
        time.sleep(10)
        video = dict(now_playing)
        if not video:
            continue
        try:
            user, path, position, duration, title = mpv(
                ["get_property", "user-data/streambox"], ["get_property", "path"], ["get_property", "time-pos"],
                ["get_property", "duration"], ["get_property", "media-title"])
        except (OSError, ValueError):
            continue
        playing = (user or {}).get("mode") == "media" and path == video["url"]
        if playing and isinstance(position, (int, float)):
            record(video, position, duration, title if title and title != video["url"] else None)
            now_playing["position"] = position
            if video["kind"] == "twitch-vod" and time.time() - video["pushed"] >= TWITCH_PUSH:
                try:
                    twitch_save_position(video["ident"], position)
                    now_playing["pushed"] = time.time()
                except (OSError, ValueError, KeyError):
                    pass
        elif not playing:   # vidéo terminée ou remplacée : dernière position envoyée à Twitch
            if video["kind"] == "twitch-vod" and video.get("position"):
                try:
                    twitch_save_position(video["ident"], video["position"])
                except (OSError, ValueError, KeyError):
                    pass
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
    elif name == "play":
        play(find_url(str(body.get("url", ""))), bool(body.get("from_start")))
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
    elif name == "qr":
        # Affichage du QR code de la télécommande sur la TV
        if body.get("mode") not in ("always", "timed", "never"):
            raise ValueError("mode inconnu")
        mpv(["script-message", "streambox-qr", body["mode"]])
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
    elif name == "follows_app":
        set_twitch_app(str(body.get("client_id", "")), str(body.get("client_secret", "")))
    elif name == "follows_login":
        follows_start()
    elif name == "follows_logout":
        follows_logout()
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
            elif self.path == "/api/events":
                try:
                    self.send(200, events_for_page())
                except (OSError, ValueError, KeyError) as e:
                    self.send(503, {"error": f"Twitch injoignable : {e}"})
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
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
