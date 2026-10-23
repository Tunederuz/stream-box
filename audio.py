#!/usr/bin/env python3
"""Stream Box : au démarrage, sortie son sur l'HDMI (la TV) si elle est disponible et pas déjà choisie.

Un nouvel utilisateur démarre souvent sur la sortie analogique (haut-parleur interne) : on bascule la carte son sur
son profil HDMI et on en fait la sortie par défaut. Ne fait rien si la sortie par défaut est déjà en HDMI, ni si
~/.config/stream-box/no-hdmi-audio existe (choix manuel à respecter). Lancé par start.sh ; utilise pactl (PipeWire).
"""
import json, os, subprocess, sys, time

if os.path.exists(os.path.expanduser("~/.config/stream-box/no-hdmi-audio")):
    sys.exit()


def pactl(*args):
    # En anglais : les descriptions traduites donnent des avertissements « Invalid ASCII character » en JSON
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=10,
                          env={**os.environ, "LC_ALL": "C"})


def default_sink():
    # « pactl get-default-sink » peut répondre « @DEFAULT_SINK@ » avec PipeWire : on lit « pactl info »
    for line in pactl("info").stdout.splitlines():
        if line.lower().startswith("default sink:"):
            return line.split(":", 1)[1].strip()
    return ""


for _ in range(10):   # PipeWire peut démarrer juste après la session
    if pactl("info").returncode == 0:
        break
    time.sleep(1)
else:
    sys.exit("audio.py : PipeWire injoignable")

if "hdmi" in default_sink().lower():
    sys.exit()

try:
    cards = json.loads(pactl("--format=json", "list", "cards").stdout or "[]")
except ValueError:
    sys.exit("audio.py : liste des cartes illisible")
for card in cards:
    profiles = card.get("profiles") or {}
    hdmi = [name for name, p in profiles.items()
            if name.startswith("output:hdmi-stereo") and p.get("available", True) and "input:" not in name]
    if not hdmi:
        continue
    profile = "output:hdmi-stereo" if "output:hdmi-stereo" in hdmi else sorted(hdmi)[0]
    pactl("set-card-profile", card["name"], profile)
    time.sleep(1)
    sinks = [l.split("\t")[1] for l in pactl("list", "sinks", "short").stdout.splitlines() if "hdmi" in l.lower()]
    if sinks:
        pactl("set-default-sink", sinks[0])
        print(f"audio.py : sortie HDMI ({card['name']}, {profile})")
    break
