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
- **Compte Twitch** facultatif : plus de pubs sur les chaînes où l'on est abonné, VOD réservées aux abonnés.
- **Mode vidéo** : liens YouTube et autres (yt-dlp, sous-titres), rediffusions et clips Twitch, partage Android
  « Partager → Stream Box », et **Jellyfin** (« Lire sur… ») via jellyfin-mpv-shim.
- **Télécommande web** : streamers et ordre de la liste, chat, volume, barre de lecture, résolution de la TV,
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
| `setup-*.sh`, `boot-mode.py` | Installation : session dédiée, mode selon le clavier, extinction depuis la page |
| `CLAUDE.md` | Documentation technique détaillée (décisions, pièges, comment tester) |

## Installation (résumé)

Pensé pour une distribution Arch (testé sur CachyOS) avec Plasma Login comme gestionnaire de connexion.

1. Copier le dépôt dans `/home/media/stream-box` et `streamers.example.txt` en `streamers.txt` (un pseudo par ligne).
2. Depuis le compte d'admin : `sudo bash setup-session.sh` (crée l'utilisateur `media`, installe cage, streamlink et
   la session dédiée), puis `sudo bash setup-boot-mode.sh` et `sudo bash setup-poweroff.sh`.
3. Pour le mode vidéo et Home Assistant : un venv `~/.local/share/media-venv` avec `yt-dlp[default] deno
   nodejs-wheel bgutil-ytdlp-pot-provider jellyfin-mpv-shim paho-mqtt`, et les unités de `systemd/` dans
   `~/.config/systemd/user/` (mises à jour, jetons anti-robot YouTube, pont MQTT).
4. Pour la télécommande web en HTTPS (nécessaire à l'installation de la PWA sur Android) : un reverse proxy vers le
   port 8080.

Les détails, et les raisons de chaque choix, sont dans `CLAUDE.md`.
