"""YouTube addon (service.py): favorite channels, search, automatic subtitles, seek bar preview, and the YouTube
account through the "TV app" access of cast/youtube_tv.js (sign-in by code, subscriptions, recommendations, progress
both ways, rating, comments)."""
import threading

from addons import Addon, Route
from i18n import tr
from . import service as yt


def prepare(video, position, duration, from_start, at):
    ident = video["ident"]
    video["thumb"] = video["thumb"] or f"https://i.ytimg.com/vi/{ident}/mqdefault.jpg"
    if not video["title"]:   # video cast from the YouTube app: only its identifier is known
        video["title"], duration = yt.yt_meta(ident)
        duration = duration or 0
    if not from_start and at is None:
        # Watched further elsewhere (phone…): resume at the account's percentage, if beyond the box's position
        pct = yt.yt_tv_progress().get(ident) or 0
        if 3 <= pct and (not duration or pct / 100 * duration > position + 30):
            duration = duration or yt.yt_meta(ident)[1] or 0
            position = int(pct / 100 * duration)
    return position, duration


def started(video):   # seek bar preview and the video's info, the account's rating
    threading.Thread(target=yt.fetch_storyboard, args=(video["ident"],), daemon=True).start()
    threading.Thread(target=yt.yt_rating_fetch, args=(video["ident"],), daemon=True).start()


def login(body):
    """YouTube account (subscriptions, recommendations, progress): a code to type on google.com/device"""
    d = yt.yt_tv("/login", {}, timeout=15)
    if not d or d.get("error"):
        raise ValueError(tr("Unable to connect: {error}",
                            error=(d or {}).get("error") or tr("cast service stopped")))


def logout(body):
    yt.yt_tv("/logout", {})
    yt.yt_tv_cache.update(at=0.0, data={})


ADDON = Addon(
    "youtube", "YouTube", order=10,
    routes={
        "/api/youtube": Route(lambda q: yt.youtube_home()),
        "/api/youtube_channels": Route(lambda q: {"channels": yt.yt_channels()}),
        "/api/youtube_account": Route(lambda q: yt.yt_account_status()),
        "/api/youtube_search": Route(lambda q: {"query": q.get("q", ""), **yt.yt_search(q.get("q", ""))}),
        "/api/youtube_channel": Route(lambda q: yt.yt_channel_videos(q.get("id", ""))),
        # automatic subtitles, for stream-box.lua (sub-add)
        "/subs": Route(lambda q: yt.fetch_auto_subs(q.get("u", "")), content_type="application/x-subrip; charset=utf-8"),
    },
    actions={
        "youtube_channels": lambda body: yt.edit_yt_channels(str(body.get("action", "")), str(body.get("channel", "")),
                                                             int(body.get("delta", 0))),
        "youtube_login": login,
        "youtube_logout": logout,
        "youtube_sync": lambda body: yt.yt_reload(),
        "yt_rate": yt.yt_rate,           # {rating: like | dislike | none}: the video being played (playback bar)
        "yt_comments": yt.yt_comments,   # its comments ({more: true}: the next page), published for the panel
    },
    more={
        "yt_search": lambda key, offset, q: yt.yt_search_more(q, offset),
        "yt_channel": lambda key, offset, q: yt.yt_channel_more(key, offset),
        "yt_recommended": lambda key, offset, q: yt.yt_tv_more("recommended", offset),
        "yt_subscriptions": lambda key, offset, q: yt.yt_tv_more("subscriptions", offset),
    },
    prepare=prepare, started=started,
    progress=lambda video, position, final: yt.yt_tv_report(video["ident"], position, final=final),
    progress_every=yt.YT_TV_PUSH,
    home=yt.youtube_home,
)
