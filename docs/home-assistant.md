# Home Assistant

La box s'annonce toute seule dans Home Assistant par la **découverte MQTT** (`mqtt_bridge.py`, service utilisateur
`stream-box-mqtt`). Config sur la box : `~/.config/stream-box/mqtt.json` (`{"host": "<ip-broker>", "port": 1883,
"user": "<utilisateur>"}`) et le mot de passe seul dans `~/.config/stream-box/mqtt-password` (mode 600).

## Entités (appareil « Stream Box »)

| Entité | Rôle |
|---|---|
| `select.stream_box_streamer` | Streamer en cours (options = la liste de la box) |
| `switch.stream_box_chat`, `switch.stream_box_pause` | Chat affiché, pause |
| `number.stream_box_volume` | Volume de mpv |
| `button.stream_box_retour_au_stream`, `button.stream_box_revenir_au_direct`, `button.stream_box_eteindre` | Actions |
| `text.stream_box_lire_un_lien` | Écrire une URL la lance sur la TV |
| `sensor.stream_box_mode`, `sensor.stream_box_en_cours`, `sensor.stream_box_streamers_en_live`, `sensor.stream_box_retard_sur_le_direct` | État (les streamers en live en attributs) |
| `binary_sensor.stream_box_lecture` | Quelque chose joue |
| `event.stream_box_lancement_de_live` | Un streamer de la liste lance son live (seulement quand la box est allumée) |

Quand la box est éteinte, toutes ses entités passent à `unavailable` (message de dernière volonté MQTT).

## Allumer la box et la TV quand un streamer lance son live

La box éteinte ne voit rien : c'est Home Assistant qui surveille Twitch (intégration **Twitch**, capteur
`sensor.<streamer>` à `streaming` / `offline`). Il faut aussi le **Wake-on-LAN** sur la box (BIOS + carte réseau, en
Ethernet) et l'intégration `wake_on_lan` dans Home Assistant.

```yaml
automation:
  - alias: "Stream Box : allumer quand <streamer> lance son live"
    triggers:
      - trigger: state
        entity_id: sensor.<streamer>
        to: streaming
    conditions:
      - condition: state            # box éteinte : on ne coupe pas ce qui est en train d'être regardé
        entity_id: select.stream_box_streamer
        state: unavailable
    actions:
      - action: wake_on_lan.send_magic_packet
        data:
          mac: "<mac-ethernet-de-la-box>"
      - action: media_player.turn_on        # facultatif : la TV, si elle s'allume depuis Home Assistant
        target:
          entity_id: media_player.<tv>
      - wait_for_trigger:                   # la box est en ligne : ses entités MQTT reviennent
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
