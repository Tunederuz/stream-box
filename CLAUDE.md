# Stream Box

> Les valeurs entre chevrons (`<ip-box>`…) et les domaines `example.com` sont propres à chaque installation. Les
> détails d'une installation donnée (réseau, matériel, comptes) vont dans `CLAUDE.local.md`, non versionné.

Mini PC Linux branché sur la TV. Au démarrage, il affiche le grand menu (page principale, fond animé, rien en lecture) ; un stream Twitch se regarde avec le chat
en overlay. Quand la souris bouge (ou avec une télécommande Bluetooth), un menu permet de changer de streamer et de
régler le chat. Une télécommande web (installable comme appli) fait la même chose depuis un téléphone, et plus encore.
Installation et mise à jour : `install.sh` (voir le README) ; sauvegarde des réglages : menu Système de la TV et page web (`backup.py`), ou `backup.sh`.

## Système
- **Distribution Arch** (testé sur CachyOS). La box tourne sous l'utilisateur dédié **`media`** (shell bash, pas de mot
  de passe ; `install.sh` lui copie la clé SSH du compte d'admin : `ssh media@<ip-box>`). Un compte d'admin avec sudo
  sert à la maintenance.
- **Session dédiée sans bureau** : le gestionnaire de connexion (Plasma Login, ou SDDM) connecte automatiquement `media`
  dans la session `/usr/share/wayland-sessions/stream-box.desktop` → `cage -s -- /home/media/stream-box/start.sh`
  (cage = compositeur Wayland « kiosque » ; `-s` garde Ctrl+Alt+F2 pour une console). Pour retrouver le bureau :
  démarrer avec un clavier branché et se connecter avec le compte d'admin.
- **Mode selon le clavier** : `stream-box-boot-mode.service` (root, avant le gestionnaire de connexion) lance
  `/usr/local/lib/stream-box/boot-mode.py` (copie root de `boot-mode.py`, installée par `install.sh`, qui lui passe
  `--dropin` selon le gestionnaire de connexion). Un périphérique avec des touches de lettres (Q, A, Z, espace) =
  clavier. Sans clavier, il écrit `<dossier .conf.d>/50-stream-box.conf` (autologin media + session Stream Box). Avec
  clavier, il le supprime et l'écran de connexion s'affiche. Le fichier de config principal ne doit pas contenir de
  section `[Autologin]` : elle passerait avant le dossier `.conf.d` (`install.sh` la retire, avec une sauvegarde
  `.bak-stream-box`). Le choix se fait au démarrage seulement. Après une modification de `boot-mode.py`, relancer
  `install.sh` (ou recopier en root). Test : `boot-mode.py --dry-run`.
- Sans bureau, le bouton power est géré par logind (`HandlePowerKey=poweroff` par défaut) : extinction directe.
- **Son** : `audio.py` (lancé par `start.sh`) bascule la carte son sur son profil HDMI et en fait la sortie par défaut
  si la sortie actuelle n'est pas déjà en HDMI : un nouvel utilisateur démarre souvent sur le haut-parleur interne.
  `~/.config/stream-box/no-hdmi-audio` désactive ce choix. WirePlumber mémorise ensuite profil et volume
  (`~media/.local/state/wireplumber/`).
- **Réseau** : de préférence en Ethernet avec une IP fixe (`install.sh --static-ip … --gateway …`), indispensable pour
  le Wake-on-LAN (`--wol`, et l'option correspondante dans le BIOS).
- **Pare-feu** : si ufw est actif, le port 8080 de la télécommande web doit être ouvert au reverse proxy
  (`install.sh --allow-from <ip-proxy>`).
- **HTTPS** : un reverse proxy (par exemple Nginx Proxy Manager) vers `http://<ip-box>:8080` avec un certificat,
  sur un nom qui peut ne se résoudre qu'en DNS local. Nécessaire pour installer la télécommande sur Android.
- Pas de sudo sans mot de passe pour `media`. mpv et cage viennent des paquets du système.

## Fichiers (`/home/media/stream-box/`)
- `start.sh` : attend le réseau (`getent hosts www.twitch.tv`), lance `chat_overlay.py` et `remote.py` en arrière-plan,
  puis boucle sur un mpv **permanent** (`--idle --force-window --fs --osc=no`, IPC `/tmp/stream-box-mpv.sock`,
  script `stream-box.lua`). La boucle relance mpv s'il est fermé, et tue d'abord les streamlink restés orphelins.
- `stream-box.lua` (script mpv) :
  - lance streamlink en mode serveur HTTP local (`--player-external-http`, 127.0.0.1, port 34501–34550 qui change
    à chaque chaîne) avec `--twitch-low-latency --retry-streams 30`, puis `loadfile http://127.0.0.1:<port>/` ;
  - si la chaîne n'est pas en live : écran noir avec « <pseudo> n'est pas en live », nouvel essai toutes les 15 s ;
  - menu au mouvement de la souris (masqué après 4 s) : streamers en grille (plusieurs colonnes et police réduite
    s'il y en a beaucoup), puis une ligne pour le chat : case à cocher pour l'afficher ou le masquer, et un bouton
    qui le fait tourner entre les 4 coins (↖ ↗ ↘ ↙) ;
  - publie `user-data/streambox/{channel,corner,chat_visible}` pour `chat_overlay.py` ;
  - script-messages pour la télécommande : `streambox-channel <pseudo>`, `streambox-toggle-chat`, `streambox-cycle-corner` ;
  - désactive le double-clic plein écran.
- `chat_overlay.py` : chat Twitch en anonyme (IRC TLS, pseudo `justinfanNNNN`, lecture seule). Il suit les
  propriétés `user-data/streambox/*` de mpv (`observe_property`) : il change de salon quand la chaîne change, et il
  vide les messages à ce moment-là. Il garde les 10 derniers messages (45 s max) et les envoie à mpv avec
  `osd-overlay` (`ass-events`, résolution 1920x1080). Fond noir semi-transparent (opacité `chat_bg`, marge `BG_PADDING`) : le texte
  est d'abord rendu caché avec `compute_bounds` pour mesurer sa taille, puis le fond (overlay 2, z=0) est dessiné sous
  le texte (overlay 1, z=1). Il gère `CLEARMSG` / `CLEARCHAT`. Bibliothèque standard uniquement.
- `remote.py` : télécommande web sur le port 8080 (bibliothèque standard, `ThreadingHTTPServer`). Sert `remote.html`
  et les fichiers PWA (`manifest.webmanifest`, `sw.js`, `icon-*.png`). API : `GET /api/state`,
  `POST /api/{channel,chat,corner,set,display,volume,mute,pause,poweroff}`, `GET /api/display`. Elle ouvre une connexion IPC par requête. Le volume est
  celui de mpv, pas celui du système.
- Compte Twitch (section de la page, `POST /api/login|logout`, `GET /api/account`) : le jeton du site (cookie
  `auth-token`) est écrit dans `~media/.config/streamlink/config.twitch` (`twitch-api-header=Authorization=OAuth …`,
  mode 600), que streamlink lit tout seul. C'est le seul jeton qui retire les pubs des chaînes où l'on est abonné
  (les jetons OAuth d'applis tierces ne le font pas). Il est vérifié via `id.twitch.tv/oauth2/validate` à
  l'enregistrement puis toutes les 30 min. **Un jeton refusé bloque toute lecture** (« Unauthorized ») : s'il
  expire, `remote.py` le supprime et relance le stream en anonyme. Sans jeton, streamlink saute les pubs et
  l'image se fige pendant leur durée. Le jeton est aussi écrit en cookie pour yt-dlp
  (`~media/.config/stream-box/twitch-cookies.txt`, option `cookies` de `ytdl-raw-options`) pour les VOD réservées
  aux abonnés. yt-dlp réécrit ce fichier en 644 à chaque lecture : c'est le dossier (700) qui le protège.
- Réglages du chat dans la page : opacité du fond (`chat_bg`, 0–100 %, défaut 60) et taille du texte (`chat_size`,
  20–60 px en 1920x1080, défaut 32). `POST /api/set` → script-message `streambox-set <clé> <valeur>` → `set_number` dans
  stream-box.lua (bornes, fichier d'état, `user-data/streambox/*`), que `chat_overlay.py` observe.
- Résolution : `display.py` (wlr-randr, que cage gère ; paquet `wlr-randr` à installer). Seuls les modes ≥ 59 Hz sont
  proposés : beaucoup de mini PC ne sortent le 4K qu'en **30 Hz** en HDMI, ce qui jette une image sur deux des streams
  à 60 i/s.
  « auto » = mode préféré de la TV s'il est à 60 Hz, sinon la plus grande définition à 60 Hz. Réglage dans
  `~media/.local/state/stream-box/display_mode`, appliqué par `start.sh` avant mpv et en direct depuis la page.
- **Mode Média** (stream-box.lua, `user-data/streambox/mode` = `twitch` | `media`) : tout fichier qui n'est pas le flux
  streamlink (lien envoyé, Jellyfin) arrête streamlink et passe en `media` ; le chat est masqué. Fin de fichier puis
  mpv vide pendant `BACK_TO_MENU` (3 s) → plus rien en lecture, grand menu (le délai laisse Jellyfin enchaîner l'épisode suivant).
  Script-messages `streambox-play <url>`, `streambox-twitch`. Un crochet `on_load` (avant l'ouverture de chaque fichier,
  y compris ceux de Jellyfin) règle `demuxer-max-bytes` (750 KiB pour le direct, 150 MiB pour les vidéos) et remet
  `hwdec=auto-safe` : le shim impose sa propre valeur de `hwdec` en s'accrochant (défaut `"no"`, réglé à `auto-safe`
  dans sa `conf.json`). `--ytdl-format` : par défaut 1440p max et **pas d'AV1**, que beaucoup d'iGPU ne décodent
  pas en matériel (le VP9 et le H.264 passent par le décodage matériel) ; une autre règle peut être mise dans
  `~/.config/stream-box/ytdl-format`. Avec yt-dlp, YouTube n'envoie pas de pub. Sous-titres : `--ytdl-raw-options-append` avec
  `sub-langs=fr,fr-FR,fr-orig,en,en-US,en-GB,en-orig` + `write-subs`/`write-auto-subs` (`fr.*` ramènerait plus de 100
  traductions automatiques). À chaud, passer `ytdl-raw-options` en objet JSON : la forme texte est coupée aux virgules.
  Les sous-titres **automatiques** (`kind=asr`) ont des répliques qui se chevauchent (deux toujours à l'écran) :
  à `file-loaded` en mode média, stream-box.lua les remplace par `http://127.0.0.1:8080/subs?u=<url>` (remote.py coupe
  chaque réplique au début de la suivante), en EDL `delay_open` pour ne télécharger que la piste choisie : YouTube
  répond 429 aux rafales, surtout pour les traductions automatiques (`tlang`). yt-dlp et jellyfin-mpv-shim sont dans `~media/.local/share/media-venv` (liens dans
  `~/.local/bin`, mise à jour : `…/media-venv/bin/pip install -U yt-dlp jellyfin-mpv-shim`).
- Page : bloc replié « Lire un lien sur la TV » (`POST /api/play {url}`, `/api/twitch`) et cible de partage Android
  (`share_target` du manifeste → `GET /share?title&text&url`, premier lien http(s) trouvé, puis redirection vers `/`).
- Jellyfin (jellyfin.example.com) : jellyfin-mpv-shim en mode mpv externe (`mpv_ext`, `mpv_ext_start=false`,
  `mpv_ext_ipc=/tmp/stream-box-mpv.sock`, `mpv_ext_no_ovr`, `enable_gui=false`, `mpv_idle_quit=false`) pilote le mpv de la
  box ; dans ce mode il ne ferme jamais mpv. Connecté au compte Jellyfin de l'utilisateur (Quick Connect ; identifiants
  dans `~media/.config/jellyfin-mpv-shim/users.json`), pour que la progression suive ce compte. Relancé par `start.sh`
  à chaque (re)lancement de mpv (il ne se raccroche pas seul à un mpv relancé), journal dans `/tmp/jellyfin-shim.log`.
  La pause de mpv survit au changement de fichier : `load_stream` la retire, sinon le direct reste figé. Pour se reconnecter : `jellyfin-mpv-shim clear`, puis
  `jellyfin-mpv-shim --no-gui --server https://jellyfin.example.com --quick-connect` et approuver le code affiché.
- **Qui est en live** : `remote.py` interroge Twitch (GQL, client-id public du site) chaque minute pour toute la
  liste (avec les photos de profil, `avatars` de `/api/state`, et la miniature du live, `thumb`, pour la page), publie le résultat dans `user-data/streambox/live` (menu de la TV : point rouge + spectateurs) et le renvoie
  dans `/api/state` (page : spectateurs, jeu, titre). Après un redémarrage de mpv, le menu le reçoit au relevé suivant.
- **Bascule automatique** (stream-box.lua, `auto_switch`, désactivable : onglet Réglages → Lecture, `POST /api/auto_switch
  {enabled}`, interrupteur MQTT, état dans `user-data/streambox/auto_switch` et le fichier d'état `auto_switch`) : si
  la chaîne en cours est hors ligne et qu'elle a été
  choisie il y a plus d'`AUTO_SWITCH` (60 s), la box passe au premier streamer en live dans l'ordre de `streamers.txt`.
- **Chien de garde** : direct dont `playback-time` n'avance plus depuis `FROZEN` (20 s), sans pause → la chaîne est
  relancée. Testé en gelant streamlink (`kill -STOP`).
- **YouTube et les jetons anti-robot** : yt-dlp a besoin d'un moteur JavaScript (**Deno**, paquet pip `deno` +
  `yt-dlp[default]` pour `yt-dlp-ejs`, lien dans `~/.local/bin`) et d'un **PO token** pour les sous-titres. Sans
  jeton, YouTube finit par bloquer l'IP publique de la maison sur `timedtext` (HTTP 429, page « Sorry… »), et un
  jeton valide n'y change rien tant que le blocage dure (quelques heures). Jetons : plugin pip
  `bgutil-ytdlp-pot-provider` + son serveur (même version, `~/.local/share/bgutil-pot-provider`, compilé avec Node
  du paquet pip `nodejs-wheel`), service utilisateur `stream-box-pot` (127.0.0.1:4416). mpv passe
  `extractor-args=youtube:player_client=tv_simply,android_vr;fetch_pot=always` : le client TV choisi par défaut
  recevait des flux refusés (HTTP 403 sur googlevideo, même en IPv4 de bout en bout). Si YouTube recasse, comparer
  les clients avec `yt-dlp --extractor-args youtube:player_client=<client> -g <url>` puis `curl -r 0-1000` sur l'URL. Vérifier : `yt-dlp -v --simulate <url>` → `PO Token Providers: bgutil:http`.
- **Retour en arrière dans le direct** : `on_load` garde `LIVE_BACK` (400 MiB ≈ 7-8 min en 1080p60) avec
  `demuxer-seekable-cache=yes`. `live_window()` lit `demuxer-cache-state.seekable-ranges`. En différé ou en pause,
  `set_live_buffer` passe le tampon avant à 150 MiB (sinon mpv cesse de lire le flux et le retard fond) ; retour au
  direct → 750 KiB. Télécommande Bluetooth : ←/→ ±10 s. Page : −30 s / +30 s / Direct
  (`POST /api/live_seek {delta|"live"}` → script-message `streambox-live-seek`), retard dans `/api/state` (`delay`).
  La barre de lecture affiche « −0:42 » ou « ● EN DIRECT ».
- **Notification de live** : `remote.py` repère les streamers qui viennent de passer en live (pas au premier relevé)
  → script-message `streambox-went-live <pseudo>` → bandeau en haut à droite 12 s ; OK y va, Retour le ferme.
- **Rediffusions et clips** : `GET /api/replays?login=` (GQL, 8 VOD + 6 clips de la semaine, cache 5 min), bloc
  replié dans la page ; un appui lance la vidéo via `/api/play`.
- **Liste des streamers depuis la page** : bloc « Gérer la liste » (`POST /api/streamers {action: add|remove,
  login}`) ; l'ajout vérifie que la chaîne existe sur Twitch, les commentaires de `streamers.txt` sont conservés.
- **Home Assistant (MQTT)** : `mqtt_bridge.py`, service utilisateur `stream-box-mqtt` (Python du venv media, paho-mqtt).
  Lit `/api/state` toutes les 2 s et publie `stream-box/state` (+ `stream-box/live`, `stream-box/status` online/offline
  en dernière volonté) ; les commandes `stream-box/cmd/*` deviennent des appels à l'API de `remote.py`. Le pont démarre
  bien avant mpv : il n'annonce `online` qu'une fois l'API prête et le Lua chargé (chaîne publiée), et garde 2 min les
  commandes reçues avant (sinon le choix du streamer envoyé par HA au réveil était perdu). 19 entités par
  découverte (`homeassistant/…/stream_box/…`), réannoncées quand HA redémarre ou que la liste change. Config locale
  `~/.config/stream-box/mqtt.json` + `mqtt-password` (600). Entités et automatisation d'exemple : `docs/home-assistant.md`.
- **Écran d'accueil à la demande** : mode `home` (`show_home`, script-message `streambox-home`, `POST /api/home`,
  bouton dans la page au-dessus des streamers, première ligne du menu de la TV, bouton MQTT) : stream arrêté, écran d'ambiance affiché, pas
  de bascule automatique ni de chien de garde ; on en sort en choisissant un streamer ou une vidéo, ou par Jellyfin.
- **Écran d'ambiance** (stream-box.lua, `draw_ambient`) quand rien ne joue (chaîne hors ligne, liste vide, mode `home`) : horloge,
  date en français, météo, prochains lives prévus, et le message d’état en petit en bas, sur un fond « aurore » (`AURORA` :
  trois taches très floues qui dérivent, redessinées toutes les 2 s, ~2 % de CPU). Le texte se déplace un peu chaque
  minute (TV). Données de `remote.py` (`ambient_loop`, toutes les 10 min, republiées toutes les 10 s dans
  `user-data/streambox/ambient`) : météo Open-Meteo (lieu dans `~/.config/stream-box/ambient.json`, `city`,
  `latitude`, `longitude`, `timezone` ; sans ce fichier, pas de météo) et plannings Twitch (GQL `schedule.segments`,
  créneaux de la semaine en cours : un créneau passé est reporté d'une semaine ; créneaux annulés (`isCancelled`)
  ignorés ; pendant une pause Twitch (`schedule.interruption`, les vacances du streamer) : « en pause jusqu'au … » ; au-delà
  d'une semaine, la date est ajoutée au jour ; calcul testable dans `next_streams`). Les captures de mpv sont vides quand
  rien ne joue : vérifier l'écran sur la TV.
- **QR code de la télécommande** (invités) : `remote.py` (`remote_qr`) le calcule avec segno (venv media, appelé en
  sous-processus : `remote.py` tourne avec le Python du système) pour l'adresse de `~/.config/stream-box/remote-url`
  (option `--remote-url` d'install.sh ; sinon `http://<IP de la box>:8080`, que le pare-feu peut bloquer), et le publie
  dans `user-data/streambox/ambient` (`qr` : adresse + lignes de « 0 »/« 1 »). `qr_code()` du Lua le dessine en un
  seul tracé ASS, en gris clair (moins marquant que du blanc) : en bas à droite de l'écran d'ambiance (il dérive avec
  le reste) et à droite du menu quand l'écran d'ambiance n'est pas affiché.
  Affichage réglable (Réglages → Affichage, `POST /api/qr {mode}`, select MQTT, script-message `streambox-qr`, fichier
  d'état `qr`) : `always`, `timed` (`QR_SECONDS` = 30 s à chaque arrivée sur l'écran d'ambiance et ouverture du menu),
  `never` ; le test se fait dans `qr_code()`.
- **Sondages et prédictions** (`remote.py`, `events_loop` / `fetch_events`) : plus de PubSub pour un spectateur, donc
  relevé GQL toutes les 10 s, seulement pendant un direct de la liste avec l'encart activé : `user.viewablePoll`
  (sondage en cours ou terminé ; pas d'heure de fin, on montre le résultat 60 s après l'avoir vu terminé),
  `channel.activePredictionEvents`, `lockedPredictionEvents`, et `resolvedPredictionEvents(first:1)` (résultat montré
  60 s après `endedAt`). Publié dans `user-data/streambox/polls` (ne pas confondre avec `user-data/streambox/events`, le
  réglage). Encart en haut au centre (`draw_events`, redessiné chaque seconde pour le temps restant), loin des coins du
  chat. Réglage oui/non `events` (Réglages → Lecture, interrupteur MQTT). Les prédictions se lisent sans compte ; aucun
  sondage n'était ouvert sur ~280 lives au moment des tests, l'affichage a été vérifié avec des données simulées
  (`set_property user-data/streambox/polls …` par l'IPC).
- **Mode nuit** : filtre audio `@night:lavfi=[acompressor=…,alimiter=…]` ajouté/retiré par le Lua (réglage `night`,
  bouton dans Télécommande → Lecture, interrupteur MQTT). `af` est une option globale de mpv : il reste d'un fichier à
  l'autre, Jellyfin compris. Réglages oui/non : script-message `streambox-flag <clé> yes|no`, `POST /api/flag {key,
  enabled}`, état dans `user-data/streambox/<clé>` et le fichier d'état du même nom.
- **Historique et reprise** (`remote.py`, `play` / `history_loop`) des vidéos lancées depuis la télécommande (liens,
  YouTube, rediffusions et clips Twitch ; Jellyfin gère sa progression). Clé stable par vidéo (`media_key` : id
  YouTube, id de VOD, slug de clip), historique dans `~media/.local/state/stream-box/history.json` (60 entrées).
  Position notée toutes les 10 s ; reprise si > 30 s et pas « vue » (à moins de 30 s de la fin ou au-delà de 95 %),
  donnée à mpv comme option `start=` du fichier (`streambox-play <url> <début>`). **Rediffusions Twitch synchronisées
  avec le compte** : position lue au lancement (`video.self.viewingHistory`, la plus récente l'emporte sur celle de la
  box) et écrite toutes les 30 s et à l'arrêt (mutation `updateUserViewedVideo`). YouTube : impossible de synchroniser
  avec le compte (pas d'API ; yt-dlp ne sait que marquer « vu »), la mémoire reste sur la box. Page : bloc Historique
  (Reprendre / Depuis le début / ✕, tout effacer) et barres de progression dans les rediffusions (`GET /api/history`,
  `POST /api/history {action: remove|clear}`, `POST /api/play {url, from_start}`). Limite connue : certaines
  rediffusions Twitch (playlist `EVENT`) démarrent une minute après le début même sans reprise, mpv nu compris.
- **Aperçu de la TV** dans la page (bloc replié, onglet Télécommande) : `GET /api/preview` →
  écran entier par **grim** (protocole wlr-screencopy de cage : écran d'ambiance, menu et bandeaux compris, réduit à
  960 px par `-s`) ; faute de grim, `screenshot-to-file … window` de mpv réduit par ffmpeg. Une
  capture à la fois, gardée 1 s pour plusieurs téléphones. La page en redemande une 1,5 s après chaque réponse,
  seulement tant que le bloc est ouvert et visible. Sans grim et sans vidéo : réponse 204.
- **Mises à jour** : `update.sh` (timer systemd utilisateur `stream-box-update.timer`, lundi ~5 h, rattrapé au démarrage)
  met à jour streamlink, yt-dlp, Deno, Node, le plugin de jetons et jellyfin-mpv-shim (et recompile le serveur de jetons si sa version change), teste chaque venv et remet les versions d'avant si le test
  échoue. Journal : `~media/.local/state/stream-box/update.log`.
- **git** : `/home/media/stream-box` est un dépôt git (pas de secret dedans : jeton Twitch et identifiants Jellyfin
  sont ailleurs). Committer après chaque modification.
- **Télécommande Bluetooth** (testé avec celle du Xiaomi TV Stick, appairée et de confiance pour `media`). Linux la
  voit comme un clavier sans les touches Q et A : la règle de démarrage ne la prend pas pour un vrai clavier. Une autre
  télécommande qui annoncerait ces touches est à ajouter à `IGNORE` dans `boot-mode.py`. cage transmet ses touches à mpv ; stream-box.lua les lie (`KEYS`, `on_key`) : OK = `0x21ffa0`, Menu ≡ =
  `0x2111a0` (codes de la télécommande Xiaomi : à adapter pour une autre), Retour = `GO_BACK`, Accueil = `HOMEPAGE`, flèches, volume (actions par défaut de mpv). Menu fermé en
  Twitch : haut/bas zappent, OK affiche/retire le bandeau d'infos (titre, « EN DIRECT » ou retard), Accueil ouvre
  le grand menu (OK aussi sur l'écran d'accueil ; le petit menu ne sert plus qu'à la souris), Menu ≡ affiche/masque le chat. Dans tous les modes : WWW (le bouton
  « navigateur ») affiche l'écran d'accueil, Play (`PLAY`/`PLAYPAUSE`, lié exprès : sinon mpv met en pause, ce qui
  figeait le direct) fait changer le chat de coin. En vidéo : OK pause, ←/→ ±10 s,
  ↑ affiche/retire la barre de lecture (↓ la retire), Menu ≡ change de sous-titres. Menu ouvert : flèches = sélection (le bouton
  le plus proche dans la direction), OK valide, Retour/Accueil ferment. Power éteint la box (logind).
  Appairage : mettre la télécommande en mode appairage (Xiaomi : Accueil + Retour jusqu'au clignotement), puis
  `bluetoothctl` → `scan on`, `pair`, `trust`. Les appairages sont dans la sauvegarde de `backup.sh`.
- **Barre de lecture des vidéos** (stream-box.lua, `draw_bar`) façon YouTube : bandeau en bas (titre, partie lue en
  violet, partie chargée, temps). Affichée `BAR_SECONDS` (5 s) par ↑, ←/→ ou OK ; ↑ ou ↓ la retirent ; toujours
  visible pendant la pause (symbole pause dessiné). Préférée à l'OSC de mpv, désactivée (`--osc=no`) car pensée
  pour la souris et en conflit avec notre menu.
- Icône d'extinction en haut à droite de la page (confirmation « Éteindre la box ? ») → `POST /api/poweroff` →
  `systemctl poweroff` en tant que media. Autorisé sans mot de passe par `/etc/polkit-1/rules.d/50-stream-box.rules`
  (installée par `install.sh`), y compris quand une autre session est ouverte (SSH).
- PWA : grâce au HTTPS du reverse proxy, Chrome Android propose « Installer l'application » ; sur iPhone, « Sur l'écran
  d'accueil ». En HTTP direct (:8080), Android ne donnerait qu'un raccourci.
- `streamers.txt` : un pseudo par ligne, `#` pour les commentaires. Relu à chaque ouverture du menu, pas besoin de redémarrer.

## État conservé (`~media/.local/state/stream-box/`)
- `channel` : dernier streamer regardé, chaîne courante au démarrage (« Reprendre … » du menu, Retour au stream) s'il est encore dans `streamers.txt` (sinon le premier).
- `chat_corner` : `tl` / `tr` / `br` / `bl`.
- `chat_visible` : `yes` / `no`.
- `chat_bg`, `chat_size` : nombres. `display_mode` : `auto` ou `LxH@Hz`.

## streamlink
Installé dans un venv `~/.local/share/streamlink-venv`, avec un lien dans `~/.local/bin/streamlink` (`start.sh` ajoute
`~/.local/bin` au PATH). Le paquet du système n'est pas utilisé : il est souvent en retard, et le module Twitch casse
quand Twitch change quelque chose. Mise à jour : `~/.local/share/streamlink-venv/bin/pip install -U streamlink`.

## Pièges connus
- La connexion IPC à mpv doit rester ouverte : mpv retire l'overlay quand le client se déconnecte.
- Les couleurs ASS sont en BGR (`&HBBGGRR&`). Le texte est échappé comme dans les scripts intégrés de mpv
  (`\` → `\` + U+FEFF, `{` → `\{`). Les pseudos trop sombres sont remplacés par du lavande (#C9B8FF).
- Les glyphes ☐/☑ ne sont pas dans toutes les polices : la case à cocher est dessinée en ASS.
- `pkill -f <motif>` lancé en SSH peut se tuer lui-même, parce que sa propre ligne de commande contient le motif.
  Utiliser `pkill -f "[c]hat_overlay"`.

## Tester à distance
- `start.sh` est lancé par cage : tuer mpv (`pkill -u media -x mpv`) le relance avec le nouveau `stream-box.lua`.
  Pour `remote.py` ou `chat_overlay.py`, les tuer puis les relancer avec `nohup` (ou redémarrer la box).
- Déployer par renommage (copie dans un dossier temporaire puis `mv`), pas en écrasant : bash relit `start.sh`
  pendant qu'il tourne.
- Simuler la souris par l'IPC : `{"command":["mouse",x,y]}` pour bouger, `["mouse",x,y,0,"single"]` pour cliquer.
  Les coordonnées sont en pixels de l'écran (`osd-dimensions`).
- Captures : `["screenshot-to-file","/tmp/x.png","window"]`. Elles sortent vides tant qu'aucune vidéo ne joue.
- Quelqu'un peut cliquer devant la TV pendant un test : l'état peut changer pendant que tu testes.

## Pistes
- Emotes en image (`overlay-add` avec des bitmaps BGRA bruts) : nettement plus complexe.
- Indiquer dans le menu qui est en live.

## Page web (remote.html)

Thème sombre en verre dépoli (glassmorphism : cartes et onglets translucides `backdrop-filter`, sur des taches de
couleur qui dérivent en `body::before/::after` ; le fond est sur `html`, sinon celui de `body` les cache), sans
dépendance externe, onglets collés en haut : en-tête avec l'état de la TV, carte « Sur la TV »
(miniature du live, streamer, titre, retour en arrière ; compacte pour l'écran d'accueil et une chaîne hors ligne),
streamers en cartes avec photo (anneau rouge en live), boutons à icônes SVG en ligne, interrupteurs (`button.toggle`
avec `aria-pressed`, dessinés en CSS). Version précédente de la page : tag git `page-v1` (`git show
page-v1:remote.html > remote.html` pour revenir en arrière). Pour juger d'un changement sans téléphone : copie de la
page avec un `render(<état de /api/state>)` à la place de `refresh()`, capturée par `firefox --headless --screenshot`
(il n'attend pas les requêtes de la page ; ne pas faire défiler : les éléments collés s'y dessinent mal).

## Grand menu de la TV (tv_menu.lua)

Façon Android TV, ouvert par le bouton Menu de la télécommande (touche Accueil) dans tous les modes : onglets à gauche
(En direct, Suivis, Rediffusions, Historique, Réglages, Système), contenu à droite, vidéo assombrie derrière, refermé par Menu, Retour depuis les
onglets, ou au bout de 90 s sans touche. Script séparé, chargé par `start.sh` (`--script` en second). Tant qu'il est
ouvert (`user-data/streambox/tvmenu`, que `chat_overlay.py` suit aussi pour masquer le chat, sinon dessiné
par-dessus), `stream-box.lua` lui transmet toutes les touches (`streambox-tvmenu-key`) ;
il lit l'état et agit par l'API de `remote.py` (curl en sous-processus), comme la page web. Réglages : ◀ ▶ changent
une valeur, OK bascule un interrupteur ; la résolution choisie aux flèches ne s'applique qu'à OK. En direct : raccourcis
au-dessus des streamers (écran d'accueil, « Reprendre <streamer> » hors du stream ; ▲ depuis la première rangée).
Système : état du compte, extinction (OK deux fois), QR code de la télécommande web pour ce qui
demande de taper du texte. Photos : images brutes posées par `overlay-add` (au-dessus du dessin ASS, coordonnées en
pixels de l'écran), préparées par `GET /api/tvimage?src=&w=&h=&round=` (ffmpeg : recadrage, disque à bord adouci,
BGRA à alpha prémultiplié, cache `/tmp/stream-box-images`, seulement les serveurs d'images Twitch et YouTube).
Tester : `keypress HOMEPAGE`, `keypress DOWN`… par l'IPC, puis `/api/preview`. Pour recharger le script sans
redémarrer la session : relancer mpv puis `load-script` une seule fois (un second `load-script` en ferait deux).
Rediffusions : puces des streamers (défilement à la largeur), puis rangées « Rediffusions » et « Clips de la
semaine » de `/api/replays` (4 cartes visibles, ◀ ▶ défilent). Historique : grille de `/api/history`, 2 rangées
visibles. Cartes vidéo : miniature à coins arrondis (`radius` de `/api/tvimage`), barre de progression et textes
dessous (rien ne se dessine sur une image posée). OK sur une vidéo commencée ouvre une fenêtre d'actions (Reprendre à
…, Depuis le début, et Retirer de l'historique dans l'historique) ; les images sont retirées tant qu'elle est ouverte,
sinon elles passeraient par-dessus. La miniature d'un live en cours (`vod-secure.twitch.tv`, image « en cours de
traitement ») n'est pas autorisée : la carte garde son ▶ dessiné.
Finitions : halo violet flou autour de l'élément choisi (`focus_ring`), textes trop longs qui défilent après une
pause (`marquee` : largeur estimée à 0,52 em par caractère, `\clip` à la largeur, redessin à 15 images/s seulement
tant qu'un texte défile, reparti du début à chaque touche ; menu ouvert ≈ +30 % d'un cœur), « En cours sur la TV »
en bas du rail, météo de l'écran d'ambiance à côté de l'heure, carte du streamer regardé teintée de violet. Textes
dimensionnés pour une TV vue du canapé (titres de cartes vidéo 33 px, infos 27 px, en 1920x1080).

## Chaînes suivies (onglet Suivis)

Twitch refuse la liste des chaînes suivies au jeton du site : GQL `currentUser.follows` / `followedLiveUsers` →
« service error » (probablement réservé au vrai navigateur, contrôle d'intégrité), Helix → « Missing scope:
user:read:follows ». D'où une appli Twitch à soi (dev.twitch.tv/console/apps, redirect `http://localhost` jamais
utilisée, type Public sans secret ou Confidentiel avec secret) et l'autorisation par code (device code flow) :
`POST /api/follows_login` → code à taper sur twitch.tv/activate (affiché sur la TV avec un QR code, et dans la page),
`follows_poll` attend la validation, jetons dans `~/.config/stream-box/twitch-follows-token.json` (600, renouvelés par
refresh token ; retirés si Twitch refuse). Config de l'appli : `twitch-app.json` (600), écrite par la page
(`POST /api/follows_app {client_id, client_secret?}`, Réglages → Chaînes suivies). `GET /api/follows` : état et listes
(Helix `streams/followed`, `channels/followed` jusqu'à 500, photos par `users`), cache 60 s. `/api/channel` accepte
aussi une chaîne suivie. Sur la TV : grille comme En direct (live d'abord), OK regarde, ou propose « Ajouter à ma
liste » si la chaîne n'y est pas. `GET /api/qr?text=` : QR code générique (segno).

## Appli Qt qui embarque mpv (ui.py, player.sh)

Pour un menu rendu par la puce graphique (animations fluides) et, plus tard, deux vidéos à la fois, la fenêtre de la
session cage n'est plus forcément mpv : `ui.py` est une appli Qt Quick (PySide6, venv `~/.local/share/ui-venv`) qui
fait dessiner la vidéo par libmpv (render API OpenGL, python-mpv) dans un `QQuickFramebufferObject` (`MpvVideo`,
scène `ui.qml`), le QML pouvant ensuite se poser par-dessus. `player.sh` (lancé par `start.sh`) est la boucle du
lecteur : appli Qt si `~/.config/stream-box/player` contient `qt`, sinon mpv seul ; retour automatique à mpv si l'appli
s'arrête trois fois de suite en moins de 30 s (journal `/tmp/stream-box-ui.log`). `ui.py` prend les mêmes options que
la ligne de commande de mpv (`--x=y`, `--script=` cumulés, `--…-append=` par `change-list`) : scripts Lua, socket IPC,
chat, Jellyfin, Home Assistant marchent comme avant. Points délicats, vérifiés :
- décodage matériel : libmpv a besoin d'une connexion Wayland (`wl_display`, ici une connexion à part ouverte par
  `wl_display_connect`) pour créer son VADisplay ; sans elle « Could not create a VA display » et décodage au processeur.
  Avec : vaapi, 1080p60 sans image perdue, ~28 % d'un cœur comme mpv seul ;
- PySide libérerait le `QOpenGLFramebufferObject` rendu à Qt (plantage dans `texture()`) : référence gardée ;
- pas de retournement vertical (`setMirrorVertically`) : l'image serait à l'envers ;
- `force-window` activé seulement une fois le contexte de rendu créé (`Bridge.ready`) : passé au démarrage, mpv ne peut
  pas encore ouvrir sa sortie vidéo et le désactive ; sans lui, rien ne se redessine sans vidéo (écran d'ambiance et
  chaîne hors ligne figés sur la dernière image) ;
- touches : Qt → noms mpv (`KEYS`) ; les touches XF86 sans nom (OK de la télécommande Xiaomi : keysym 0x1008ffa0)
  prennent le nom que mpv leur donnait, « 0x21 » + 4 derniers chiffres du keysym (`0x21ffa0`) ; souris → `mouse` ;
- `jellyfin-mpv-shim` abandonne si le socket n'existe pas encore (l'appli l'ouvre plus tard que mpv) : `player.sh`
  efface l'ancien socket et attend le nouveau avant de lancer le shim. Attention aux `pkill -f '[j]ellyfin-mpv-shim'`
  de la boucle : ils tuent aussi une commande SSH qui contiendrait ce mot ;
- streamlink (`--player-external-http`) ne sert qu'un client à la fois : pour tester une seconde fenêtre, un second
  streamlink sur un autre port.
Changer de lecteur sans redémarrer la box : écrire le fichier puis `quit` par l'IPC (la boucle relance). Un nouveau
`start.sh`/`player.sh` ne s'applique qu'au démarrage suivant de la session (bash garde le script lu en mémoire).

### Grand menu en QML (qml/TvMenu.qml)

Avec l'appli Qt, le grand menu est en QML (rendu par la puce graphique, animations : fondu à l'ouverture, pastille
d'onglet qui glisse, contenu qui arrive en glissant, cartes qui grossissent avec un halo flou, défilement doux des
grilles et rangées, interrupteurs animés, fenêtre d'actions qui rebondit). `ui.py` ne charge alors pas `tv_menu.lua`
(deux menus répondraient), qui reste le menu de secours en mode mpv seul ou si le QML ne se charge pas. Ouverture :
`streambox-tvmenu-open` de stream-box.lua intercepté par python-mpv (`register_message_handler`). Touches : tant que le
menu est ouvert, `View.keyPressEvent` les donne au QML (`box.keyPressed`, rôles de `MENU_KEYS` : up, ok, back, home…)
au lieu de mpv (le volume reste à mpv) ; une touche envoyée par l'IPC (`keypress` → stream-box.lua →
`streambox-tvmenu-key`) arrive au même endroit, ce qui sert aux tests. `box.setMenuOpen` écrit un vrai booléen dans
`user-data/streambox/tvmenu` (`MPV_FORMAT_FLAG` : python-mpv écrirait la chaîne « yes ») pour le chat et la souris.
Données et actions : `XMLHttpRequest` vers l'API de remote.py ; photos et miniatures chargées directement depuis
Twitch / YouTube par Qt et arrondies par `MultiEffect` (plus besoin de `/api/tvimage`) ; météo et QR code par
`box.ambient` (propriété observée), voile opaque sans vidéo (`box.videoActive`). Composants : `RoundImage`,
`Marquee` (texte coupé au repos, deux copies qui défilent au focus), `FocusFrame`, `StreamerCard`, `VideoCard`,
`SettingRow`, `QrCode`, `fmt.js`. Pièges : tailles de police ×0,78 par rapport au menu ASS (Qt dessine plus grand pour
la même valeur) ; dans `onTabChanged`, lire `tabs[tab].id` et pas `tabId` (liaison pas encore recalculée) ; listes
avec `clip` : marges (`leftMargin`, `topMargin`) pour ne pas couper le halo du focus ; modèles en nombre d'éléments
(les délégués lisent les tableaux) pour que la liste ne se réinitialise pas à chaque relevé de l'état. Tester sans
télécommande : `keypress HOMEPAGE`, `keypress DOWN`… par l'IPC, captures par `grim`.

Fils et libmpv (blocages et plantages vus, corrigés) :
- le fil principal de Qt n'appelle jamais mpv directement (touches, souris, `force-window`, booléen du menu) : file
  `to_mpv` vidée par un fil à part. Un appel synchrone pouvait attendre la sortie vidéo, qui attend le fil de rendu,
  bloqué par le fil principal ;
- rendu : `ctx.update()` avant chaque `render`, et `block_for_target_time=False` : sinon le fil de rendu restait bloqué
  dans `render` au démarrage, une relance sur deux ou trois (socket IPC qui coupe les connexions, image figée) ;
  10 relances de suite sans blocage après correction ;
- à la sortie, pas de `player.terminate()` : libmpv s'arrête net (abort, code 134) si le contexte de rendu existe
  encore ; `os._exit` directement (mpv a déjà quitté). Avant, chaque `quit` finissait en plantage, et trois arrêts
  rapprochés ont fait basculer `player.sh` sur mpv seul jusqu'au redémarrage suivant ;
- `kill -USR1 <pid de ui.py>` écrit la pile de chaque fil dans `/tmp/stream-box-ui.log` ; plantages : `coredumpctl`.
Halo du focus : `RectangularShadow` (QtQuick.Effects), sous l'élément. Grilles et rangées sans `clip` (il coupait le
halo) : les éléments hors de la zone visible s'effacent en fondu (`rel` = position moins `contentX`/`contentY`).
Marges des vues seulement dans le sens du défilement (`topMargin` d'une rangée horizontale, `leftMargin` d'une grille
verticale) : Qt remet l'autre axe à zéro au premier `positionViewAtIndex`, et la rangée sautait sur le texte voisin.

### Deux streams à la fois (appli Qt)

Second lecteur libmpv (`pip_player` dans ui.py, son coupé, petit tampon de direct, pas d'interface) avec son propre
streamlink (port `PIP_PORT` 34590 ; 720p en incrustation, meilleure qualité côte à côte), dessiné par un second
`MpvVideo { which: "pip" }`. Dispositions dans ui.qml : `pip` (30 % de l'écran, en haut, du côté opposé au chat s'il
est en haut à droite, ombre et liseré) et `split` (deux moitiés). Les vidéos gardent leur taille de rendu et sont
réduites par `scale` : transitions animées sans recréer les tampons d'image. Commandes : menu QML (Menu ≡ sur une carte
En direct ou Suivis en live : En incrustation, Côte à côte ; raccourcis Inverser, Côte à côte/Incrustation, Fermer),
page web (barre « Second stream » quand il est actif), `POST /api/pip {action: open|close|swap|layout, name, layout}` →
script-message `streambox-pip` → classe `Pip` de ui.py. État dans `user-data/streambox/pip` et `/api/state` (`pip`).
Inverser = la chaîne du second passe en principal (`streambox-channel`) et inversement, donc le son suit. Le second se
ferme seul si le principal passe en écran d'accueil, en vidéo, ou sur la même chaîne. Charge mesurée : ~66 % d'un cœur
pour les deux (1080p60 + 720p60, décodage vaapi).

### Choix du lecteur

Système → Lecteur (menus QML et Lua de la TV ; section Système des réglages de la page web) : `POST /api/player {mode: qt|mpv}` écrit
`~/.config/stream-box/player` et quitte le lecteur ; la boucle de player.sh relance le bon. `/api/state` donne `player`
(choisi) et `player_running` (`qt` si `current-vo` vaut `libmpv`) : la page signale un retour automatique à mpv.
player.sh oublie les échecs de l'appli Qt quand le fichier est réécrit (date de modification), ce qui permet de la
réessayer sans redémarrer.

### Chat avec émotes (appli Qt)

`chat_qt.py` (importé par ui.py) lit le chat comme chat_overlay.py (IRC anonyme) et découpe chaque message en mots et
émotes : Twitch par le tag `emotes` (positions en caractères), 7TV / BTTV / FFZ par nom (listes globales chargées une
fois, listes de la chaîne dès le ROOMSTATE qui donne son identifiant ; priorité 7TV > BTTV > FFZ). `qml/ChatOverlay.qml`
les dessine (Flow de Text et d'AnimatedImage : GIF et WebP animés, plugin `libqwebp` de Qt), dans le coin et avec le fond
et la taille réglés, masqué en vidéo, sur l'écran d'accueil et menu ouvert. Quand l'appli tourne, elle écrit
`user-data/streambox/chat_ui = qml` et chat_overlay.py (texte dans mpv) se tait ; il repart de zéro à chaque nouveau
lecteur (mpv seul : chat texte). Piège QML : `left`, `top` sont des propriétés réservées des éléments (FINAL) ; une
erreur de chargement de ui.qml fait retomber l'appli sur le menu Lua et le chat texte, sans planter.
Fermeture : à l'événement `shutdown` de mpv, `os._exit` tout de suite depuis le fil d'événements de python-mpv (qui
sinon détruit sa connexion et attend le contexte de rendu tenu par Qt : appli figée, pas de relance ; 6/6 relances
propres après correction).

### Écran d'accueil en QML (appli Qt)

`qml/AmbientScreen.qml` : affiché quand stream-box.lua le décide (`user-data/streambox/ambient_on`, publié par
`update_ambient` ; `draw_ambient` ne dessine plus rien quand `chat_ui` vaut `qml`), avec le message d'état
(`user-data/streambox/status`, publié par `set_status`) et le mode du QR code (`qr`), relayés par `box` (`ambientOn`,
`statusText`, `qrMode`). Fond : taches de couleur en `RectangularShadow` très flous (pas de calque, flou par la puce
graphique) qui dérivent sur une minute ou plus ; contenu qui dérive de ±36 px sur 7 à 11 min. Horloge, date (locale
fr_FR), météo avec `WeatherIcon.qml` (icône dessinée et animée d'après le code WMO, `code` ajouté par remote.py ; lune
de 20 h à 7 h), « En live maintenant » (streamers de la liste en live hors celui regardé, `/api/state`), prochains
lives en cartes de verre avec photos, QR code (toujours, 30 s à chaque arrivée, jamais).

### Voter aux sondages et prédictions depuis la page

Helix n'a rien pour un spectateur : GQL du site avec le jeton du compte connecté, sans contrôle d'intégrité (vérifié
avec des identifiants factices : `POLL_NOT_FOUND`, `NOT_FOUND`). Sondage : `voteInPoll(input: {pollID, choiceID,
userID, voteID})` ; prédiction : `makePrediction(input: {eventID, outcomeID, points, transactionID})`. Le relevé
(`fetch_events`) donne maintenant les identifiants, le pari en cours (`PredictionEvent.self.prediction`) et le solde de
points (`channel.self.communityPoints.balance`) ; Twitch ne redonne pas le choix fait dans un sondage : `poll_votes`
retient ceux faits depuis la box. `GET /api/events` (relevé fait sur place si l'encart de la TV est désactivé),
`POST /api/vote {poll, choice}`, `POST /api/predict {event, outcome, points}` (codes d'erreur traduits, `VOTE_ERRORS`).
Page : carte « Sondage / Prédiction » sous « Sur la TV », relevée toutes les 3 s pendant un direct ; mise 10, 100, 1000,
Tout ou libre, confirmation avant de parier. Le relevé régulier suit maintenant toute chaîne en direct, pas seulement
celles de la liste. Non testé en vrai (pas de sondage ouvert, et un pari dépense des points) : affichage vérifié avec
des données simulées.

### Bandeau, barre de lecture, notification, encart des sondages en QML (appli Qt)

stream-box.lua garde la logique (OK, ←/→, pause, délais, touches de la notification) et, quand `qt_ui()` (chat_ui =
qml), publie au lieu de dessiner : `user-data/streambox/bar` (barre visible), `toast` ({name, title, game, viewers,
seconds}, vide à la fin) ; `draw_bar` et `draw_events` ne dessinent rien. ui.py (`Osd`) relaie ces propriétés, `polls`,
`storyboard`, `live`, et lit la position de lecture (time-pos, duration, pause, cache, fenêtre du différé) depuis un fil
à part, 4 fois par seconde seulement quand la barre est visible. QML : `InfoBar.qml` (direct : photo, titre, jeu,
spectateurs, « en live depuis » d'après `started` = `stream.createdAt` ajouté par remote.py, mémoire du différé et
« EN DIRECT » ou retard ; vidéo : pause, titre, partie chargée, durée, et aperçu YouTube), `Toast.qml` (glisse depuis
la droite, ligne de temps restant), `PollsOverlay.qml` (barres animées, ★ gagnant, ✓ vote ou pari fait depuis la box).
Aperçu YouTube : à chaque lecture YouTube, remote.py lance `yt-dlp -J` une fois et publie la planche de miniatures
(`storyboard` : fragments d'images en grille rows × columns, chacun couvrant `duration` s) ; la case affichée est
choisie d'après la position. Piège QML encore : `left` (FINAL) ne peut pas servir de nom de propriété.
Couleur de la barre selon la source (`InfoBar.source`, d'après `path` relayé par ui.py) : rouge pour YouTube, bleu
pour Jellyfin (lien de serveur : `/Videos/…`, `api_key=`, `MediaSourceId=`), violet sinon et en direct.

### État de la box (page, Réglages → Système)

`GET /api/health` : températures (hwmon `coretemp`/`k10temp` et `nvme`), processeur (% sur 5 s, `health_loop`) et
charge, mémoire, disque, réseau (interface de la route par défaut, vitesse du lien, débits sur 5 s), lecture (lecteur
réellement actif, décodage, taille, images/s, images perdues), services utilisateur (MQTT, jetons YouTube :
`systemctl --user is-active`), mises à jour (en cours, prochaine d'après le minuteur, dernière d'après
`update.log`). `POST /api/update` lance `stream-box-update.service` (`--no-block`). La page relit toutes les 5 s tant
que l'onglet Réglages est affiché ; tuiles en orange ou rouge au-delà des seuils (70 °C, 85 °C, mémoire, disque,
service arrêté, décodage par le processeur).
Même état dans l'onglet Système du menu QML de la TV (tuiles sous les lignes, `/api/health` relu toutes les 5 s tant
que l'onglet est affiché), avec une ligne « Mettre à jour maintenant » (dernière et prochaine mise à jour).

### YouTube (chaînes et recherche)

Liste de chaînes dans `~/.config/stream-box/youtube.json` (id UC…, nom, @, photo), éditée par
`POST /api/youtube_channels` {action: add|remove|move, channel, delta} ; l'ajout résout « @nom », un lien ou un id avec
`yt-dlp --flat-playlist -J --playlist-items 0` (~1 s). `GET /api/youtube` : 15 dernières vidéos par chaîne d'après le
flux RSS public (`feeds/videos.xml?channel_id=`, sans clé, Shorts écartés, cache 20 min), fusionnées avec
l'historique (position, vu). `GET /api/youtube_search?q=` : `yt-dlp --flat-playlist -J ytsearch20:` (~1,6 s, cache
10 min, `youtube:lang=fr` sinon titres traduits en anglais) : vidéos, et chaînes dont le nom correspond (même
requête ; id UC…, abonnés, photo, `saved`), playlists écartées. `GET /api/youtube_channel?id=UC…` : dernières vidéos
d'une chaîne trouvée, même hors de la liste. Peu de requêtes : YouTube a déjà limité
l'adresse IP de la box.
Compte YouTube (rangée « Abonnements », en tête des rangées de chaînes) : appli Google à soi (console.cloud.google.com,
YouTube Data API v3, audience Externe publiée sinon jetons valables 7 jours, client « TV et appareils à saisie
limitée »), autorisation par code sur google.com/device, droit `youtube.readonly`. `youtube-app.json` (client_id,
client_secret), `youtube-token.json`, `youtube-subs.json` (abonnements relus une fois par jour), en 600 dans
`~/.config/stream-box`. Tout passe par googleapis.com (quota 10 000 unités par jour), rien par youtube.com :
`subscriptions` (1 unité par 50), puis par chaîne `playlistItems` sur la playlist `UULF` + id sans « UC » (vidéos sans
Shorts ni directs ; `UU` en secours), 4 dernières, 8 en parallèle ; `videos` pour durées, vues et directs à venir
(écartés), 60 vidéos gardées, durées et vues relues au plus toutes les heures. Chaque chaîne à son rythme
(`YT_CHANNEL_RHYTHM`, âge de sa dernière vidéo : < 2 j → toutes les heures, < 7 j → 3 h, < 30 j → 12 h, sinon 24 h),
tour toutes les minutes (`yt_subfeed_loop`, 16 en parallèle) ; relevés dans `youtube-subfeed.json` (et unités du
jour, quota remis à zéro à minuit heure du Pacifique, plafond `YT_DAILY_BUDGET` 7000). 347 abonnements : ~1 800
unités par jour. `/api/youtube` sert le dernier fil (le tout premier, juste après l'autorisation, est attendu).
`GET /api/youtube` → `subs` {configured, authorized, pending, channels, synced, videos} ; `GET /api/youtube_account` ;
`POST /api/youtube_app|youtube_login|youtube_logout|youtube_sync`. TV : carte « + Connecter mon compte » dans la rangée
tant que la box n'est pas autorisée → fenêtre du code et QR code (`ytAuth`, relue toutes les 3 s) ; ligne « Compte
YouTube » du menu Système (relire les abonnements, déconnecter). Page : section « Compte YouTube » des Réglages
(création de l'appli, code, état). tv_menu.lua affiche la rangée, sans connexion.
Favoris : servis par le relevé des abonnements quand la chaîne en fait partie (`yt_fav_videos`, 15 vidéos par
favori au lieu de 4, durées et vues, aucune requête à youtube.com : `/api/youtube` en ~15 ms), sinon flux RSS lus en
parallèle, échecs gardés 10 min (`YT_FEED_RETRY`). Le menu garde `yt` d'une ouverture à l'autre et le relit en fond ;
la page ne lit que la liste (`GET /api/youtube_channels`). Rangées : cartes créées seulement pour les rangées visées
et leurs voisines (`near`).
Favoris (liste `youtube.json`, une rangée par chaîne) : Options sur une vidéo des abonnements → « Ajouter aux favoris »
(chaîne prise dans `youtube-subs.json`, sans requête à YouTube), « Voir ses dernières vidéos », « Lire la vidéo ».
Page : bloc YouTube de l'onglet Télécommande (recherche, une puce par chaîne) et « Chaînes YouTube » dans Réglages.
TV (onglet YouTube du menu QML) : ligne de recherche → clavier à l'écran (grille de 10 de large, ↑↓←→ et OK, Retour
ferme), puis les chaînes trouvées (photos rondes ; OK : « Voir ses dernières vidéos », rangée `preview` juste dessous, ou
« Ajouter / Retirer de mes chaînes »), les vidéos trouvées et une rangée par chaîne de la liste ; OK sur une vidéo
lance (ou propose la reprise, `chooseVideo`). Page : chaînes trouvées en tête des résultats (toucher : leurs vidéos,
« + Ajouter »).
Les résultats restent d'une ouverture du menu à l'autre (pas d'un redémarrage du lecteur). Couleurs par onglet (`menu.theme`, `menu.pal`) : violet pour
Twitch (direct, suivis, rediffusions), rouge pour YouTube, neutre anthracite à halo blanc pour historique, réglages et
système ; fond, lueurs, rail, halos (`FocusFrame.glow`), `VideoCard.accent`, `SettingRow.pal` (interrupteur clair à
bouton sombre en neutre), fenêtre d'actions, clavier. Le bleu reste libre pour Jellyfin. Logo (`qml/Logo.qml`, icônes `icon-*.png`,
tv_menu.lua) : tuile blanche, triangle anthracite arrondi, neutre sur fond violet comme rouge.

### Jellyfin (onglet du menu QML et page)

remote.py réutilise le serveur associé à jellyfin-mpv-shim (`~/.config/jellyfin-mpv-shim/users.json` : adresse,
UserId, AccessToken ; en-tête `Authorization: MediaBrowser Token="…"`, rien d'autre à configurer). `GET /api/jellyfin`
(cache 30 s) : `Items/Resume`, `Shows/NextUp`, `Items/Latest` par bibliothèque (films, séries ; les séries arrivent
par saison) ; `GET /api/jellyfin_search?q=`, `GET /api/jellyfin_series?id=` (épisodes et index du premier pas vu) ;
`POST /api/jellyfin_play` {id, from_start} : flux direct `/Videos/{id}/stream?static=true&api_key=…`, reprise à la
position du serveur, titre passé à mpv (`streambox-play url start titre` → `force-media-title`, longueur en
préfixe %n%). Progression renvoyée au serveur : `Sessions/Playing` au lancement, `/Progress` toutes les 10 s par
history_loop, `/Stopped` à l'arrêt (le serveur décide du « vu »). Entrée dans l'historique de la box sous
« jellyfin:ID » (sans jeton ; `play()` la relance par jellyfin_play), aussi pour les lectures lancées par le shim
(« Lire sur… », `shim_video` : le shim rend compte lui-même). Sous-titres externes (.srt à côté du fichier) absents du
flux direct : ajoutés par `sub-add` une fois la vidéo ouverte (`jf_add_subtitles`). Les
images du serveur sont publiques (pas de jeton dans leurs liens).
TV : onglet « Jellyfin » (thème bleu) sur la même page que YouTube (`mediaRows`, `mRow`/`mSel`, `keyMedia`, état
propre `jfRow`/`jfSel`) : recherche au clavier à l'écran, épisodes d'une série ouverte, Reprendre, Prochains
épisodes, ajouts récents ; OK sur un film ou un épisode : Reprendre / Depuis le début / Tous les épisodes. Rail
resserré (pas de 76) pour 9 onglets. Rangées
horizontales : défilement carte par carte aligné à gauche (`first`, `fits`), rangée découpée 28 px avant le contenu
(`clip` sur une enveloppe plus haute que les cartes, pour le halo) et cartes affichées d'après la fenêtre visée, pas
leur position animée : celle qui sort s'efface en 90 ms sans passer sous le rail. Même chose à la verticale : grilles (direct, suivis,
historique), listes (réglages, système) et rangées YouTube/Jellyfin sont dans une enveloppe `clip` (marge de 40 px
autour pour le halo) qui s'arrête sous le titre et au-dessus de l'aide en bas ; rangées YouTube/Jellyfin affichées
d'après la rangée visée. Piège QML : une fonction ne doit pas reprendre le nom d'une propriété
(`setSel` existait : les touches de l'onglet échouaient en silence, sauf dans le journal).
Page : bloc Jellyfin de l'onglet Télécommande (puces par rangée, recherche, épisodes d'une série).

### Sous-titres et audio pendant une vidéo (touche ≡, appli Qt)

stream-box.lua : en mode vidéo, ≡ ouvre la liste (track-list : « Désactivés », sous-titres, puis pistes audio s'il y en
a plusieurs ; langues en français, « (forcés) », « (d'origine) ») et affiche la barre ; tant qu'elle est ouverte
(`tracks_open`), ↑ ↓ choisissent, OK règle `sid`/`aid` et ferme, toute autre touche ferme. État publié dans
`user-data/streambox/tracks` {open, items, sel}, relayé par ui.py (`osd.tracks`), dessiné par `qml/TracksPanel.qml`
au-dessus de la barre, à droite. La barre rappelle « ≡ sous-titres et audio ». Avec mpv seul, ≡ passe aux
sous-titres suivants (comme avant).
Réglages « Taille des sous-titres » (`sub_size`, 50–200 %, → `sub-scale`) et « Fond des sous-titres » (`sub_bg`,
0–100 % : bandeau noir `sub-border-style=background-box` + `sub-back-color` #AA000000, 0 = contour habituel) : NUMBERS
de stream-box.lua (`apply_sub_style`), `POST /api/set`, onglet Réglages de la TV et section Sous-titres de la page.
Les deux menus s'ouvrent sur l'onglet du média en cours (`mediaTab` / `media_tab`, d'après `mode` et `media_kind` de
/api/state : direct → En direct, YouTube, Jellyfin, rediffusion ou clip → Rediffusions, autre lien → Historique),
recalé quand l'état arrive tant qu'aucune touche n'a été pressée ; YouTube et Jellyfin gardent rangée et carte. mpv gardant la pause d'un fichier à l'autre,
`play_media` et `start_channel` la retirent.
Fond du menu : deux lueurs floues (RectangularShadow, pas de forme nette) de la couleur de l'onglet, en haut à droite
(`pal.glow`) et en bas (`pal.glowLow`), sur tous les thèmes ; presque invisibles en neutre.
Menu Lua (mpv seul, tv_menu.lua) : onglets YouTube et Jellyfin (rangées de cartes, reprise, épisodes d'une série ;
pas de recherche, faute de clavier : elle passe par la page), réglages des sous-titres, onglet gardé à la
réouverture. Tailles de texte ×1,2 (`FONT`) pour le même aspect que l'appli Qt. `/api/tvimage` accepte aussi les
images du serveur Jellyfin.
Onglet Système du menu Lua : ligne « Mettre à jour maintenant » et tuiles d'état (`draw_health`, /api/health toutes les 5 s).

### Écran de chargement entre deux vidéos ou chaînes

stream-box.lua (`set_loading`) publie `user-data/streambox/loading` {title, thumb} au lancement d'une vidéo
(`play_media url start titre_imposé image titre_affiché`) ou d'une chaîne (`start_channel`), et l'efface à la première
image (`playback-restart`), sur erreur, à l'écran d'accueil ou au bout de 45 s. `qml/LoadingOverlay.qml` (relais
`osd.loading`, `kind` : twitch, youtube, jellyfin, video) : miniature floutée, logo de la box qui respire, lueur de la
couleur de la source qui court sur le contour du triangle (ShapePath en pointillés, `dashOffset` animé), ondes ;
ombre portée sous les textes ; fondu à l'entrée et à la sortie. Avec mpv seul
(`vo` ≠ libmpv) : message « Chargement de … » à l'écran. Titre et image viennent de remote.py (historique, Jellyfin)
ou de la requête (`POST /api/play` accepte `title`, `thumb` : le menu QML les envoie).
Bandeau et barre de lecture (InfoBar.qml) : dégradé plus sombre plus haut et ombre portée sous l'en-tête, pour lire le
titre sur une image claire.

### Barre de lecture d'une vidéo (appli Qt)

- Avance rapide qui accélère (stream-box.lua `media_seek`) : appuis rapprochés (< 0,8 s) ou touche maintenue (au plus
  8 sauts/s) → 10 s ×3, puis 30 s, puis 1 min ; total publié dans `user-data/streambox/seekfx` {text, n}, bulle
  « +2 min 30 » au-dessus du curseur (InfoBar.qml). Marche aussi avec mpv seul (sans la bulle).
- Rangée de boutons : ↓ y descend (focus sur Pause/Lecture), ← → et OK, ↑ ou Retour remontent ; −10 s, Pause/Lecture,
  +10 s, Sous-titres, Chapitre suivant (s'il y a des chapitres), Épisode suivant (Jellyfin). `ctrl_focus`,
  `user-data/streambox/controls` {items, focus} ; disparaît avec la barre.
- Infos : `user-data/streambox/meta` publié par remote.py (YouTube : chaîne, date, vues, description, depuis le
  `yt-dlp -J` de l'aperçu ; Jellyfin : série, épisode, année, note, résumé) ; chapitres (`chapter-list`, `chapter`)
  relevés par ui.py avec la position : repères sur la barre, chapitre en cours dans la ligne d'infos. Temps restant
  et heure de fin (« −21:26 · fin à 02:30 »).
- Écran de pause (`qml/PauseScreen.qml`) : image assombrie, grande icône pause, résumé au-dessus du bandeau.
- Épisode suivant (Jellyfin) : remote.py publie `user-data/streambox/next_up` {id, of, title, episode, thumb}
  (`Shows/{série}/Episodes?AdjacentTo=`) ; dans les 20 dernières secondes, stream-box.lua publie `next_card`
  {seconds, …} → `qml/NextUp.qml` (OK : lancer, Retour : rester) ; à la fin du fichier, l'épisode suivant part
  (POST /api/jellyfin_play). `of` : seulement pendant l'épisode dont c'est la suite (pas pour une lecture du shim).

### Home Assistant : état « Allumée »

mqtt_bridge.py : `binary_sensor.stream_box_allumee` sur `stream-box/power` (ON à la connexion du pont, OFF par le
message de dernière volonté, à l'arrêt du service — SIGTERM — et juste avant « Éteindre ») ; sans `availability`,
donc `off` et jamais `unavailable`. Les autres entités : disponibles si `status` = online (box prête) ET power = ON
(`availability_mode: all`), sauf « Éteindre » : disponible dès power = ON et exécuté tout de suite par le pont
(`systemctl poweroff`, polkit), même pendant le démarrage. Exemples d'automatisation (allumer et éteindre avec la TV) dans docs/home-assistant.md.

### Image disque installable (image/, mkosi)

`bash image/build.sh` construit `image/mkosi.output/stream-box.raw` (~3 Go, à écrire sur un disque ou une clé USB ;
`bash image/build.sh xz` : stream-box.raw.xz, ~1,8 Go, la version à télécharger)
dans un conteneur Docker Arch avec mkosi 27 (rien d'installé sur la machine) ; `bash image/build.sh vm` la démarre
dans QEMU. Base Arch (pas CachyOS), UEFI, systemd-boot + UKI. greetd lance la session cage de media au démarrage
(pas de choix clavier/écran de connexion comme boot-mode.py). `mkosi.prepare.chroot` (avec réseau) : utilisateur
media, clone du dépôt (origin = GitHub), venvs, serveur de jetons YouTube ; `mkosi.postinst.chroot` : config SSH,
services utilisateur, jellyfin-mpv-shim, lecteur Qt ; `mkosi.finalize.chroot` : activation des services système et
graphical.target (après le `systemctl preset-all` de mkosi, qui annulerait des `enable` faits plus tôt).
`/usr/lib/repart.d/10-root.conf` agrandit la partition système à tout le disque au premier démarrage. Aucun réglage
personnel dans l'image : tout passe par la télécommande web. Testé dans QEMU (écran d'accueil de l'appli Qt, API).
Piège : `pkill -f motif` dans une commande dont le texte contient ce motif se tue lui-même (`[q]emu…`).

### Mise en veille

Menu de la TV (Système) : « Mettre en veille » (`POST /api/poweroff {"mode": "suspend"}`) et « Éteindre la box »
(`{"mode": "full"}`), plus le réglage « Bouton d'arrêt (téléphone, Home Assistant) » : `~/.config/stream-box/power-action`
(`suspend` ou `poweroff`, défaut), lu par remote.py (`POST /api/poweroff` sans mode, bouton de la page) et
mqtt_bridge.py (bouton « Éteindre » ; select « Bouton d'arrêt »). Veille par `systemctl suspend` : permise d'office à
remote.py (session locale active) ; règle polkit `login1.suspend*` ajoutée (install.sh, image) pour le pont, qui
tourne hors session. Pendant la veille, Allumée passe à OFF : le pont prend un verrou logind « delay » et suit
PrepareForSleep (gdbus monitor), publie OFF avant la veille et ON + status au réveil. Réveil : Wake-on-LAN (même paquet
que pour l'allumage) ou bouton power. Au réveil, remote.py redémarre l'adaptateur Bluetooth (`bluetoothctl power off/on` : le dongle CSR restait bloqué,
télécommande « connectée » sans périphérique d'entrée), puis (`resume_loop`, PrepareForSleep false) attend que twitch.tv réponde puis envoie
`streambox-resume` : stream-box.lua relance la chaîne, ou la vidéo à sa position (flux morts pendant la veille, image
figée sinon). Testé : réveil par WoL en 6 s, stream de retour 8 s après le paquet. La veille demandée par remote.py
n'est permise d'office que s'il tourne dans la session de la TV (lancé par start.sh) ; hors session (relancé par ssh),
il faut la règle polkit `login1.suspend*`.
Bouton power (télécommande Bluetooth, bouton du boîtier) : remote.py tient un verrou logind `handle-power-key`
(`hold_power_key`, permis dans la session de la TV) ; stream-box.lua lie `POWER` (mpv seul) et `0x21ff2a` (appli Qt,
keysym XF86PowerOff) à `power_key` → `POST /api/poweroff` sans mode, donc le réglage « Bouton d'arrêt ». Ignoré 15 s
après le démarrage et après un réveil. Lecteur arrêté : le bouton ne fait rien (logind ne reprend la main que si
remote.py meurt).

### Mode configuration Wi-Fi (netsetup.py)

Sans réseau (aucune connexion Ethernet ou Wi-Fi active) et avec une carte Wi-Fi, remote.py (`netsetup.setup_loop`,
25 s après le démarrage) crée le point d'accès NetworkManager `stream-box-setup` (« Stream Box XXXX », mot de passe
tiré une fois, `~/.config/stream-box/hotspot.json`, adresse de la box 10.42.0.1, dnsmasq pour le DHCP). L'écran
d'accueil (AmbientScreen.qml ; texte avec mpv seul) montre « 1. Connecte ton téléphone » (QR code WIFI:…) et « 2. Ouvre
la configuration » (QR code http://10.42.0.1:8080/). La page, ouverte sur 10.42.0.1, s'ouvre sur la section Wi-Fi
(liste relevée juste avant le point d'accès, une seule radio) ; `POST /api/wifi {action: connect, ssid, password}`
arrête le point d'accès, cherche le réseau, s'y connecte ; échec → point d'accès de nouveau, erreur dans
`GET /api/wifi`. Récupération à tout moment : Wi-Fi enregistré perdu → 60 s de grâce (NetworkManager réessaie) puis
point d'accès ; sans téléphone dessus, il s'efface toutes les 3 min pour réessayer le Wi-Fi enregistré ; réseau revenu
(câble…) → il s'arrête. Menu Système de la TV : ligne « Wi-Fi » (OK : mode configuration, gardé 15 min). En Ethernet,
rien ne change. Carte choisie : celle du point d'accès, sinon la première par nom qui ne sert pas déjà de point
d'accès. start.sh n'attend plus le réseau que 20 s. Test : `bash image/build.sh test` (mac80211_hwsim : deux cartes
simulées, clé SSH de test gitignorée) ; testé dans QEMU : écran, recherche, mauvais puis bon mot de passe.

Adresse de la télécommande (QR code) : par défaut http://<IP locale>:8080 ; nom de domaine optionnel dans Réglages →
Affichage (`POST /api/remote_url`, fichier remote-url, vide = réseau local).

### Télécommande virtuelle (page)

Section « Télécommande » en haut de l'onglet Télécommande : pavé ▲▼◀▶ + OK, Retour, Menu (menu de la TV), Options (≡),
Lecture (`cycle pause` : la touche lecture Xiaomi, elle, change le coin du chat). `POST /api/key {key}` → `keypress` mpv avec les noms que lie stream-box.lua (UP… ENTER, GO_BACK, HOMEPAGE,
0x2111a0, PLAYPAUSE ; liste blanche dans remote.py) : même effet que la télécommande Bluetooth, menu de la TV compris.
Flèches répétées tant qu'on reste appuyé (400 ms puis toutes les 120 ms), petite vibration à chaque appui.

### Page allégée (télécommande virtuelle d'abord)

Depuis la télécommande virtuelle, la page ne garde que ce que le téléphone fait mieux que le menu de la TV. Onglet
Télécommande : télécommande virtuelle, En cours (titre ; vidéo : titre et « Retour au stream »), votes, Son (volume,
couper le son), aperçu de la TV, lien à lire. Réglages : Wi-Fi,
listes des streamers et des chaînes YouTube, adresse de la télécommande, état de la box et mises à jour, compte
Twitch, chaînes suivies. Retirés (dans le menu de la TV) : grille des streamers et second stream, retour en arrière
du direct, barre de lecture et sous-titres, pause, mode nuit, chat (affiché, coin, apparence), parcours YouTube
(dernières vidéos par chaîne) et Jellyfin (rangées), rediffusions, historique, bascule auto, sondages affichés,
sous-titres, résolution, bouton d'arrêt, QR code, lecteur. L'API garde ces actions (menu de la TV, Home Assistant).
Banc d'essai de la page : jsdom dans Docker, fetch relayé vers l'API de la box (lecture seule), erreurs JS rapportées.

### Clavier du téléphone pour la recherche du menu de la TV

Clavier de recherche (YouTube, Jellyfin) ouvert ou fermé dans TvMenu.qml (`onKbOpenChanged`, aussi fermé avec le menu)
→ `POST /api/keyboard {open, text, target}` ; remote.py le garde (`keyboard`, oublié après 10 min) et le publie dans
`/api/state` (`keyboard`). La page affiche alors en tête « Recherche … (sur la TV) » : chaque frappe (120 ms après) →
`POST /api/keyboard_input {text}` → `script-message streambox-tvmenu-text <texte> <0|1>` → ui.py `box.textInput` →
`kbText` ; Entrée ou « Rechercher » (`submit`) lance la recherche et ferme le clavier. Les blocs de recherche
YouTube et Jellyfin de la page sont retirés : la recherche se fait sur la TV. Appli Qt seulement (pas de recherche
dans le menu de mpv seul).
Allègement de l'image (5,7 → 3,0 Go) : partition système en btrfs compressé zstd, `Minimize=best` (pas de place vide
écrite, agrandie au premier démarrage) ; pas de deno ni de nodejs-wheel dans le venv media (yt-dlp passe par le Node du
système : `--js-runtimes node` dans player.sh, remote.py `YTDLP_JS`, update.sh, seulement si deno est absent, la box
installée par install.sh garde deno) ; serveur de jetons sans ses dépendances de développement (`npm prune
--omit=dev`) ; `mkosi.finalize.chroot` retire /usr/include, doc, man, traductions autres que fr et en, outils de
développement Qt du venv. Firmwares, LLVM, polices Noto et Qt gardés (compatibilité). Testé dans QEMU sur une clé de
16 Go : partition agrandie à 16 Go, vidéo YouTube lue.

### Sortie son (audio.py)

`audio.py watch` (lancé par start.sh, en continu) : sorties = prises HDMI / DisplayPort marquées « available » par
PipeWire (écran ou TV qui sait jouer le son branché ; nom d'après l'EDID, `device.product.name`), appareils USB et
Bluetooth (sinks `device.bus` usb / bluez5), sortie analogique de la carte. Choix dans `~/.config/stream-box/audio-output` :
« auto » (Bluetooth > USB > HDMI branché ; rien de tout ça : on ne touche à rien) ou l'identifiant d'une sortie (absente
→ automatique en attendant). Nouveau choix 1,5 s après chaque évènement sink/card de `pactl subscribe` ; changement de
profil de carte, sortie par défaut, lectures en cours déplacées. `GET /api/audio` (sorties, choix, actuelle),
`POST /api/audio {output}` ; ligne « Sortie son » dans Réglages de la TV (QML et Lua) et de la page. Descriptions lues
dans le listing texte de pactl (le JSON perd les accents). no-hdmi-audio (ancien) vaut « analogique ».

### Touches lues à la source (input.py), appairage et apprentissage depuis le menu

`input.py` (lancé par start.sh) lit /dev/input/event* (groupe input : install.sh l'ajoute, l'image le donne) avec les
noms de Linux (table de linux/input-event-codes.h embarquée ; KEY_SELECT = OK Xiaomi, KEY_VIDEOPHONE = ≡ Xiaomi,
BTN_* et pavé ABS_HAT des manettes), traduit en actions (DEFAULTS, puis keymap.json) et envoie
`script-message streambox-input <nom> <action>` ; il annonce `user-data/streambox/input` = « evdev:<heure> » toutes les
5 s, et tant que c'est frais (15 s) stream-box.lua et ui.py ignorent les touches reçues par mpv / Qt (sinon doublées).
Sans droits sur /dev/input, il s'arrête : ancien chemin (noms mpv et keysyms 0x21…, KEYS de stream-box.lua) en
secours. Actions : up down left right ok back home menu homescreen corner power volume_up volume_down mute. La
télécommande virtuelle de la page envoie aussi des actions (`streambox-input VIRTUAL <action>`, jamais apprise).
Assistant « Configurer les touches » (menu Système, QML et Lua ; `POST /api/keymap {action: wizard|reset}`) : dans
stream-box.lua, les actions une par une (8 s chacune, sans touche elle garde la sienne ; une touche déjà prise est
refusée), touches apprises ajoutées à `~/.config/stream-box/keymap.json` ({nom: action}, noms Linux via input.py ou
noms mpv en secours), état dans `user-data/streambox/learn` → `qml/KeyWizard.qml` (message à l'écran avec mpv seul).
ui.py applique aussi keymap.json au menu QML ouvert. Bluetooth (btsetup.py, `GET/POST /api/bluetooth`) : liste des
appareils appairés, recherche de 20 s, appairage sans code (agent NoInputNoOutput) + trust + connect, dissociation ;
fenêtre « Télécommandes et manettes » du menu Système (QML : `btMenu`, `btScan`, relue toutes les 2 s).
Redémarrage : `POST /api/reboot` (`systemctl reboot`, polkit login1.reboot* ajouté), « Redémarrer la box » dans le menu Système
(QML et Lua, deuxième OK dans les 4 s), bouton dans Réglages → Système de la page, bouton « Redémarrer » dans Home Assistant.
Power maintenu 1 s → fenêtre « Box » (veille, redémarrer, éteindre, annuler ; menu QML `powerMenu`, tv_menu.lua
`streambox-power-menu`) au lieu de l'action du réglage « Bouton d'arrêt », qui part désormais au relâchement d'un
appui court. input.py mesure l'appui (valeurs 1 / 0 de evdev, action `power_menu` envoyée à 1 s) ; en secours,
stream-box.lua lie power en « complex » (down / up de mpv) et ui.py envoie keydown / keyup pour ces touches.
La fenêtre s'affiche seule sur la vidéo, sans le menu derrière (`powerOnly` / `power_only`) ; Retour ferme tout.


### YouTube Cast

`cast/cast.js` (Node, `yt-cast-receiver` 2.1.0, protocole non officiel) : la box apparaît comme « Stream Box » dans le
bouton Caster de l'appli YouTube (découverte DIAL / SSDP sur le réseau local, port TCP 3000, UDP 1900 ; pare-feu à
ouvrir s'il y en a un). Vidéo castée → `POST /api/play` {url, start} (position imposée par l'appli, `play(at=)`) ;
pause, reprise, avance, volume → IPC mpv ; état changé à la télécommande renvoyé à l'appli (`notifyExternalStateChange`),
fin de vidéo → suivante de la file ; « Arrêter la diffusion » → retour au stream (`/api/twitch`). Appairages dans
`~/.config/stream-box/cast-receiver.json`. Lancé par start.sh si `cast/node_modules` existe ; modules installés par
`npm ci --omit=dev` dans `cast/` (versions de `cast/package-lock.json`, ~40 Mo) par install.sh, l'image
(mkosi.prepare.chroot) et update.sh (si le fichier de versions a changé). Titre de l'écran de chargement : l'appli ne
donne que l'identifiant, `yt_title` le demande à l'API Google (compte connecté, 1 unité) ou à l'oEmbed public.
Testé : découverte, lecture, pause, avance, volume, file d'attente, pause à la télécommande, arrêt.

### Progression YouTube du compte (mixte)

L'API officielle ne donne ni historique ni positions : `cast/youtube_tv.js` (même processus que `cast.js`) se connecte
comme l'appli YouTube des TV (youtubei.js, client TV, code sur google.com/device, Google affiche « YouTube on TV » ;
jeton `~/.config/stream-box/youtube-tv-token.json`), serveur local 127.0.0.1:8091 (`/status`, `/login`, `/logout`,
`/progress`, `/report`). Fonctionnement mixte, essayé avant de choisir :
- la box garde ses positions (reprise exacte sur la TV) et les renvoie à YouTube (`history_loop` : toutes les
  `YT_TV_PUSH` = 30 s, et à l'arrêt `final`) comme un lecteur : `/player` (URL de suivi, cpn), ping `playback`, puis
  `watchtime` (segment st→et, temps réel rt). Vérifié : le téléphone reprend à la seconde près ;
- pour une vidéo vue ailleurs, ou vue plus loin ailleurs que sur la box (la position la plus avancée gagne), le
  pourcentage du compte (`percentDurationWatched` des cartes de FEhistory, 8 pages ≈ 120 vidéos, et de FEsubscriptions,
  2 pages ; gardé 10 min, relu seulement quand l'onglet YouTube le demande) donne la barre de progression (`percent`) et la reprise
  (`play()` : pourcentage × durée, durée par l'API Google). YouTube ne met ce pourcentage à jour qu'avec 15 à 20 min de
  retard, et seulement là : aucun autre client (web, Android, iOS, /next) ne donne la position exacte avec ce jeton.
`/api/youtube_account` → `tv` {connected, pending, error} ; `POST /api/youtube_tv_login|youtube_tv_logout`. TV :
Système → Compte YouTube → « Synchroniser la progression » (fenêtre du code, `ytAuth.tv`). Jellyfin : le serveur reste
la référence ; rediffusions Twitch : positions déjà renvoyées au compte Twitch (`twitch_save_position`).

### Chargements évités (menu, page)

Menu QML : `/api/state` toutes les 4 s, mais `st` remplacé seulement si la réponse change (`stJson`) ; onglets cachés
sans calcul (`rows: visible ? … : []` pour Rediffusions, YouTube/Jellyfin, Réglages, Système, tuiles d'état) ; liste
des suivis calculée une fois (`followItems`). Page : `/api/state` en pause quand la page est en arrière-plan ; sections
des Réglages (chaînes suivies, compte YouTube, Wi-Fi) chargées à l'ouverture de l'onglet (`settingsLoaders`).

### Sauvegarde et restauration (backup.py)
Menu Système → « Sauvegarde et restauration » (QML `backupMenu`, Lua `backup_menu`, fenêtre relue toutes les 2 s) :
par clé USB branchée, « Sauvegarder sur … » puis ses 4 dernières sauvegardes (OK → confirmation → restauration puis
redémarrage). Page : Réglages → Sauvegarde, « Télécharger la sauvegarde » (`GET /api/backup/download`) et « Restaurer
depuis un fichier » (`POST /api/backup_restore`, corps brut). API : `GET /api/backup` (clés, sauvegardes, busy,
message affiché une minute), `POST /api/backup` `{action: save_usb|restore_usb, path, name}`.
Archive au format de `backup.sh` (`home/<utilisateur>/…`, reprise par `install.sh --restore` et inversement) +
`stream-box-backup.json` (date, nom de la box) + `stream-box-wifi.json` (Wi-Fi enregistrés dont le mot de passe est
lisible par nmcli, recréés s'ils manquent). Pas les appairages Bluetooth (root ; `backup.sh` les garde). Restauration :
seuls les chemins de la liste, remappés vers le dossier personnel d'ici, filtre « data » de tarfile, droits des
dossiers remis (700) ; les réglages d'avant sont gardés dans `~/.local/state/stream-box/before-restore.tar.gz`.
Clés : `lsblk` (USB / amovible, jamais le disque de la box), montées par `udisksctl` le temps de lire ou d'écrire puis
démontées (retirables tout de suite) ; fichiers `stream-box-backup-AAAA-MM-JJ-HHMM.tar.gz` à la racine. Liste lue une
fois par clé branchée. Image : udisks2, exfatprogs, dosfstools et règle polkit `52-stream-box-usb.rules` (montage pour
media même hors de la session de la TV ; install.sh l'ajoute aussi).

### Menu comme page principale (bouton Retour)
Le grand menu est la page principale : au démarrage (`home_menu()` 3 s après le chargement de stream-box.lua, le temps
que le menu se charge), à la fin d'une vidéo (`BACK_TO_MENU`) et sur Retour pendant un stream ou une vidéo, la lecture
s'arrête (`show_home`, mode `home`) et le menu s'ouvre par-dessus l'écran d'accueil. Plus de Retour ×2 (ni
`/api/resume_last`) : « Reprendre <streamer> » dans En direct et l'Historique font ce travail. En mode `home` (menu
fermé par Menu ou au bout de 90 s : écran d'accueil animé), toute touche rouvre le menu. Menu ouvert sans rien en
lecture : Retour sur les onglets ne le ferme pas (QML `st.mode`, Lua `state.mode`). Fond du menu : lueurs de la
couleur de l'onglet qui dérivent, deux de plus sans vidéo derrière (le voile y est opaque, pour cacher l'écran
d'accueil).

### Fonds animés (qml/Backdrop.qml)
Écran d'accueil (AmbientScreen) et menu sans vidéo derrière (TvMenu, aux couleurs de l'onglet : `hueShift`, calque à
60 %) partagent `Backdrop.qml` : un **fond** (`none` couleur unie, `aurora` taches floues, `fluid` bruit replié, `borealis` rideaux
d'aurore boréale) + un **calque** (`none`, `silk` fils lumineux, `stars` étoiles sur deux plans).
Les calques shader rendent `vec4(lumière, 0)` : mélange additif avec l'alpha prémultiplié de Qt. Fondu enchaîné à
chaque changement (`shownBase` / `shownOverlay`). Réglages → Affichage : « Fond animé », « Par-dessus », « Couleurs de l'accueil » (`color` : violet, blue, green, sunset, pink, ice ; palettes
dans AmbientScreen, le menu garde la couleur de ses onglets). `POST /api/backdrop {base?, overlay?, color?}`,
`~/.config/stream-box/backdrop` (JSON ; ancienne valeur seule acceptée), `backdrop` (le choix) dans
`/api/state` ; l'accueil prend le plus récent de son état (20 s) et de celui du menu ouvert (ui.qml). Au-dessus d'une
vidéo, le menu n'a que son voile (plus de lueurs). Shaders dans `qml/shaders/*.frag`, compilés en `.qsb` versionnés
par `qml/shaders/build.sh` (Docker, PySide6 de la même version que la box : Essentials n'a pas qsb), rendus à
mi-résolution (`layer.textureSize`, composant `ShaderLayer`). Coût mesuré : ~25 % d'un cœur pour ui.py quel que soit
le fond, menu compris.

### Installateur (installer.py, image)
L'image démarre sur une clé USB (live, tout marche, réglages compris) ; menu Système → « Installer sur ce PC »
(QML `installMenu`, visible si `/api/install` dit `available` : disque de `/` en USB / amovible, et image avec
l'installateur) → disques internes de 16 Go ou plus (modèle, taille, ce qu'ils contiennent) → confirmation → progression
→ « Retire la clé USB, puis redémarre ». `POST /api/install {disk}` → `systemctl start --no-block
stream-box-install@<disque>.service` (règle polkit `53-stream-box-install.rules` : media ne peut démarrer que ce
service) → `/usr/local/lib/stream-box/install-to-disk` (root) : revérifie le disque (pas celui de la box, interne,
16 Go), GPT (ESP 512 Mo + partition « root-x86-64 » btrfs zstd sur le reste), `cp -a --one-file-system /` (système en
marche tel quel, `/home/media` compris : comptes, favoris, historique), points de montage recréés, copie de l'ESP de la
clé, `bootctl install` (entrée du micrologiciel ; sinon chemin de secours EFI/BOOT/BOOTX64.EFI). Pas de root= : systemd
retrouve la partition système par son type sur le disque d'où il a démarré. État : `/run/stream-box-install.json`
(state running|done|error, step, percent, error). Testé dans QEMU (clé usb-storage + NVMe vierge, puis NVMe seul).

### Accès SSH (menu Système)
Ligne « Accès SSH » (interrupteur, QML `loadSsh`, visible si l'unité existe) : `GET /api/ssh` (`available`, `enabled`,
`active` de sshd.service), `POST /api/ssh {enabled}` → `systemctl start stream-box-ssh@enable|disable.service`
(root, `/usr/local/lib/stream-box/ssh-access` ; règle polkit `54-stream-box-ssh.rules`, media ne peut lancer que ces
deux-là). L'image n'autorise SSH que par clé et media n'a pas de mot de passe : activer tire un mot de passe lisible
(3 × 4 caractères), le donne à media, ajoute `sshd_config.d/10-stream-box-password.conf` (PasswordAuthentication yes)
et le garde dans `/var/lib/stream-box/ssh-password` (root:media 640) ; le menu affiche `ssh media@<adresse>` et ce mot
de passe (`/api/ssh` ne le donne qu'aux requêtes de 127.0.0.1). Couper : sshd désactivé, mot de passe et autorisation
retirés (les clés restent). Image : SSH coupé par défaut (mkosi.finalize.chroot). Script, unité et règle dans `image/mkosi.extra`, copiés aussi par install.sh. Couper SSH ne ferme pas les
sessions ouvertes (elles sont dans leur scope de session, pas dans sshd.service).

### Mode développeur (menu Système)
L'image n'a pas de mot de passe root, media n'a pas sudo, le noyau (UKI) a une ligne de commande figée : sans ce mode,
une box installée n'offre aucun accès root. « Mode développeur » (interrupteur, confirmation à l'activation) :
`POST /api/dev {enabled}` → `stream-box-dev@enable|disable.service` → `/usr/local/lib/stream-box/dev-mode` (root) :
`/etc/sudoers.d/90-stream-box-dev` (`media ALL=(ALL:ALL) NOPASSWD: ALL`, vérifié par visudo) + `ssh-access enable`
(mot de passe affiché sur la TV) ; marque lisible par media `/var/lib/stream-box/dev-mode` (`GET /api/dev`). Couper
retire sudo, SSH garde son réglage. `POST /api/ssh` et `/api/dev` : 403 hors de 127.0.0.1 (seulement depuis le menu
de la TV, pas depuis le réseau). Règle polkit `55-stream-box-dev.rules`.

### Première configuration (box neuve)
Tant que `~/.config/stream-box/setup-done` manque (et sans historique : une box qui a déjà servi compte comme
configurée, la marque est alors posée), `/api/state` et l'état de l'écran d'accueil ont `first_run`. TV : l'écran
d'accueil montre « Bienvenue · Continue sur ton téléphone » et le QR code de la page en grand (330 px), sans lives ni
plannings ; stream-box.lua (`setup_pending`, même règle, lue dans les fichiers) n'ouvre pas le menu, ni au démarrage
ni par une touche (message « Continue la configuration sur ton téléphone »). Page : écran `#setup` à la place des
onglets (restaurer une sauvegarde ; sections Wi-Fi et streamers des Réglages déplacées dedans ; « Terminer » →
`POST /api/setup` → marque + script-message `streambox-setup-done` → la TV ouvre le menu). Une restauration
(`backup.restore`) pose aussi la marque.

### Curseur
cage a un thème de curseur invisible (`cursors/blank`, lien `cursors/default` : wlroots ignore `XCURSOR_THEME` et
charge toujours le thème « default », cherché d'abord dans le `XCURSOR_PATH` donné par la session : image et install.sh) : son pointeur n'apparaît plus pendant les transitions sans fenêtre. start.sh retire ces variables pour
les applis (une vraie souris garde son pointeur, masqué au bout de 4 s).

Assistant des touches : Retour sur la télécommande virtuelle de la page l'annule sans rien enregistrer (`learn_cancel`,
phase `cancel` de KeyWizard.qml).

### Agent Bluetooth (btagent.py)
Les télécommandes Xiaomi lancent elles-mêmes l'appairage (et le refont à la reconnexion) : sans agent, BlueZ refuse
(« No agent available »), la télécommande se reconnecte en boucle toutes les 10 s sans marcher. btagent.py (lancé par
start.sh avec le Python de media-venv, dbus-fast) est l'agent par défaut (NoInputNoOutput) : accepte les appareils de
confiance, et tous pendant une recherche ou un appairage du menu (btsetup.py touche
`$XDG_RUNTIME_DIR/stream-box-bt-pairing`, fenêtre de 120 s), refuse le reste ; se réenregistre si bluetoothd redémarre.

### Pièges de la box installée
- Relancer la session : `sudo rm -f /run/greetd.run && sudo systemctl restart greetd` (sans retirer ce fichier, greetd
  ne relance pas `initial_session` et tombe sur l'invite de connexion texte de tty1).
- Dell OptiPlex en « RAID On » (Intel RST) : le SSD NVMe est caché au noyau d'Arch (« remapped NVMe », seul le noyau
  de CachyOS a un correctif) ; BIOS → SATA Operation → AHCI. L'installateur le détecte (contrôleur de classe 0x010400,
  `raid_mode`) et le dit.

### Écran de démarrage (Plymouth, image)
Thème `stream-box` (créé par mkosi.postinst.chroot à partir de « spinner » : logo arrondi + « Stream Box » rendu par
ffmpeg, roue, fond de l'écran d'accueil 0x0b0710), `/etc/plymouth/plymouthd.conf`, ligne de commande `splash
plymouth.ignore-serial-consoles vt.global_cursor_default=0` (en VM, systemd ajoute une console série : sans
ignore-serial-consoles, Plymouth passe en texte). `plymouth-quit.service.d/10-retain-splash.conf` : `plymouth quit
--retain-splash`, l'image reste jusqu'à ce que cage prenne l'écran. Ne pas masquer plymouth-quit : greetd attend
plymouth-quit-wait (démarrage bloqué « Hold until boot process finishes up »). Pas de Plymouth dans l'initrd : l'écran
apparaît après le passage sur la partition système. Sur clé USB, le chargeur (~20 s) et Mesa (~11 s) sont lents ; sur
le SSD, bien plus courts.

### Essais en VM (image de test)
`bash image/build.sh test` : image `stream-box-test.raw` avec SSH activé par la clé `image/test-key` (créée au premier
essai, jamais publiée : `/etc/ssh/stream-box-test-keys`). QEMU dans le conteneur mkosi (KVM, OVMF), clé en
`usb-storage` + NVMe vierge pour l'installateur, `-vga std`, moniteur QEMU pour des captures (`screendump`).

### Clavier classique
Par défaut (input.py `DEFAULTS`, secours stream-box.lua `KEYS`) : flèches, Entrée = OK, Échap / Retour arrière =
Retour, Windows, Début ou M = menu de la TV, O = options (≡), H = écran d'accueil, Espace = lecture / pause (action `corner`),
+ / − (et pavé numérique) = volume, touches multimédia (suivante / précédente = → / ←, arrêt = Retour). Codes de Linux
positionnels (QWERTY) : le M d'un AZERTY arrive en KEY_SEMICOLON, mappé aussi.
