"""Inlet: Jellyfin library for the companion app and the TV menu (server paired with jellyfin-mpv-shim), playback
of its videos and progress reports to the server. Standard library only.
"""
import json, os, re, shutil, socket, subprocess, threading, time, urllib.parse, urllib.request

import history   # history.py: the box's history and the video being played
from common import mpv, tool
from i18n import tr

# Jellyfin: library of the server already paired with jellyfin-mpv-shim ("Play on…"), with its credentials
# (~/.config/jellyfin-mpv-shim/users.json: address, UserId, AccessToken; nothing more to configure). The box reads
# "Continue watching", "Next up", recent additions per library, searches, and reports progress to the
# server during playback (Sessions/Playing, /Progress, /Stopped): "watched" and resume follow everywhere.

JF_USERS = os.path.expanduser("~/.config/jellyfin-mpv-shim/users.json")
SHIM = tool("jellyfin-mpv-shim")
SHIM_LOG = "/tmp/jellyfin-shim.log"
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
        raise ValueError(tr("Jellyfin is not paired with the box."))
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
    """Jellyfin item → card: title, info line, landscape image, duration, position, watched"""
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
    elif kind == "Season":   # recent additions of a series, grouped by season
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


def jellyfin_more(library_id, offset, count=16):
    """"Load more" in a library's row: the next items added, newest first (Items/Latest has no paging: the same order
    from the items list)"""
    if not re.fullmatch(r"[0-9a-f]{32}", library_id or ""):
        raise ValueError(tr("unknown library"))
    items = jf_api("/Users/{user}/Items", params={
        "ParentId": library_id, "Recursive": "true", "IncludeItemTypes": "Movie,Series,Video",
        "SortBy": "DateCreated", "SortOrder": "Descending", "StartIndex": offset, "Limit": count, **JF_FIELDS})["Items"]
    return {"items": [jf_item(i) for i in items], "more": len(items) >= count}


def jellyfin_more_home(kind, offset, count=16):
    """"Load more" in Resume (kind "resume") or Next episodes ("nextup")"""
    srv = jf_server()
    if kind == "resume":
        items = jf_api("/Users/{user}/Items/Resume", params={"StartIndex": offset, "Limit": count,
                                                             "MediaTypes": "Video", **JF_FIELDS})["Items"]
    else:
        items = jf_api("/Shows/NextUp", params={"UserId": srv["user"] if srv else "", "StartIndex": offset,
                                                "Limit": count, **JF_FIELDS})["Items"]
    return {"items": [jf_item(i) for i in items], "more": len(items) >= count}


def jellyfin_search_more(query, offset, count=30):
    """"Load more" in the search results"""
    query = " ".join(query.split())[:100]
    if not query:
        return {"items": [], "more": False}
    items = jf_api("/Users/{user}/Items", params={"searchTerm": query, "IncludeItemTypes": "Movie,Series,Episode",
                                                  "Recursive": "true", "StartIndex": offset, "Limit": count,
                                                  **JF_FIELDS})["Items"]
    return {"items": [jf_item(i) for i in items], "more": len(items) >= count}


def jellyfin_search(query):
    query = " ".join(query.split())[:100]
    if not query:
        return []
    items = jf_api("/Users/{user}/Items", params={"searchTerm": query, "IncludeItemTypes": "Movie,Series,Episode",
                                                  "Recursive": "true", "Limit": 30, **JF_FIELDS})["Items"]
    return [jf_item(i) for i in items]


def jellyfin_series(series_id):
    """Episodes of a series, and the index of the first one not yet watched (where to put the focus)"""
    if not re.fullmatch(r"[0-9a-f]{32}", series_id):
        raise ValueError(tr("invalid series"))
    srv = jf_server()
    eps = [jf_item(i) for i in jf_api(f"/Shows/{series_id}/Episodes", params={"UserId": srv["user"], **JF_FIELDS})["Items"]]
    first = next((n for n, e in enumerate(eps) if not e["finished"]), 0)
    return {"id": series_id, "episodes": eps, "first": first}


def jellyfin_play(item_id, from_start=False):
    if not re.fullmatch(r"[0-9a-f]{32}", item_id):
        raise ValueError(tr("invalid item"))
    srv = jf_server()
    raw = jf_api(f"/Users/{{user}}/Items/{item_id}")
    i = jf_item(raw)
    if i["type"] == "Series":
        raise ValueError(tr("Pick an episode."))
    title = f"{i['title']} · {i['episode']}" if i.get("episode") else i["title"]
    start = 0 if from_start or i["position"] < history.RESUME_MIN or i["finished"] else i["position"]
    url = f"{srv['address']}/Videos/{item_id}/stream?static=true&api_key={srv['token']}"
    history.now_playing.clear()
    history.now_playing.update(key=f"jellyfin:{item_id}", url=url, link=f"jellyfin:{item_id}", kind="jellyfin",
                               ident=item_id, title=title, thumb=i["thumb"], position=start)
    mpv(["script-message", "streambox-play", url, str(start), title, i["thumb"] or ""])
    mpv(["set_property", "user-data/streambox/storyboard", {}])
    # Seek bar and pause screen: series, episode, year, overview; next episode for the end card
    mpv(["set_property", "user-data/streambox/meta",
         {"source": "jellyfin", "series": raw.get("SeriesName") or "", "episode": i.get("episode") or "",
          "year": raw.get("ProductionYear") or "", "rating": raw.get("CommunityRating") or 0,
          "overview": (raw.get("Overview") or "")[:3000], "thumb": i.get("thumb") or ""}])
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
    history.record(dict(history.now_playing), start, i["seconds"])
    jf_report("", item_id, start)
    # Separate subtitles (.srt… files next to the video): missing from the direct stream, added to mpv once the video
    # is open; those embedded in the file are already there
    source = (raw.get("MediaSources") or [{}])[0]
    external = [m for m in source.get("MediaStreams") or [] if m.get("Type") == "Subtitle" and m.get("IsExternal")]
    if external:
        threading.Thread(target=jf_add_subtitles, args=(url, item_id, source["Id"], external, srv), daemon=True).start()


def jf_add_subtitles(url, item_id, source_id, streams, srv):
    for _ in range(30):   # up to 15 s for the video to open
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
    """Progress to the server: what = "" (start), "/Progress" or "/Stopped" """
    try:
        jf_api(f"/Sessions/Playing{what}", {"ItemId": item_id, "PositionTicks": int(position * 1e7), "IsPaused": paused,
                                            "CanSeek": True, "PlayMethod": "DirectStream"})
    except (OSError, ValueError):
        pass
    if what == "/Stopped":
        jf_cache.pop("home", None)


# Connection to a server by Quick Connect, from the TV or the companion app. The box looks for servers on the local
# network (Jellyfin answers "who is JellyfinServer?" on UDP 7359; a server in Docker without the host network does not:
# then its address is given in the companion app). jellyfin-mpv-shim then signs in itself (--quick-connect: it prints a
# 6-digit code to approve in Jellyfin, user menu → Quick Connect, and writes its users.json, a format it owns), and
# stays running as the box's player. Its previous users.json is put back if that fails or is cancelled.

QC_WAIT = 300   # seconds before giving up on the code
qc = {}         # sign-in in progress: server, name, code, error, proc, backup, started
qc_lock = threading.Lock()


def discover(timeout=1.5):
    """Jellyfin servers that answer on the local network: [{address, name}]"""
    found = {}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(0.3)
            s.sendto(b"who is JellyfinServer?", ("255.255.255.255", 7359))
            end = time.time() + timeout
            while time.time() < end:
                try:
                    data, (ip, _) = s.recvfrom(4096)
                    d = json.loads(data)
                except (socket.timeout, ValueError):
                    continue
                # the address it gives can be internal (Docker): the one it answered from, with its scheme and port
                announced = urllib.parse.urlsplit(d.get("Address") or "")
                address = f"{announced.scheme or 'http'}://{ip}:{announced.port or 8096}"
                found[d.get("Id") or address] = {"address": address, "name": d.get("Name") or address}
    except OSError:
        pass
    return list(found.values())


def server_info(address):
    """Public information of a server (name, Quick Connect), or ValueError"""
    try:
        with urllib.request.urlopen(address.rstrip("/") + "/System/Info/Public", timeout=5) as r:
            return json.load(r)
    except (OSError, ValueError) as e:
        raise ValueError(tr("Jellyfin unreachable: {error}", error=e))


def restart_shim():
    """The usual shim (as player.sh starts it), after a sign-in"""
    subprocess.run(["pkill", "-u", str(os.getuid()), "-f", "[j]ellyfin-mpv-shim"], capture_output=True)
    with open(SHIM_LOG, "a") as log:
        subprocess.Popen([SHIM, "--no-gui"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)


def qc_start(address):
    address = (address or "").strip().rstrip("/")
    if not re.match(r"https?://", address):
        address = "http://" + address
    if not urllib.parse.urlsplit(address).port and urllib.parse.urlsplit(address).scheme == "http":
        address += ":8096"
    info = server_info(address)
    qc_cancel()
    backup = JF_USERS + ".before-quick-connect"
    if os.path.exists(JF_USERS):
        shutil.copy2(JF_USERS, backup)
    subprocess.run(["pkill", "-u", str(os.getuid()), "-f", "[j]ellyfin-mpv-shim"], capture_output=True)
    # "clear": this server replaces the previous one (put back if the sign-in fails)
    proc = subprocess.Popen([SHIM, "--no-gui", "--server", address, "--quick-connect", "clear"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    with qc_lock:
        qc.clear()
        qc.update(server=address, name=info.get("ServerName") or address, proc=proc, started=time.time(),
                  backup=backup if os.path.exists(backup) else None)
    threading.Thread(target=qc_follow, args=(proc,), daemon=True).start()


def qc_follow(proc):
    """Reads the shim's output: its code, then whether it signed in; the output then goes on to its log"""
    with open(SHIM_LOG, "a") as log:
        for line in proc.stdout:
            log.write(line)
            log.flush()
            m = re.fullmatch(r"\s*(\d{6})\s*", line)
            with qc_lock:
                if qc.get("proc") is not proc:
                    continue
                if m and not qc.get("code"):
                    qc["code"] = m.group(1)
                srv = jf_server()
                if qc.get("code") and srv and srv["address"].rstrip("/") == qc["server"] and not qc.get("done"):
                    qc["done"] = True   # signed in: the shim carries on as the player
                    jf_cache.clear()
    with qc_lock:
        if qc.get("proc") is proc and not qc.get("done") and not qc.get("cancelled"):
            qc["error"] = tr("Quick Connect refused or expired")
    qc_restore(proc)


def qc_restore(proc):
    """Sign-in that did not go through: the previous connection and the usual shim come back"""
    with qc_lock:
        if qc.get("proc") is not proc or qc.get("done"):
            return
        backup = qc.pop("backup", None)
    if backup and os.path.exists(backup):
        shutil.copy2(backup, JF_USERS)
    restart_shim()
    with qc_lock:
        if qc.get("proc") is proc and qc.get("cancelled"):
            qc.clear()   # given up on purpose: nothing left to show


def qc_cancel():
    with qc_lock:
        proc = qc.get("proc")
        done = qc.get("done")
        if proc and not done:
            qc["cancelled"] = True
    if proc and not done and proc.poll() is None:
        proc.terminate()   # qc_follow then puts the previous connection back
        try:
            proc.wait(3)
        except subprocess.TimeoutExpired:   # the shim waiting for its code does not always stop on TERM
            proc.kill()
            proc.wait(3)


def forget():
    """Disconnects the box from its server: the shim has no account any more (it stops)"""
    qc_cancel()
    if os.path.exists(JF_USERS):
        os.remove(JF_USERS)
    jf_cache.clear()
    subprocess.run(["pkill", "-u", str(os.getuid()), "-f", "[j]ellyfin-mpv-shim"], capture_output=True)


def link_action(body):
    """POST /api/jellyfin_link: {address} signs in by Quick Connect, {action: cancel | forget}"""
    if body.get("action") == "cancel":
        qc_cancel()
    elif body.get("action") == "forget":
        forget()
    else:
        qc_start(str(body.get("address", "")))


def link_state(find=False):
    """Connected server, servers found on the network (find), sign-in in progress"""
    with qc_lock:
        expired = qc and qc.get("proc") and not qc.get("done") and time.time() - qc["started"] > QC_WAIT
        pending = {k: qc.get(k) for k in ("server", "name", "code", "error")} if qc and not qc.get("done") else None
    if expired:
        qc_cancel()
    srv = jf_server()
    out = {"configured": bool(srv), "address": srv["address"] if srv else "", "name": srv["name"] if srv else "",
           "pending": pending}
    if find:
        out["servers"] = discover()
    return out

