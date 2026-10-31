"""Inlet: addons, the box's integrations, one folder each (addons/<id>/, whose __init__.py declares ADDON). What an
addon brings, all optional: GET routes (path → Route), POST actions (/api/<name>), "Load more" sources of the TV menu,
the links it plays ("<id>:<item>", from the history), what happens around the videos of its kinds (before and once
started, progress), a video started outside the box (Jellyfin's "Play on…"), keys of /api/state, its home for the
quick menu (mpv alone). Jellyfin, Plex and YouTube so far; Twitch (the base, always there) and the PC link to follow.
Standard library only.
"""
import importlib, os


class Route:
    """A GET route: fn(query) → JSON (query: the first value of each parameter), or text of content_type when given.
    Its errors (OSError, ValueError, KeyError) answer 400 with their message, or 503 with unreachable(error)"""
    def __init__(self, fn, unreachable=None, content_type=None):
        self.fn, self.unreachable, self.content_type = fn, unreachable, content_type


class Addon:
    """id: its folder and the prefix of its routes, actions, sources and links; order: its place in the lists (TV
    menu, quick menu); configured(): whether it can be used (a server chosen…); kinds: the history kinds of its videos
    (history.media_key; its id by default).
    Videos played from a link (playback.play): prepare(video, position, duration, from_start, at) → (position,
    duration) before, it may fill video's title and thumb; started(video) once mpv has it; progress(video, position,
    final) every progress_every seconds while it plays, and once at the end (final).
    Videos it plays itself (its links): report(video, position, duration, paused, stopped) instead, the history kept by
    playback's loop. outside_video() returns the video being played when it was started outside the box, None
    otherwise; state() adds keys to /api/state; home() its lists, for the quick menu; library: the (home, series, play)
    of a media library, for the quick menu"""
    def __init__(self, id, name, order=50, configured=lambda: True, kinds=None, routes=None, actions=None, more=None,
                 links=None, prepare=None, started=None, progress=None, progress_every=30, report=None,
                 outside_video=None, state=None, home=None, library=None):
        self.id, self.name, self.order, self.configured, self.kinds = id, name, order, configured, kinds or (id,)
        self.routes, self.actions, self.more, self.links = routes or {}, actions or {}, more or {}, links or {}
        self.prepare, self.started, self.progress, self.progress_every = prepare, started, progress, progress_every
        self.report, self.outside_video, self.state, self.home, self.library = report, outside_video, state, home, library


def library(id, home, search, series, play, more_lib, more_home, more_search, unreachable):
    """Routes, actions, "Load more" sources and link of a media library (Jellyfin, Plex: the same TV tab and cards):
    GET /api/<id>, /api/<id>_search?q=, /api/<id>_series?id=; POST /api/<id>_play {id, from_start}; sources <id>_lib,
    <id>_resume, <id>_nextup, <id>_search; links <id>:<item>"""
    return {
        "routes": {f"/api/{id}": Route(lambda q: home(), unreachable),
                   f"/api/{id}_search": Route(lambda q: {"query": q.get("q", ""), "results": search(q.get("q", ""))}),
                   f"/api/{id}_series": Route(lambda q: series(q.get("id", "")))},
        "actions": {f"{id}_play": lambda body: play(str(body.get("id", "")), bool(body.get("from_start")))},
        "more": {f"{id}_lib": lambda key, offset, q: more_lib(key, offset),
                 f"{id}_resume": lambda key, offset, q: more_home("resume", offset),
                 f"{id}_nextup": lambda key, offset, q: more_home("nextup", offset),
                 f"{id}_search": lambda key, offset, q: more_search(q, offset)},
        "links": {id: play},
        "home": home,
        "library": (home, series, play),
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
    """(addon, Route) of a GET path (without its parameters), or None"""
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


def state():
    out = {}
    for a in ADDONS:
        if a.state:
            out.update(a.state())
    return out


load()
