"""Twitch addon, the base (service.py): the streamer list and who is live (played by stream-box.lua itself, through
streamlink), followed channels, polls and predictions, replays and clips, the Twitch account. Always there; the core's
modules (state, ambient screen, quick menu) use its service directly."""
import datetime

from addons import Addon, Route
from common import mpv
from i18n import tr
from . import service as twitch


def channel(body):
    # Streamer from the list, or followed channel (Following tab of the TV menu)
    if body.get("name") not in twitch.read_streamers() and body.get("name") not in twitch.follows_logins():
        raise ValueError(tr("unknown streamer"))
    mpv(["script-message", "streambox-channel", body["name"]])


def prepare(video, entry, from_start, at):
    """Replay: title, thumbnail, duration and the position saved on the account (when watched more recently elsewhere
    than on the box); clip: title, thumbnail, duration"""
    position, duration, ident = entry.get("position", 0), entry.get("duration", 0), video["ident"]
    try:
        if video["kind"] == "twitch-vod":
            v = twitch.twitch_gql("query($id:ID!){video(id:$id){title lengthSeconds "
                                  "previewThumbnailURL(width:320,height:180) self{viewingHistory{position updatedAt}}}}",
                                  {"id": ident}).get("video") or {}
            video.update(title=v.get("title") or video["title"], thumb=v.get("previewThumbnailURL") or video["thumb"])
            duration = v.get("lengthSeconds") or duration
            seen = (v.get("self") or {}).get("viewingHistory") or {}
            if seen.get("updatedAt"):
                seen_at = datetime.datetime.fromisoformat(seen["updatedAt"].replace("Z", "+00:00")).timestamp()
                if seen_at > entry.get("updated", 0):   # watched more recently elsewhere (site, app) than on the box
                    position = seen.get("position") or 0
        else:
            c = twitch.twitch_gql("query($s:ID!){clip(slug:$s){title durationSeconds thumbnailURL}}",
                                  {"s": ident}).get("clip") or {}
            video.update(title=c.get("title") or video["title"], thumb=c.get("thumbnailURL") or video["thumb"])
            duration = c.get("durationSeconds") or duration
    except (OSError, ValueError, KeyError):
        pass   # Twitch unreachable: make do with the box's history
    return position, duration


def progress(video, position, final):
    if video["kind"] == "twitch-vod":   # the position of a replay, saved on the account
        try:
            twitch.twitch_save_position(video["ident"], position)
        except (OSError, ValueError, KeyError):
            pass


def unreachable(e):
    return tr("Twitch unreachable: {error}", error=e)


ADDON = Addon(
    "twitch", "Twitch", order=0, base=True, kinds=("twitch-vod", "twitch-clip"),
    description="Live streams, followed channels, replays, polls and predictions",
    routes={
        "/api/replays": Route(lambda q: twitch.replays(q.get("login", ""))),
        "/api/events": Route(lambda q: twitch.events_for_page(), unreachable),   # poll and prediction being watched
        "/api/follows": Route(lambda q: twitch.follows_status(), unreachable),
        "/api/account": Route(lambda q: twitch.account_status()),
    },
    actions={
        "channel": channel,
        "twitch": lambda body: mpv(["script-message", "streambox-twitch"]),   # back to the live stream
        "streamers": lambda body: twitch.edit_streamers(str(body.get("action", "")), str(body.get("login", "")),
                                                        int(body.get("delta", 0))),
        "vote": lambda body: twitch.vote_poll(str(body.get("poll", "")), str(body.get("choice", ""))),
        "predict": lambda body: twitch.predict(str(body.get("event", "")), str(body.get("outcome", "")),
                                               int(body.get("points", 0))),
        "login": lambda body: twitch.login(str(body.get("token", ""))),
        "logout": lambda body: twitch.logout(),
        "login_code": lambda body: twitch.account_start(),   # sign-in by code on twitch.tv/activate
        "follows_app": lambda body: twitch.set_twitch_app(str(body.get("client_id", "")),
                                                          str(body.get("client_secret", ""))),
        "follows_login": lambda body: twitch.follows_start(),
        "follows_logout": lambda body: twitch.follows_logout(),
    },
    more={
        "twitch_vods": lambda key, offset, q: twitch.replays_more(key, "vods", offset),
        "twitch_clips": lambda key, offset, q: twitch.replays_more(key, "clips", offset),
    },
    prepare=prepare, progress=progress, progress_every=30,
    state=lambda: {"streamers": twitch.read_streamers(), "avatars": twitch.avatars, "live": twitch.live_now},
    start=lambda: twitch.write_cookies(twitch.read_token()),   # cookies aligned with the saved token
    loops=(twitch.account_loop, twitch.live_loop, twitch.events_loop),
)
