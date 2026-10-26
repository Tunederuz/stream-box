# Home Assistant

The box announces itself in Home Assistant through **MQTT discovery** (`mqtt_bridge.py`, user service
`stream-box-mqtt`). Config on the box: `~/.config/stream-box/mqtt.json` (`{"host": "<broker-ip>", "port": 1883,
"user": "<user>"}`) and the password alone in `~/.config/stream-box/mqtt-password` (mode 600).

## Entities ("Stream Box" device)

| Entity | Role |
|---|---|
| `select.stream_box_streamer` | Current streamer (options = the box's list) |
| `switch.stream_box_chat`, `switch.stream_box_pause` | Chat shown, pause |
| `switch.stream_box_auto_switch`, `switch.stream_box_night_mode`, `switch.stream_box_polls_and_predictions` | Auto switch, night mode, polls and predictions on screen |
| `select.stream_box_companion_app_qr_code` | Companion app QR code on the TV: Always, 30 seconds, Never |
| `number.stream_box_volume` | mpv volume |
| `button.stream_box_back_to_the_stream`, `button.stream_box_home_screen`, `button.stream_box_go_back_to_live`, `button.stream_box_restart`, `button.stream_box_turn_off` | Actions (back to the stream, home screen, go back to live, restart, turn off) |
| `text.stream_box_play_a_link` | Writing a URL plays it on the TV |
| `sensor.stream_box_mode`, `sensor.stream_box_now_playing`, `sensor.stream_box_live_streamers`, `sensor.stream_box_delay_behind_live` | Status: mode, now playing, live streamers (as attributes), delay behind live |
| `binary_sensor.stream_box_playing` | Something is playing |
| `select.stream_box_power_button` | Action of the "Turn off" button (and of the companion app's): Sleep or Full shutdown |
| `binary_sensor.stream_box_powered_on` | Box powered on: `on` / `off`, never `unavailable` (use it in automations) |
| `event.stream_box_went_live` | A streamer from the list goes live (only when the box is on) |

Entity names (and options) follow the interface language; Home Assistant derives the ids from the names when the
entities are first discovered and keeps them. The ids above are those of a box in English at that time.

**Powered on** (`binary_sensor.stream_box_powered_on`) switches to `on` as soon as the system has started (the MQTT bridge
is connected) and to `off` right away on shutdown (service stopped), when it goes to sleep, or, after a power cut, when the broker
notices the disconnection (last will message). The other entities then switch to `unavailable`. At boot, they only
become available again once the box is ready to receive commands: you can therefore wait for that before choosing the
streamer (a command sent too early is kept for two minutes anyway).

## Turning the box on with the TV

This needs Wake-on-LAN (see below) and a TV that Home Assistant sees turning on (`media_player.<tv>`, or a power
consumption sensor):

```yaml
automation:
  - alias: "Stream Box: turn on with the TV"
    triggers:
      - trigger: state
        entity_id: media_player.<tv>
        from: "off"
    conditions:
      - condition: state
        entity_id: binary_sensor.stream_box_powered_on
        state: "off"
    actions:
      - action: button.press              # button created by the Wake on LAN integration
        target:
          entity_id: button.wake_on_lan_<mac>

  - alias: "Stream Box: turn off with the TV"   # optional
    triggers:
      - trigger: state
        entity_id: media_player.<tv>
        to: "off"
        for: "00:05:00"                   # not for a TV turned off for a minute
    actions:
      # Box still booting (turned on with the TV just before): wait until it is on.
      # wait_template and not wait_for_trigger: the latter waits for a change and sees nothing if it is already on.
      - wait_template: "{{ is_state('binary_sensor.stream_box_powered_on', 'on') }}"
        timeout: "00:05:00"
        continue_on_timeout: false
      - action: button.press             # available as soon as the box is on, even before it is ready
        target:
          entity_id: button.stream_box_turn_off
```

## Turning the box and the TV on when a streamer goes live

A box that is off sees nothing: Home Assistant watches Twitch (**Twitch** integration, sensor `sensor.<streamer>` at
`streaming` / `offline`). The box also needs **Wake-on-LAN**, over Ethernet:

- BIOS: wake on network enabled, deep sleep disabled (on a Dell: *Wake on LAN = LAN Only*,
  *Deep Sleep Control = Disabled*);
- Linux: `sudo bash install.sh --wol` (or `nmcli connection modify "<wired connection>" 802-3-ethernet.wake-on-lan magic`).

In Home Assistant, the simplest is the **Wake on LAN** integration added through the UI (box MAC and network broadcast
address): it creates a button, which can also be used to turn the box on by hand. The
`wake_on_lan.send_magic_packet` action only exists if `wake_on_lan:` is declared in `configuration.yaml` (full restart
required).

```yaml
automation:
  - alias: "Stream Box: turn on when <streamer> goes live"
    triggers:
      - trigger: state
        entity_id: sensor.<streamer>
        to: streaming
    conditions:
      - condition: state            # box off: do not interrupt what is being watched
        entity_id: binary_sensor.stream_box_powered_on
        state: "off"
    actions:
      - action: button.press              # button created by the Wake on LAN integration
        target:
          entity_id: button.wake_on_lan_<mac>
      - action: media_player.turn_on        # optional: the TV, if it can be turned on from Home Assistant
        target:
          entity_id: media_player.<tv>
      - wait_for_trigger:                   # the box is online: its MQTT entities come back
          - trigger: state
            entity_id: select.stream_box_streamer
            from: unavailable
        timeout: "00:04:00"
        continue_on_timeout: false
      - action: select.select_option
        target:
          entity_id: select.stream_box_streamer
        data:
          option: <streamer>
