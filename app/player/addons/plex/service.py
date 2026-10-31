"""Inlet: Plex library for the companion app and the TV menu, playback of its videos (direct play) and progress
reports to the server. Standard library only.
"""
import json, os, re, threading, time, urllib.error, urllib.parse, urllib.request, uuid

import history   # history.py: the box's history and the video being played
from common import COOKIES_DIR, mpv, read_json_file, write_private_json
from i18n import tr

# Plex: a server of the local network (~/.config/stream-box/plex.json: address, token, name), chosen in two ways: signing
# in with a Plex account by code (below: the account's servers, the first one the box reaches), or its address given in
# the companion app. Without a token, the server must let the box in without signing in (Plex setting "List of IP
# addresses and networks that are allowed without auth"). The box reads On Deck (resume and next episodes), the recent additions of
# each library, searches, the episodes of a series, plays the file as is (no transcoding) and reports the position
# (/:/progress) and the end (/:/scrobble): "watched" and resume follow on the other Plex apps.

PLEX_FILE = os.path.join(COOKIES_DIR, "plex.json")
PX_CACHE = 30
px_cache = {}


def px_config():
    c = read_json_file(PLEX_FILE)
    return c if isinstance(c, dict) and c.get("address") else None


def px_client():
    """Identifier of the box for Plex (X-Plex-Client-Identifier), created once"""
    c = read_json_file(PLEX_FILE) or {}
    if not c.get("client"):
        c["client"] = str(uuid.uuid4())
        write_private_json(PLEX_FILE, c)
    return c["client"]


def set_plex(address, token="", account=""):
    """Server chosen in the companion app: checked (/identity, then the libraries with the token) before being kept"""
    address = (address or "").strip().rstrip("/")
    if not address:   # forget the server
        c = read_json_file(PLEX_FILE) or {}
        write_private_json(PLEX_FILE, {"client": c["client"]} if c.get("client") else {})
        px_cache.clear()
        return {"configured": False}
    if not re.match(r"https?://", address):
        address = "http://" + address
    if not urllib.parse.urlsplit(address).port and urllib.parse.urlsplit(address).scheme == "http":
        address += ":32400"
    try:
        name = px_request(address, (token or "").strip(), "/")["MediaContainer"].get("friendlyName") or "Plex"
        px_request(address, (token or "").strip(), "/library/sections")
    except urllib.error.HTTPError as e:
        raise ValueError(tr("Plex refuses the box ({code}): give a token, or allow the network in Plex's settings",
                            code=e.code))
    except (OSError, ValueError, KeyError) as e:
        raise ValueError(tr("Plex unreachable: {error}", error=e))
    c = read_json_file(PLEX_FILE) or {}
    c.update(address=address, token=(token or "").strip(), name=name, account=account)
    write_private_json(PLEX_FILE, c)
    px_cache.clear()
    return {"configured": True, "name": name}


# Sign-in with a Plex account by code: the box asks plex.tv for a 4-character code, shown on the TV and in the companion
# app, to type on plex.tv/link; a thread waits for it (every 3 s), then reads the account's servers (plex.tv resources)
# and keeps the first one the box reaches: its own servers first, local addresses first (plain http to the LAN
# address, then the plex.direct https one), with the server's access token.

PLEX_TV = "https://plex.tv/api/v2"
LINK_URL = "https://plex.tv/link"
link_pending = {}   # code, url, expires_at, error
link_lock = threading.Lock()


def plex_tv(method, path, params=None, token=None):
    headers = {"Accept": "application/json", "X-Plex-Product": "Inlet", "X-Plex-Client-Identifier": px_client(),
               "X-Plex-Device-Name": "Inlet"}
    if token:
        headers["X-Plex-Token"] = token
    query = urllib.parse.urlencode(params or {})
    data = query.encode() if method == "POST" else None
    url = PLEX_TV + path + ("?" + query if query and method != "POST" else "")
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=15) as r:
        return json.loads(r.read() or b"{}")


def link_start():
    try:
        d = plex_tv("POST", "/pins", {"strong": "false"})
    except (OSError, ValueError) as e:
        raise ValueError(tr("plex.tv unreachable: {error}", error=e))
    expires_at = time.time() + int(d.get("expiresIn") or 900)
    with link_lock:
        link_pending.clear()
        link_pending.update(code=d["code"], url=LINK_URL, expires_at=expires_at)
    threading.Thread(target=link_wait, args=(d["id"], expires_at), daemon=True).start()


def link_wait(pin_id, expires_at):
    while time.time() < expires_at:
        time.sleep(3)
        with link_lock:
            if not link_pending:   # cancelled, or another code asked for since
                return
        try:
            token = plex_tv("GET", f"/pins/{pin_id}").get("authToken")
        except (OSError, ValueError):
            continue
        if not token:
            continue
        try:
            link_servers(token)
            with link_lock:
                link_pending.clear()
        except ValueError as e:
            with link_lock:
                link_pending.update(error=str(e))
        return
    with link_lock:
        link_pending.update(error=tr("code expired"))


def link_servers(token):
    """Keeps the first server of the account the box reaches"""
    try:
        resources = plex_tv("GET", "/resources", {"includeHttps": 1, "includeRelay": 0}, token)
        user = plex_tv("GET", "/user", token=token)
    except (OSError, ValueError) as e:
        raise ValueError(tr("plex.tv unreachable: {error}", error=e))
    servers = sorted((r for r in resources if "server" in (r.get("provides") or "")), key=lambda r: not r.get("owned"))
    for r in servers:
        for c in sorted(r.get("connections") or [], key=lambda c: not c.get("local")):
            addresses = [f"http://{c['address']}:{c['port']}"] if c.get("local") and c.get("address") else []
            for address in addresses + ([c["uri"]] if c.get("uri") else []):
                try:
                    set_plex(address, r.get("accessToken") or token, user.get("username") or user.get("title") or "")
                    return
                except ValueError:
                    continue
    raise ValueError(tr("No Plex server of this account answers the box") if servers
                     else tr("This Plex account has no server"))


def link_state():
    with link_lock:
        if link_pending and link_pending.get("expires_at", 0) > time.time() - 60:
            pending = {k: link_pending.get(k) for k in ("code", "url", "error")}
        else:
            pending = None
    c = px_config() or {}
    return {"configured": bool(c), "name": c.get("name") or "", "account": c.get("account") or "", "pending": pending}


def link_cancel():
    with link_lock:
        link_pending.clear()


def px_request(address, token, path, params=None):
    params = dict(params or {})
    if token:
        params["X-Plex-Token"] = token
    url = address + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "X-Plex-Product": "Inlet",
                                               "X-Plex-Client-Identifier": px_client(),
                                               "X-Plex-Device-Name": "Inlet"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = r.read()
    return json.loads(data) if data.strip() else {}


def px_api(path, params=None):
    c = px_config()
    if not c:
        raise ValueError(tr("Plex is not connected to the box."))
    return px_request(c["address"], c.get("token") or "", path, params)


def px_url(path, **params):
    """Link to the server, with the token (images, video files)"""
    c = px_config() or {"address": ""}
    if c.get("token"):
        params["X-Plex-Token"] = c["token"]
    return c["address"] + path + ("?" + urllib.parse.urlencode(params) if params else "")


def px_image(path):
    return px_url("/photo/:/transcode", width=480, height=270, minSize=1, upscale=1, url=path) if path else ""


TYPES = {"movie": "Movie", "episode": "Episode", "show": "Series", "season": "Season"}


def px_item(m):
    """Plex item → card (same fields as Jellyfin's: the TV menu shows both the same way)"""
    kind = TYPES.get(m.get("type"), m.get("type"))
    # landscape picture: still of the episode, otherwise the background (art) of the movie or the series
    thumb = m.get("thumb") if kind == "Episode" else m.get("art") or m.get("grandparentArt") or m.get("thumb")
    out = {"id": m.get("ratingKey"), "type": kind, "title": m.get("title") or "", "thumb": px_image(thumb),
           "seconds": int((m.get("duration") or 0) / 1000) or None, "position": int((m.get("viewOffset") or 0) / 1000),
           "finished": bool(m.get("viewCount")) and not m.get("viewOffset"), "year": m.get("year")}
    if kind == "Episode":
        out["title"] = m.get("grandparentTitle") or out["title"]
        out["episode"] = (f"S{m.get('parentIndex') or 0}·E{m.get('index')} · " if m.get("index") else "") + (m.get("title") or "")
        out["series"] = m.get("grandparentRatingKey")
    elif kind == "Season":
        out.update(title=m.get("parentTitle") or out["title"], episode=m.get("title") or "", series=m.get("parentRatingKey"))
    elif kind == "Series":
        leaves, viewed = m.get("leafCount") or 0, m.get("viewedLeafCount") or 0
        out.update(series=m.get("ratingKey"), unplayed=max(0, leaves - viewed), finished=bool(leaves) and viewed >= leaves)
    return out


def px_list(path, params=None):
    return [px_item(m) for m in px_api(path, params).get("MediaContainer", {}).get("Metadata") or []]


def plex_more(section, offset, count=16):
    """"Load more" in a library's row: the next recently added items"""
    if not str(section).isdigit():
        raise ValueError(tr("unknown library"))
    items = px_list(f"/library/sections/{section}/recentlyAdded",
                    {"X-Plex-Container-Start": offset, "X-Plex-Container-Size": count})
    return {"items": items, "more": len(items) >= count}


def plex_home():
    cached = px_cache.get("home")
    if cached and time.time() - cached[0] < PX_CACHE:
        return cached[1]
    c = px_config()
    if not c:
        return {"configured": False}
    deck = px_list("/library/onDeck")
    libraries = []
    for d in px_api("/library/sections").get("MediaContainer", {}).get("Directory") or []:
        if d.get("type") not in ("movie", "show"):
            continue
        items = px_list(f"/library/sections/{d['key']}/recentlyAdded",
                        {"X-Plex-Container-Start": 0, "X-Plex-Container-Size": 16})
        libraries.append({"id": d["key"], "name": d.get("title") or "", "items": items})
    home = {"configured": True, "server": c.get("name") or "Plex", "resume": [i for i in deck if i["position"]],
            "nextup": [i for i in deck if not i["position"]], "libraries": libraries}
    px_cache["home"] = (time.time(), home)
    return home


def plex_more_home(kind, offset, count=16):
    """"Load more" in Resume (kind "resume") or Next episodes ("nextup"): both come from On Deck, read whole"""
    deck = px_list("/library/onDeck", {"X-Plex-Container-Start": 0, "X-Plex-Container-Size": 200})
    items = [i for i in deck if bool(i["position"]) == (kind == "resume")]
    return {"items": items[offset:offset + count], "more": len(items) > offset + count}


def plex_search_more(query, offset, count=30):
    """"Load more" in the search results (Plex's search has no paging: a larger limit, the start cut off)"""
    items = plex_search(query, offset + count)
    return {"items": items[offset:], "more": len(items) >= offset + count}


def plex_search(query, limit=30):
    query = " ".join(query.split())[:100]
    if not query:
        return []
    hubs = px_api("/hubs/search", {"query": query, "limit": limit}).get("MediaContainer", {}).get("Hub") or []
    return [px_item(m) for h in hubs if h.get("type") in ("movie", "show", "episode") for m in h.get("Metadata") or []]


def plex_series(series_id):
    """Episodes of a series, and the index of the first one not yet watched (where to put the focus)"""
    if not re.fullmatch(r"\d{1,10}", series_id):
        raise ValueError(tr("invalid series"))
    eps = px_list(f"/library/metadata/{series_id}/allLeaves")
    first = next((n for n, e in enumerate(eps) if not e["finished"]), 0)
    return {"id": series_id, "episodes": eps, "first": first}


def plex_play(item_id, from_start=False):
    if not re.fullmatch(r"\d{1,10}", item_id):
        raise ValueError(tr("invalid item"))
    raw = px_api(f"/library/metadata/{item_id}")["MediaContainer"]["Metadata"][0]
    i = px_item(raw)
    if i["type"] in ("Series", "Season"):
        raise ValueError(tr("Pick an episode."))
    part = raw["Media"][0]["Part"][0]
    title = f"{i['title']} · {i['episode']}" if i.get("episode") else i["title"]
    start = 0 if from_start or i["position"] < history.RESUME_MIN or i["finished"] else i["position"]
    url = px_url(part["key"])
    history.now_playing.clear()
    history.now_playing.update(key=f"plex:{item_id}", url=url, link=f"plex:{item_id}", kind="plex", ident=item_id,
                               title=title, thumb=i["thumb"], position=start)
    mpv(["script-message", "streambox-play", url, str(start), title, i["thumb"] or ""])
    mpv(["set_property", "user-data/streambox/storyboard", {}])
    # Seek bar and pause screen: series, episode, year, overview; next episode for the end card
    mpv(["set_property", "user-data/streambox/meta",
         {"source": "plex", "series": raw.get("grandparentTitle") or "", "episode": i.get("episode") or "",
          "year": raw.get("year") or "", "rating": raw.get("audienceRating") or raw.get("rating") or 0,
          "overview": (raw.get("summary") or "")[:3000], "thumb": i.get("thumb") or ""}])
    nxt = {}
    if i["type"] == "Episode" and i.get("series"):
        try:
            eps = px_list(f"/library/metadata/{i['series']}/allLeaves")
            ids = [e["id"] for e in eps]
            if item_id in ids and ids.index(item_id) + 1 < len(eps):
                n = eps[ids.index(item_id) + 1]
                nxt = {"id": n["id"], "of": item_id, "title": n["title"], "episode": n.get("episode") or "",
                       "thumb": n["thumb"], "service": "plex", "path": url}
        except (OSError, ValueError, KeyError):
            pass
    mpv(["set_property", "user-data/streambox/next_up", nxt])
    px_cache.pop("home", None)
    history.record(dict(history.now_playing), start, i["seconds"])
    px_report(item_id, start, i["seconds"], "playing")


def px_report(item_id, position, duration, state, paused=False):
    """Position to the server (state: playing, paused or stopped); at the end of the video, watched"""
    try:
        px_api("/:/timeline", {"ratingKey": item_id, "key": f"/library/metadata/{item_id}",
                               "state": "paused" if paused and state == "playing" else state,
                               "time": int(position * 1000), "duration": int((duration or 0) * 1000)})
        px_api("/:/progress", {"key": item_id, "identifier": "com.plexapp.plugins.library",
                               "time": int(position * 1000), "state": state})
        if state == "stopped" and history.finished(position, duration):
            px_api("/:/scrobble", {"key": item_id, "identifier": "com.plexapp.plugins.library"})
    except (OSError, ValueError):
        pass
    if state == "stopped":
        px_cache.pop("home", None)
