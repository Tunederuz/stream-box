# Home Assistant

La box s'annonce toute seule dans Home Assistant par la **découverte MQTT** (`mqtt_bridge.py`, service utilisateur
`stream-box-mqtt`). Config sur la box : `~/.config/stream-box/mqtt.json` (`{"host": "<ip-broker>", "port": 1883,
"user": "<utilisateur>"}`) et le mot de passe seul dans `~/.config/stream-box/mqtt-password` (mode 600).

## Entités (appareil « Stream Box »)

| Entité | Rôle |
|---|---|
| `select.stream_box_streamer` | Streamer en cours (options = la liste de la box) |
| `switch.stream_box_chat`, `switch.stream_box_pause` | Chat affiché, pause |
| `switch.stream_box_auto_switch`, `switch.stream_box_night`, `switch.stream_box_events` | Bascule automatique, mode nuit, sondages et prédictions à l'écran |
| `select.stream_box_qr` | QR code de la télécommande sur la TV : Toujours, 30 secondes, Jamais |
| `number.stream_box_volume` | Volume de mpv |
| `button.stream_box_retour_au_stream`, `button.stream_box_revenir_au_direct`, `button.stream_box_eteindre` | Actions |
| `text.stream_box_lire_un_lien` | Écrire une URL la lance sur la TV |
| `sensor.stream_box_mode`, `sensor.stream_box_en_cours`, `sensor.stream_box_streamers_en_live`, `sensor.stream_box_retard_sur_le_direct` | État (les streamers en live en attributs) |
| `binary_sensor.stream_box_lecture` | Quelque chose joue |
| `binary_sensor.stream_box_allumee` | Box allumée : `on` / `off`, jamais `unavailable` (à utiliser dans les automatisations) |
| `event.stream_box_lancement_de_live` | Un streamer de la liste lance son live (seulement quand la box est allumée) |

**Allumée** passe à `on` dès que le système a démarré (le pont MQTT est connecté) et à `off` tout de suite à l'extinction
(arrêt du service) ou, en cas de coupure, quand le broker constate la déconnexion (message de dernière volonté). Les
autres entités passent alors à `unavailable`. Au démarrage,
elles ne redeviennent disponibles qu'une fois la box prête à recevoir des commandes : on peut donc attendre ce retour
avant de choisir le streamer (une commande envoyée trop tôt est de toute façon gardée deux minutes).

## Allumer la box avec la TV

Il faut le Wake-on-LAN (voir plus bas) et une TV que Home Assistant voit s'allumer (`media_player.<tv>`, ou un
capteur de consommation) :

```yaml
automation:
  - alias: "Stream Box : allumer avec la TV"
    triggers:
      - trigger: state
        entity_id: media_player.<tv>
        from: "off"
    conditions:
      - condition: state
        entity_id: binary_sensor.stream_box_allumee
        state: "off"
    actions:
      - action: button.press              # bouton créé par l'intégration Wake on LAN
        target:
          entity_id: button.wake_on_lan_<mac>

  - alias: "Stream Box : éteindre avec la TV"   # facultatif
    triggers:
      - trigger: state
        entity_id: media_player.<tv>
        to: "off"
        for: "00:05:00"                   # pas pour une TV éteinte une minute
    actions:
      # Box encore en train de démarrer (allumée avec la TV juste avant) : on attend qu'elle soit allumée.
      # wait_template et pas wait_for_trigger : celui-ci attend un changement et ne voit rien si elle l'est déjà.
      - wait_template: "{{ is_state('binary_sensor.stream_box_allumee', 'on') }}"
        timeout: "00:05:00"
        continue_on_timeout: false
      - action: button.press             # disponible dès que la box est allumée, même avant qu'elle soit prête
        target:
          entity_id: button.stream_box_eteindre
```

## Allumer la box et la TV quand un streamer lance son live

La box éteinte ne voit rien : c'est Home Assistant qui surveille Twitch (intégration **Twitch**, capteur
`sensor.<streamer>` à `streaming` / `offline`). Il faut aussi le **Wake-on-LAN** sur la box, en Ethernet :

- BIOS : réveil par le réseau activé, veille profonde désactivée (sur un Dell : *Wake on LAN = LAN Only*,
  *Deep Sleep Control = Disabled*) ;
- Linux : `sudo bash install.sh --wol` (ou `nmcli connection modify "<connexion filaire>" 802-3-ethernet.wake-on-lan magic`).

Dans Home Assistant, le plus simple est l'intégration **Wake on LAN** ajoutée par l'interface (MAC de la box et
adresse de diffusion du réseau) : elle crée un bouton, qui sert aussi à allumer la box à la main. L'action
`wake_on_lan.send_magic_packet` n'existe que si `wake_on_lan:` est déclaré dans `configuration.yaml` (redémarrage
complet nécessaire).

```yaml
automation:
  - alias: "Stream Box : allumer quand <streamer> lance son live"
    triggers:
      - trigger: state
        entity_id: sensor.<streamer>
        to: streaming
    conditions:
      - condition: state            # box éteinte : on ne coupe pas ce qui est en train d'être regardé
        entity_id: binary_sensor.stream_box_allumee
        state: "off"
    actions:
      - action: button.press              # bouton créé par l'intégration Wake on LAN
        target:
          entity_id: button.wake_on_lan_<mac>
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
