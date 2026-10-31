"""YouTube addon (service.py): favorite channels, search, automatic subtitles, seek bar preview, and the YouTube
account through the "TV app" access of cast/youtube_tv.js (sign-in by code, subscriptions, recommendations, progress
both ways, rating, comments)."""
import threading

from addons import Addon, Route
from addons import cards as R
from i18n import tr
from . import service as yt


def prepare(video, entry, from_start, at):
    ident = video["ident"]
    position, duration = entry.get("position", 0), entry.get("duration", 0)
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


# TV menu rows (addons/cards.py): the account's recommendations and subscriptions, one row per favorite channel; a
# search's channels and videos; a channel opened; the next cards of each

def channel_options(channel_id, name, favorites, see=True):
    """≡ of a video whose channel is known: its latest videos (not in that channel's own opened row), favorite on or
    off"""
    if not channel_id:
        return []
    fav = channel_id in favorites
    out = [{"label": tr("▶  See latest videos of {channel}", channel=name or tr("the channel")),
            "open": {"target": "channel:" + channel_id, "name": name or ""}}] if see else []
    return out + [{"label": tr("✕  Remove from favorites") if fav else tr("★  Add to favorites"), "danger": fav,
                   "action": "youtube_channels", "body": {"action": "remove" if fav else "add", "channel": channel_id}}]


def video_card(v, kind, favorites, own=None):
    """kind: rec, subs, results (channel, duration, views), channel or preview (date, views); own: (id, name) of the
    row's channel (favorites, the opened channel), otherwise the video's"""
    if kind == "subs":
        meta = [v.get("channel"), tr("● LIVE") if v.get("live") else R.ago(v.get("date")), R.clock(v["seconds"]) if v.get("seconds") else ""]
    elif kind in ("rec", "results"):
        meta = [v.get("channel"), tr("● LIVE") if v.get("live") else R.clock(v["seconds"]) if v.get("seconds") else "",
                tr("{n} views", n=R.big(v["views"])) if v.get("views") else ""]
    else:
        meta = [R.ago(v.get("date")), tr("{n} views", n=R.big(v["views"])) if v.get("views") else ""]
    channel_id, name = own or (v.get("channel_id"), v.get("channel"))
    return R.card(v.get("url") or v.get("id"), v.get("title"), R.line(*meta, finished=v.get("finished")), v.get("thumb"),
                  progress=R.progress(v), play={"url": v.get("url")}, position=v.get("position"),
                  seconds=v.get("seconds"), finished=v.get("finished") or None,
                  options=channel_options(channel_id, name, favorites, see=kind != "preview"))


def favorites():
    return {c["id"] for c in yt.yt_channels()}


def tab_rows():
    d, fav = yt.youtube_home(), favorites()
    rows = []
    if d.get("recommended"):
        rows.append(R.row("rec", tr("Recommended for you"), [video_card(v, "rec", fav) for v in d["recommended"]],
                          more={"source": "yt_recommended", "key": ""}))
    subs = d.get("subs") or {}
    if subs.get("authorized"):
        rows.append(R.row("subs", tr("Subscriptions"), [video_card(v, "subs", fav) for v in subs.get("videos") or []],
                          more={"source": "yt_subscriptions", "key": ""}, loading=subs.get("videos") is None or None))
    elif subs and not subs.get("unavailable"):
        rows.append(R.row("connect", tr("Subscriptions"), [R.card("connect", tr("Connect my account"),
                                                                  tr("Your YouTube subscriptions"), glyph="+", connect="youtube")]))
    for c in d.get("channels") or []:
        rows.append(R.row("channel:" + c["id"], c["name"], [video_card(v, "channel", fav, (c["id"], c["name"]))
                                                            for v in c.get("videos") or []],
                          avatar=c.get("avatar"), more={"source": "yt_channel", "key": c["id"]},
                          error=c.get("videos") is None or None))
    return {"rows": rows, "channels": len(d.get("channels") or []), "authorized": bool(subs.get("authorized"))}


def channel_card(c, fav):
    return R.card(c["id"], c.get("name"), R.line(tr("{n} subscribers", n=R.big(c["followers"])) if c.get("followers") else "",
                                                  tr("★ favorite") if c["id"] in fav else ""),
                  c.get("avatar"), saved=c["id"] in fav, options=channel_options(c["id"], c.get("name"), fav))


def search_rows(q):
    d, fav = yt.yt_search(q), favorites()
    rows = []
    if d.get("channels"):
        rows.append(R.row("chans", tr("Channels"), [channel_card(c, fav) for c in d["channels"]], style="channels"))
    rows.append(R.row("search", tr("Results for \"{query}\"", query=q), [video_card(v, "results", fav) for v in d.get("results") or []],
                      more={"source": "yt_search", "key": "", "q": q}))
    return {"rows": rows}


def open_row(target, name):
    kind, _, channel_id = target.partition(":")
    if kind != "channel":
        raise ValueError(tr("not found"))
    d, fav = yt.yt_channel_videos(channel_id), favorites()
    return {"rows": [R.row("preview", tr("{name} · latest videos", name=name), [video_card(v, "preview", fav, (channel_id, name))
                                                                               for v in d.get("videos") or []],
                           more={"source": "yt_channel", "key": channel_id})]}


MORE_KINDS = {"yt_search": "results", "yt_recommended": "rec", "yt_subscriptions": "subs", "yt_channel": "channel"}


def more_cards(source, key, q, offset):
    d, fav = ADDON.more[source](key, offset, q), favorites()
    return {"items": [video_card(v, MORE_KINDS[source], fav) for v in d.get("items") or []], "more": d.get("more")}


ADDON = Addon(
    "youtube", "YouTube", order=10,
    description="Favorite channels, search, your account's subscriptions and recommendations",
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
    rows={"tab": tab_rows, "search": search_rows, "open": open_row, "more": more_cards},
)
