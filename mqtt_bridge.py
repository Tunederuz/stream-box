#!/usr/bin/env python3
"""Stream Box : pont MQTT ↔ Home Assistant (découverte automatique).

Lit l'état de la box par l'API de remote.py (http://127.0.0.1:8080), le publie sur MQTT et transforme les commandes
reçues de Home Assistant en appels à cette même API : les vérifications de remote.py s'appliquent donc aussi ici.
Config : ~/.config/stream-box/mqtt.json ({"host", "port", "user"}) et le mot de passe seul dans mqtt-password (600).
Lancé par le service utilisateur stream-box-mqtt, avec le Python du venv media (paho-mqtt).
"""
import json, os, time, urllib.request

import paho.mqtt.client as mqtt

API = "http://127.0.0.1:8080"
CONF_DIR = os.path.expanduser("~/.config/stream-box")
BASE = "stream-box"                 # préfixe des topics de la box
DISCOVERY = "homeassistant"         # préfixe de découverte de Home Assistant
POLL = 2                            # secondes entre deux lectures de l'état
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
        ("switch", "pause", {"name": "Pause", "icon": "mdi:pause", "state_topic": state, "command_topic": cmd("pause"),
                             "value_template": "{{ 'ON' if value_json.pause else 'OFF' }}"}),
        ("number", "volume", {"name": "Volume", "icon": "mdi:volume-high", "min": 0, "max": 130, "step": 5,
                              "unit_of_measurement": "%", "state_topic": state, "command_topic": cmd("volume"),
                              "value_template": "{{ value_json.volume }}"}),
        ("button", "back_to_stream", {"name": "Retour au stream", "icon": "mdi:twitch",
                                      "command_topic": cmd("back_to_stream")}),
        ("button", "go_live", {"name": "Revenir au direct", "icon": "mdi:skip-forward", "command_topic": cmd("go_live")}),
        ("button", "poweroff", {"name": "Éteindre", "icon": "mdi:power",
                                "command_topic": cmd("poweroff")}),
        ("text", "play_url", {"name": "Lire un lien", "icon": "mdi:play-box", "mode": "text", "max": 255,
                              "command_topic": cmd("play"), "state_topic": f"{BASE}/play_url"}),
        ("sensor", "mode", {"name": "Mode", "icon": "mdi:television-play", "state_topic": state,
                            "value_template": "{{ 'Vidéo' if value_json.mode == 'media' else 'Twitch' }}"}),
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
        ("event", "went_live", {"name": "Lancement de live", "icon": "mdi:bell-ring", "event_types": ["went_live"],
                                "state_topic": f"{BASE}/event/went_live"}),
    ]


class Bridge:
    def __init__(self):
        conf = json.load(open(os.path.join(CONF_DIR, "mqtt.json")))
        password = open(os.path.join(CONF_DIR, "mqtt-password")).read().strip()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="stream-box")
        self.client.username_pw_set(conf["user"], password)
        self.client.will_set(f"{BASE}/status", "offline", retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect_async(conf["host"], int(conf.get("port", 1883)))
        self.state, self.published, self.streamers, self.live = {}, None, None, None

    def announce(self):
        for component, object_id, config in entities(self.streamers):
            config = {**config, "unique_id": f"stream_box_{object_id}", "device": DEVICE,
                      "availability_topic": f"{BASE}/status"}
            self.client.publish(f"{DISCOVERY}/{component}/stream_box/{object_id}/config", json.dumps(config), retain=True)

    def on_connect(self, client, userdata, flags, reason, properties=None):
        client.subscribe([(f"{BASE}/cmd/#", 0), (f"{DISCOVERY}/status", 0)])
        client.publish(f"{BASE}/status", "online", retain=True)
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
        s = self.state
        try:
            if command == "channel" and payload in (self.streamers or []):
                api("/api/channel", {"name": payload})
            elif command == "chat" and (payload == "ON") != bool(s.get("chat_visible")):
                api("/api/chat", {})
            elif command == "pause" and (payload == "ON") != bool(s.get("pause")):
                api("/api/pause", {})
            elif command == "volume":
                api("/api/volume", {"delta": max(-20, min(20, round(float(payload)) - int(s.get("volume", 0))))})
            elif command == "back_to_stream":
                api("/api/twitch", {})
            elif command == "go_live":
                api("/api/live_seek", {"delta": "live"})
            elif command == "poweroff":
                api("/api/poweroff", {})
            elif command == "play" and payload:
                api("/api/play", {"url": payload})
                self.client.publish(f"{BASE}/play_url", "", retain=True)
        except (OSError, ValueError) as e:
            print(f"commande {command} refusée : {e}", flush=True)

    def poll(self):
        try:
            s = api("/api/state")
        except (OSError, ValueError):
            return
        self.state = s
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
        public = {k: s.get(k) for k in ("channel", "mode", "title", "chat_visible", "pause", "volume", "playing")}
        public.update(live=sorted(live), delay=None if delay is None else int(delay))
        if public != self.published:
            self.client.publish(f"{BASE}/state", json.dumps(public), retain=True)
            self.published = public

    def run(self):
        self.client.loop_start()
        while True:
            self.poll()
            time.sleep(POLL)


if __name__ == "__main__":
    Bridge().run()
