"""Plex addon: the library of a server of the local network (service.py), chosen by signing in with a Plex account by
code or by its address, its videos (direct play) and their progress on the server."""
from addons import Addon, Route, library
from i18n import tr
from . import service as px


def report(video, position, duration, paused, stopped):
    if stopped:
        px.px_report(video["ident"], video.get("position") or 0, video.get("duration"), "stopped")
    else:
        px.px_report(video["ident"], position, duration, "playing", paused)


lib = library("plex", px.plex_home, px.plex_search, px.plex_series, px.plex_play,
              px.plex_more, px.plex_more_home, px.plex_search_more,
              lambda e: tr("Plex unreachable: {error}", error=e))
lib["routes"]["/api/plex_link"] = Route(lambda q: px.link_state())   # Plex server, and the sign-in code being waited for
lib["actions"].update({
    "plex": lambda body: px.set_plex(str(body.get("address", "")), str(body.get("token", ""))),   # server (empty: forget)
    # Plex account by code (plex.tv/link): start, or give up
    "plex_link": lambda body: px.link_cancel() if body.get("action") == "cancel" else px.link_start(),
})

ADDON = Addon("plex", "Plex", order=30, configured=lambda: px.px_config() is not None, report=report,
              state=lambda: {"plex_server": (px.px_config() or {}).get("address", "")}, **lib)
