"""Inlet: box settings kept in ~/.config/stream-box: player (Qt app or mpv), action of the power button, animated
background of the home screen. Standard library only.
"""
import json, os

from common import COOKIES_DIR, mpv
from i18n import tr

PLAYER_FILE = os.path.join(COOKIES_DIR, "player")   # "qt": Qt app embedding mpv (see player.sh)


def player_choice():
    try:
        with open(PLAYER_FILE, encoding="utf-8") as f:
            return "qt" if f.readline().strip() == "qt" else "mpv"
    except OSError:
        return "mpv"


def set_player(mode):
    """Player choice, applied right away: quit the player, player.sh's loop starts the right one"""
    if mode not in ("qt", "mpv"):
        raise ValueError(tr("unknown player"))
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    with open(PLAYER_FILE, "w", encoding="utf-8") as f:
        f.write(mode + "\n")
    mpv(["quit"])


# Action of the power button of the companion app and Home Assistant: "suspend" (sleep, wake on
# network) or "poweroff" (full shutdown, default). The TV menu has its own two lines, "Sleep" and
# "Turn off the box", which do not depend on this setting. Also read by mqtt_bridge.py.
POWER_ACTION_FILE = os.path.join(COOKIES_DIR, "power-action")


def power_action():
    try:
        with open(POWER_ACTION_FILE, encoding="utf-8") as f:
            return "suspend" if f.readline().strip() == "suspend" else "poweroff"
    except OSError:
        return "poweroff"


def set_power_action(mode):
    if mode not in ("suspend", "poweroff"):
        raise ValueError(tr("unknown action"))
    os.makedirs(COOKIES_DIR, mode=0o700, exist_ok=True)
    with open(POWER_ACTION_FILE, "w", encoding="utf-8") as f:
        f.write(mode + "\n")


# Animated background of the home screen and of the menu without video (qml/Backdrop.qml), chosen in the TV Settings: a
# background, a layer on top, the home screen colors. ~/.config/stream-box/backdrop:
# {"base", "overlay", "color"}
BACKDROP_FILE = os.path.expanduser("~/.config/stream-box/backdrop")
BACKDROP_BASES = ("none", "aurora", "fluid", "borealis")
BACKDROP_OVERLAYS = ("none", "silk", "stars")
BACKDROP_COLORS = ("violet", "blue", "green", "sunset", "pink", "ice")   # home screen (the menu follows its tabs)


def backdrop():
    b = {"base": "aurora", "overlay": "none", "color": "violet"}
    try:
        with open(BACKDROP_FILE) as f:
            raw = f.read().strip()
        saved = json.loads(raw) if raw.startswith("{") else {"base": raw}
        if saved.get("base") == "silk":   # old style that became a layer
            saved = {"base": "aurora", "overlay": saved["base"]}
        b.update({k: v for k, v in saved.items() if k in b})
    except (OSError, ValueError, AttributeError):
        pass
    if b["base"] not in BACKDROP_BASES:
        b["base"] = "aurora"
    if b["overlay"] not in BACKDROP_OVERLAYS:
        b["overlay"] = "none"
    if b["color"] not in BACKDROP_COLORS:
        b["color"] = "violet"
    return b


def set_backdrop(body):
    b = backdrop()
    for key, allowed in (("base", BACKDROP_BASES), ("overlay", BACKDROP_OVERLAYS), ("color", BACKDROP_COLORS)):
        if key in body:
            if body[key] not in allowed:
                raise ValueError(tr("unknown background"))
            b[key] = body[key]
    with open(BACKDROP_FILE, "w") as f:
        json.dump(b, f)
