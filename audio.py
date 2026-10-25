#!/usr/bin/env python3
"""Stream Box : sortie son, choisie et suivie par PipeWire (pactl).

Sorties proposées : les prises HDMI / DisplayPort où un écran ou une TV qui sait jouer le son est branché (la carte
graphique le signale : port « available », nom de l'appareil d'après son EDID), les appareils USB et Bluetooth
(casque, barre de son, enceinte), et la sortie analogique de la carte son (haut-parleurs, prise jack).

Choix : ~/.config/stream-box/audio-output contient « auto » (par défaut) ou l'identifiant d'une sortie choisie à la
main (Réglages de la TV, page web). En automatique : un appareil Bluetooth ou USB branché passe en premier, sinon
l'HDMI / DisplayPort où il y a une TV ; si rien de tout ça, on ne touche à rien (TV éteinte : le son ne part pas sur
les haut-parleurs du PC). Une sortie choisie à la main et absente (enceinte éteinte) laisse la place à l'automatique,
et reprend dès qu'elle revient. ~/.config/stream-box/no-hdmi-audio (ancien réglage) vaut « analogique ».

  audio.py          choix au démarrage, une fois
  audio.py watch    choix au démarrage, puis à chaque branchement ou débranchement (pactl subscribe) ; lancé par
                    start.sh
remote.py s'en sert aussi (outputs, current, set_choice) pour /api/audio.
"""
import json, os, re, subprocess, sys, threading, time

CONF = os.path.expanduser("~/.config/stream-box/audio-output")
NO_HDMI = os.path.expanduser("~/.config/stream-box/no-hdmi-audio")
lock = threading.Lock()


def pactl(*args, timeout=10):
    # En anglais : les descriptions traduites donnent des avertissements « Invalid ASCII character » en JSON
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "LC_ALL": "C"})


def listing(kind):
    try:
        return json.loads(pactl("--format=json", "list", kind).stdout or "[]")
    except ValueError:
        return []


def descriptions():
    """Noms lisibles des sorties (« Description: » du listing texte : le JSON les perd dès qu'il y a un accent)"""
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
    """Sorties possibles : [{id, label, kind, card?, profile?, port?, sink?}], meilleures d'abord"""
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
                          "label": "TV / écran" + (f" · {product}" if product else "") + num})
        if "output:analog-stereo" in profiles and profiles["output:analog-stereo"].get("available", True):
            found.append({"id": f"analog:{card['name']}", "kind": "analog", "card": card["name"],
                          "profile": "output:analog-stereo", "label": "Haut-parleurs / prise jack"})
    for s in sinks:
        props = s.get("properties") or {}
        bus = props.get("device.bus") or ""
        api = props.get("device.api") or ""
        if api == "bluez5" or bus == "bluetooth":
            kind = "bluetooth"
        elif bus == "usb":
            kind = "usb"
        else:
            continue   # cartes PCI : déjà proposées par leurs prises ci-dessus
        label = desc.get(s["name"]) or props.get("device.description") or props.get("device.product.name") or s["name"]
        found.append({"id": f"sink:{s['name']}", "kind": kind, "sink": s["name"],
                      "label": label + (" (Bluetooth)" if kind == "bluetooth" else " (USB)")})
    order = {"bluetooth": 0, "usb": 1, "hdmi": 2, "analog": 3}
    return sorted(found, key=lambda o: order[o["kind"]])


def current(outs=None):
    """Identifiant de la sortie par défaut actuelle"""
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
        for _ in range(20):   # la sortie de ce profil apparaît en quelques dixièmes de seconde
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
    # Lectures en cours (mpv…) déplacées vers la nouvelle sortie
    for line in pactl("list", "short", "sink-inputs").stdout.splitlines():
        pactl("move-sink-input", line.split("\t")[0], sink)
    return True


def choose():
    """Applique le choix (manuel s'il est là, sinon automatique) ; renvoie la sortie retenue ou None"""
    with lock:
        outs = outputs()
        if not outs:
            return None
        c, target = choice(), None
        if c == "analog":
            target = next((o for o in outs if o["kind"] == "analog"), None)
        elif c != "auto":
            target = next((o for o in outs if o["id"] == c), None)
        if target is None:   # automatique, ou sortie choisie absente pour l'instant
            target = next((o for o in outs if o["kind"] in ("bluetooth", "usb", "hdmi")), None)
        if target is None or current(outs) == target["id"]:
            return target
        if apply(target):
            print(f"audio.py : sortie {target['label']} ({target['id']})", flush=True)
        return target


def set_choice(value):
    """« auto » ou l'identifiant d'une sortie ; appliqué tout de suite"""
    if value != "auto" and not any(o["id"] == value for o in outputs()):
        raise ValueError("sortie inconnue")
    os.makedirs(os.path.dirname(CONF), mode=0o700, exist_ok=True)
    with open(CONF, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    if os.path.exists(NO_HDMI):
        os.remove(NO_HDMI)
    choose()


def wait_pipewire():
    for _ in range(15):   # PipeWire peut démarrer juste après la session
        if pactl("info").returncode == 0:
            return True
        time.sleep(1)
    return False


def watch():
    """Branchements et débranchements : nouveau choix 1,5 s après le dernier évènement (le temps qu'ils se calment)"""
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
        time.sleep(3)   # PipeWire relancé : on se réabonne


if __name__ == "__main__":
    if not wait_pipewire():
        sys.exit("audio.py : PipeWire injoignable")
    if sys.argv[1:] == ["watch"]:
        watch()
    else:
        choose()
