#!/usr/bin/env python3
"""Stream Box : pont MQTT ↔ Home Assistant (découverte automatique).

Lit l'état de la box par l'API de remote.py (http://127.0.0.1:8080), le publie sur MQTT et transforme les commandes
reçues de Home Assistant en appels à cette même API : les vérifications de remote.py s'appliquent donc aussi ici.
Config : ~/.config/stream-box/mqtt.json ({"host", "port", "user"}) et le mot de passe seul dans mqtt-password (600).
Lancé par le service utilisateur stream-box-mqtt, avec le Python du venv media (paho-mqtt).
"""
import json, os, signal, subprocess, sys, threading, time, urllib.request

import paho.mqtt.client as mqtt

API = "http://127.0.0.1:8080"
CONF_DIR = os.path.expanduser("~/.config/stream-box")
BASE = "stream-box"                 # préfixe des topics de la box
# Allumée : ON dès que le pont est connecté (système démarré), OFF par le message de dernière volonté MQTT (coupure)
# ou à l'arrêt du service (extinction propre). « status » dit en plus si la box est prête à recevoir des commandes.
POWER = f"{BASE}/power"
DISCOVERY = "homeassistant"         # préfixe de découverte de Home Assistant
POLL = 2                            # secondes entre deux lectures de l'état
OFFLINE_AFTER = 30                  # secondes sans réponse de l'API avant d'annoncer la box hors ligne
PENDING_FOR = 120                   # une commande reçue avant que la box soit prête est gardée ce temps-là
QR_MODES = {"always": "Toujours", "timed": "30 secondes", "never": "Jamais"}   # select de Home Assistant
POWER_MODES = {"suspend": "Mise en veille", "poweroff": "Arrêt complet"}       # action du bouton « Éteindre »
POWER_ACTION_FILE = os.path.join(CONF_DIR, "power-action")                     # même fichier que remote.py
DEVICE = {"identifiers": ["stream_box"], "name": "Stream Box", "model": "Stream Box", "manufacturer": "Stream Box"}


def api(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def entities(streamers):
    """Entités annoncées à Home Assistant : (composant, identifiant, config)."""
    state = f"{BASE}/state"
    def cmd(name): return f"{BASE}/cmd/{name}"
    return [
        ("select", "streamer", {"name": "Streamer", "icon": "mdi:twitch", "options": streamers or ["—"],
                                "state_topic": state, "value_template": "{{ value_json.channel }}",
                                "command_topic": cmd("channel")}),
        ("switch", "chat", {"name": "Chat", "icon": "mdi:chat", "state_topic": state, "command_topic": cmd("chat"),
                            "value_template": "{{ 'ON' if value_json.chat_visible else 'OFF' }}"}),
        ("switch", "auto_switch", {"name": "Bascule automatique", "icon": "mdi:swap-horizontal",
                                   "state_topic": state, "command_topic": cmd("auto_switch"),
                                   "value_template": "{{ 'ON' if value_json.auto_switch else 'OFF' }}"}),
        ("switch", "night", {"name": "Mode nuit", "icon": "mdi:weather-night", "state_topic": state,
                             "command_topic": cmd("night"),
                             "value_template": "{{ 'ON' if value_json.night else 'OFF' }}"}),
        ("switch", "events", {"name": "Sondages et prédictions", "icon": "mdi:poll", "state_topic": state,
                              "command_topic": cmd("events"),
                              "value_template": "{{ 'ON' if value_json.events else 'OFF' }}"}),
        ("select", "qr", {"name": "QR code de la télécommande", "icon": "mdi:qrcode", "options": list(QR_MODES.values()),
                          "state_topic": state, "command_topic": cmd("qr"),
                          "value_template": "{{ %s.get(value_json.qr, '') }}" % json.dumps(QR_MODES)}),
        ("switch", "pause", {"name": "Pause", "icon": "mdi:pause", "state_topic": state, "command_topic": cmd("pause"),
                             "value_template": "{{ 'ON' if value_json.pause else 'OFF' }}"}),
        ("number", "volume", {"name": "Volume", "icon": "mdi:volume-high", "min": 0, "max": 130, "step": 5,
                              "unit_of_measurement": "%", "state_topic": state, "command_topic": cmd("volume"),
                              "value_template": "{{ value_json.volume }}"}),
        ("button", "back_to_stream", {"name": "Retour au stream", "icon": "mdi:twitch",
                                      "command_topic": cmd("back_to_stream")}),
        ("button", "home", {"name": "Écran d'accueil", "icon": "mdi:home", "command_topic": cmd("home")}),
        ("button", "go_live", {"name": "Revenir au direct", "icon": "mdi:skip-forward", "command_topic": cmd("go_live")}),
        ("button", "reboot", {"name": "Redémarrer", "icon": "mdi:restart", "command_topic": cmd("reboot")}),
        ("button", "poweroff", {"name": "Éteindre", "icon": "mdi:power",   # veille ou arrêt complet, selon le réglage
                                "command_topic": cmd("poweroff")}),
        ("select", "power_action", {"name": "Bouton d'arrêt", "icon": "mdi:power-sleep",
                                    "options": list(POWER_MODES.values()), "state_topic": state,
                                    "command_topic": cmd("power_action"),
                                    "value_template": "{{ %s.get(value_json.power_action, '') }}" % json.dumps(POWER_MODES)}),
        ("text", "play_url", {"name": "Lire un lien", "icon": "mdi:play-box", "mode": "text", "max": 255,
                              "command_topic": cmd("play"), "state_topic": f"{BASE}/play_url"}),
        ("sensor", "mode", {"name": "Mode", "icon": "mdi:television-play", "state_topic": state,
                            "value_template": "{{ {'media': 'Vidéo', 'home': 'Accueil'}.get(value_json.mode, 'Twitch') }}"}),
        ("sensor", "now_playing", {"name": "En cours", "icon": "mdi:play", "state_topic": state,
                                   "value_template": "{{ value_json.title or value_json.channel or '' }}"}),
        ("sensor", "live_count", {"name": "Streamers en live", "icon": "mdi:access-point", "state_topic": state,
                                  "value_template": "{{ value_json.live | count }}",
                                  "json_attributes_topic": f"{BASE}/live"}),
        ("sensor", "delay", {"name": "Retard sur le direct", "icon": "mdi:history", "unit_of_measurement": "s",
                             "device_class": "duration", "state_topic": state,
                             "value_template": "{{ value_json.delay if value_json.delay is not none else 0 }}"}),
        ("binary_sensor", "playing", {"name": "Lecture", "icon": "mdi:play-circle", "state_topic": state,
                                      "value_template": "{{ 'ON' if value_json.playing else 'OFF' }}"}),
        # Pas d'« availability » : OFF quand la box est éteinte, au lieu d'« indisponible » (automatisations fiables)
        ("binary_sensor", "power", {"name": "Allumée", "device_class": "power", "state_topic": POWER,
                                    "payload_on": "ON", "payload_off": "OFF"}),
        ("event", "went_live", {"name": "Lancement de live", "icon": "mdi:bell-ring", "event_types": ["went_live"],
                                "state_topic": f"{BASE}/event/went_live"}),
    ]


class Bridge:
    def __init__(self):
        conf = json.load(open(os.path.join(CONF_DIR, "mqtt.json")))
        password = open(os.path.join(CONF_DIR, "mqtt-password")).read().strip()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="stream-box")
        self.client.username_pw_set(conf["user"], password)
        self.client.will_set(POWER, "OFF", retain=True)   # coupure, plantage : le broker annonce la box éteinte
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect_async(conf["host"], int(conf.get("port", 1883)))
        self.state, self.published, self.streamers, self.live = {}, None, None, None
        # « En ligne » seulement quand l'API répond : au démarrage, le pont est prêt bien avant mpv et remote.py, et
        # Home Assistant enverrait ses commandes dans le vide
        self.available, self.last_ok, self.pending = False, time.time(), []

    def announce(self):
        for component, object_id, config in entities(self.streamers):
            config = {**config, "unique_id": f"stream_box_{object_id}", "device": DEVICE}
            powered = {"topic": POWER, "payload_available": "ON", "payload_not_available": "OFF"}
            if object_id == "poweroff":   # dès que la box est allumée, même en plein démarrage
                config.update(availability=[powered])
            elif object_id != "power":   # disponibles quand la box est allumée et prête
                config.update(availability=[{"topic": f"{BASE}/status"}, powered], availability_mode="all")
            self.client.publish(f"{DISCOVERY}/{component}/stream_box/{object_id}/config", json.dumps(config), retain=True)

    def on_connect(self, client, userdata, flags, reason, properties=None):
        client.subscribe([(f"{BASE}/cmd/#", 0), (f"{DISCOVERY}/status", 0)])
        client.publish(POWER, "ON", retain=True)
        client.publish(f"{BASE}/status", "online" if self.available else "offline", retain=True)
        self.published = None   # republier l'état après une reconnexion
        if self.streamers is not None:
            self.announce()

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", "replace").strip()
        if msg.topic == f"{DISCOVERY}/status":
            if payload == "online":   # Home Assistant redémarré : il faut se réannoncer
                self.announce()
                self.published = None
            return
        command = msg.topic.rsplit("/", 1)[1]
        if command == "poweroff":   # sans attendre que la box soit prête (ni mpv ni remote.py n'en ont besoin)
            return self.poweroff()
        if not self.available:
            self.pending.append((time.time(), command, payload))   # appliquée dès que la box est prête
            return
        self.run_command(command, payload)

    def run_command(self, command, payload):
        s = self.state
        try:
            if command == "channel" and payload in (self.streamers or []):
                api("/api/channel", {"name": payload})
            elif command == "chat" and (payload == "ON") != bool(s.get("chat_visible")):
                api("/api/chat", {})
            elif command == "auto_switch":
                api("/api/auto_switch", {"enabled": payload == "ON"})
            elif command == "power_action" and payload in POWER_MODES.values():
                api("/api/power_action", {"mode": next(k for k, v in POWER_MODES.items() if v == payload)})
            elif command == "qr" and payload in QR_MODES.values():
                api("/api/qr", {"mode": next(k for k, v in QR_MODES.items() if v == payload)})
            elif command in ("night", "events"):
                api("/api/flag", {"key": command, "enabled": payload == "ON"})
            elif command == "pause" and (payload == "ON") != bool(s.get("pause")):
                api("/api/pause", {})
            elif command == "volume":
                api("/api/volume", {"delta": max(-20, min(20, round(float(payload)) - int(s.get("volume", 0))))})
            elif command == "reboot":
                api("/api/reboot", {})
            elif command == "back_to_stream":
                api("/api/twitch", {})
            elif command == "home":
                api("/api/home", {})
            elif command == "go_live":
                api("/api/live_seek", {"delta": "live"})
            elif command == "play" and payload:
                api("/api/play", {"url": payload})
                self.client.publish(f"{BASE}/play_url", "", retain=True)
        except (OSError, ValueError) as e:
            print(f"commande {command} refusée : {e}", flush=True)

    def poll(self):
        try:
            s = api("/api/state")
        except (OSError, ValueError):
            if self.available and time.time() - self.last_ok > OFFLINE_AFTER:
                self.available = False
                self.client.publish(f"{BASE}/status", "offline", retain=True)
            return
        self.state, self.last_ok = s, time.time()
        if s.get("streamers") != self.streamers:   # liste modifiée : nouvelles options du sélecteur
            self.streamers = s.get("streamers")
            self.announce()
        live = s.get("live") or {}
        if self.live is not None:
            for login in live:
                if login not in self.live:
                    info = live[login]
                    self.client.publish(f"{BASE}/event/went_live", json.dumps(
                        {"event_type": "went_live", "streamer": login, "title": info.get("title"),
                         "game": info.get("game"), "viewers": info.get("viewers")}))
        if live != self.live:
            self.client.publish(f"{BASE}/live", json.dumps(live), retain=True)
        self.live = live
        delay = s.get("delay")
        public = {k: s.get(k) for k in ("channel", "mode", "title", "chat_visible", "pause", "volume", "playing",
                                        "auto_switch", "night", "events", "qr", "power_action")}
        public.update(live=sorted(live), delay=None if delay is None else int(delay))
        if public != self.published:
            self.client.publish(f"{BASE}/state", json.dumps(public), retain=True)
            self.published = public
        # Prête quand le script Lua de mpv tourne (il publie la chaîne en cours) : avant, ses messages seraient perdus
        ready = s.get("channel") is not None or not s.get("streamers")
        if ready and not self.available:   # box prête : on l'annonce, puis on applique ce qui attendait
            self.available = True
            self.client.publish(f"{BASE}/status", "online", retain=True)
            pending, self.pending = self.pending, []
            for received, command, payload in pending:
                if time.time() - received < PENDING_FOR:
                    self.run_command(command, payload)

    def poweroff(self):
        """Bouton « Éteindre » : mise en veille ou arrêt complet selon le réglage (fichier power-action)"""
        try:
            with open(POWER_ACTION_FILE, encoding="utf-8") as f:
                suspend = f.readline().strip() == "suspend"
        except OSError:
            suspend = False
        if suspend:
            # Par remote.py, qui tourne dans la session (veille permise d'office à une session locale active) ; le
            # capteur passe à OFF par watch_sleep. Box pas encore prête : systemctl, permis par la règle polkit.
            try:
                api("/api/poweroff", {"mode": "suspend"})
                return
            except (OSError, ValueError):
                pass
        else:
            self.off()
        r = subprocess.run(["systemctl", "suspend" if suspend else "poweroff"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            print(f"{'mise en veille' if suspend else 'extinction'} refusée : {r.stderr.strip() or r.returncode}", flush=True)
            self.client.publish(POWER, "ON", retain=True)

    def watch_sleep(self):
        """Mise en veille (quelle qu'en soit l'origine : menu, page, Home Assistant) : Allumée passe à OFF avant, puis à
        ON au réveil. Un verrou « delay » de logind retarde la veille le temps d'envoyer le message ; logind signale
        PrepareForSleep (true avant, false après), suivi par gdbus."""
        while True:
            lock = subprocess.Popen(["systemd-inhibit", "--what=sleep", "--mode=delay", "--who=Stream Box MQTT",
                                     "--why=Annoncer la mise en veille à Home Assistant", "sleep", "infinity"])
            mon = subprocess.Popen(["gdbus", "monitor", "--system", "--dest", "org.freedesktop.login1",
                                    "--object-path", "/org/freedesktop/login1"], stdout=subprocess.PIPE, text=True)
            for line in mon.stdout:
                if "PrepareForSleep (true" in line:
                    self.off()
                    lock.terminate()   # veille autorisée
                elif "PrepareForSleep (false" in line:
                    self.client.publish(POWER, "ON", retain=True)
                    self.client.publish(f"{BASE}/status", "online" if self.available else "offline", retain=True)
                    self.published = None   # republier l'état au réveil
                    break
            mon.terminate()
            lock.terminate()
            time.sleep(1)

    def off(self):
        """Box qui s'éteint : annoncée tout de suite, sans attendre que le broker constate la coupure"""
        self.client.publish(f"{BASE}/status", "offline", retain=True)
        try:
            self.client.publish(POWER, "OFF", retain=True).wait_for_publish(3)
        except (RuntimeError, ValueError):   # pas connecté : le message de dernière volonté fera l'affaire
            pass

    def stop(self, *_):   # arrêt du service (extinction, redémarrage) : OFF, puis déconnexion propre
        try:
            self.off()
            self.client.disconnect()
        finally:
            sys.exit(0)

    def run(self):
        signal.signal(signal.SIGTERM, self.stop)
        threading.Thread(target=self.watch_sleep, daemon=True).start()
        self.client.loop_start()
        while True:
            self.poll()
            time.sleep(POLL)


if __name__ == "__main__":
    Bridge().run()
