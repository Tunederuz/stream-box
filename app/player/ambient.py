"""Owlink: ambient screen data (weather, upcoming scheduled lives), companion app QR code and first setup, published
by ambient_loop in user-data/streambox/ambient. Standard library only.
"""
import datetime, json, os, re, subprocess, sys, time, urllib.parse, urllib.request, zoneinfo

import history   # history.py: a box that has a history counts as set up
import twitch    # twitch.py: streamer list, Twitch schedules
from common import COOKIES_DIR, PORT, PUBLISH_EVERY, lan_ip, mpv
from i18n import tr
from sysparts import netsetup   # setup Wi-Fi access point (None in the Owlink app)

# Ambient screen (drawn by stream-box.lua when nothing is playing): weather and upcoming scheduled lives, published in
# user-data/streambox/ambient. Weather comes from Open-Meteo (no account); location in ~/.config/stream-box/ambient.json:
# {"city": "...", "latitude": ..., "longitude": ..., "timezone": "Europe/..."} (without this file: no weather).

AMBIENT_FILE = os.path.join(COOKIES_DIR, "ambient.json")
AMBIENT_FETCH = 600   # seconds between two fetches (weather, schedules)
# WMO code -> text (English; translated with tr() when published)
WEATHER = [((0,), "Clear sky"), ((1,), "Mostly clear"), ((2,), "Partly cloudy"), ((3,), "Overcast"),
           ((45, 48), "Fog"), ((51, 53, 55), "Drizzle"), ((56, 57), "Freezing drizzle"), ((61,), "Light rain"),
           ((63,), "Rain"), ((65,), "Heavy rain"), ((66, 67), "Freezing rain"), ((71,), "Light snow"),
           ((73,), "Snow"), ((75,), "Heavy snow"), ((77,), "Snow grains"), ((80, 81, 82), "Showers"),
           ((85, 86), "Snow showers"), ((95,), "Thunderstorm"), ((96, 99), "Thunderstorm with hail")]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def ambient_conf():
    try:
        with open(AMBIENT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def fetch_weather(conf):
    if "latitude" not in conf:
        return None
    query = urllib.parse.urlencode({
        "latitude": conf["latitude"], "longitude": conf["longitude"], "timezone": conf.get("timezone", "auto"),
        "current": "temperature_2m,weather_code", "forecast_days": 1,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=10) as r:
        d = json.load(r)
    code = d["current"]["weather_code"]
    return {"city": conf.get("city"), "temp": round(d["current"]["temperature_2m"]), "code": code,
            "text": next((tr(t) for codes, t in WEATHER if code in codes), ""),
            "min": round(d["daily"]["temperature_2m_min"][0]), "max": round(d["daily"]["temperature_2m_max"][0]),
            "rain": d["daily"]["precipitation_probability_max"][0]}


def fetch_schedule(logins, tz):
    """Upcoming scheduled lives of the list (Twitch schedules), see next_streams."""
    if not logins:
        return []
    query = ("query($l:[String!]){users(logins:$l){login channel{schedule{"
             "interruption{startAt endAt} segments{startAt endAt title isCancelled}}}}}")
    req = urllib.request.Request(
        "https://gql.twitch.tv/gql", data=json.dumps({"query": query, "variables": {"l": logins}}).encode(),
        headers={"Client-ID": twitch.TWITCH_WEB_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        users = json.load(r)["data"]["users"]
    return next_streams(users, datetime.datetime.now(tz))


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December"]


def day_month(d):
    """Day and month, such as "March 5", in the current language"""
    month = tr(MONTHS[d.month - 1])
    return tr("{month} 1", month=month) if d.day == 1 else tr("{month} {day}", month=month, day=d.day)


def next_streams(users, now):
    """Next slot of each streamer, from nearest to furthest, then the streamers on a break.

    Schedules are weekly: a past slot is moved a week later. Cancelled slots are ignored, and so are those falling
    during a break (Twitch "interruption", the streamer's holidays); a streamer currently on a break is shown as
    "on a break until …" instead of a slot.
    """
    tz = now.tzinfo

    def when(value):
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(tz)

    upcoming, paused = [], []
    for u in users:
        schedule = ((u or {}).get("channel") or {}).get("schedule") or {}
        pause = schedule.get("interruption") or {}
        pause = (when(pause["startAt"]), when(pause["endAt"])) if pause.get("startAt") and pause.get("endAt") else None
        if pause and pause[0] <= now < pause[1]:
            end = pause[1]
            paused.append({"login": u["login"], "when": tr("on a break until {date}", date=day_month(end)),
                           "title": ""})
            continue
        best = None
        for seg in schedule.get("segments") or []:
            if seg.get("isCancelled"):
                continue
            start = when(seg["startAt"])
            while start < now - datetime.timedelta(hours=1) or (pause and pause[0] <= start < pause[1]):
                start += datetime.timedelta(days=7)   # past slot, or during the break: the following week
            if not best or start < best[0]:
                best = (start, seg.get("title") or "")
        if best:
            upcoming.append((best[0], u["login"], best[1]))
    out = []
    for start, login, title in sorted(upcoming)[:4]:
        days = (start.date() - now.date()).days
        day = tr("today") if days == 0 else tr("tomorrow") if days == 1 else tr(DAYS[start.weekday()])
        if days >= 7:   # beyond a week (after a break), the day alone would be misleading
            day = tr("{weekday}, {date}", weekday=day, date=day_month(start))
        out.append({"login": login, "when": f"{day} {start:%H:%M}", "title": title})
    return out + paused[:2]


# QR code of the companion app, for guests (ambient screen and TV menu). Address in
# ~/.config/stream-box/remote-url (the HTTPS reverse proxy's, for example), otherwise http://<box IP>:8080.
# The QR code is computed by segno, in the media venv, and published as rows of "0" and "1".

REMOTE_URL_FILE = os.path.join(COOKIES_DIR, "remote-url")
MEDIA_PYTHON = os.path.expanduser("~/.local/share/media-venv/bin/python")
if not os.access(MEDIA_PYTHON, os.X_OK):
    MEDIA_PYTHON = sys.executable   # Owlink app: segno is installed next to the app


def remote_url():
    try:
        with open(REMOTE_URL_FILE, encoding="utf-8") as f:
            url = f.read().strip()
        if re.match(r"https?://", url):
            return url
    except OSError:
        pass
    return f"http://{lan_ip()}:{PORT}"


def custom_remote_url():
    try:
        with open(REMOTE_URL_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def set_remote_url(url):
    """Companion app address shown as a QR code: domain name (HTTPS reverse proxy…); empty = local network"""
    url = url.strip()
    if not url:
        try:
            os.remove(REMOTE_URL_FILE)
        except FileNotFoundError:
            pass
        return
    if not re.match(r"https?://[\w.-]+(:\d+)?(/\S*)?$", url):
        raise ValueError(tr("Expected address: https://… (or http://…)"))
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    with open(REMOTE_URL_FILE, "w", encoding="utf-8") as f:
        f.write(url + "\n")


qr_cache = {}   # address -> QR code rows


def qr_rows(text):
    if text not in qr_cache:
        try:
            r = subprocess.run([MEDIA_PYTHON, "-I", "-c", "import segno, sys\n"
                                "for row in segno.make(sys.argv[1], error='m', micro=False).matrix:\n"
                                "    print(''.join(str(int(bool(v))) for v in row))", text],
                               capture_output=True, text=True, timeout=20, check=True)
            qr_cache[text] = r.stdout.split()
        except (OSError, subprocess.SubprocessError):
            qr_cache[text] = None   # segno missing: no new attempt before the next start
    return qr_cache[text]


# First setup (new box): until it is done from the phone's page ("setup" screen), the TV stays on the home screen
# with the QR code in large. Done: ~/.config/stream-box/setup-done (also created by a restore). A box that has already
# been used (history) counts as set up; stream-box.lua follows the same rule
SETUP_DONE = os.path.expanduser("~/.config/stream-box/setup-done")


def setup_done():
    if os.path.exists(SETUP_DONE):
        return True
    if os.path.exists(history.HISTORY_FILE):
        finish_setup(notify=False)
        return True
    return False


def finish_setup(notify=True):
    os.makedirs(os.path.dirname(SETUP_DONE), exist_ok=True)
    open(SETUP_DONE, "a").close()
    if notify:
        mpv(["script-message", "streambox-setup-done"])   # the TV moves on to the menu


def remote_qr():
    url = remote_url()
    rows = qr_rows(url)
    return {"url": url, "rows": rows} if rows else None


def ambient_loop():
    data, fetched = {}, 0
    while True:
        try:
            data["qr"] = remote_qr()   # address read again every round: a change shows right away
        except OSError:
            data["qr"] = None   # no network: no address to show
        # Setup mode (the box's Wi-Fi access point): QR code to join its network, then for the page
        try:
            w = netsetup.status() if netsetup else {}
        except (OSError, subprocess.SubprocessError):
            w = {}
        h = w.get("hotspot")
        data["first_run"] = not setup_done()
        data["setup"] = {"ssid": h["ssid"], "password": h["password"], "url": h["url"],
                         "wifi_rows": qr_rows(f"WIFI:T:WPA;S:{h['ssid']};P:{h['password']};;"),
                         "url_rows": qr_rows(h["url"]), "error": w.get("error")} if h else (
                        {"connecting": w["connecting"]} if w.get("connecting") else None)
        if time.time() - fetched > AMBIENT_FETCH:
            conf = ambient_conf()
            try:
                tz = zoneinfo.ZoneInfo(conf["timezone"])
            except (KeyError, zoneinfo.ZoneInfoNotFoundError, ValueError):
                tz = datetime.datetime.now().astimezone().tzinfo   # system time zone
            for key, fetch in (("weather", lambda: fetch_weather(conf)),
                               ("schedule", lambda: fetch_schedule(twitch.read_streamers(), tz))):
                try:
                    data[key] = fetch()
                except (OSError, ValueError, KeyError, TypeError):
                    pass   # service unreachable: keep the last value
            fetched = time.time()
        try:
            mpv(["set_property", "user-data/streambox/ambient", data])
        except OSError:
            pass
        time.sleep(PUBLISH_EVERY)
