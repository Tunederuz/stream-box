"""Inlet: TV menu rows and cards built by the addons (GET /api/rows), the same shapes for every service, so that the
menu draws and drives them without knowing the service. Standard library only.

A row: {key, title, items, avatar?, style? ("channels": round pictures), more? ({source, key, q}: its next cards,
GET /api/rows?addon=…&more=<source>…), sel? (the card to focus first)}.
A card: {key (unique in the row), title, thumb, meta (its info line, translated), progress (0 to 1), glyph?, and what
it does: play ({url}: a link, POST /api/play; or {action, id}: POST /api/<action> {id, from_start}), open ({target,
name}: a row of its own just below the search, GET /api/rows?addon=…&open=<target>&name=<name>), connect (the addon's
account sign-in); position, seconds, finished (resume or from the beginning); options ([{label, open} or {label,
action, body, danger}]: added to its ≡ dialog; with no play, its only choices)}.
"""
import datetime, time

from i18n import tr

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _decimal(x):
    i, d = f"{x:.1f}".split(".")
    return {"int": i, "dec": d}


def big(v):
    """16617298 → "16.6M", 4500 → "4.5k" (translated separator)"""
    v = float(v or 0)
    if v >= 1e6:
        return tr("{int}.{dec}M", **_decimal(v / 1e6))
    return tr("{int}.{dec}k", **_decimal(v / 1000)) if v >= 1000 else str(int(v))


def clock(t):
    t = max(0, int(t or 0))
    h, m, s = t // 3600, t // 60 % 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def hm(t):
    h, m = int(t) // 3600, int(t) // 60 % 60
    return f"{h} h {m:02d}" if h else f"{m} min"


def ago(iso):
    """"today", "3 d ago", "2 wk ago", then the date"""
    try:
        day = datetime.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return ""
    days = (datetime.date.today() - day).days
    return (tr("today") if days <= 0 else tr("yesterday") if days == 1 else tr("{n} d ago", n=days) if days < 7
            else tr("{n} wk ago", n=days // 7) if days < 31 else tr("{month} {day}", month=tr(MONTHS[day.month - 1]), day=day.day))


def line(*parts, finished=False):
    """Info line: its parts joined with " · ", "watched" at the end"""
    return " · ".join(str(p) for p in parts if p) + (" · " + tr("watched") if finished else "")


def progress(it):
    if it.get("finished"):
        return 1
    if it.get("position") and it.get("seconds"):
        return min(1, it["position"] / it["seconds"])
    return (it.get("percent") or 0) / 100


def card(key, title, meta="", thumb="", **fields):
    out = {"key": key, "title": title or "", "meta": meta, "thumb": thumb or ""}
    out.update({k: v for k, v in fields.items() if v is not None})
    return out


def row(key, title, items, **fields):
    out = {"key": key, "title": title, "items": items}
    out.update({k: v for k, v in fields.items() if v is not None})
    return out


def now():
    return time.time()
