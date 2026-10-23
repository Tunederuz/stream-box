#!/usr/bin/env python3
"""Stream Box : résolution de la sortie vidéo, via wlr-randr (cage gère wlr-output-management).

Seuls les modes à 60 Hz (ou presque) sont proposés : beaucoup de mini PC ne sortent le 4K qu'en 30 Hz en HDMI, ce qui
fait sauter une image sur deux d'un stream à 60 i/s. « auto » = le mode préféré de la TV s'il est à 60 Hz, sinon la plus
grande définition à 60 Hz.

Usage : display.py apply   applique le réglage enregistré (lancé par start.sh avant mpv)
        display.py list    affiche les modes disponibles
Aussi importé par remote.py.
"""
import json, os, subprocess, sys

STATE_FILE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                          "stream-box", "display_mode")
MIN_REFRESH = 59
MIN_WIDTH, MIN_HEIGHT = 1280, 720   # les petits modes (640x480, 1024x768…) ne sont pas proposés dans la page


def wlr_env():
    # remote.py peut avoir été relancé hors de la session (SSH) : on retrouve alors le socket de cage
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
        raise OSError("wlr-randr n'est pas installé (sudo pacman -S wlr-randr)") from None
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or f"wlr-randr a échoué ({r.returncode})")
    return r.stdout


def label(mode):
    return f"{mode['width']}x{mode['height']}@{round(mode['refresh'])}"


def output():
    """Première sortie active : (nom, modes à 60 Hz sans doublons, du plus grand au plus petit)."""
    for out in json.loads(wlr_randr("--json")):
        if out.get("enabled"):
            modes = {}
            for m in out["modes"]:
                modes.setdefault(label(m), m)
            ordered = sorted(modes.values(), key=lambda m: (m["width"] * m["height"], m["refresh"]), reverse=True)
            fluid = [m for m in ordered if m["refresh"] >= MIN_REFRESH or m.get("current")]
            return out["name"], fluid or ordered
    raise OSError("aucune sortie vidéo active")


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
            "modes": [label(m) for m in modes if m["refresh"] >= MIN_REFRESH and m["width"] >= MIN_WIDTH and m["height"] >= MIN_HEIGHT]}


def apply(setting=None):
    """Enregistre le réglage s'il est donné, puis l'applique. Renvoie le mode choisi."""
    name, modes = output()
    if setting is not None:
        if setting != "auto" and setting not in {label(m) for m in modes}:
            raise ValueError("mode inconnu")
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(setting + "\n")
    mode = choose(read_setting(), modes)
    if not mode.get("current"):
        wlr_randr("--output", name, "--mode", f"{mode['width']}x{mode['height']}@{mode['refresh']}")
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
        sys.exit(f"display.py : {e}")
