#!/usr/bin/env python3
"""Inlet: sound output, chosen and tracked through PipeWire (pactl).

Outputs offered: the HDMI / DisplayPort connectors where a screen or TV able to play sound is plugged in (the graphics
card reports it: port "available", device name from its EDID), USB and Bluetooth devices (headset, soundbar,
speaker), and the analog output of the sound card (speakers, headphone jack).

Choice: ~/.config/stream-box/audio-output holds "auto" (the default) or the id of an output picked by hand (TV
Settings, companion app). In automatic mode: a plugged-in Bluetooth or USB device comes first, otherwise the HDMI /
DisplayPort with a TV on it; if none of these, nothing is touched (TV off: the sound doesn't go to the PC's speakers).
An output picked by hand and missing (speaker off) gives way to automatic mode, and takes over again as soon as it
comes back. ~/.config/stream-box/no-hdmi-audio (old setting) means "analog".

  audio.py          choice at startup, once
  audio.py watch    choice at startup, then on every plug or unplug (pactl subscribe); started by start.sh
remote.py also uses it (outputs, current, set_choice) for /api/audio.
"""
import json, os, re, subprocess, sys, threading, time

# app/player and app/system on the import path: the modules import each other by name, from either folder (system/
# is not part of the Inlet app)
sys.path[:0] = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), d) for d in ("player", "system")]

from i18n import tr

CONF = os.path.expanduser("~/.config/stream-box/audio-output")
NO_HDMI = os.path.expanduser("~/.config/stream-box/no-hdmi-audio")
lock = threading.Lock()


def pactl(*args, timeout=10):
    # In English: translated descriptions give "Invalid ASCII character" warnings in JSON
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "LC_ALL": "C"})


def listing(kind):
    try:
        return json.loads(pactl("--format=json", "list", kind).stdout or "[]")
    except ValueError:
        return []


def descriptions():
    """Readable output names ("Description:" from the text listing: the JSON loses them as soon as there is an accent)"""
    out, name = {}, None
    for line in subprocess.run(["pactl", "list", "sinks"], capture_output=True, text=True, timeout=10).stdout.splitlines():
        m = re.match(r"\s*(?:Name|Nom)\s*:\s*(\S+)", line)
        if m:
            name = m.group(1)
        m = re.match(r"\s*Description\s*:\s*(.+)", line)
        if m and name:
            out[name] = m.group(1).strip()
    return out


def default_sink():
    for line in pactl("info").stdout.splitlines():
        if line.lower().startswith("default sink:"):
            return line.split(":", 1)[1].strip()
    return ""


def outputs():
    """Possible outputs: [{id, label, kind, card?, profile?, port?, sink?}], best first"""
    found, desc = [], descriptions()
    sinks = listing("sinks")
    for card in listing("cards"):
        ports = card.get("ports") or {}
        profiles = card.get("profiles") or {}
        hdmi = [(n, p) for n, p in ports.items() if n.startswith("hdmi-output")]
        for name, port in hdmi:
            if port.get("availability") == "not available":
                continue
            outs = [p for p in port.get("profiles") or [] if p.startswith("output:hdmi-stereo") and "+input" not in p]
            if not outs:
                continue
            product = (port.get("properties") or {}).get("device.product.name") or ""
            num = f" (HDMI {int(name.rsplit('-', 1)[1]) + 1})" if len(hdmi) > 1 else ""
            found.append({"id": f"hdmi:{card['name']}:{name}", "kind": "hdmi", "card": card["name"],
                          "profile": outs[0], "port": name,
                          "label": tr("TV / screen") + (f" · {product}" if product else "") + num})
        if "output:analog-stereo" in profiles and profiles["output:analog-stereo"].get("available", True):
            found.append({"id": f"analog:{card['name']}", "kind": "analog", "card": card["name"],
                          "profile": "output:analog-stereo", "label": tr("Speakers / headphone jack")})
    for s in sinks:
        props = s.get("properties") or {}
        bus = props.get("device.bus") or ""
        api = props.get("device.api") or ""
        if api == "bluez5" or bus == "bluetooth":
            kind = "bluetooth"
        elif bus == "usb":
            kind = "usb"
        else:
            continue   # PCI cards: already offered through their connectors above
        label = desc.get(s["name"]) or props.get("device.description") or props.get("device.product.name") or s["name"]
        found.append({"id": f"sink:{s['name']}", "kind": kind, "sink": s["name"],
                      "label": label + (" (Bluetooth)" if kind == "bluetooth" else " (USB)")})
    order = {"bluetooth": 0, "usb": 1, "hdmi": 2, "analog": 3}
    return sorted(found, key=lambda o: order[o["kind"]])


def current(outs=None):
    """Id of the current default output"""
    name = default_sink()
    sinks = {s["name"]: s for s in listing("sinks")}
    s = sinks.get(name) or {}
    props = s.get("properties") or {}
    for o in outs if outs is not None else outputs():
        if o.get("sink") == name:
            return o["id"]
        if o.get("card") and props.get("device.name") == o["card"]:
            if o["kind"] == "hdmi" and s.get("active_port") == o["port"]:
                return o["id"]
            if o["kind"] == "analog" and "analog" in name:
                return o["id"]
    return ""


def choice():
    try:
        with open(CONF, encoding="utf-8") as f:
            c = f.read().strip()
        if c:
            return c
    except OSError:
        pass
    return "analog" if os.path.exists(NO_HDMI) else "auto"


def apply(o):
    if o.get("card"):
        pactl("set-card-profile", o["card"], o["profile"])
        for _ in range(20):   # the output of this profile shows up within a few tenths of a second
            sink = next((s["name"] for s in listing("sinks")
                         if (s.get("properties") or {}).get("device.name") == o["card"]
                         and (o["kind"] != "hdmi" or s.get("active_port") == o["port"])), None)
            if sink:
                break
            time.sleep(0.2)
        else:
            return False
    else:
        sink = o["sink"]
    pactl("set-default-sink", sink)
    # Playing streams (mpv…) moved to the new output
    for line in pactl("list", "short", "sink-inputs").stdout.splitlines():
        pactl("move-sink-input", line.split("\t")[0], sink)
    return True


def choose():
    """Applies the choice (manual if there is one, otherwise automatic); returns the selected output or None"""
    with lock:
        outs = outputs()
        if not outs:
            return None
        c, target = choice(), None
        if c == "analog":
            target = next((o for o in outs if o["kind"] == "analog"), None)
        elif c != "auto":
            target = next((o for o in outs if o["id"] == c), None)
        if target is None:   # automatic, or the chosen output is missing for now
            target = next((o for o in outs if o["kind"] in ("bluetooth", "usb", "hdmi")), None)
        if target is None or current(outs) == target["id"]:
            return target
        if apply(target):
            print(f"audio.py: output {target['label']} ({target['id']})", flush=True)
        return target


def set_choice(value):
    """"auto" or the id of an output; applied right away"""
    if value != "auto" and not any(o["id"] == value for o in outputs()):
        raise ValueError(tr("unknown output"))
    os.makedirs(os.path.dirname(CONF), mode=0o700, exist_ok=True)
    with open(CONF, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    if os.path.exists(NO_HDMI):
        os.remove(NO_HDMI)
    choose()


def wait_pipewire():
    for _ in range(15):   # PipeWire may start just after the session
        if pactl("info").returncode == 0:
            return True
        time.sleep(1)
    return False


def watch():
    """Plugs and unplugs: new choice 1.5 s after the last event (time for them to settle)"""
    choose()
    while True:
        proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, text=True, env={**os.environ, "LC_ALL": "C"})
        timer = None
        for line in proc.stdout:
            if " on sink " in line or " on card " in line:
                if timer:
                    timer.cancel()
                timer = threading.Timer(1.5, choose)
                timer.start()
        proc.wait()
        time.sleep(3)   # PipeWire restarted: subscribe again


if __name__ == "__main__":
    if not wait_pipewire():
        sys.exit("audio.py: PipeWire unreachable")
    if sys.argv[1:] == ["watch"]:
        watch()
    else:
        choose()
