# Stream Box

> Les valeurs entre chevrons (`<ip-box>`…) et les domaines `example.com` sont propres à chaque installation. Les
> détails d'une installation donnée (réseau, matériel, comptes) vont dans `CLAUDE.local.md`, non versionné.

Mini PC Linux branché sur la TV. Au démarrage, il lance en plein écran le dernier stream Twitch regardé, avec le chat
en overlay. Quand la souris bouge (ou avec une télécommande Bluetooth), un menu permet de changer de streamer et de
régler le chat. Une télécommande web (installable comme appli) fait la même chose depuis un téléphone, et plus encore.
Installation et mise à jour : `install.sh` (voir le README) ; sauvegarde des réglages : `backup.sh`.

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
  mpv vide pendant `BACK_TO_TWITCH` (3 s) → retour au stream (le délai laisse Jellyfin enchaîner l'épisode suivant).
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
- Page : carte « En cours » visible seulement en mode média (titre, barre de lecture qu'on touche pour sauter —
  pas de glisser, qui partirait en faisant défiler — via `POST /api/seek_to {position}`, ±, sous-titres via `POST /api/sub {id}`
  → `sid`, retour au stream), et bloc replié « Lire un lien sur la TV » (`POST /api/play {url}`, `/api/seek {delta}`,
  `/api/twitch`) et cible de partage Android
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
  direct → 750 KiB. Télécommande Bluetooth : ←/→ ±10 s, Retour = direct. Page : −30 s / +30 s / Direct
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
  ↑ affiche/retire la barre de lecture (↓ la retire), Menu ≡ change de sous-titres, Retour ×2 revient au stream. Menu ouvert : flèches = sélection (le bouton
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
- `channel` : dernier streamer regardé, repris au démarrage s'il est encore dans `streamers.txt` (sinon le premier).
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
(En direct, Rediffusions, Historique, Réglages, Système), contenu à droite, vidéo assombrie derrière, refermé par Menu, Retour depuis les
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
traitement ») n'est pas autorisée : la carte garde son ▶ dessiné. Prochaine étape : finitions.
