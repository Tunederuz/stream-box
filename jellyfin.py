"""Stream Box: Jellyfin library for the companion app and the TV menu (server paired with jellyfin-mpv-shim), playback
of its videos and progress reports to the server. Standard library only.
"""
import json, os, re, threading, time, urllib.parse, urllib.request

import history   # history.py: the box's history and the video being played
from common import mpv
from i18n import tr

# Jellyfin: library of the server already paired with jellyfin-mpv-shim ("Play on…"), with its credentials
# (~/.config/jellyfin-mpv-shim/users.json: address, UserId, AccessToken; nothing more to configure). The box reads
# "Continue watching", "Next up", recent additions per library, searches, and reports progress to the
# server during playback (Sessions/Playing, /Progress, /Stopped): "watched" and resume follow everywhere.

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
