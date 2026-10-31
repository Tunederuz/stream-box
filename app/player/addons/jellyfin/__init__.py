"""Jellyfin addon: the library of the server paired with jellyfin-mpv-shim (service.py), its videos, their progress on
the server, and the videos started from a Jellyfin app ("Play on…", played by the shim)."""
import history   # history.py: media keys
from addons import Addon, Route, library
from common import mpv
from i18n import tr
from . import service as jf

shim_items = {}   # Jellyfin identifier → card (title, image), for the history of the shim's playbacks


def shim_video():
    """Jellyfin video started by jellyfin-mpv-shim ("Play on…" from a Jellyfin app), from the link being
    played; None otherwise"""
    try:
        user, path = mpv(["get_property", "user-data/streambox"], ["get_property", "path"])
    except (OSError, ValueError):
        return None
    srv = jf.jf_server()
    if (user or {}).get("mode") != "media" or not srv or not str(path or "").startswith(srv["address"]):
        return None
    key, kind, ident = history.media_key(path)
    if kind != "jellyfin":
        return None
    if ident not in shim_items:
        try:
            shim_items[ident] = jf.jf_item(jf.jf_api(f"/Users/{{user}}/Items/{ident}"))
        except (OSError, ValueError, KeyError):
            return None
    i = shim_items[ident]
    return {"key": key, "url": path, "link": key, "kind": kind, "ident": ident, "shim": True, "thumb": i["thumb"],
            "title": f"{i['title']} · {i['episode']}" if i.get("episode") else i["title"]}


def report(video, position, duration, paused, stopped):
    if stopped:
        jf.jf_report("/Stopped", video["ident"], video.get("position") or 0)
    else:
        jf.jf_report("/Progress", video["ident"], position, paused)


lib = library("jellyfin", jf.jellyfin_home, jf.jellyfin_search, jf.jellyfin_series, jf.jellyfin_play,
              jf.jellyfin_more, jf.jellyfin_more_home, jf.jellyfin_search_more,
              lambda e: tr("Jellyfin unreachable: {error}", error=e))
# Jellyfin server, Quick Connect in progress (?find=1: the servers that answer on the network); sign-in, cancel, forget
lib["routes"]["/api/jellyfin_link"] = Route(lambda q: jf.link_state(find=q.get("find") == "1"))
lib["actions"]["jellyfin_link"] = jf.link_action

ADDON = Addon("jellyfin", "Jellyfin", order=20, configured=lambda: jf.jf_server() is not None, report=report,
              outside_video=shim_video, state=lambda: {"jellyfin_server": (jf.jf_server() or {}).get("address", "")},
              **lib)
