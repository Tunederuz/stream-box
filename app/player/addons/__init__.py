"""Inlet: addons, the box's integrations, one folder each (addons/<id>/, whose __init__.py declares ADDON). What an
addon brings, all optional: GET routes (path → Route), POST actions (/api/<name>), "Load more" sources of the TV menu,
the links it plays ("<id>:<item>", from the history), what happens around the videos of its kinds (before and once
started, progress), a video started outside the box (Jellyfin's "Play on…"), keys of /api/state and /api/features, background loops, its home
for the quick menu (mpv alone). Twitch is the base (always there, its live streams played by stream-box.lua itself):
the core's modules may use its service directly; YouTube, Jellyfin, Plex and the PC link.
Standard library only.
"""
import importlib, os


class Route:
    """A GET route: fn(query) → JSON (query: the first value of each parameter), or, with content_type, text or bytes
    (None: 404). Its errors (OSError, ValueError, KeyError) answer 400 with their message, or 503 with
    unreachable(error)"""
    def __init__(self, fn, unreachable=None, content_type=None):
        self.fn, self.unreachable, self.content_type = fn, unreachable, content_type


class Addon:
    """id: its folder and the prefix of its routes, actions, sources and links; order: its place in the lists (TV
    menu, quick menu); configured(): whether it can be used (a server chosen…); kinds: the history kinds of its videos
    (history.media_key; its id by default).
    Videos played from a link (playback.play): prepare(video, entry, from_start, at) → (position, duration) before
    (entry: its history entry, {} when new: position, duration, updated), it may fill video's title and thumb;
    started(video) once mpv has it; progress(video, position, final) every progress_every seconds while it plays, and
    once at the end (final).
    Videos it plays itself (its links): report(video, position, duration, paused, stopped) instead, the history kept by
    playback's loop. outside_video() returns the video being played when it was started outside the box, None
    otherwise; state() adds keys to /api/state, features() to /api/features (what this installation has: the TV menu
    and the companion app hide the rest); home() its lists, for the quick menu; library: the (home, series, play) of a
    media library, for the quick menu; start() at the server's start, loops: functions run each in its thread.
    rows: its TV menu tab (GET /api/rows, addons/cards.py): {"tab": fn() → {rows, …}, "search": fn(q) → {rows},
    "open": fn(target, name) → {rows: [the opened row]}, "more": fn(source, key, q, offset) → {items, more}}"""
    def __init__(self, id, name, order=50, configured=lambda: True, kinds=None, routes=None, actions=None, more=None,
                 links=None, prepare=None, started=None, progress=None, progress_every=30, report=None,
                 outside_video=None, state=None, features=None, home=None, library=None, start=None, loops=(),
                 rows=None):
        self.id, self.name, self.order, self.configured, self.kinds = id, name, order, configured, kinds or (id,)
        self.routes, self.actions, self.more, self.links = routes or {}, actions or {}, more or {}, links or {}
        self.prepare, self.started, self.progress, self.progress_every = prepare, started, progress, progress_every
        self.report, self.outside_video, self.state, self.home, self.library = report, outside_video, state, home, library
        self.features, self.start, self.loops, self.rows = features, start, loops, rows


def library(id, home, search, series, play, more_lib, more_home, more_search, unreachable):
    """Routes, actions, "Load more" sources, link and TV menu rows of a media library (Jellyfin, Plex: the same cards):
    GET /api/<id>, /api/<id>_search?q=, /api/<id>_series?id=; POST /api/<id>_play {id, from_start}; sources <id>_lib,
    <id>_resume, <id>_nextup, <id>_search; links <id>:<item>"""
    from addons import cards as R
    from i18n import tr

    def lib_card(it, in_series=None):
        """A movie or episode plays (Resume / From the beginning), a series or season opens its episodes; ≡ on an
        episode: all the episodes of its series (not in that series' opened row)"""
        if it.get("type") == "Series":
            meta = [tr("{n} unwatched", n=it["unplayed"]) if it.get("unplayed") else tr("Series"), it.get("year")]
        elif it.get("episode"):
            meta = [it["episode"]]
        else:
            meta = [it.get("year"), R.hm(it["seconds"]) if it.get("seconds") else ""]
        name = f"{it['title']} · {it['episode']}" if it.get("episode") else it.get("title")
        if it.get("type") in ("Series", "Season"):
            return R.card(it["id"], it.get("title"), R.line(*meta), it.get("thumb"), progress=R.progress(it),
                          open={"target": "series:" + str(it.get("series") or it["id"]), "name": it.get("title")})
        options = [{"label": tr("☰  All episodes"), "open": {"target": "series:" + str(it["series"]), "name": it.get("title")}}] \
            if it.get("type") == "Episode" and it.get("series") and str(it["series"]) != str(in_series) else []
        return R.card(it["id"], it.get("title"), R.line(*meta, finished=it.get("finished")), it.get("thumb"),
                      progress=R.progress(it), play={"action": f"{id}_play", "id": it["id"]}, label=name,
                      position=it.get("position"), seconds=it.get("seconds"), finished=it.get("finished") or None,
                      options=options)

    def tab_rows():
        try:
            d = home()
        except (OSError, ValueError, KeyError):
            return {"configured": True, "error": True, "rows": []}
        if not d.get("configured"):
            return {"configured": False, "rows": []}
        rows = []
        if d.get("resume"):
            rows.append(R.row("resume", tr("Resume"), [lib_card(i) for i in d["resume"]],
                              more={"source": f"{id}_resume", "key": ""}))
        if d.get("nextup"):
            rows.append(R.row("nextup", tr("Next episodes"), [lib_card(i) for i in d["nextup"]],
                              more={"source": f"{id}_nextup", "key": ""}))
        for lib in d.get("libraries") or []:
            rows.append(R.row("lib:" + str(lib["id"]), tr("{name} · recently added", name=lib["name"]),
                              [lib_card(i) for i in lib.get("items") or []], more={"source": f"{id}_lib", "key": str(lib["id"])}))
        return {"configured": True, "server": d.get("server") or "", "rows": rows}

    def search_rows(q):
        return {"rows": [R.row("search", tr("Results for \"{query}\"", query=q), [lib_card(i) for i in search(q)],
                               more={"source": f"{id}_search", "key": "", "q": q})]}

    def open_row(target, name):
        kind, _, series_id = target.partition(":")
        if kind != "series":
            raise ValueError(tr("not found"))
        d = series(series_id)
        return {"rows": [R.row("preview", tr("{name} · episodes", name=name),
                               [lib_card(i, series_id) for i in d.get("episodes") or []], sel=d.get("first") or 0)]}

    sources = {f"{id}_lib": lambda key, offset, q: more_lib(key, offset),
               f"{id}_resume": lambda key, offset, q: more_home("resume", offset),
               f"{id}_nextup": lambda key, offset, q: more_home("nextup", offset),
               f"{id}_search": lambda key, offset, q: more_search(q, offset)}

    def more_cards(source, key, q, offset):
        d = sources[source](key, offset, q)
        return {"items": [lib_card(i) for i in d.get("items") or []], "more": d.get("more")}

    return {
        "routes": {f"/api/{id}": Route(lambda q: home(), unreachable),
                   f"/api/{id}_search": Route(lambda q: {"query": q.get("q", ""), "results": search(q.get("q", ""))}),
                   f"/api/{id}_series": Route(lambda q: series(q.get("id", "")))},
        "actions": {f"{id}_play": lambda body: play(str(body.get("id", "")), bool(body.get("from_start")))},
        "more": sources,
        "links": {id: play},
        "home": home,
        "library": (home, series, play),
        "rows": {"tab": tab_rows, "search": search_rows, "open": open_row, "more": more_cards},
    }


ADDONS = []   # in their order


def load():
    here = os.path.dirname(os.path.abspath(__file__))
    for name in sorted(os.listdir(here)):
        if os.path.isfile(os.path.join(here, name, "__init__.py")):
            ADDONS.append(importlib.import_module(f"addons.{name}").ADDON)
    ADDONS.sort(key=lambda a: a.order)


def get(addon_id):
    return next((a for a in ADDONS if a.id == addon_id), None)


def route(path):
    """(addon, Route) of a GET path (without its parameters), or None; the registry's own (/api/rows): no addon"""
    if path in CORE_ROUTES:
        return None, CORE_ROUTES[path]
    return next(((a, a.routes[path]) for a in ADDONS if path in a.routes), None)


def actions():
    return {name: fn for a in ADDONS for name, fn in a.actions.items()}


def more_source(source):
    return next((a.more[source] for a in ADDONS if source in a.more), None)


def play_link(url, from_start=False):
    """Plays a link "<id>:<item>" of an addon (from the history); False when no addon has it"""
    prefix, _, item = (url or "").partition(":")
    a = next((a for a in ADDONS if prefix in a.links), None)
    if not a:
        return False
    a.links[prefix](item, from_start)
    return True


def for_kind(kind):
    """The addon whose videos are of this history kind (youtube, jellyfin…), or None"""
    return next((a for a in ADDONS if kind in a.kinds), None)


def outside_video():
    for a in ADDONS:
        if a.outside_video:
            video = a.outside_video()
            if video:
                return video
    return None


def rows(query):
    """GET /api/rows?addon=<id>: its tab's rows; &q=: a search's; &open=<target>&name=: the row of something opened (a
    channel, a series); &more=<source>&key=&q=&offset=: the next cards of a row"""
    a = get(query.get("addon", ""))
    if not a or not a.rows:
        raise ValueError("unknown addon")
    if query.get("more"):
        offset = int(query.get("offset") or 0)
        if not 0 <= offset <= 500 or query["more"] not in a.more:
            raise ValueError("not found")
        return a.rows["more"](query["more"], query.get("key", ""), query.get("q", ""), offset)
    if query.get("open"):
        return a.rows["open"](query["open"], query.get("name", ""))
    if query.get("q", "").strip():
        return a.rows["search"](" ".join(query["q"].split())[:100])
    return a.rows["tab"]()


CORE_ROUTES = {"/api/rows": Route(rows)}


def state():
    out = {}
    for a in ADDONS:
        if a.state:
            out.update(a.state())
    return out


def features():
    out = {}
    for a in ADDONS:
        if a.features:
            out.update(a.features())
    return out


load()
