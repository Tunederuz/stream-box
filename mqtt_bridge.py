#!/usr/bin/env python3
"""Stream Box: MQTT ↔ Home Assistant bridge (automatic discovery).

Reads the box state through remote.py's API (http://127.0.0.1:8080), publishes it on MQTT and turns the commands
received from Home Assistant into calls to that same API: remote.py's checks therefore apply here too.
Config: ~/.config/stream-box/mqtt.json ({"host", "port", "user"}) and the password alone in mqtt-password (600).
Started by the stream-box-mqtt user service, with the Python of the media venv (paho-mqtt).
Entity names and select options are translated (i18n.py) when announced to Home Assistant.
"""
import json, os, signal, subprocess, sys, threading, time, urllib.request

import paho.mqtt.client as mqtt

import i18n
from i18n import tr

API = "http://127.0.0.1:8080"
CONF_DIR = os.path.expanduser("~/.config/stream-box")
BASE = "stream-box"                 # prefix of the box topics
# Powered on: ON as soon as the bridge is connected (system started), OFF through the MQTT last will message (power
# cut) or when the service stops (clean shutdown). "status" also tells whether the box is ready to receive commands.
POWER = f"{BASE}/power"
DISCOVERY = "homeassistant"         # Home Assistant discovery prefix
POLL = 2                            # seconds between two state reads
OFFLINE_AFTER = 30                  # seconds without an API answer before announcing the box offline
PENDING_FOR = 120                   # a command received before the box is ready is kept this long
QR_MODES = {"always": "Always", "timed": "30 seconds", "never": "Never"}   # Home Assistant select (translated with tr)
POWER_MODES = {"suspend": "Sleep", "poweroff": "Full shutdown"}               # action of the "Turn off" button
POWER_ACTION_FILE = os.path.join(CONF_DIR, "power-action")                     # same file as remote.py
DEVICE = {"identifiers": ["stream_box"], "name": "Stream Box", "model": "Stream Box", "manufacturer": "Stream Box"}


def translated(modes):
    """Select options in the current language: {key: translated text}"""
    return {k: tr(v) for k, v in modes.items()}


def mode_key(modes, payload):
    """Key of the option chosen in Home Assistant (translated text, or the English one)"""
    return next((k for k, v in modes.items() if payload in (v, tr(v))), None)


def api(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def entities(streamers):
    """Entities announced to Home Assistant: (component, id, config)."""
    state = f"{BASE}/state"
    def cmd(name): return f"{BASE}/cmd/{name}"
    return [
        ("select", "streamer", {"name": tr("Streamer"), "icon": "mdi:twitch", "options": streamers or ["—"],
                                "state_topic": state, "value_template": "{{ value_json.channel }}",
                                "command_topic": cmd("channel")}),
        ("switch", "chat", {"name": tr("Chat"), "icon": "mdi:chat", "state_topic": state, "command_topic": cmd("chat"),
                            "value_template": "{{ 'ON' if value_json.chat_visible else 'OFF' }}"}),
        ("switch", "auto_switch", {"name": tr("Auto switch"), "icon": "mdi:swap-horizontal",
                                   "state_topic": state, "command_topic": cmd("auto_switch"),
                                   "value_template": "{{ 'ON' if value_json.auto_switch else 'OFF' }}"}),
        ("switch", "night", {"name": tr("Night mode"), "icon": "mdi:weather-night", "state_topic": state,
                             "command_topic": cmd("night"),
                             "value_template": "{{ 'ON' if value_json.night else 'OFF' }}"}),
        ("switch", "events", {"name": tr("Polls and predictions"), "icon": "mdi:poll", "state_topic": state,
                              "command_topic": cmd("events"),
                              "value_template": "{{ 'ON' if value_json.events else 'OFF' }}"}),
        ("select", "qr", {"name": tr("Companion app QR code"), "icon": "mdi:qrcode",
                          "options": list(translated(QR_MODES).values()),
                          "state_topic": state, "command_topic": cmd("qr"),
                          "value_template": "{{ %s.get(value_json.qr, '') }}" % json.dumps(translated(QR_MODES))}),
        ("switch", "pause", {"name": tr("Pause"), "icon": "mdi:pause", "state_topic": state, "command_topic": cmd("pause"),
                             "value_template": "{{ 'ON' if value_json.pause else 'OFF' }}"}),
        ("number", "volume", {"name": tr("Volume"), "icon": "mdi:volume-high", "min": 0, "max": 130, "step": 5,
                              "unit_of_measurement": "%", "state_topic": state, "command_topic": cmd("volume"),
                              "value_template": "{{ value_json.volume }}"}),
        ("button", "back_to_stream", {"name": tr("Back to the stream"), "icon": "mdi:twitch",
                                      "command_topic": cmd("back_to_stream")}),
        ("button", "home", {"name": tr("Home screen"), "icon": "mdi:home", "command_topic": cmd("home")}),
        ("button", "go_live", {"name": tr("Go back to live"), "icon": "mdi:skip-forward", "command_topic": cmd("go_live")}),
        ("button", "reboot", {"name": tr("Restart"), "icon": "mdi:restart", "command_topic": cmd("reboot")}),
        ("button", "poweroff", {"name": tr("Turn off"), "icon": "mdi:power",   # sleep or full shutdown, depending on the setting
                                "command_topic": cmd("poweroff")}),
        ("select", "power_action", {"name": tr("Power button"), "icon": "mdi:power-sleep",
                                    "options": list(translated(POWER_MODES).values()), "state_topic": state,
                                    "command_topic": cmd("power_action"),
                                    "value_template": "{{ %s.get(value_json.power_action, '') }}"
                                                      % json.dumps(translated(POWER_MODES))}),
        ("text", "play_url", {"name": tr("Play a link"), "icon": "mdi:play-box", "mode": "text", "max": 255,
                              "command_topic": cmd("play"), "state_topic": f"{BASE}/play_url"}),
        ("sensor", "mode", {"name": tr("Mode"), "icon": "mdi:television-play", "state_topic": state,
                            "value_template": "{{ %s.get(value_json.mode, 'Twitch') }}" % json.dumps(
                                {"media": tr("Video"), "home": tr("Home")})}),
        ("sensor", "now_playing", {"name": tr("Now playing"), "icon": "mdi:play", "state_topic": state,
                                   "value_template": "{{ value_json.title or value_json.channel or '' }}"}),
        ("sensor", "live_count", {"name": tr("Live streamers"), "icon": "mdi:access-point", "state_topic": state,
                                  "value_template": "{{ value_json.live | count }}",
                                  "json_attributes_topic": f"{BASE}/live"}),
        ("sensor", "delay", {"name": tr("Delay behind live"), "icon": "mdi:history", "unit_of_measurement": "s",
                             "device_class": "duration", "state_topic": state,
                             "value_template": "{{ value_json.delay if value_json.delay is not none else 0 }}"}),
        ("binary_sensor", "playing", {"name": tr("Playing"), "icon": "mdi:play-circle", "state_topic": state,
                                      "value_template": "{{ 'ON' if value_json.playing else 'OFF' }}"}),
        # No "availability": OFF when the box is off, instead of "unavailable" (reliable automations)
        ("binary_sensor", "power", {"name": tr("Powered on"), "device_class": "power", "state_topic": POWER,
                                    "payload_on": "ON", "payload_off": "OFF"}),
        ("event", "went_live", {"name": tr("Went live"), "icon": "mdi:bell-ring", "event_types": ["went_live"],
                                "state_topic": f"{BASE}/event/went_live"}),
    ]


class Bridge:
    def __init__(self):
        conf = json.load(open(os.path.join(CONF_DIR, "mqtt.json")))
        password = open(os.path.join(CONF_DIR, "mqtt-password")).read().strip()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="stream-box")
        self.client.username_pw_set(conf["user"], password)
        self.client.will_set(POWER, "OFF", retain=True)   # power cut, crash: the broker announces the box as off
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect_async(conf["host"], int(conf.get("port", 1883)))
        self.state, self.published, self.streamers, self.live = {}, None, None, None
        # "Online" only when the API answers: at boot, the bridge is ready well before mpv and remote.py, and
        # Home Assistant would send its commands into the void
        self.available, self.last_ok, self.pending = False, time.time(), []
        self.language = i18n.language()   # language of the announced names: announced again when it changes

    def announce(self):
        self.language = i18n.language()
        for component, object_id, config in entities(self.streamers):
            config = {**config, "unique_id": f"stream_box_{object_id}", "device": DEVICE}
            powered = {"topic": POWER, "payload_available": "ON", "payload_not_available": "OFF"}
            if object_id == "poweroff":   # as soon as the box is on, even in the middle of booting
                config.update(availability=[powered])
            elif object_id != "power":   # available when the box is on and ready
                config.update(availability=[{"topic": f"{BASE}/status"}, powered], availability_mode="all")
            self.client.publish(f"{DISCOVERY}/{component}/stream_box/{object_id}/config", json.dumps(config), retain=True)

    def on_connect(self, client, userdata, flags, reason, properties=None):
        client.subscribe([(f"{BASE}/cmd/#", 0), (f"{DISCOVERY}/status", 0)])
        client.publish(POWER, "ON", retain=True)
        client.publish(f"{BASE}/status", "online" if self.available else "offline", retain=True)
        self.published = None   # publish the state again after a reconnection
        if self.streamers is not None:
            self.announce()

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", "replace").strip()
        if msg.topic == f"{DISCOVERY}/status":
            if payload == "online":   # Home Assistant restarted: announce again
                self.announce()
                self.published = None
            return
        command = msg.topic.rsplit("/", 1)[1]
        if command == "poweroff":   # without waiting for the box to be ready (neither mpv nor remote.py is needed)
            return self.poweroff()
        if not self.available:
            self.pending.append((time.time(), command, payload))   # applied as soon as the box is ready
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
            elif command == "power_action" and mode_key(POWER_MODES, payload):
                api("/api/power_action", {"mode": mode_key(POWER_MODES, payload)})
            elif command == "qr" and mode_key(QR_MODES, payload):
                api("/api/qr", {"mode": mode_key(QR_MODES, payload)})
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
            print(f"command {command} refused: {e}", flush=True)

    def poll(self):
        try:
            s = api("/api/state")
        except (OSError, ValueError):
            if self.available and time.time() - self.last_ok > OFFLINE_AFTER:
                self.available = False
                self.client.publish(f"{BASE}/status", "offline", retain=True)
            return
        self.state, self.last_ok = s, time.time()
        if s.get("streamers") != self.streamers:   # list changed: new options for the select
            self.streamers = s.get("streamers")
            self.announce()
        elif i18n.language() != self.language:   # language changed: names announced again
            self.announce()
            self.published = None
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
        # Ready when mpv's Lua script runs (it publishes the current channel): before that, its messages would be lost
        ready = s.get("channel") is not None or not s.get("streamers")
        if ready and not self.available:   # box ready: announce it, then apply what was waiting
            self.available = True
            self.client.publish(f"{BASE}/status", "online", retain=True)
            pending, self.pending = self.pending, []
            for received, command, payload in pending:
                if time.time() - received < PENDING_FOR:
                    self.run_command(command, payload)

    def poweroff(self):
        """"Turn off" button: sleep or full shutdown depending on the setting (power-action file)"""
        try:
            with open(POWER_ACTION_FILE, encoding="utf-8") as f:
                suspend = f.readline().strip() == "suspend"
        except OSError:
            suspend = False
        if suspend:
            # Through remote.py, which runs in the session (sleep allowed by default for an active local session); the
            # sensor goes OFF through watch_sleep. Box not ready yet: systemctl, allowed by the polkit rule.
            try:
                api("/api/poweroff", {"mode": "suspend"})
                return
            except (OSError, ValueError):
                pass
        else:
            self.off()
        r = subprocess.run(["systemctl", "suspend" if suspend else "poweroff"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            print(f"{'suspend' if suspend else 'poweroff'} refused: {r.stderr.strip() or r.returncode}", flush=True)
            self.client.publish(POWER, "ON", retain=True)

    def watch_sleep(self):
        """Sleep (whatever its origin: menu, companion app, Home Assistant): Powered on goes OFF before, then ON on
        wake-up. A logind "delay" lock holds off the sleep while the message is sent; logind signals PrepareForSleep
        (true before, false after), followed through gdbus."""
        while True:
            lock = subprocess.Popen(["systemd-inhibit", "--what=sleep", "--mode=delay", "--who=Stream Box MQTT",
                                     "--why=Announce sleep to Home Assistant", "sleep", "infinity"])
            mon = subprocess.Popen(["gdbus", "monitor", "--system", "--dest", "org.freedesktop.login1",
                                    "--object-path", "/org/freedesktop/login1"], stdout=subprocess.PIPE, text=True)
            for line in mon.stdout:
                if "PrepareForSleep (true" in line:
                    self.off()
                    lock.terminate()   # sleep allowed
                elif "PrepareForSleep (false" in line:
                    self.client.publish(POWER, "ON", retain=True)
                    self.client.publish(f"{BASE}/status", "online" if self.available else "offline", retain=True)
                    self.published = None   # publish the state again on wake-up
                    break
            mon.terminate()
            lock.terminate()
            time.sleep(1)

    def off(self):
        """Box shutting down: announced right away, without waiting for the broker to notice the disconnection"""
        self.client.publish(f"{BASE}/status", "offline", retain=True)
        try:
            self.client.publish(POWER, "OFF", retain=True).wait_for_publish(3)
        except (RuntimeError, ValueError):   # not connected: the last will message will do
            pass

    def stop(self, *_):   # service stop (shutdown, restart): OFF, then clean disconnection
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
