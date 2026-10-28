#!/usr/bin/env python3
"""Stream Box: video output resolution, through wlr-randr (cage supports wlr-output-management).

Only 60 Hz modes (or close) are offered: many mini PCs only output 4K at 30 Hz over HDMI, which drops every other
frame of a 60 fps stream. "auto" = the TV's preferred mode if it is 60 Hz, otherwise the largest resolution at 60 Hz.
A built-in screen mounted sideways (Steam Deck: an 800x1280 portrait panel) is turned the right way up: the kernel
tells its orientation (DRM "panel orientation", read with modetest), cage does not apply it by itself.

Usage: display.py apply   applies the saved setting (started by start.sh before mpv)
       display.py list    shows the available modes
Also imported by remote.py.
"""
import json, os, re, subprocess, sys

from i18n import tr

STATE_FILE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                          "stream-box", "display_mode")
MIN_REFRESH = 59
MIN_WIDTH, MIN_HEIGHT = 1280, 720   # small modes (640x480, 1024x768…) are not offered in the companion app
# Kernel panel orientation → wlr-randr transform (Steam Deck, "Right Side Up": 270, checked on the device)
TRANSFORMS = {"Normal": "normal", "Upside Down": "180", "Left Side Up": "90", "Right Side Up": "270"}


def wlr_env():
    # remote.py may have been restarted outside the session (SSH): find cage's socket then
    env = dict(os.environ)
    run = env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if "WAYLAND_DISPLAY" not in env:
        sockets = sorted(f for f in os.listdir(run) if f.startswith("wayland-") and not f.endswith(".lock"))
        if sockets:
            env["WAYLAND_DISPLAY"] = sockets[0]
    return env


def wlr_randr(*args):
    try:
        r = subprocess.run(["wlr-randr", *args], capture_output=True, text=True, env=wlr_env(), timeout=15)
    except FileNotFoundError:
        raise OSError(tr("wlr-randr is not installed (sudo pacman -S wlr-randr)")) from None
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or tr("wlr-randr failed ({code})", code=r.returncode))
    return r.stdout


def label(mode):
    return f"{mode['width']}x{mode['height']}@{round(mode['refresh'])}"


def output(full=False):
    """First active output: (name, 60 Hz modes without duplicates, largest to smallest), and its wlr-randr entry if
    full"""
    for out in json.loads(wlr_randr("--json")):
        if out.get("enabled"):
            modes = {}
            for m in out["modes"]:
                modes.setdefault(label(m), m)
            ordered = sorted(modes.values(), key=lambda m: (m["width"] * m["height"], m["refresh"]), reverse=True)
            fluid = [m for m in ordered if m["refresh"] >= MIN_REFRESH or m.get("current")]
            return (out["name"], fluid or ordered, out) if full else (out["name"], fluid or ordered)
    raise OSError(tr("no active video output"))


def panel_transform(name):
    """Transform of a built-in screen from its kernel orientation, None without one (modetest -c: the connectors and
    their properties, as text)"""
    try:
        text = subprocess.run(["modetest", "-c"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    # The connector's block (line "<id> <encoder> connected <name> …" up to the next one), then its property:
    #   panel orientation: / flags: immutable enum / enums: Normal=0 Upside Down=1 … / value: 3
    block = re.search(rf"^\d+\s+\d+\s+connected\s+{re.escape(name)}\s.*?(?=^\d+\s+\d+\s+\w+\s|\Z)", text, re.S | re.M)
    prop = block and re.search(r"panel orientation:.*?enums:([^\n]*)\n\s*value:\s*(\d+)", block.group(0), re.S)
    if not prop:
        return None
    enums = {int(v): n.strip() for n, v in re.findall(r"([^=]+?)=(\d+)", prop.group(1))}
    return TRANSFORMS.get(enums.get(int(prop.group(2)), ""))


def rotate(name, out):
    """Built-in screen (eDP, DSI, LVDS) turned the way its kernel orientation says, if not already"""
    if not re.match(r"(eDP|DSI|LVDS)-", name):
        return
    transform = panel_transform(name)
    if transform and out.get("transform", "normal") != transform:
        wlr_randr("--output", name, "--transform", transform)


def choose(setting, modes):
    if setting != "auto":
        for m in modes:
            if label(m) == setting:
                return m
    preferred = [m for m in modes if m.get("preferred")]
    if preferred and preferred[0]["refresh"] >= MIN_REFRESH:
        return preferred[0]
    fluid = [m for m in modes if m["refresh"] >= MIN_REFRESH]
    return (fluid or modes)[0]


def read_setting():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return f.read().strip() or "auto"
    except OSError:
        return "auto"


def info():
    name, modes = output()
    current = next((label(m) for m in modes if m.get("current")), None)
    return {"setting": read_setting(), "current": current, "auto": label(choose("auto", modes)),
            # (a portrait panel turned sideways, 800x1280, counts as 1280x800)
            "modes": [label(m) for m in modes if m["refresh"] >= MIN_REFRESH
                      and max(m["width"], m["height"]) >= MIN_WIDTH and min(m["width"], m["height"]) >= MIN_HEIGHT]}


def apply(setting=None):
    """Saves the setting if given, then applies it (and turns a sideways built-in screen). Returns the chosen mode."""
    name, modes, out = output(full=True)
    if setting is not None:
        if setting != "auto" and setting not in {label(m) for m in modes}:
            raise ValueError(tr("unknown mode"))
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(setting + "\n")
    mode = choose(read_setting(), modes)
    if not mode.get("current"):
        wlr_randr("--output", name, "--mode", f"{mode['width']}x{mode['height']}@{mode['refresh']}")
    rotate(name, out)
    return label(mode)


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["apply"]:
            print(apply())
        elif sys.argv[1:] == ["list"]:
            print(json.dumps(info(), indent=2))
        else:
            sys.exit(__doc__)
    except (OSError, ValueError) as e:
        sys.exit(f"display.py: {e}")
