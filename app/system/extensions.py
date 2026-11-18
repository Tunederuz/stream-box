"""Inlet: the system's extensions (Moonlight for the PC link, Node.js for YouTube) in line with the add-ons, on the
box's image (/usr/local/lib/stream-box/extensions, stream-box-extensions.service): their state, and a sync started when
an add-on is turned on or off. Without that service (a box installed by install.sh): nothing to do, those packages are
part of its system. Standard library only.
"""
import json, os, subprocess

STATE = "/run/stream-box-extensions.json"
UNIT = "/etc/systemd/system/stream-box-extensions.service"


def available():
    return os.path.exists(UNIT)


def state(name):
    """{state: ready | downloading | error | off | builtin (an image from before, which has it), error} of an extension,
    None when the box has none"""
    if not available():
        return None
    try:
        with open(STATE) as f:
            return json.load(f).get(name) or {"state": "pending"}
    except (OSError, ValueError):
        return {"state": "pending"}


def sync():
    """Downloads the extensions of the add-ons on, removes the others (in the background)"""
    if available():
        subprocess.run(["systemctl", "start", "--no-block", "stream-box-extensions.service"], capture_output=True, timeout=10)
