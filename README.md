# Stream Box

Un mini PC Linux branché sur la TV qui affiche en plein écran le stream Twitch de tes streamers préférés, avec le
chat en overlay, sans bureau ni clavier. On le pilote avec une télécommande Bluetooth, la souris ou une
télécommande web installable sur téléphone (PWA).


## Ce qu'elle fait

- **Stream Twitch en plein écran** (streamlink + mpv, faible latence, pubs sautées), reprise du dernier streamer
  regardé au démarrage, bascule automatique vers un streamer en live si le sien est hors ligne, relance d'un direct
  figé.
- **Chat Twitch en overlay** (lecture anonyme), dans le coin de son choix, avec fond et taille réglables.
- **Retour en arrière dans le direct** (quelques minutes gardées en mémoire), pause en différé.
- **Qui est en live** dans le menu et la télécommande, **notification** quand un streamer de la liste lance son live.
- **Écran d'ambiance** quand rien ne joue : horloge, date, météo et prochains lives prévus (plannings Twitch).
- **Sondages et prédictions** de la chaîne regardée affichés sur la TV, avec le temps restant et les résultats.
- **QR code de la télécommande** sur l'écran d'ambiance et dans le menu, pour les invités.
- **Mode nuit** : son compressé (sons forts atténués, voix remontées) pour regarder à faible volume.
- **Compte Twitch** facultatif : plus de pubs sur les chaînes où l'on est abonné, VOD réservées aux abonnés.
- **Historique et reprise de lecture** : chaque vidéo reprend où on s'était arrêté ; les rediffusions Twitch sont
  synchronisées avec le compte Twitch connecté.
- **Mode vidéo** : liens YouTube et autres (yt-dlp, sous-titres), rediffusions et clips Twitch, partage Android
  « Partager → Stream Box », et **Jellyfin** (« Lire sur… ») via jellyfin-mpv-shim.
- **Télécommande web** : aperçu de l'écran à la demande, streamers et ordre de la liste, chat, volume, barre de lecture, résolution de la TV,
  extinction. **Télécommande Bluetooth** (testé avec celle du Xiaomi TV Stick) et menu à la souris.
- **Session dédiée sans bureau** (compositeur cage) ; écran de connexion normal si un clavier est branché au démarrage.
- **Home Assistant** par la découverte MQTT : contrôle depuis HA, et allumage automatique (Wake-on-LAN) quand un
  streamer lance son live. Voir `docs/home-assistant.md`.
- **Mises à jour hebdomadaires** de streamlink, yt-dlp et du reste, avec retour arrière si un test échoue.

## Comment c'est construit

| Fichier | Rôle |
|---|---|
| `start.sh` | Lancé par la session : chat, télécommande web, résolution, puis boucle sur un mpv permanent |
| `stream-box.lua` | Script mpv : streamlink, menu, modes Twitch / vidéo, différé, barre de lecture, touches |
| `chat_overlay.py` | Chat Twitch (IRC anonyme) affiché dans mpv par son IPC |
| `remote.py` + `remote.html` | Télécommande web (bibliothèque standard Python) et sa page |
| `display.py` | Résolution de la sortie vidéo (wlr-randr), jamais en dessous de 60 Hz |
| `mqtt_bridge.py` | Pont MQTT vers Home Assistant (découverte automatique) |
| `update.sh`, `systemd/` | Mises à jour, jetons anti-robot YouTube, pont MQTT |
| `install.sh`, `backup.sh`, `boot-mode.py` | Installation, mise à jour, sauvegarde ; mode selon le clavier au démarrage |
| `audio.py` | Sortie son sur l'HDMI de la TV au démarrage |
| `CLAUDE.md` | Documentation technique détaillée (décisions, pièges, comment tester) |

## Installation (résumé)

Pensé pour une distribution Arch (testé sur CachyOS) avec Plasma Login comme gestionnaire de connexion. SDDM, dont
Plasma Login dérive, est pris en charge par le script mais n'a pas encore été essayé.

Depuis un compte d'admin, dans une copie du dépôt :

```
git clone https://github.com/Tunederuz/stream-box.git && cd stream-box
sudo bash install.sh --city "Ta ville" --streamers chaine1,chaine2
```

Le script installe les paquets, crée l'utilisateur `media` qui fait tourner la box, y copie le dépôt, installe
streamlink, yt-dlp, jellyfin-mpv-shim et le reste dans des venvs, active les services et met en place la session
sans bureau. Il peut être relancé pour mettre à jour une installation (`git pull`, puis `sudo bash install.sh`).
Les options sont facultatives (`sudo bash install.sh --help`) :

| Option | Rôle |
|---|---|
| `--city VILLE` | Météo de l'écran d'ambiance |
| `--remote-url URL` | Adresse de la télécommande web montrée en QR code (sinon `http://<IP de la box>:8080`) |
| `--streamers a,b,c` | Liste de départ (elle se remplit aussi depuis la télécommande web) |
| `--allow-from IP` | Ouvre le port 8080 à cette adresse (reverse proxy HTTPS) si le pare-feu ufw est actif |
| `--static-ip IP/PRÉFIXE --gateway IP [--dns IP]` | IP fixe sur la connexion Ethernet |
| `--wol` | Wake-on-LAN sur la connexion Ethernet (à activer aussi dans le BIOS) |
| `--restore ARCHIVE` | Remet les réglages et connexions sauvegardés par `backup.sh` |

À la fin, il affiche les réglages restants (compte Twitch, HTTPS, Jellyfin, Home Assistant).

### Sauvegarde et réinstallation

`sudo bash backup.sh` crée une archive de tout ce qui est propre à la box : liste des streamers, réglages, jeton
Twitch, connexion Jellyfin, configuration MQTT et météo, son, appairages Bluetooth. Elle contient des secrets : elle
n'est lisible que par celui qui la crée, et n'a rien à faire dans le dépôt. Après une réinstallation du système :

```
sudo bash install.sh --restore stream-box-backup-AAAA-MM-JJ.tar.gz --static-ip … --gateway … --wol --allow-from …
```

Les détails, et les raisons de chaque choix, sont dans `CLAUDE.md`.
