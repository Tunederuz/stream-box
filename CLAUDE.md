# Stream Box

> Values in angle brackets (`<box-ip>`…) and the `example.com` domains are specific to each installation. The details
> of a given installation (network, hardware, accounts) go in `CLAUDE.local.md`, which is not versioned.

Linux mini PC plugged into the TV. At boot, it shows the large menu (main page, animated background, nothing playing); a Twitch stream is watched with the chat
as an overlay. With a Bluetooth remote, a menu lets you change streamer and adjust the
chat (moving the mouse no longer opens anything). A companion app (installable as an app) does the same from a phone, and more.
Installation and update: `install.sh` (see the README); settings backup: TV System menu and companion app (`backup.py`), or `backup.sh`.

## Languages
- Code, comments and docs are in English. User-facing texts are written in English in the code and wrapped with
  `tr()`: Python `i18n.py`; QML `qml/i18n.js` + the `i18n.dict` context property set by `ui.py`; Lua `tr()` of
  `lua/streambox/i18n.lua` (used by `stream-box.lua` and its modules); companion app `tr()` and translation of static texts in `remote.html`.
- Translations: `locales/<lang>.json`, keyed by the English text (placeholders `{name}`).
- Language stored in `~/.config/stream-box/language` (default `en`), changed by `POST /api/language`, which sends the
  script-message `streambox-language` to the TV.
- `GET /api/state` carries `lang` (current code) and `languages` (`{code: name in its own language}`, from
  `i18n.LANGUAGES`). Pickers: companion app section `#language-section` of Settings (moved to the top of the
  `#setup` screen in setup mode, so the language is chosen first); TV: "Interface language" row (header "Language")
  in `settingsRows()` (QML).
- Adding a language: add its code to `LANGUAGES` in `i18n.py` and create `locales/<code>.json`. Decimal separator:
  `qml/fmt.js` (translatable `{int}.{dec}` keys), `I18N.dec` in `lua/streambox/i18n.lua`, and the
  `LANG === "fr"` checks in `remote.html` (currently only `fr` uses a comma); QML dates pick the Qt locale from
  `i18n.lang` in `qml/TvMenu.qml` (`fr_FR` or `en_US`).

## System
- **Arch distribution** (tested on CachyOS). The box runs as the dedicated user **`media`** (bash shell, no
  password; `install.sh` copies the admin account's SSH key to it: `ssh media@<box-ip>`). An admin account with sudo
  is used for maintenance.
- **Dedicated session without a desktop**: the display manager (Plasma Login, or SDDM) automatically logs `media` in
  to the session `/usr/share/wayland-sessions/stream-box.desktop` → `cage -s -- /home/media/stream-box/start.sh`
  (cage = "kiosk" Wayland compositor; `-s` keeps Ctrl+Alt+F2 for a console). To get the desktop back:
  boot with a keyboard plugged in and log in with the admin account.
- **Mode depending on the keyboard**: `stream-box-boot-mode.service` (root, before the display manager) runs
  `/usr/local/lib/stream-box/boot-mode.py` (root copy of `boot-mode.py`, installed by `install.sh`, which passes it
  `--dropin` depending on the display manager). A device with letter keys (Q, A, Z, space) = keyboard. Without a
  keyboard, it writes `<.conf.d folder>/50-stream-box.conf` (autologin media + Stream Box session). With a keyboard,
  it deletes it and the login screen is shown. The main config file must not contain an `[Autologin]` section: it
  would take precedence over the `.conf.d` folder (`install.sh` removes it, with a `.bak-stream-box` backup). The
  choice is made at boot only. After changing `boot-mode.py`, run `install.sh` again (or copy it again as root).
  Test: `boot-mode.py --dry-run`.
- Without a desktop, the power button is handled by logind (`HandlePowerKey=poweroff` by default): immediate shutdown.
- **Sound**: `audio.py` (run by `start.sh`) switches the sound card to its HDMI profile and makes it the default output
  if the current output is not already HDMI: a new user often starts on the internal speaker.
  `~/.config/stream-box/no-hdmi-audio` disables this. WirePlumber then remembers profile and volume
  (`~media/.local/state/wireplumber/`).
- **Network**: preferably Ethernet with a static IP (`install.sh --static-ip … --gateway …`), required for
  Wake-on-LAN (`--wol`, and the matching option in the BIOS). The image enables it on every Ethernet connection
  (`/etc/NetworkManager/conf.d/50-stream-box-wol.conf`: `ethernet.wake-on-lan=64`, a number: the word `magic` is silently ignored there): without it the r8169 driver
  powers the port down at shutdown (link light off, no wake-up from Home Assistant). NetworkManager applies it when
  the connection is activated (`nmcli device reapply` does not); check with `/sys/class/net/<if>/device/power/wakeup`
  (`enabled`).
- **Firewall**: if ufw is active, the companion app's port 8080 must be open to the reverse proxy
  (`install.sh --allow-from <proxy-ip>`).
- **HTTPS**: a reverse proxy (for example Nginx Proxy Manager) to `http://<box-ip>:8080` with a certificate,
  on a name that may only resolve in local DNS. Needed to install the companion app on Android.
- No passwordless sudo for `media`. mpv and cage come from the system packages.

## Files (`/home/media/stream-box/`)
- `start.sh`: waits for the network (`getent hosts www.twitch.tv`), starts `chat_overlay.py` and `remote.py` in the
  background, then loops on a **permanent** mpv (`--idle --force-window --fs --osc=no`, IPC `/tmp/stream-box-mpv.sock`,
  script `stream-box.lua`). The loop restarts mpv if it is closed, and first kills any orphaned streamlink.
- `stream-box.lua` (mpv script; it keeps the state and the orchestration, its self-contained parts are modules in
  `lua/streambox/`, loaded with `require "streambox.…"` through `package.path`: `i18n` (interface language), `ass` (OSD
  drawing helpers, QR code), `fmt` (clock, shorten, amounts), `ambient` (home screen with mpv alone), `polls` (polls
  and predictions with mpv alone), `keys` (fallback key names, learned keys, "Set up keys" wizard, streambox-input).
  Lua allows 200 locals in a chunk: new self-contained parts go into a module):
  - starts streamlink in local HTTP server mode (`--player-external-http`, 127.0.0.1, port 34501–34550, which changes
    with each channel) with `--twitch-low-latency --retry-streams 30`, then `loadfile http://127.0.0.1:<port>/`;
  - if the channel is not live: black screen with "{channel} is not live, retrying in {seconds} s", new attempt every 15 s;
  - quick menu of the simplified version (`lua/streambox/quickmenu.lua` draws the lists of quickmenu.py, see below);
  - publishes `user-data/streambox/{channel,corner,chat_visible}` for `chat_overlay.py`;
  - script-messages for the companion app: `streambox-channel <login>`, `streambox-toggle-chat`, `streambox-cycle-corner`;
  - disables double-click full screen.
- `chat_overlay.py`: anonymous Twitch chat (IRC TLS, login `justinfanNNNN`, read-only). It follows mpv's
  `user-data/streambox/*` properties (`observe_property`): it changes room when the channel changes, and clears the
  messages at that moment. It keeps the last 10 messages (45 s max) and sends them to mpv with
  `osd-overlay` (`ass-events`, resolution 1920x1080). Semi-transparent black background (opacity `chat_bg`, margin `BG_PADDING`): the text
  is first rendered hidden with `compute_bounds` to measure its size, then the background (overlay 2, z=0) is drawn
  under the text (overlay 1, z=1). It handles `CLEARMSG` / `CLEARCHAT`. Standard library only.
- `remote.py`: companion app server on port 8080 (standard library, `ThreadingHTTPServer`): the entry point (same
  command line), which starts the background loops and serves `api.Handler`. Serves `remote.html` and the PWA files
  (`manifest.webmanifest`, `sw.js`, `icon-*.png`). It opens one IPC connection per request. The volume is mpv's, not
  the system's. Its modules (no import cycle; shared mutable state has one owner module and is always reached as
  `module.attr`, never copied by `from … import`):
  - `common.py`: port, mpv socket and `mpv()`, paths, `lan_ip`, JSON file helpers;
  - `api.py`: static files, `state()`, GET routes (`JSON_ROUTES` for exact paths, then the others), POST dispatch;
  - `actions.py`: `POST /api/<name>` handlers (`ACTIONS` dict), the TV menu `keyboard`;
  - `twitch.py`: streamers.txt, who is live (`live_now`), polls and predictions, replays, GQL, followed channels,
    Twitch account; `youtube.py`: channels, feeds, search, auto subtitles (`/subs`), storyboard, TV app progress,
    Google account and subscriptions; `jellyfin.py`: server, home, search, series, play, subtitles, progress;
  - `playback.py`: `play()`, `history_loop`; `history.py`: history.json, `media_key`, `now_playing`;
  - `ambient.py`: weather, Twitch schedules, companion app URL and QR code, first setup, `ambient_loop`;
  - `images.py`: TV preview; `settings.py`: player, power button action, backdrop; `system.py`: power, power key
    lock, wake-up, SSH, developer mode, health, update.
- Twitch account (section of the page, `POST /api/login|logout`, `GET /api/account`): the website's token (cookie
  `auth-token`) is written to `~media/.config/streamlink/config.twitch` (`twitch-api-header=Authorization=OAuth …`,
  mode 600), which streamlink reads on its own. It is the only token that removes ads on channels you are subscribed to
  (third-party app OAuth tokens do not). It is checked via `id.twitch.tv/oauth2/validate` when saved, then every
  30 min. **A rejected token blocks all playback** ("Unauthorized"): if it expires, `remote.py` deletes it and restarts
  the stream anonymously. Without a token, streamlink skips the ads and the picture freezes for their duration. The
  token is also written as a cookie for yt-dlp (`~media/.config/stream-box/twitch-cookies.txt`, `cookies` option of
  `ytdl-raw-options`) for subscriber-only VODs. yt-dlp rewrites this file as 644 on each playback: the folder (700) is
  what protects it.
- Chat settings in the page: background opacity (`chat_bg`, 0–100 %, default 60) and text size (`chat_size`,
  20–60 px at 1920x1080, default 32). `POST /api/set` → script-message `streambox-set <key> <value>` → `set_number` in
  stream-box.lua (bounds, state file, `user-data/streambox/*`), which `chat_overlay.py` observes.
- Resolution: `display.py` (wlr-randr, which cage supports; `wlr-randr` package to install). Only modes ≥ 59 Hz are
  offered: many mini PCs only output 4K at **30 Hz** over HDMI, which drops every other frame of 60 fps
  streams.
  "auto" = the TV's preferred mode if it is 60 Hz, otherwise the highest resolution at 60 Hz. Setting stored in
  `~media/.local/state/stream-box/display_mode`, applied by `start.sh` before mpv and live from the page.
- **Media mode** (stream-box.lua, `user-data/streambox/mode` = `twitch` | `media`): any file that is not the streamlink
  stream (link sent, Jellyfin) stops streamlink and switches to `media`; the chat is hidden. End of file then
  mpv idle for `BACK_TO_MENU` (3 s) → nothing playing any more, large menu (the delay lets Jellyfin move on to the next episode).
  Script-messages `streambox-play <url>`, `streambox-twitch`. An `on_load` hook (before each file is opened,
  including Jellyfin's) sets `demuxer-max-bytes` (750 KiB for live, 150 MiB for videos) and resets
  `hwdec=auto-safe`: the shim imposes its own `hwdec` value when it attaches (default `"no"`, set to `auto-safe`
  in its `conf.json`). `--ytdl-format`: by default 1440p max and **no AV1**, which many iGPUs cannot decode
  in hardware (VP9 and H.264 go through hardware decoding); another rule can be put in
  `~/.config/stream-box/ytdl-format`. With yt-dlp, YouTube sends no ads. Subtitles: `--ytdl-raw-options-append` with
  `sub-langs=fr,fr-FR,fr-orig,en,en-US,en-GB,en-orig` + `write-subs`/`write-auto-subs` (`fr.*` would bring more than 100
  automatic translations). At runtime, pass `ytdl-raw-options` as a JSON object: the text form is split at commas.
  **Automatic** subtitles (`kind=asr`) have overlapping lines (two always on screen):
  at `file-loaded` in media mode, stream-box.lua replaces them with `http://127.0.0.1:8080/subs?u=<url>` (remote.py cuts
  each line at the start of the next one), as EDL `delay_open` so that only the chosen track is downloaded: YouTube
  answers 429 to bursts, especially for automatic translations (`tlang`). yt-dlp and jellyfin-mpv-shim are in `~media/.local/share/media-venv` (links in
  `~/.local/bin`, update: `…/media-venv/bin/pip install -U yt-dlp jellyfin-mpv-shim`).
- Page: collapsed "Play a link on the TV" block (`POST /api/play {url}`, `/api/twitch`) and Android share target
  (`share_target` of the manifest → `GET /share?title&text&url`, first http(s) link found, then redirect to `/`).
- Jellyfin (jellyfin.example.com): jellyfin-mpv-shim in external mpv mode (`mpv_ext`, `mpv_ext_start=false`,
  `mpv_ext_ipc=/tmp/stream-box-mpv.sock`, `mpv_ext_no_ovr`, `enable_gui=false`, `mpv_idle_quit=false`) drives the box's
  mpv; in this mode it never closes mpv. Connected to the user's Jellyfin account (Quick Connect; credentials
  in `~media/.config/jellyfin-mpv-shim/users.json`), so that progress follows that account. Restarted by `start.sh`
  each time mpv is (re)started (it does not reattach to a restarted mpv on its own), log in `/tmp/jellyfin-shim.log`.
  mpv's pause survives a file change: `load_stream` removes it, otherwise the live stream stays frozen. To reconnect: System → Jellyfin on the TV, or
  Settings → Jellyfin in the companion app (Quick Connect, see "Jellyfin (QML menu tab and page)").
- **Who is live**: `remote.py` queries Twitch (GQL, the website's public client-id) every minute for the whole
  list (with profile pictures, `avatars` of `/api/state`, and the live thumbnail, `thumb`, for the page), publishes the result in `user-data/streambox/live` (TV menu: red dot + viewers) and returns it
  in `/api/state` (page: viewers, game, title). After an mpv restart, the menu receives it at the next poll.
- **Auto switch** (stream-box.lua, `auto_switch`, can be disabled: Settings tab → Playback, `POST /api/auto_switch
  {enabled}`, MQTT switch, state in `user-data/streambox/auto_switch` and the `auto_switch` state file): if
  the current channel is offline and was
  chosen more than `AUTO_SWITCH` (60 s) ago, the box switches to the first live streamer in the order of `streamers.txt`.
- **Watchdog**: a live stream whose `playback-time` has not advanced for `FROZEN` (20 s), without pause → the channel
  is restarted. Tested by freezing streamlink (`kill -STOP`).
- **YouTube and anti-bot tokens**: yt-dlp needs a JavaScript engine (**Deno**, pip package `deno` +
  `yt-dlp[default]` for `yt-dlp-ejs`, link in `~/.local/bin`) and a **PO token** for subtitles. Without a
  token, YouTube ends up blocking the home's public IP on `timedtext` (HTTP 429, "Sorry…" page), and a
  valid token changes nothing while the block lasts (a few hours). Tokens: pip plugin
  `bgutil-ytdlp-pot-provider` + its server (same version, `~/.local/share/bgutil-pot-provider`, built with Node
  from the pip package `nodejs-wheel`), user service `stream-box-pot` (127.0.0.1:4416). mpv passes
  `extractor-args=youtube:player_client=mweb,tv_simply;fetch_pot=always`: the TV client chosen by default
  received rejected streams (HTTP 403 on googlevideo, even with IPv4 end to end); tv_simply (2026-10-28) served only
  the first megabytes (403 further on: a video resumed from the history failed at once, "Can't play this video"),
  mweb the whole file; android_vr's https formats are skipped (no GVS token). If YouTube breaks again, compare the
  clients with `yt-dlp --extractor-args "youtube:player_client=<client>;fetch_pot=always" -g <url>` then `curl -r`
  on the URL **both at the start and far into the file** (`-r 0-1000`, `-r 20000000-20001000`): a 206 at the start
  alone proves nothing. Check: `yt-dlp -v --simulate <url>` → `PO Token Providers: bgutil:http`.
- **Rewinding the live stream**: `on_load` keeps `LIVE_BACK` (400 MiB ≈ 7-8 min at 1080p60) with
  `demuxer-seekable-cache=yes`. `live_window()` reads `demuxer-cache-state.seekable-ranges`. When time-shifted or paused,
  `set_live_buffer` raises the forward buffer to 150 MiB (otherwise mpv stops reading the stream and the delay melts
  away); back to live → 750 KiB. Bluetooth remote: ←/→ ±10 s. Page: −30 s / +30 s / Live
  (`POST /api/live_seek {delta|"live"}` → script-message `streambox-live-seek`), delay in `/api/state` (`delay`).
  The playback bar shows "−0:42" or "● LIVE".
- **Live notification**: `remote.py` spots the streamers who have just gone live (not at the first poll)
  → script-message `streambox-went-live <login>` → banner at the top right for 12 s; OK goes there, Back closes it.
- **Replays and clips**: `GET /api/replays?login=` (GQL, 8 VODs + 6 clips of the week, 5 min cache), collapsed
  block in the page; a tap plays the video via `/api/play`.
- **Streamer list from the page**: "Streamer list" section of Settings (`POST /api/streamers {action: add|remove,
  login}`); adding checks that the channel exists on Twitch, comments in `streamers.txt` are kept.
- **Home Assistant (MQTT)**: `mqtt_bridge.py`, user service `stream-box-mqtt` (Python from the media venv, paho-mqtt).
  Reads `/api/state` every 2 s and publishes `stream-box/state` (+ `stream-box/live`, `stream-box/status` online/offline
  as last will); the `stream-box/cmd/*` commands become calls to the `remote.py` API. The bridge starts
  well before mpv: it only announces `online` once the API is ready and the Lua loaded (channel published), and keeps
  commands received before that for 2 min (otherwise the streamer choice sent by HA at wake-up was lost). 19 entities by
  discovery (`homeassistant/…/stream_box/…`), announced again when HA restarts or the list changes. Local config
  `~/.config/stream-box/mqtt.json` + `mqtt-password` (600). Entities and example automation: `docs/home-assistant.md`.
- **Home screen on demand**: `home` mode (`show_home`, script-message `streambox-home`, `POST /api/home`,
  button in the page above the streamers, first row of the TV menu, MQTT button): stream stopped, ambient screen shown, no
  automatic switch or watchdog; you leave it by choosing a streamer or a video, or through Jellyfin.
- **Ambient screen** (stream-box.lua, `draw_ambient`) when nothing is playing (channel offline, empty list, `home` mode): clock,
  date in the interface language, weather, upcoming scheduled streams, and the status message small at the bottom, on an "aurora" background (`AURORA`:
  three very blurry blobs that drift, redrawn every 2 s, ~2 % CPU). The text moves a little every
  minute (TV). Data from `remote.py` (`ambient.ambient_loop`, every 10 min, republished every 10 s in
  `user-data/streambox/ambient`): Open-Meteo weather (location in `~/.config/stream-box/ambient.json`, `city`,
  `latitude`, `longitude`, `timezone`; without this file, no weather) and Twitch schedules (GQL `schedule.segments`,
  slots of the current week: a past slot is moved forward one week; cancelled slots (`isCancelled`)
  ignored; during a Twitch break (`schedule.interruption`, the streamer's vacation): "on a break until {date}"; beyond
  a week, the date is added to the day; testable computation in `next_streams`). mpv screenshots are empty when
  nothing is playing: check the screen on the TV.
- **Companion app QR code** (guests): `remote.py` (`ambient.remote_qr`) computes it with segno (media venv, called as a
  subprocess: `remote.py` runs with the system Python) for the address in `~/.config/stream-box/remote-url`
  (install.sh's `--remote-url` option; otherwise `http://<box IP>:8080`, which the firewall may block), and publishes it
  in `user-data/streambox/ambient` (`qr`: address + lines of "0"/"1"). The Lua's `qr_code()` draws it as a
  single ASS path, in light gray (less striking than white): at the bottom right of the ambient screen (it drifts with
  the rest) and to the right of the menu when the ambient screen is not shown.
  Adjustable display (Settings → Display, `POST /api/qr {mode}`, MQTT select, script-message `streambox-qr`, state
  file `qr`): `always`, `timed` (`QR_SECONDS` = 30 s each time the ambient screen appears and the menu opens),
  `never`; the check is done in `qr_code()`.
- **Polls and predictions** (`twitch.events_loop` / `fetch_events`): no more PubSub for a viewer, so
  GQL polling every 10 s, only during a live stream from the list with the panel enabled: `user.viewablePoll`
  (current or ended poll; no end time, the result is shown for 60 s after it is seen ended),
  `channel.activePredictionEvents`, `lockedPredictionEvents`, and `resolvedPredictionEvents(first:1)` (result shown
  for 60 s after `endedAt`). Published in `user-data/streambox/polls` (not to be confused with `user-data/streambox/events`, the
  setting). Panel at the top center (`draw_events`, redrawn every second for the time left), away from the chat
  corners. Yes/no setting `events` (Settings → Playback, MQTT switch). Predictions can be read without an account; no
  poll was open on ~280 live streams at testing time, the display was checked with simulated data
  (`set_property user-data/streambox/polls …` through the IPC).
- **Night mode**: audio filter `@night:lavfi=[acompressor=…,alimiter=…]` added/removed by the Lua (setting `night`,
  TV Settings → Playback, MQTT switch). `af` is a global mpv option: it stays from one file to
  the next, Jellyfin included. Yes/no settings: script-message `streambox-flag <key> yes|no`, `POST /api/flag {key,
  enabled}`, state in `user-data/streambox/<key>` and the state file of the same name.
- **History and resume** (`playback.play` / `history_loop`, `history.py`) of videos started from the companion app (links,
  YouTube, Twitch replays and clips; Jellyfin handles its own progress). Stable key per video (`media_key`: YouTube
  id, VOD id, clip slug), history in `~media/.local/state/stream-box/history.json` (60 entries).
  Position recorded every 10 s; resume if > 30 s and not "watched" (less than 30 s from the end or beyond 95 %),
  given to mpv as the file's `start=` option (`streambox-play <url> <start>`). **Twitch replays synced
  with the account**: position read at start (`video.self.viewingHistory`, the most recent wins over the box's)
  and written every 30 s and on stop (mutation `updateUserViewedVideo`). YouTube: impossible to sync
  with the account (no API; yt-dlp can only mark as "watched"), the memory stays on the box. Page: History block
  (Resume / From the beginning / ✕, clear all) and progress bars in the replays (`GET /api/history`,
  `POST /api/history {action: remove|clear}`, `POST /api/play {url, from_start}`). Known limitation: some
  Twitch replays (`EVENT` playlist) start one minute after the beginning even without resuming, bare mpv included.
- **TV preview** in the page (collapsed block, Remote tab): `GET /api/preview` →
  whole screen by **grim** (cage's wlr-screencopy protocol: ambient screen, menu and banners included, scaled down to
  960 px by `-s`); without grim, mpv's `screenshot-to-file … window` scaled down by ffmpeg. One
  capture at a time, kept for 1 s for several phones. The page asks for another one 1.5 s after each response,
  only while the block is open and visible. Without grim and without video: 204 response.
- **Dependencies**: `update.sh` (systemd user timer `stream-box-update.timer`, every day ~5 am, caught up at boot,
  without a word; by hand: Settings → Advanced → "Update dependencies", `POST /api/update_deps`) updates streamlink, yt-dlp, Deno, Node, the token plugin and jellyfin-mpv-shim (and rebuilds the token server if its version changes), tests each venv and restores the previous versions if the test
  fails. Log: `~media/.local/state/stream-box/update.log`.
- **git**: `/home/media/stream-box` is a git repository (no secrets in it: Twitch token and Jellyfin credentials
  are elsewhere). Commit after each change.
- **Bluetooth remote** (tested with the Xiaomi TV Stick one, paired and trusted for `media`). Linux
  sees it as a keyboard without the Q and A keys: the boot rule does not take it for a real keyboard. Another
  remote that would announce these keys must be added to `IGNORE` in `boot-mode.py`. cage passes its keys to mpv; stream-box.lua binds them (`KEYS`, `on_key`): OK = `0x21ffa0`, Menu ≡ =
  `0x2111a0` (Xiaomi remote codes: to adapt for another one), Back = `GO_BACK`, Home = `HOMEPAGE`, arrows, volume (mpv's default actions). Menu closed in
  Twitch: up/down change channel, OK shows/hides the info banner (title, "LIVE" or delay), Home opens
  the large menu (OK too on the home screen; the quick menu with mpv alone), Menu ≡ shows/hides the chat. In all modes: WWW (the
  "browser" button) shows the home screen, Play (`PLAY`/`PLAYPAUSE`, bound on purpose: otherwise mpv pauses, which
  froze the live stream) moves the chat to another corner. In video: OK pauses, ←/→ ±10 s,
  ↑ shows/hides the playback bar (↓ hides it), Menu ≡ changes subtitles. Menu open: arrows = selection (the closest
  button in that direction), OK confirms, Back/Home close it. Power turns the box off (logind).
  Pairing: put the remote in pairing mode (Xiaomi: Home + Back until it blinks), then
  `bluetoothctl` → `scan on`, `pair`, `trust`. Pairings are included in the `backup.sh` backup.
- **Video playback bar** (stream-box.lua, `draw_bar`) in the style of YouTube: banner at the bottom (title, played
  part in purple, buffered part, time). Shown for `BAR_SECONDS` (2.5 s) by ↑, ←/→ or OK; ↑ or ↓ hide it; always
  visible while paused (pause symbol drawn). Preferred to mpv's OSC, disabled (`--osc=no`) because it is designed
  for the mouse and conflicts with our menu.
- Power icon at the top right of the page (confirmation "Turn off the box?", or "Put the box to sleep?" when the power button is set to sleep) → `POST /api/poweroff` →
  `systemctl poweroff` as media. Allowed without a password by `/etc/polkit-1/rules.d/50-stream-box.rules`
  (installed by `install.sh`), including when another session is open (SSH).
- PWA: thanks to the reverse proxy's HTTPS, Chrome Android offers "Install app"; on iPhone, "Add to Home
  Screen". Over direct HTTP (:8080), Android would only give a shortcut.
- `~/.config/stream-box/streamers.txt`: one login per line, `#` for comments. Reread each time the menu opens, no need to restart.

## Saved state (`~media/.local/state/stream-box/`)
- `channel`: last streamer watched, current channel at boot ("▶  Resume {channel}" in the menu, "Back to the stream") if it is still in `streamers.txt` (otherwise the first one).
- `chat_corner`: `tl` / `tr` / `br` / `bl`.
- `chat_visible`: `yes` / `no`.
- `chat_bg`, `chat_size`: numbers. `display_mode`: `auto` or `WxH@Hz`.

## streamlink
Installed in a venv `~/.local/share/streamlink-venv`, with a link in `~/.local/bin/streamlink` (`start.sh` adds
`~/.local/bin` to the PATH). The system package is not used: it is often behind, and the Twitch plugin breaks
when Twitch changes something. Update: `~/.local/share/streamlink-venv/bin/pip install -U streamlink`.

## Known pitfalls
- The IPC connection to mpv must stay open: mpv removes the overlay when the client disconnects.
- ASS colors are in BGR (`&HBBGGRR&`). Text is escaped as in mpv's built-in scripts
  (`\` → `\` + U+FEFF, `{` → `\{`). Logins that are too dark are replaced with lavender (#C9B8FF).
- The ☐/☑ glyphs are not in every font: the checkbox is drawn in ASS.
- `pkill -f <pattern>` run over SSH can kill itself, because its own command line contains the pattern.
  Use `pkill -f "[c]hat_overlay"`.

## Testing remotely
- `start.sh` is run by cage: killing mpv (`pkill -u media -x mpv`) restarts it with the new `stream-box.lua`.
  For `remote.py` or `chat_overlay.py`, kill them then start them again with `nohup` (or reboot the box).
- Deploy by renaming (copy to a temporary folder then `mv`), not by overwriting: bash rereads `start.sh`
  while it runs.
- Simulate the mouse through the IPC: `{"command":["mouse",x,y]}` to move, `["mouse",x,y,0,"single"]` to click.
  Coordinates are in screen pixels (`osd-dimensions`).
- Screenshots: `["screenshot-to-file","/tmp/x.png","window"]`. They come out empty as long as no video is playing.
- Someone may click in front of the TV during a test: the state can change while you are testing.

## Tests and checks
- Workflow: work on a branch, merged into main through a pull request; `.github/workflows/checks.yml` runs on pull
  requests to main only (and by hand), testing the branch merged into main: squash-merge once they pass, after
  bringing the branch up to date with main if main moved since. Before pushing, the parts of `tools/check.sh` that the
  change touches (`python` for Python or the translations; `page` for remote.html; `shell`; `qml`), all of them for a
  broad change; each part exits non-zero on a failure (gate the commit on it).
- `tools/check.sh` runs locally, in Docker, what `.github/workflows/checks.yml` runs: `python` (ruff with
  the pyflakes rules of `ruff.toml`, syntax errors included, `python3 -m unittest discover -s tests -t .`), `page`
  (`tests/page/check-page.js`: remote.html in jsdom against a fake API, `tools/qmlshots/fixtures.json` and
  `tests/page/fixtures.json`, on both tabs with every Settings group open; fails on a thrown or rejected error, a
  `console.error` or a "status error" shown; the page's silent `catch` blocks call `bug(e)`, which logs mistakes in
  the code but not the box being unreachable), `lua` (`tests/test_lua.py`
  in the same mpv as the box image: Lua modules under luajit, then `stream-box.lua` loaded in a real mpv **in French**
  and driven through its IPC), `shell` (shellcheck), `qml` (qmllint `[syntax]`, then the steps of
  `tools/qmlshots` without ReferenceError / TypeError / binding loop, `QMLSHOTS_NOSHOTS=1`: no screenshot there).
  The fixtures follow the real API's shape (both menus read them: a missing field is a false error). Tests needing mpv or luajit are skipped without them.
- `tests/`: translations (`test_locales.py`: same placeholders, every literal `tr()` translated, no stale key: remove
  the keys of texts you delete), `input.py` key repeat on a fake input device, `i18n.py`, `history.media_key`, the
  remote.py API started for real (`test_api.py`: throwaway HOME, fake mpv socket; skipped on a running box).
- A change visible on the TV still gets tested in the VM, with the box set to French before the session starts.

## Ideas
- Emotes as images (`overlay-add` with raw BGRA bitmaps): much more complex.
- Show in the menu who is live.

## Companion app page (remote.html)

Dark frosted-glass theme (glassmorphism: translucent `backdrop-filter` cards and tabs, over drifting color blobs
in `body::before/::after`; the background is on `html`, otherwise the `body` one hides them), with no
external dependency, tabs stuck at the top: header with the TV state, "On the TV" card
(live thumbnail, streamer, title, rewind; compact for the home screen and an offline channel),
streamers as cards with a picture (red ring when live), inline SVG icon buttons, switches (`button.toggle`
with `aria-pressed`, drawn in CSS). Previous version of the page: git tag `page-v1` (`git show
page-v1:remote.html > remote.html` to go back). To judge a change without a phone: copy of the
page with a `render(<state from /api/state>)` instead of `refresh()`, captured by `firefox --headless --screenshot`
(it does not wait for the page's requests; do not scroll: sticky elements are drawn badly there).

## Large TV menu

In the style of Android TV, opened by the remote's Menu button (Home key) in all modes: rail on the left ("⌂  Home
screen", then the tabs Live, Following, Replays, YouTube, Jellyfin, History, Settings, System), content on the right,
video dimmed behind; closed by Menu, by Back from the rail over a video, or after 90 s without a key press. While it
is open (`user-data/streambox/tvmenu`, which `chat_overlay.py` also follows to hide the chat), `stream-box.lua`
passes it all keys (`streambox-tvmenu-key`); it reads the state and acts through the remote.py API, like the
companion app. Settings: ◀ ▶ change a value, OK toggles a switch; the resolution chosen with the arrows is only
applied on OK. Live: shortcuts above the streamers ("▶  Resume {channel}" outside the stream, second stream; ▲ from
the first row). System: account status, power off (OK twice), companion app QR code for whatever requires typing
text. Testing: `keypress HOMEPAGE`, `keypress DOWN`… through the IPC, then `/api/preview`.

With mpv alone, the "simplified version" (System → Version setting, fallback after the Qt app failed, or QML menu that failed to load: ui.py
then writes `user-data/streambox/menu = small`) there is no big menu: Menu opens and closes the quick menu, and
holding power does the power button's usual action. (The Lua copy of the big menu, tv_menu.lua, was dropped: it
duplicated every feature and kept drifting from the QML one.)
Quick menu: lists of text, no thumbnails nor keyboard (searches from the companion app). `quickmenu.py` (remote.py)
builds them from the same functions as the API (live, following, replays, YouTube favorites and subscriptions,
Jellyfin and Plex rows and series, history, home screen, settings: sound, resolution, language, chat; system: back to
the full version, sleep, shutdown, restart) and keeps the navigation (stack of screens, selection); stream-box.lua
only forwards the keys (`script-message streambox-qm open | close | key <name>`, heard by quickmenu.py on its own
IPC connection as `client-message` events) and draws `user-data/streambox/quickmenu` ({title, items {label, info,
on, dim}, sel, note}; `{}` closed) with `lua/streambox/quickmenu.lua` (panel on the left, scrolls with the
selection). A screen builds its items in a thread ("Loading…" meanwhile; an error becomes an "Unavailable" row) and
again after an action that changes it; playing closes the menu first. No answer within 3 s: "Menu unavailable"
message (remote.py down). Closed after 2 min without a key. Moving the mouse opens nothing.

### Large menu in QML (qml/TvMenu.qml)

With the Qt app, the large menu is in QML (rendered by the GPU, animations: fade on opening, tab
pill that slides, content that slides in, cards that grow with a blurred glow, smooth scrolling of
grids and rows, animated switches, actions popup that bounces). Opening:
stream-box.lua's `streambox-tvmenu-open` intercepted by python-mpv (`register_message_handler`). Keys: while the
menu is open, `View.keyPressEvent` gives them to QML (`box.keyPressed`, roles from `MENU_KEYS`: up, ok, back, home…)
instead of mpv (volume stays with mpv); a key sent through the IPC (`keypress` → stream-box.lua →
`streambox-tvmenu-key`) arrives at the same place, which is useful for tests. `box.setMenuOpen` writes a real boolean to
`user-data/streambox/tvmenu` (`MPV_FORMAT_FLAG`: python-mpv would write the string "yes") for the chat and the mouse.
Data and actions: `XMLHttpRequest` to the remote.py API; pictures and thumbnails loaded directly from
Twitch / YouTube by Qt and rounded by `MultiEffect`; weather and QR code through
`box.ambient` (observed property), opaque veil without video (`box.videoActive`). Components: `RoundImage`,
`Marquee` (text clipped at rest, two copies that scroll on focus), `FocusFrame`, `StreamerCard`, `VideoCard`,
`SettingRow`, `QrCode`, `fmt.js`.
Settings tab (one tab; "System menu" below means it): `settingsRows()` is the list of sections (`sectionIds`, each
row with `sectionHint` (what it holds, grey line) and `sectionAlert` (only when something needs attention: update
ready or failed, no network, installation running), OK or ▶ opens it, `open: true`) then the power rows (sleep, restart, shut down); a section
open (`section`, `sectionRows(id)`: picture, playback, chat, look, accounts, network, devices, updates, backup,
advanced), its rows, title in the header (`sectionTitle`); Back or ◀ (on a row without a value) returns to the list
on that section (`leaveSection`, `rootSel`). The Lua menu of the simplified version keeps its own System menu.
Companion app, Settings tab: the same grouping, folded groups (`.group`, `data-group`: channels, accounts, picture,
look, network, updates, backup; `openGroup(id)`, the open ones remembered in localStorage `groups`).
Structure: `TvMenu.qml` keeps the data, the API calls, the timers, open / close, the computed rows (`settingsRows`,
`ytRows`…), the dialog builders and all the key handling; the drawing lives in `qml/menu/`, one component per part,
each taking the menu as `required property var menu` (`LiveTab { menu: menu }`; no id lookups across files): `Rail`,
`Header`, `LiveTab`, `FollowsTab`, `ReplaysTab`, `MediaTab` (YouTube and Jellyfin page), `HistoryTab`, `RowsTab`
(Settings list), `SystemStatus` (QR code and status tiles, beside the list of sections), `SearchKeyboard`, `YtAuthDialog`,
`ActionDialog`, and `CardRow`, the horizontal card row (clip wrapper, ListView scrolling card by card with its
`first` / `fits` window). Layout numbers in `qml/menu/layout.js` (content x and width, card size and step, row
height…). `CardRow` pitfalls: callers bind `view.model`, `view.currentIndex`, `view.delegate`, `view.visible`
directly on its ListView (going through properties of `CardRow`, the index reset when a row changed was never
re-applied), and its sizes are literal numbers, not bindings to `layout.js` (the caller's current index arrives
before, `fits` was then -1 and the first scroll was lost).
YouTube card previews (the focused card playing its video) were tried and dropped on 2026-10-27: resolving links with
yt-dlp, in advance for the neighboring cards, got the box taken for a robot by YouTube within two hours ("Sign in to
confirm you're not a bot" for every video, the player's included). Do not add requests to YouTube per card.
Live and Following tabs, live in the background: after 0.9 s on a live channel (`menu.bgLive`: Live or Following
tab, content, no dialog nor keyboard, and nothing playing behind the menu, `box.videoActive` false), its live plays muted behind the whole menu,
above the backdrop and under a black veil (0.55) that keeps the cards readable; moving to another streamer stops it
and restarts the 0.9 s. The video is `qml/menu/LivePreview.qml` (third libmpv player `preview_player` of ui.py,
"livePreview"; never fully invisible, opacity 0.001: libmpv needs its render context before a video starts):
`startPreview(login)`; ui.py starts its own streamlink (`PREVIEW_PORT` 34591,
720p) and loads it once served (retries every 1.5 s while the player is idle, 6 at most). (Tried before: a banner
above the grid took too much room; a card growing over its neighbors hid them; a full-screen peek on ▶.)
Video cards (`VideoCard`: 456 px wide, 16:9 thumbnail, height from the width): 3 per row in Replays, YouTube,
Jellyfin (step 482) and History (3 columns, 2 rows); the Replays and YouTube/Jellyfin rows scroll vertically (one full
row, the top of the next one showing).
Back: from the content to the rail, from the rail closes the menu only over a video (nothing playing: the menu stays the main page). A tab with
nothing to focus (empty list, history…) keeps the focus on the rail (`canEnter`, `checkArea`). Pitfalls: font sizes ×0.78 compared to the ASS menu (Qt draws larger for
the same value); in `onTabChanged`, read `tabs[tab].id` and not `tabId` (binding not recomputed yet); lists
with `clip`: margins (`leftMargin`, `topMargin`) so as not to cut the focus glow; models as an item count
(the delegates read the arrays) so that the list does not reset on every state poll. Testing without
a remote: `keypress HOMEPAGE`, `keypress DOWN`… through the IPC, screenshots with `grim`. Without a box:
`tools/qmlshots` (Docker: PySide6 of the box, Xvfb, Mesa; mocks of ui.py and of the remote.py API, `fixtures.json`)
plays 233 steps through every tab and dialog and saves one PNG per step plus `console.log` (QML warnings, menu state,
requests); `run.sh shoot` before / after a change, then `run.sh diff` (see its README).

Threads and libmpv (hangs and crashes seen, fixed):
- Qt's main thread never calls mpv directly (keys, mouse, `force-window`, menu boolean): queue
  `to_mpv` emptied by a separate thread. A synchronous call could wait for the video output, which waits for the render
  thread, blocked by the main thread;
- rendering: `ctx.update()` before each `render`, and `block_for_target_time=False`: otherwise the render thread stayed
  blocked in `render` at startup, one restart in two or three (IPC socket dropping connections, frozen picture);
  10 restarts in a row without hanging after the fix;
- on exit, no `player.terminate()`: libmpv stops abruptly (abort, code 134) if the render context still
  exists; `os._exit` directly (mpv has already quit). Before, every `quit` ended in a crash, and three stops
  close together made `player.sh` fall back to mpv alone until the next reboot;
- `kill -USR1 <ui.py pid>` writes each thread's stack to `/tmp/stream-box-ui.log`; crashes: `coredumpctl`.
Focus glow: `RectangularShadow` (QtQuick.Effects), under the item. Grids and rows without `clip` (it cut the
glow): items outside the visible area fade out (`rel` = position minus `contentX`/`contentY`).
View margins only in the scrolling direction (`topMargin` of a horizontal row, `leftMargin` of a vertical
grid): Qt resets the other axis to zero at the first `positionViewAtIndex`, and the row jumped onto the neighboring text.

### Two streams at once (Qt app)

Second libmpv player (`pip_player` in ui.py, muted, small live buffer, no interface) with its own
streamlink (port `PIP_PORT` 34590; 720p in picture-in-picture, best quality side by side), drawn by a second
`MpvVideo { which: "pip" }`. Layouts in ui.qml: `pip` (30 % of the screen, at the top, on the side opposite the chat if
it is at the top right, shadow and border) and `split` (two halves). The videos keep their render size and are
scaled down by `scale`: animated transitions without recreating the frame buffers. Commands: QML menu (Menu ≡ on a Live
or Following card that is live: Picture-in-picture, Side by side; shortcuts Swap, Side by side/Picture-in-picture, Close),
companion app ("Second stream" bar when it is active), `POST /api/pip {action: open|close|swap|layout, name, layout}` →
script-message `streambox-pip` → `Pip` class of ui.py. State in `user-data/streambox/pip` and `/api/state` (`pip`).
Swap = the second one's channel becomes the main one (`streambox-channel`) and vice versa, so the sound follows. The
second one closes on its own if the main one switches to the home screen, to a video, or to the same channel. Measured
load: ~66 % of a core for both (1080p60 + 720p60, vaapi decoding).

### Choice of player

System → Player (QML and Lua TV menus; System section of the companion app settings): `POST /api/player {mode: qt|mpv}` writes
`~/.config/stream-box/player` and quits the player; the player.sh loop starts the right one. `/api/state` gives `player`
(chosen) and `player_running` (`qt` if `current-vo` is `libmpv`): the page reports an automatic fallback to mpv.
player.sh forgets the Qt app's failures when the file is rewritten (modification date), which allows retrying it
without rebooting.

### Chat with emotes (Qt app)

`chat_qt.py` (imported by ui.py) reads the chat like chat_overlay.py (anonymous IRC) and splits each message into words
and emotes: Twitch through the `emotes` tag (positions in characters), 7TV / BTTV / FFZ by name (global lists loaded
once, channel lists as soon as the ROOMSTATE that gives its id arrives; priority 7TV > BTTV > FFZ). `qml/ChatOverlay.qml`
draws them (Flow of Text and AnimatedImage: animated GIF and WebP, Qt's `libqwebp` plugin), in the corner and with the
background and size set, hidden in video, on the home screen and with the menu open. When the app runs, it writes
`user-data/streambox/chat_ui = qml` and chat_overlay.py (text in mpv) goes silent; it starts from scratch with each new
player (mpv alone: text chat). QML pitfall: `left`, `top` are reserved item properties (FINAL); an
error loading ui.qml makes the app fall back to the quick menu and the text chat, without crashing.
Shutdown: on mpv's `shutdown` event, `os._exit` right away from python-mpv's event thread (which
otherwise destroys its connection and waits for the render context held by Qt: frozen app, no restart; 6/6 clean
restarts after the fix).

### Home screen in QML (Qt app)

`qml/AmbientScreen.qml`: shown when stream-box.lua decides so (`user-data/streambox/ambient_on`, published by
`update_ambient`; `draw_ambient` no longer draws anything when `chat_ui` is `qml`), with the status message
(`user-data/streambox/status`, published by `set_status`) and the QR code mode (`qr`), relayed by `box` (`ambientOn`,
`statusText`, `qrMode`). Background: very blurry color blobs as `RectangularShadow` (no layer, blur done by the
GPU) that drift over a minute or more; content that drifts by ±36 px over 7 to 11 min. Clock, date (locale of the
interface language), weather with `WeatherIcon.qml` (icon drawn and animated from the WMO code, `code` added by
remote.py; moon from 8 pm to 7 am), "Live now" (streamers from the list who are live, except the one being watched,
`/api/state`), upcoming streams as glass cards with pictures, QR code (always, 30 s at each arrival, never).

### Voting in polls and predictions from the page

Helix has nothing for a viewer: the website's GQL with the connected account's token, without integrity check (checked
with fake ids: `POLL_NOT_FOUND`, `NOT_FOUND`). Poll: `voteInPoll(input: {pollID, choiceID,
userID, voteID})`; prediction: `makePrediction(input: {eventID, outcomeID, points, transactionID})`. The poll
(`fetch_events`) now gives the ids, the current bet (`PredictionEvent.self.prediction`) and the points
balance (`channel.self.communityPoints.balance`); Twitch does not return the choice made in a poll: `poll_votes`
remembers those made from the box. `GET /api/events` (polled on the spot if the TV panel is disabled),
`POST /api/vote {poll, choice}`, `POST /api/predict {event, outcome, points}` (translated error codes, `VOTE_ERRORS`).
Page: "Poll / Prediction" card under "On the TV", polled every 3 s during a live stream; bet 10, 100, 1000,
All or custom, confirmation before betting. Regular polling now follows any live channel, not only
those from the list. Not tested for real (no open poll, and a bet spends points): display checked with
simulated data.

### Banner, playback bar, notification, polls panel in QML (Qt app)

stream-box.lua keeps the logic (OK, ←/→, pause, delays, notification keys) and, when `qt_ui()` (chat_ui =
qml), publishes instead of drawing: `user-data/streambox/bar` (bar visible), `toast` ({name, title, game, viewers,
seconds}, empty at the end); `draw_bar` and `draw_events` draw nothing. ui.py (`Osd`) relays these properties, `polls`,
`storyboard`, `live`, and reads the playback position (time-pos, duration, pause, cache, time-shift window) from a separate
thread, 4 times per second only when the bar is visible. QML: `InfoBar.qml` (live: picture, title, game,
viewers, "live for" based on `started` = `stream.createdAt` added by remote.py, time-shift memory and
"LIVE" or delay; video: pause, title, buffered part, duration, and YouTube preview), `Toast.qml` (slides in from
the right, time-left line), `PollsOverlay.qml` (animated bars, ★ winner, ✓ vote or bet made from the box).
YouTube preview: at each YouTube playback, remote.py reads the `yt-dlp -J` result of mpv's ytdl_hook
(`user-data/mpv/ytdl/json-subprocess-result`: no second extraction, it doubled the player requests behind YouTube's
"not a bot" check) and publishes the thumbnail sheet
(`storyboard`: image fragments in a rows × columns grid, each covering `duration` s); the cell shown is
chosen from the position. QML pitfall again: `left` (FINAL) cannot be used as a property name.
Bar color depending on the source (`InfoBar.source`, from `path` relayed by ui.py): red for YouTube, blue
for Jellyfin (server link: `/Videos/…`, `api_key=`, `MediaSourceId=`), purple otherwise and for live.

### Box status (page, Settings → Status and updates)

`GET /api/health`: temperatures (hwmon `coretemp`/`k10temp` and `nvme`), CPU (% over 5 s, `health_loop`) and
load, memory, disk, network (interface of the default route, link speed, throughput over 5 s), playback (player
actually running, decoding, size, frames/s, dropped frames), user services (MQTT, YouTube tokens:
`systemctl --user is-active`), updates (in progress, next one from the timer, last one from
`update.log`). `POST /api/update` starts `stream-box-update.service` (`--no-block`). The page rereads every 5 s while
the Settings tab is shown; tiles in orange or red beyond thresholds (70 °C, 85 °C, memory, disk,
stopped service, CPU decoding).
Same status in the System tab of the QML TV menu (tiles under the rows, `/api/health` reread every 5 s while
the tab is shown).
- **UI rule: a press always shows something at once.** TV menu: change the bound data optimistically (`updateAct`,
  `display.setting`, `wifi.connecting`…), open dialogs at once and fill them when the box answers (`loadingModal`), then
  read the real state shortly after (`healthSoon` → `readBox`) instead of at the next 5 s reading. Companion app: the
  pressed button is greyed out (`.busy`) while its `send()` runs; handlers that fetch by themselves set their text or
  status line before awaiting. Check it for every new button.

### YouTube (channels and search)

Channel list in `~/.config/stream-box/youtube.json` (UC… id, name, @, picture), edited by
`POST /api/youtube_channels` {action: add|remove|move, channel, delta}; adding resolves "@name", a link or an id with
`yt-dlp --flat-playlist -J --playlist-items 0` (~1 s). `GET /api/youtube`: 15 latest videos per channel from the
public RSS feed (`feeds/videos.xml?channel_id=`, no key, Shorts excluded, 20 min cache), merged with
the history (position, watched). `GET /api/youtube_search?q=`: `yt-dlp --flat-playlist -J ytsearch20:` (~1.6 s, 10 min
cache, `youtube:lang=fr`, otherwise titles are translated into English): videos, and channels whose name matches (same
request; UC… id, subscribers, picture, `saved`), playlists excluded. `GET /api/youtube_channel?id=UC…`: latest videos
of a channel found, even outside the list. Few requests: YouTube has already rate-limited
the box's IP address.
YouTube account ("Subscriptions" row, at the top of the channel rows): a Google app of your own (console.cloud.google.com,
YouTube Data API v3, External audience published, otherwise tokens valid for 7 days, client "TVs and Limited Input
devices"), authorization by code on google.com/device, `youtube.readonly` scope. `youtube-app.json` (client_id,
client_secret), `youtube-token.json`, `youtube-subs.json` (subscriptions reread once a day), as 600 in
`~/.config/stream-box`. Everything goes through googleapis.com (quota 10,000 units per day), nothing through youtube.com:
`subscriptions` (1 unit per 50), then per channel `playlistItems` on the `UULF` playlist + id without "UC" (videos without
Shorts or live streams; `UU` as fallback), 4 latest, 8 in parallel; `videos` for durations, views and upcoming live streams
(excluded), 60 videos kept, durations and views reread at most every hour. Each channel at its own pace
(`YT_CHANNEL_RHYTHM`, age of its latest video: < 2 d → every hour, < 7 d → 3 h, < 30 d → 12 h, otherwise 24 h),
a round every minute (`yt_subfeed_loop`, 16 in parallel); results in `youtube-subfeed.json` (and the day's units,
quota reset at midnight Pacific time, cap `YT_DAILY_BUDGET` 7000). 347 subscriptions: ~1,800
units per day. `/api/youtube` serves the latest feed (the very first one, right after authorization, is awaited).
`GET /api/youtube` → `subs` {configured, authorized, pending, channels, synced, videos}; `GET /api/youtube_account`;
`POST /api/youtube_app|youtube_login|youtube_logout|youtube_sync`. TV: "Connect my account" card in the Subscriptions row
as long as the box is not authorized → code popup and QR code (`ytAuth`, reread every 3 s); "YouTube
account" row of the System menu (reread subscriptions, disconnect). Page: "YouTube account" section of Settings
(app creation, code, status).
Favorites: served by the subscription poll when the channel is part of it (`yt_fav_videos`, 15 videos per
favorite instead of 4, durations and views, no request to youtube.com: `/api/youtube` in ~15 ms), otherwise RSS feeds
read in parallel, failures kept for 10 min (`YT_FEED_RETRY`). The menu keeps `yt` from one opening to the next and
rereads it in the background; the page only reads the list (`GET /api/youtube_channels`). Rows: cards created only for
the targeted rows and their neighbors (`near`).
Recommended for you (first row under the search): the account's YouTube home through the "YouTube TV app" access
(cast/youtube_tv.js `GET /recommended`: `/browse` FEwhat_to_watch with the TV client, first two pages, video tiles
only — `tileRenderer` with `TILE_CONTENT_TYPE_VIDEO`: contentId, title, first line = channel, duration and views from
the overlay and the lines, "LIVE" overlay — without duplicates, 30 at most, kept 30 min; `recommendedVideos(data)` is
the pure parsing), `youtube.yt_tv_recommended`, `youtube_home()["recommended"]` with the progress (`with_progress`).
Authenticated requests as the TV app makes them, not yt-dlp extractions: no bot check. Row kind `rec` in the QML menu,
"Recommended for you" in the quick menu; not in the companion app (it shows no video rows).
Favorites (`youtube.json` list, one row per channel): Options on a subscription video → "Add to favorites"
(channel taken from `youtube-subs.json`, no request to YouTube), "See latest videos", "Play the video".
Page: YouTube block of the Remote tab (search, one chip per channel) and "YouTube favorites" in Settings.
TV (YouTube tab of the QML menu): search row → on-screen keyboard (grid 10 wide, ↑↓←→ and OK, Back
closes), then the channels found (round pictures; OK: "See latest videos", `preview` row right below, or
"★  Add to favorites" / "✕  Remove from favorites"), the videos found and one row per channel of the list; OK on a video
plays it (or offers to resume, `chooseVideo`). Page: channels found at the top of the results (tap: their videos,
"Add").
Results are kept from one menu opening to the next (not across a player restart). Colors per tab (`menu.theme`, `menu.pal`): purple for
Twitch (live, following, replays), red for YouTube, neutral charcoal with a white glow for history, settings and
system; background, glows, rail, focus glows (`FocusFrame.glow`), `VideoCard.accent`, `SettingRow.pal` (light switch with a
dark knob in neutral), actions popup, keyboard. Blue is left free for Jellyfin. Logo (`qml/Logo.qml`, icons `icon-*.png`): white tile, rounded charcoal triangle, neutral on a purple background as well as on red.

### Plex (QML menu tab and page)
`plex.py`: a Plex server of the local network, chosen in the companion app (Settings → Plex, `POST /api/plex
{address, token?}`, checked with `/identity` and `/library/sections` before being kept; empty address: forget it), in
`~/.config/stream-box/plex.json` (600, with the box's `X-Plex-Client-Identifier`). Without a token, Plex must let the
box's network in (Plex setting "List of IP addresses and networks that are allowed without auth"). Same card fields
as Jellyfin (`px_item`), same API shape: `/api/plex` (On Deck split into resume / next episodes, recent additions per
library), `/api/plex_search` (`/hubs/search`), `/api/plex_series` (`allLeaves`), `POST /api/plex_play` (direct play
of the file, `/library/parts/…`, no transcoding). Progress: `/:/timeline` and `/:/progress` every 10 s
(`playback.history_loop`), `/:/scrobble` at the end (`px_report`); links `plex:<ratingKey>` in the history. Next
episode: `next_up` with `service: "plex"` and the `path` being played (Plex files hold no item id). Colors: amber
(`#e5a00d`), bar and loading screen too.
Sign-in with a Plex account by code: `POST /api/plex_link` (`plex.link_start`: plex.tv PIN, 4 characters, 15 min),
`GET /api/plex_link` (`link_state`: configured, name, account, pending {code, error}); a thread polls the PIN every
3 s, then reads the account's servers (`/resources`), owned ones first, and keeps the first the box reaches (local
connections first, plain `http://<LAN address>:<port>` before the plex.direct https one) through `set_plex`, with the
server's access token and the account name. TV: "Plex" row of the System menu (`plexMenu`: sign in, disconnect), code
dialog `CodeDialog` (shared with the YouTube account: `menu.codeDialog` gives its texts, QR code of plex.tv/link);
companion app: "Sign in with a Plex account" button in the Plex section (polls while a code is shown).
TV menu: Jellyfin and Plex share the code of the library tabs (`libs[id]`: home, results, preview, searching, row, sel;
`libRows`, `libChoose`, `libPlay`; `/api/<id>…`). A library tab only shows when it is connected (`st.libraries`);
while none is, a "Libraries" tab (`LibrariesTab`) tells how to connect Jellyfin or Plex, with the QR code. `tabs` is
filtered from `allTabs`; `tabKept` keeps the same tab when the list changes; `railStep` 70 instead of 76 with 9 tabs.
Test server: Docker `plexinc/pms-docker`, port published with `-p` (it then gets past ufw, `--network host` does
not), `ALLOWED_NETWORKS` = the LAN.

### Jellyfin (QML menu tab and page)

remote.py reuses the server associated with jellyfin-mpv-shim (`~/.config/jellyfin-mpv-shim/users.json`: address,
UserId, AccessToken; header `Authorization: MediaBrowser Token="…"`, nothing else to configure). `GET /api/jellyfin`
(30 s cache): `Items/Resume`, `Shows/NextUp`, `Items/Latest` per library (movies, series; series arrive
by season); `GET /api/jellyfin_search?q=`, `GET /api/jellyfin_series?id=` (episodes and index of the first unwatched one);
`POST /api/jellyfin_play` {id, from_start}: direct stream `/Videos/{id}/stream?static=true&api_key=…`, resumed at the
server's position, title passed to mpv (`streambox-play url start title` → `force-media-title`, length as a
%n% prefix). Progress reported to the server: `Sessions/Playing` at start, `/Progress` every 10 s by
history_loop, `/Stopped` on stop (the server decides what is "watched"). Entry in the box's history as
"jellyfin:ID" (without token; `play()` restarts it through jellyfin_play), also for playbacks started by the shim
("Play on…", `shim_video`: the shim reports on its own). External subtitles (.srt next to the file) missing from the
direct stream: added by `sub-add` once the video is open (`jf_add_subtitles`). The
server's images are public (no token in their links).
TV: "Jellyfin" tab (blue theme) on the same page as YouTube (`mediaRows`, `mRow`/`mSel`, `keyMedia`, its own
state `jfRow`/`jfSel`): search with the on-screen keyboard, episodes of an open series, Continue watching, Next
up, recently added; OK on a movie or an episode: Resume / From the beginning / All episodes. Rail
tightened (step of 76) for 9 tabs. Horizontal
rows: card-by-card scrolling aligned to the left (`first`, `fits`), row clipped 28 px before the content
(`clip` on a wrapper taller than the cards, for the glow) and cards shown according to the targeted window, not
their animated position: the one leaving fades out in 90 ms without passing under the rail. Same thing vertically: grids (live, following,
history), lists (settings, system) and YouTube/Jellyfin rows are in a `clip` wrapper (40 px margin
around for the glow) that stops under the title and above the help at the bottom; YouTube/Jellyfin rows shown
according to the targeted row. QML pitfall: a function must not reuse the name of a property
(`setSel` existed: the tab's keys failed silently, except in the log).
Page: Jellyfin block of the Remote tab (chips per row, search, episodes of a series).
Sign-in by Quick Connect (`jellyfin.py`, the shim does it): `POST /api/jellyfin_link {address}` (`qc_start`: address
completed with `http://` and `:8096`, checked with `/System/Info/Public`, `users.json` saved as
`users.json.before-quick-connect`, then `jellyfin-mpv-shim --no-gui --server <address> --quick-connect clear`, which
prints the 6-digit code alone on a line, writes `users.json` once approved and goes on as the usual player; it needs
the mpv socket). `qc_follow` reads its output (code, then done when `jf_server()` is that server); if it ends without
signing in, or on `{action: "cancel"}` (`qc_cancel`: terminate, kill after 3 s), the saved `users.json` is put back
and the usual shim restarted (`qc_restore`); given up after 5 min. `{action: "forget"}` removes `users.json` and stops
the shim. `GET /api/jellyfin_link[?find=1]` (`link_state`: configured, address, name, pending {server, name, code,
error}, `servers` found by UDP broadcast "who is JellyfinServer?" on 7359, address = the IP that answered: the one
announced can be a Docker one). TV: "Jellyfin" row of the System menu (`jellyfinMenu`: servers found, disconnect;
none found: the companion app), code in `CodeDialog` (`jfLink`, polled every 2 s, Back cancels); companion app:
Jellyfin section of Settings (address, Connect, code, Cancel, Disconnect). Test server: Docker `jellyfin/jellyfin`,
`-p 8096:8096 -p 7359:7359/udp` (broadcasts do not reach it through Docker's NAT: give the address).

### Subtitles and audio during a video (≡ key, Qt app)

stream-box.lua: in video mode, ≡ opens the list (track-list: "Off", subtitles, then audio tracks if there are
several; language names in the interface language, "(forced)", "(original)") and shows the bar; while it is open
(`tracks_open`), ↑ ↓ choose, OK sets `sid`/`aid` and closes, any other key closes. State published in
`user-data/streambox/tracks` {open, items, sel}, relayed by ui.py (`osd.tracks`), drawn by `qml/TracksPanel.qml`
above the bar, on the right. The row of buttons below the bar has "Subtitles" (and "Quality", see below). With mpv alone, ≡ switches to the
next subtitles (as before).
Settings "Subtitle size" (`sub_size`, 50–200 %, → `sub-scale`) and "Subtitle background" (`sub_bg`,
0–100 %: black band `sub-border-style=background-box` + `sub-back-color` #AA000000, 0 = usual outline): NUMBERS
of stream-box.lua (`apply_sub_style`), `POST /api/set`, Settings tab of the TV and Subtitles section of the page.
Both menus open on the tab of the current media (`mediaTab` / `media_tab`, from `mode` and `media_kind` of
/api/state: live → Live, YouTube, Jellyfin, replay or clip → Replays, other link → History),
readjusted when the state arrives as long as no key has been pressed; YouTube and Jellyfin keep row and card. Since mpv keeps the pause from one file to the next,
`play_media` and `start_channel` remove it.
Menu background: two blurred glows (RectangularShadow, no sharp shape) in the tab's color, at the top right
(`pal.glow`) and at the bottom (`pal.glowLow`), on all themes; almost invisible in neutral.

### Loading screen between two videos or channels

stream-box.lua (`set_loading`) publishes `user-data/streambox/loading` {title, thumb} when a video starts
(`play_media url start forced_title image shown_title`) or a channel starts (`start_channel`), and clears it at the first
frame (`playback-restart`), on error, on the home screen or after 45 s. `qml/LoadingOverlay.qml` (relay
`osd.loading`, `kind`: twitch, youtube, jellyfin, video): blurred thumbnail, box logo that breathes, glow in the
source's color running along the triangle's outline (dashed ShapePath, animated `dashOffset`), ripples;
drop shadow under the texts; fade in and out. With mpv alone
(`vo` ≠ libmpv): "Loading {title}…" as the centered status message (the only one, also for a Twitch channel). Title and image come from remote.py (history, Jellyfin)
or from the request (`POST /api/play` accepts `title`, `thumb`: the QML menu sends them).
Banner and playback bar (InfoBar.qml): darker gradient reaching higher and drop shadow under the header, to read the
title over a light image.

### Video playback bar (Qt app)

- Scrubbing (stream-box.lua `media_seek`, `scrub`): ← → in a video pause it and move a target; each press jumps 10 s,
  however fast; only a held key speeds up (`seek_held`: less than 0.2 s since the previous jump means repeats, which
  input.py sends every 0.08 s; at most 8 jumps/s kept): 10 s for the first second held, 30 s for the next, then 1 min; `user-data/streambox/seekfx`
  {text: offset from where it started, n, target}: InfoBar.qml puts the cursor, the time and the preview on the
  target and keeps the "+2 min 30" bubble while scrubbing. OK (`scrub_end(true)`) seeks there and plays; Back or any
  other key gives up: back where it was, playing or paused as before (seekfx {n} without text). The −10 s / +10 s
  buttons of the row jump at once (`media_seek(dir, true)`). Also works with mpv alone (cursor on the target, no
  bubble).
- Changing video: the bar hides on `start-file` (stream-box.lua); ui.py drops the playback state when mpv's `path`
  changes (`new_file`; not when the bar hides: it keeps its values while fading out) and reads it at once when the bar
  is asked for (`wake`, instead of waiting for the next poll, up to 1 s); InfoBar.qml shows only once that state is
  there (`pbIn.path` defined; it draws `pb`, the last state received, kept while fading out) and animates the progress
  only once settled on a video (`animate`: off when it appears or when `pb.path` changes, on again after 300 ms): the
  bar never shows empty (purple, 0 s) nor slides from the previous video's position and colors.
- Focus in a video, top to bottom: title (OK: Info panel), the bar itself (← → scrub; focused whenever the bar shows
  and neither of the others is: InfoBar.qml `barFocus`, track 8 → 12 px, cursor 22 → 28 px and a faint halo), row of
  buttons. Bar hidden: ↑ or ↓ shows it, focus on the bar; from the bar ↑ the title, ↓ the buttons; from the title ↓,
  from the buttons ↑ or Back, back to the bar.
- Row of buttons: ↓ from the bar (focus on Pause/Play), ← → and OK;
  Subtitles, −10 s, Pause/Play, +10 s, Quality (YouTube), Next chapter (if there are chapters), Next
  episode (Jellyfin). Row centered on Pause/Play (InfoBar.qml `playIndex`). `ctrl_focus`,
  `user-data/streambox/controls` {items, focus}; disappears with the bar. Round centered buttons, drawn icons
  (`qml/PlayerIcon.qml`, QtQuick.Shapes: no Unicode characters, whose rendering depends on the fonts), Play / Pause
  larger, name of the selected button below.
- Layout (InfoBar.qml): title and info line right above the bar; the YouTube preview (thumbnail
  sheet) and the jump bubble only appear while seeking forward or backward (`seeking`, 1.5 s after the last
  jump), as close as possible to the bar; the title then slides up, the bubble sits on the edge of the preview.
- Info: `user-data/streambox/meta` published by remote.py (YouTube: channel, date, views, description, from the
  ytdl_hook's `yt-dlp -J`; Jellyfin: series, episode, year, rating, overview); chapters (`chapter-list`, `chapter`)
  read by ui.py with the position: marks on the bar, current chapter in the info line. Time left
  and end time ("−21:26 · ends at 02:30").
- Pause screen (`qml/PauseScreen.qml`): dimmed image, pause icon in the center of the screen (no more overview here).
- Next episode (Jellyfin): remote.py publishes `user-data/streambox/next_up` {id, of, title, episode, thumb}
  (`Shows/{series}/Episodes?AdjacentTo=`); in the last 20 seconds, stream-box.lua publishes `next_card`
  {seconds, …} → `qml/NextUp.qml` (OK: play, Back: stay); at the end of the file, the next episode starts
  (POST /api/jellyfin_play). `of`: only during the episode it follows (not for a playback from the shim).

### Home Assistant: "Powered on" state

mqtt_bridge.py: `binary_sensor.stream_box_powered_on` on `stream-box/power` (ON when the bridge connects, OFF through the
last will message, when the service stops — SIGTERM — and right before "Turn off"); without `availability`,
so `off` and never `unavailable`. The other entities: available if `status` = online (box ready) AND power = ON
(`availability_mode: all`), except "Turn off": available as soon as power = ON and executed right away by the bridge
(`systemctl poweroff`, polkit), even during boot. Example automations (turning on and off with the TV) in docs/home-assistant.md.

### Installable disk image (image/, mkosi)

`bash image/build.sh` builds `image/mkosi.output/stream-box.raw` (~3 GB, to write to a disk or a USB stick;
`bash image/build.sh xz`: stream-box.raw.xz, ~1.6 GB, the version to download; built and published as a GitHub
release with its sha256 by `.github/workflows/image.yml` on every `v*` tag, release files being limited to 2 GB; the
release text is the version's section of CHANGELOG.md (`## [x.y.z]`, important changes only, written before tagging),
then how to install; `.github/workflows/release-notes.yml` (run by hand from the Actions tab) rewrites the text of an
existing release from main's CHANGELOG.md without rebuilding; versions are SemVer: tags vX.Y.Z)
in an Arch Docker container with mkosi 27 (nothing installed on the machine); `bash image/build.sh vm` boots it
in QEMU. Arch base (not CachyOS), UEFI, systemd-boot + UKI. greetd starts media's cage session at boot
(no keyboard/login screen choice like boot-mode.py). `mkosi.prepare.chroot` (with network): user
media, repository clone (origin = GitHub), venvs, YouTube token server; `mkosi.postinst.chroot`: SSH config,
user services, jellyfin-mpv-shim, Qt player; `mkosi.finalize.chroot`: enabling system services and
graphical.target (after mkosi's `systemctl preset-all`, which would undo `enable`s done earlier).
`/usr/lib/repart.d/10-root.conf` grows the system partition to the whole disk at first boot. No personal
settings in the image: everything goes through the companion app. Tested in QEMU (Qt app home screen, API).
Pitfall: `pkill -f pattern` in a command whose text contains this pattern kills itself (`[q]emu…`).

### Standby

TV menu (System): "Put to sleep" (`POST /api/poweroff {"mode": "suspend"}`) and "Shut down the box" (Lua: "Turn off the box")
(`{"mode": "full"}`), plus the setting "Power button" ("Sleep" or "Full shutdown"; remote, phone, Home Assistant): `~/.config/stream-box/power-action`
(`suspend` or `poweroff`, default), read by remote.py (`POST /api/poweroff` without mode, page button) and
mqtt_bridge.py ("Turn off" button; "Power button" select). Standby via `systemctl suspend`: allowed by default for
remote.py (active local session); polkit rule `login1.suspend*` added (install.sh, image) for the bridge, which
runs outside a session. During standby, Powered on switches to OFF: the bridge takes a logind "delay" lock and follows
PrepareForSleep (gdbus monitor), publishes OFF before standby and ON + status on wake-up. Wake-up: Wake-on-LAN (same packet
as for power on) or power button. On wake-up, remote.py restarts the Bluetooth adapter (`bluetoothctl power off/on`: the CSR dongle stayed stuck,
remote "connected" without an input device), then (`resume_loop`, PrepareForSleep false) waits for twitch.tv to answer, then sends
`streambox-resume`: stream-box.lua restarts the channel, or the video at its position (streams died during standby, frozen
picture otherwise). Tested: wake-up by WoL in 6 s, stream back 8 s after the packet. Standby requested by remote.py
is allowed by default only if it runs in the TV session (started by start.sh); outside a session (restarted over ssh),
the polkit rule `login1.suspend*` is needed.
Full shutdown: a Bluetooth remote still connected when the power goes off makes the dongle wake the box right back up
(BIOS wake-up type "Power switch"; with the remote's power key it is a race: the remote often hangs up first). The image's
`stream-box-bt-disconnect.service` (ExecStop at shutdown and reboot, before bluetooth.service stops; sleep does not stop
services) runs `/usr/local/lib/stream-box/bt-disconnect`: disconnect the devices, then `bluetoothctl power off`. A mere
disconnection was not enough (the remote reconnects at once). Not remembered: bluetoothd powers the adapter on at boot
(`AutoEnable`, default true). Tested: remote connected, shutdown over SSH, the box stays off (it came back before).
Power button (Bluetooth remote, case button): remote.py holds a logind `handle-power-key` lock
(`hold_power_key`, allowed in the TV session); stream-box.lua binds `POWER` (mpv alone) and `0x21ff2a` (Qt app,
keysym XF86PowerOff) to `power_key` → `POST /api/poweroff` without mode, hence the "Power button" setting. Ignored for 15 s
after boot and after a wake-up. Player stopped: the button does nothing (logind only takes over if
remote.py dies).

### Wi-Fi setup mode (netsetup.py)

Without network (no active Ethernet or Wi-Fi connection) and with a Wi-Fi card, remote.py (`netsetup.setup_loop`,
25 s after boot) creates the NetworkManager access point `stream-box-setup` ("Stream Box XXXX", password
generated once, `~/.config/stream-box/hotspot.json`, box address 10.42.0.1, dnsmasq for DHCP). The home
screen (AmbientScreen.qml; text with mpv alone) shows "1. Connect your phone" (WIFI:… QR code) and "2. Open
the setup" (QR code http://10.42.0.1:8080/). The page, opened on 10.42.0.1, opens on the Wi-Fi section
(list scanned right before the access point, a single radio); `POST /api/wifi {action: connect, ssid, password}`
stops the access point, looks for the network, connects to it; failure → access point again, error in
`GET /api/wifi`. Recovery at any time: saved Wi-Fi lost → 60 s grace period (NetworkManager retries) then
access point; with no phone on it, it goes away every 3 min to retry the saved Wi-Fi; network back
(cable…) → it stops. TV System menu: "Wi-Fi" row (OK: setup mode, kept for 15 min). Over Ethernet,
nothing changes. Card chosen: the access point's, otherwise the first by name that is not already used as an access
point. start.sh now only waits 20 s for the network. Test: `bash image/build.sh test` (mac80211_hwsim: two simulated
cards, gitignored test SSH key); tested in QEMU: screen, scan, wrong then right password.

Companion app address (QR code): by default http://<local IP>:8080; optional domain name in Settings →
Companion app address (`POST /api/remote_url`, remote-url file, empty = local network).

### Virtual remote (page)

"Remote" section at the top of the Remote tab: ▲▼◀▶ pad + OK, Back, Menu (TV menu), Options (≡),
Play (`cycle pause`: the Xiaomi play key, for its part, changes the chat corner). `POST /api/key {key}` → mpv `keypress` with the names stream-box.lua binds (UP… ENTER, GO_BACK, HOMEPAGE,
0x2111a0, PLAYPAUSE; allowlist in remote.py): same effect as the Bluetooth remote, TV menu included.
Arrows repeated while held down (400 ms then every 120 ms), short vibration on each press.

### Slimmed-down page (virtual remote first)

Since the virtual remote, the page only keeps what the phone does better than the TV menu. Remote
tab: virtual remote, "Video playing" (title; video: title and "Back to the stream"), votes, Sound (volume,
mute), TV preview, link to play. Settings: Wi-Fi,
streamer and YouTube channel lists, companion app address, box status and updates, Twitch
account, followed channels. Removed (available in the TV menu): streamer grid and second stream, live
rewind, playback bar and subtitles, pause, night mode, chat (shown, corner, appearance), YouTube browsing
(latest videos per channel) and Jellyfin (rows), replays, history, auto switch, polls shown,
subtitles, resolution, power button, QR code, player. The API keeps these actions (TV menu, Home Assistant).
Page test bench: jsdom in Docker, fetch relayed to the box's API (read-only), JS errors reported.

### Phone keyboard for the TV menu search

Search keyboard (YouTube, Jellyfin) opened or closed in TvMenu.qml (`onKbOpenChanged`, also closed with the menu)
→ `POST /api/keyboard {open, text, target}`; remote.py keeps it (`keyboard`, forgotten after 10 min) and publishes it in
`/api/state` (`keyboard`). The page then shows at the top "Search (on the TV)" (or "Search on YouTube / in Jellyfin (on the TV)"): each keystroke (120 ms later) →
`POST /api/keyboard_input {text}` → `script-message streambox-tvmenu-text <text> <0|1>` → ui.py `box.textInput` →
`kbText`; Enter or "Search" (`submit`) starts the search and closes the keyboard. The page's YouTube and Jellyfin
search blocks are removed: search is done on the TV. Qt app only (no search
in the mpv-alone menu).
Image slimming (5.7 → 3.0 GB): system partition in zstd-compressed btrfs, `Minimize=best` (no empty space
written, grown at first boot); no deno or nodejs-wheel in the media venv (yt-dlp uses the system
Node: `--js-runtimes node` in player.sh and update.sh, only if deno is missing; a box
installed by install.sh keeps deno); token server without its development dependencies (`npm prune
--omit=dev`); `mkosi.finalize.chroot` removes /usr/include, doc, man, translations other than fr and en, Qt
development tools from the venv. Firmware, LLVM, Noto fonts and Qt kept (compatibility). Tested in QEMU on a
16 GB stick: partition grown to 16 GB, YouTube video played.

### Sound output (audio.py)

`audio.py watch` (started by start.sh, continuously): outputs = HDMI / DisplayPort jacks marked "available" by
PipeWire (screen or TV able to play sound plugged in; name from the EDID, `device.product.name`), USB and
Bluetooth devices (sinks `device.bus` usb / bluez5), the card's analog output. Choice in `~/.config/stream-box/audio-output`:
"auto" (Bluetooth > USB > plugged-in HDMI; none of these: nothing is touched) or the id of an output (missing
→ automatic in the meantime). New choice 1.5 s after each sink/card event from `pactl subscribe`; card profile
change, default output, current playbacks moved. `GET /api/audio` (outputs, choice, current),
`POST /api/audio {output}`; "Sound output" row in Settings on the TV (QML and Lua) and in the page. Descriptions read
from pactl's text listing (the JSON loses accents). no-hdmi-audio (legacy) means "analog".

### Keys read at the source (input.py), pairing and learning from the menu

`input.py` (started by start.sh) reads /dev/input/event* (input group: install.sh adds it, the image grants it) with
Linux names (embedded table from linux/input-event-codes.h; KEY_SELECT = Xiaomi OK, KEY_VIDEOPHONE = Xiaomi ≡,
BTN_* and ABS_HAT pad of gamepads), translated into actions (DEFAULTS, then keymap.json) and sends
`script-message streambox-input <name> <action>`; it announces `user-data/streambox/input` = "evdev:<time>" every
5 s, and as long as that is fresh (15 s) stream-box.lua and ui.py ignore keys received by mpv / Qt (otherwise doubled).
Without permissions on /dev/input, it stops: old path (mpv names and 0x21… keysyms, KEYS of stream-box.lua) as
fallback. Actions: up down left right ok back home menu homescreen corner power volume_up volume_down mute. The
page's virtual remote also sends actions (`streambox-input VIRTUAL <action>`, never learned).
Held key: repeated by input.py itself (`REPEATABLE`: arrows, volume; 400 ms then every 80 ms, the gamepad d-pad
too), the kernel's repeats (value 2) are ignored: the Xiaomi remote's "Consumer Control" entry (arrows, OK, volume)
has no autorepeat (no EV_REP), only its "Keyboard" entry did, hence keys that repeated "sometimes".
"Set up keys" wizard (System menu, QML and Lua; `POST /api/keymap {action: wizard|reset}`): in
stream-box.lua, the actions one by one (8 s each, without a key it keeps its own; a key already taken is
refused), learned keys added to `~/.config/stream-box/keymap.json` ({name: action}, Linux names via input.py or
mpv names as fallback), state in `user-data/streambox/learn` → `qml/KeyWizard.qml` (on-screen message with mpv alone).
ui.py also applies keymap.json to the open QML menu. Bluetooth (btsetup.py, `GET/POST /api/bluetooth`): list of
paired devices, 20 s scan, pairing without a code (NoInputNoOutput agent) + trust + connect, unpairing;
"Remotes and controllers" popup of the System menu (QML: `btMenu`, `btScan`, reread every 2 s).
Reboot: `POST /api/reboot` (`systemctl reboot`, polkit login1.reboot* added), "Restart the box" in the System menu
(second OK within 4 s), button in Settings → Status and updates of the page, "Restart" button in Home Assistant.
Power held for 1 s → "Box" popup ("☾  Sleep", "↻  Restart", "⏻  Shut down", "Cancel"; QML menu `powerMenu`,
`streambox-power-menu`) instead of the action of the "Power button" setting, which now fires on release of a
short press. input.py measures the press (evdev values 1 / 0, action `power_menu` sent at 1 s); as fallback,
stream-box.lua binds power as "complex" (mpv's down / up) and ui.py sends keydown / keyup for these keys.
The popup is shown alone over the video, without the menu behind it (`powerOnly` / `power_only`); Back closes everything.


### YouTube Cast

`cast/cast.js` (Node, `yt-cast-receiver` 2.1.0, unofficial protocol): the box appears as "Stream Box" in the
YouTube app's Cast button (DIAL / SSDP discovery on the local network, TCP port 3000, UDP 1900; firewall to
open if there is one). Cast video → `POST /api/play` {url, start} (position set by the app, `play(at=)`);
pause, resume, seek, volume → mpv IPC; state changed from the remote sent back to the app (`notifyExternalStateChange`),
end of video → next in the queue; "Stop casting" → back to the stream (`/api/twitch`). Pairings in
`~/.config/stream-box/cast-receiver.json`. Started by start.sh if `cast/node_modules` exists; modules installed by
`npm ci --omit=dev` in `cast/` (versions from `cast/package-lock.json`, ~40 MB) by install.sh, the image
(mkosi.prepare.chroot) and update.sh (if the versions file has changed). Loading screen title: the app only
gives the id, `yt_title` asks the Google API for it (connected account, 1 unit) or the public oEmbed.
Tested: discovery, playback, pause, seek, volume, queue, pause from the remote, stop.

### Account YouTube progress (mixed)

The official API gives neither history nor positions: `cast/youtube_tv.js` (same process as `cast.js`) signs in
as the YouTube TV app (youtubei.js, TV client, code on google.com/device, Google shows "YouTube on TV";
token `~/.config/stream-box/youtube-tv-token.json`), local server 127.0.0.1:8091 (`/status`, `/login`, `/logout`,
`/progress`, `/report`). Mixed operation, tried before choosing:
- the box keeps its positions (exact resume on the TV) and reports them to YouTube (`history_loop`: every
  `YT_TV_PUSH` = 30 s, and on stop `final`) like a player: `/player` (tracking URL, cpn), `playback` ping, then
  `watchtime` (segment st→et, real time rt). Checked: the phone resumes to the second;
- for a video watched elsewhere, or watched further elsewhere than on the box (the furthest position wins), the
  account's percentage (`percentDurationWatched` of the FEhistory cards, 8 pages ≈ 120 videos, and of FEsubscriptions,
  2 pages; kept for 10 min, reread only when the YouTube tab asks for it) gives the progress bar (`percent`) and the resume
  (`play()`: percentage × duration, duration from the Google API). YouTube only updates this percentage with a 15 to 20 min
  delay, and only there: no other client (web, Android, iOS, /next) gives the exact position with this token.
`/api/youtube_account` → `tv` {connected, pending, error}; `POST /api/youtube_tv_login|youtube_tv_logout`. TV:
System → YouTube account → "Sync progress" (code popup, `ytAuth.tv`). Jellyfin: the server remains
the reference; Twitch replays: positions already reported to the Twitch account (`twitch_save_position`).

### Avoided loads (menu, page)

QML menu: `/api/state` every 4 s, but `st` replaced only if the response changes (`stJson`); hidden tabs
not computed (`rows: visible ? … : []` in ReplaysTab, MediaTab, RowsTab and the status tiles); following
list computed once (`followItems`). Page: `/api/state` paused when the page is in the background; Settings
sections (followed channels, YouTube account, Wi-Fi) loaded when the tab opens (`settingsLoaders`).

### Backup and restore (backup.py)
System menu → "Backup and restore" (QML `backupMenu`, Lua `backup_menu`, popup reread every 2 s):
per plugged-in USB stick, "↓  Back up to {name}" (Lua: "↓  Save to {name}") then its 4 latest backups (OK → confirmation → restore then
reboot). Page: Settings → Backup, "Download the backup" (`GET /api/backup/download`) and "Restore
from a file…" (`POST /api/backup_restore`, raw body). API: `GET /api/backup` (sticks, backups, busy,
message shown for one minute), `POST /api/backup` `{action: save_usb|restore_usb, path, name}`.
Archive in the `backup.sh` format (`home/<user>/…`, accepted by `install.sh --restore` and vice versa) +
`stream-box-backup.json` (date, box name) + `stream-box-wifi.json` (saved Wi-Fi networks whose password is
readable by nmcli, recreated if missing). Not the Bluetooth pairings (root; `backup.sh` keeps them). Restore:
only the paths from the list, remapped to the local home folder, tarfile's "data" filter, folder permissions
reset (700); the previous settings are kept in `~/.local/state/stream-box/before-restore.tar.gz`.
Sticks: `lsblk` (USB / removable, never the box's disk), mounted by `udisksctl` just long enough to read or write, then
unmounted (removable right away); files `stream-box-backup-YYYY-MM-DD-HHMM.tar.gz` at the root. List read once
per plugged-in stick. Image: udisks2, exfatprogs, dosfstools and polkit rule `52-stream-box-usb.rules` (mounting for
media even outside the TV session; install.sh adds it too).

### Menu as the main page (Back button)
The large menu is the main page: at boot (`home_menu()` 3 s after stream-box.lua is loaded, the time
for the menu to load), at the end of a video (`BACK_TO_MENU`) and on Back during a stream or a video, playback
stops (`show_home`, `home` mode) and the menu opens. No more Back ×2 (nor
`/api/resume_last`): "▶  Resume {channel}" in Live and the History do this job. In `home` mode (menu
closed after 90 s, by Menu, by "⌂  Home screen": animated home screen), any key reopens the
menu. The home screen is a layer **above** the menu (somewhere you go, Back returns to the menu): in ui.qml the
menu has `z: -1` while `box.ambientOn` (except the "Box" dialog alone), the home screen fades in over it when it
closes (`TvMenu.underHome` keeps the menu shown 650 ms under it) and fades out to reveal it (`AmbientScreen.covered`
while the menu is open). Menu open with nothing playing: Back on the tabs does not close it (QML `st.mode`, Lua `state.mode`). Menu background: glows in the
tab's color that drift, two more without video behind (the veil is opaque there, to hide the home
screen).

### Animated backgrounds (qml/Backdrop.qml)
Home screen (AmbientScreen) and menu without video behind (TvMenu, in the tab's colors: `hueShift`, layer at
60 %) share `Backdrop.qml`: a **background** (`none` solid color, `aurora` blurred blobs, `fluid` folded noise, `borealis`
northern lights curtains) + a **layer** (`none`, `silk` luminous threads, `stars` stars on two planes).
The shader layers render `vec4(light, 0)`: additive blending with Qt's premultiplied alpha. Crossfade on
each change (`shownBase` / `shownOverlay`). Settings → Display: "Animated background", "On top", "Home colors" (`color`: violet, blue, green, sunset, pink, ice; palettes
in AmbientScreen, the menu keeps the color of its tabs). `POST /api/backdrop {base?, overlay?, color?}`,
`~/.config/stream-box/backdrop` (JSON; old single value accepted), `backdrop` (the choice) in
`/api/state`; the home screen takes the most recent of its state (20 s) and that of the open menu (ui.qml). Over a
video, the menu only has its veil (no more glows). Shaders in `qml/shaders/*.frag`, compiled to versioned `.qsb`
by `qml/shaders/build.sh` (Docker, PySide6 of the same version as the box: Essentials has no qsb), rendered at
half resolution (`layer.textureSize`, `ShaderLayer` component). Measured cost: ~25 % of a core for ui.py whatever
the background, menu included.

### Partitions and persistent data (A/B, step 1: layout)
Installed box (install-to-disk): ESP 512 MB, system A 5 GB (the running system), system B 5 GB (empty, label `_empty`,
GPT attribute 63 no-auto: boot ignores it until an update writes it), data partition on the rest (btrfs, GPT label
`data`). USB drive: no B (it is for trying the box, not for A/B updates); first boot (systemd-repart,
/usr/lib/repart.d): system partition grown to its fixed 5 GB (10-root.conf), data partition created on the rest
(30-data.conf). Everything that must survive the replacement of the system partition is on the data partition:
`/usr/local/lib/stream-box/persist mount` (stream-box-persist.service, before sysinit.target) mounts the partition
labelled `data` of the disk of `/` on /data, then binds /data/<path> on each path (seeded the first time with what the
system has there): ~media/.config/{stream-box,streamlink,jellyfin-mpv-shim}, ~media/.local/state, ~media/.ssh,
/var/lib/bluetooth, /etc/NetworkManager/system-connections, /var/lib/stream-box (developer mode, SSH password),
/etc/ssh/keys. `persist restore` (stream-box-restore.service, before sshd and greetd) puts back what lives elsewhere in
/etc: machine-id (/data/machine-id, a new system takes it at its next boot), sudo of the developer mode (`dev-mode
restore`), media's SSH password and sshd enabled (`ssh-access restore`, start --no-block: restarting synchronously
there would wait for itself); SSH host keys in /etc/ssh/keys (sshd_config.d/40-stream-box-keys.conf), copied from
/etc/ssh the first time (same identity) or made. Without a data partition (box installed before), persist mount does
nothing and the settings stay on the system partition. The streamer list moved to ~/.config/stream-box/streamers.txt
(the code folder is replaced with the system): twitch.py moves a list still next to the code there at its start
(also one restored from an older backup), stream-box.lua reads the old place until then. The installer copies the USB
drive's /data to the disk's. The data partition is found with `blkid -p` on the disk of / (persist runs before udev
has read the labels: lsblk returned nothing on the installed disk). Tested in QEMU with the test image: stick (first
boot: 5 GB system, data partition, binds), settings made there (language, developer mode, a file), installation on a
blank disk (A, B no-auto, data), boot from the disk alone (same settings, same SSH host key), then /etc state removed
(sudo of the developer mode, media's password, sshd disabled) and put back at the next boot.

### A/B system updates (step 2: release files, sysupdate, rollback)
Versioned build: `VERSION` (release workflow: the tag without its v; otherwise `git describe`, e.g. 0.1.1-15-gabc)
→ `mkosi --image-version` (IMAGE_VERSION in os-release), system partition labelled `stream-box_<version>`
(mkosi.repart/10-root.conf, `%A`), UKI booting it by that label (`root=PARTLABEL=stream-box_%v` in
KernelCommandLine): each UKI goes with its own system partition, falling back to the previous UKI falls back to the
previous system. `SplitArtifacts=uki,partitions`: `bash image/build.sh release` (after build; `FROM=stream-box-test`
for the test image) makes mkosi.output/release: stream-box.raw.xz (disk image, to install),
stream-box_<version>.root-x86-64.raw.xz, stream-box_<version>.efi, SHA256SUMS. The workflow signs SHA256SUMS
(SHA256SUMS.gpg) with the secret RELEASE_SIGNING_KEY (ed25519 key "Stream Box releases", fingerprint
21B56DA5485308DDF1F7E8585167D4557A63D205; public part in image/release-signing-key.asc and, binary, in
/etc/systemd/import-pubring.pgp of the image, which systemd-sysupdate checks) and stops before building without it.
On the box: /usr/lib/sysupdate.d/10-root.transfer (latest release's system partition → the root partition not in use,
`InstancesMax=2`, `ProtectVersion=%A`: the running one is never touched; label stream-box_<version>)
and 20-uki.transfer (UKI → ESP /EFI/Linux, `TriesLeft=3`: stream-box_<version>+3-0.efi). Source:
github.com/Tunederuz/stream-box/releases/latest/download/. systemd-boot starts the newest UKI; systemd-bless-boot
keeps it once boot-complete.target is reached, which requires stream-box-boot-check.service (boot-check: remote.py
answers within 3 min; otherwise, on a boot that is counted — LoaderBootCountPath EFI variable, the selected entry's
name has no tries in it — reboot, and after 3 failures systemd-boot goes back to the previous UKI and system). The UKI
is written 0644: 0444 sets the FAT read-only attribute and systemd-boot then cannot rename it to count (no
LoaderBootCountPath, the new version is neither kept nor rolled back). mkosi names the UKI in the ESP
stream-box_<version>.efi (`UnifiedKernelImageFormat=%i_%v`; default: after the kernel version, which sysupdate would
not count as an installed instance). systemd-sysupdate is /usr/lib/systemd/systemd-sysupdate (not in PATH).
Tested in QEMU with two test builds (0.2.0-test1 installed from a stick, 0.2.0-test2 served locally, SHA256SUMS signed
with the real key): update into slot B (signature checked, 37 s), reboot on test2 from B (file system grown, data and
developer mode back), kept by systemd-bless-boot; then test2 broken (remote.py removed) and put back on trial: the
box rebooted after 3 min and came back on test1 from slot A by itself, test2 marked bad (+0-1). A system partition written by an update has a file system
shrunk to the minimum: `persist mount` grows it (`btrfs filesystem resize max /`). The installer labels system A like
the running system partition (its UKI boots it by label). Limit: two disks with the same `stream-box_<version>`
partition (the USB drive left plugged in after installing the same version) make `root=PARTLABEL` ambiguous: remove
the stick after installing.

### System update (image)
Checked every day, installed when the user accepts. `stream-box-update-check.timer` (root, 04:00 + up to 1 h,
Persistent) runs `system-update check`: A/B, `systemd-sysupdate --json=short check-new` (`{"available": v | null}`, exit
code 1 when nothing is newer: the JSON tells success apart; no network: nothing written); before A/B, the latest `v*`
tag of its clone against the files installed; writes `available` and `checked` into system-update.json (report()
carries them over; an install clears `available`). system.system_update() → `offered` (available, not running, not
installed and waiting, no update running), `checking`, `direct` (`run: direct` written by system-update while a direct
update runs: its status shows on its own row, never on the release one). The TV menu offers it at start and wake-up
(update_prompt `available`, id `boot:wake-ups:version`: "Version X is available. Update now?" / "Later" / "Don't ask
again") and Settings → Updates has one row whose action follows the state ("Check for updates" → `update_check`
(stream-box-update-check.service, polkit rule 56), "Install version X" → `update`, "Restart to apply version X");
companion app: one button, same states. Accepting runs stream-box-system-update.service directly (no update.sh any
more) with the update-manual marker: applied at once when nothing plays, otherwise it waits and asks.
Developer mode updates as any box. Direct update, by hand only and in developer mode ("Direct
update (source)" in Settings → Advanced and the companion app: `POST /api/update {direct: true}`, system.start_update leaves
~/.local/state/stream-box/update-direct, used up by system-update within 2 h, applied at once like "Update now"), any
box: the git path below, from main
(root clone `fetch origin main`, media's code fast-forwarded to it) instead of the latest release, no system image;
`kind: direct`, version `<IMAGE_VERSION or latest tag>+<commit>`, shown with "dev" on the TV and explained in the
companion app ("the system itself is not updated").
A/B box (step 3: the running system partition labelled `stream-box_*` and at least two root-x86-64 partitions on its
disk): system-update runs `/usr/lib/systemd/systemd-sysupdate update` instead of the git path below, then looks in the
ESP for the newest UKI above the running version that was not given up (`+0-…`: 3 failed tries, after a rollback it is
not offered again until a newer release): it reboots onto it when /api/state says `home`, otherwise `restart: pending`
("restart to finish"). system-update.json: `kind: ab`, `version` = running, `new` = the version waiting. On a USB drive
(one slot): nothing, message "install the box on the PC". Boxes from before A/B (one system partition, label
root-x86-64) keep the git path. Tested in QEMU (see the A/B sections).
Applying an update: never by itself on a run nobody asked for. A/B: system-update installs the new system, then pins the boot on the running version (`bootctl set-default
stream-box_<running>.efi`) and writes `restart: pending`; files path: no session restart, `pending`. "Update now"
(system.start_update leaves ~/.local/state/stream-box/update-manual, used up by system-update within 2 h) applies at
once when nothing plays (`bootctl set-default ""` and reboot, or session restart). At each boot,
stream-box-update-state.service (before greetd) runs `system-update state`: A/B, recomputes `new` (newest UKI above
the running one, not given up) and the pin; files, `pending` cleared (the boot applied them). `GET /api/update_prompt`
{pending, id = boot_id:wake-ups (system.resume_loop counts them), new, kind}: the TV menu asks once per id when it
opens ("Version X is ready. Restart now to apply it?" / "Later" / "Don't ask again": `dismiss_update` writes the update's
key, its A/B version or files date, to ~/.local/state/stream-box/update-dismissed, then `dismissed` until a newer one);
a plain restart does not apply an A/B update (pinned boot): while one waits, Settings → Updates (TV, askUpdate(true))
and the companion app's button become "Restart now"; "Restart now" → `POST /api/apply_update` →
stream-box-apply-update.service (polkit rule 58, apply-update: A/B unpin and reboot, files session restart). Disk tile
(TV, companion app): the data partition on an A/B box, the system partition (5 GB slot) aside (`health.disk.system`).
Local update (A/B boxes, without the Internet): the full disk image of a release (stream-box.raw.xz, the one used to
install) with its SHA256SUMS and SHA256SUMS.gpg; unsigned: developer mode only. From a USB stick (TV System menu
"Update from a USB stick", images at the root of the drive, listed once per drive like the backups) or sent from the
companion app (Settings → Status and updates → "Update from a file": raw bodies, `POST /api/local_update_upload?file=image|sums|sig`,
XMLHttpRequest for the upload progress, then `POST /api/local_update {action: start}`). localupdate.py (media) puts
the files in ~/.local/state/stream-box/local-update (on the data partition; free space checked: image + 700 MB) and
starts stream-box-local-update.service (polkit rule 57); `/usr/local/lib/stream-box/local-update` (root, Python):
files renamed into /data/local-update (root only: not swappable once checked), signature (gpgv with
/etc/systemd/import-pubring.pgp, sha256 of the image in SHA256SUMS), version from the label of the image's system
partition (GPT read from the first MB), newer than the running one (`systemd-analyze compare-versions`: systemd-boot
boots the newest), one decompression pass (lzma, as a stream: the ESP into a file, the system partition straight into
the slot not in use, labelled `_empty` while written, then `stream-box_<version>`, no-auto cleared), UKI copied from
the ESP image (loop mount) as stream-box_<version>+3-0.efi (0644), reboot; boot-check and systemd-boot roll back as for
an online update. Progress in /run/stream-box-local-update.json ({state, step, percent, version, signed, error}),
`GET /api/local_update` ({available, dev, busy, copy, job, usb}). Tested in QEMU: unsigned image without developer mode refused;
the real v0.2.0 release files (signed) accepted, then refused as not newer than the running 0.2.0-test1; developer
mode, image on a FAT32 USB key: copied, written into slot B and restarted onto it in 30 s, kept by the boot check.
Monthly rebuild (.github/workflows/image.yml, 1st of the month 01:00 UTC, or by hand): the latest release's code
(checkout of its tag) rebuilt with the Arch packages of the day as the next patch version, published only if the
package manifest (mkosi `ManifestFormat=json`, stream-box_<version>.manifest.json in each release) differs from the
latest release's, with the updated packages as release text; its tag is created on that commit by `gh release create
--target` (a tag pushed with the workflow's token starts no other workflow). Releases from before A/B (no `build.sh
release`) are not rebuilt.
Accepting an update (TV menu, companion app) starts `stream-box-system-update.service` (root; polkit rule 56 lets media
start it and stream-box-update-check.service, nothing else); update.sh (dependencies) no longer starts it. `/usr/local/lib/stream-box/system-update`: its own root-owned clone (`/var/lib/stream-box/src`, from GitHub:
what is installed as root never comes from media's copy) → latest `v*` tag → system files of `image/mkosi.extra`
installed when their sha256 differs, those a release dropped removed (`/var/lib/stream-box/system-files`: list of the
previous one; none before the first run), daemon-reload, units of /etc/systemd/system/stream-box-* with an [Install]
section enabled → media's code fast-forwarded to the tag (`runuser -u media`, `fetch --tags --force`: a moved tag
such as page-v1 made the fetch fail), never backwards (`ahead`: kept) → session restarted when something changed and
`/api/state` says `home`, otherwise `restart: pending` (next restart). Result in
`/var/lib/stream-box/system-update.json` {ok, message ("failed: <step>"), version, files, code: updated | same |
ahead, restart: now | pending | no, date}: `/api/health` → `update.system` {running, last}; TV: value of the "Update
now" row (version, "restart to finish", "System: failed"); companion app: under the update log. Not the Arch packages
nor the kernel. A box installed from an image without it (v0.1) needs the three files installed once by hand
(developer mode: system-update, its service, rule 56). Tested in QEMU: polkit, ahead, behind → fast-forward and
restart, the whole chain from `POST /api/update`. The service does not wait for network-online.target (it pulled
systemd-networkd-wait-online, which gives up after 2 min on a NetworkManager box). update.sh lists the changed packages with `comm` (the image has
no diffutils: `diff` made it log "failed").

### On a USB drive (flash-mode, image)
`/usr/local/lib/stream-box/flash-mode` (`stream-box-flash-mode.service`, at each boot before greetd): when `/` is on a
USB disk (`lsblk -dno TRAN` = usb: the image on a stick, before "Install on this PC" or kept there), fewer writes to
it: journal in memory (`/run/systemd/journald.conf.d/50-stream-box-usb.conf`, `Storage=volatile`, 64 MB, then
journald restarted), `/` remounted `commit=120,noatime`, `~media/.cache` in a 1 GB tmpfs, marker
`/run/stream-box/usb-root`: history.py then writes the history at most once a minute (`WRITE_EVERY`, positions kept
in `pending`, written by `flush()` from history_loop, and at once on SIGTERM of remote.py; removals and clearing at
once). Nothing on an internal disk, nothing kept (all in /run or in memory). Tested in QEMU with the disk as
`usb-storage`: all applied; at rest, writes come in bursts at each btrfs commit (~0.4 MB/min on average).

### Installer (installer.py, image)
The image boots from a USB stick (live, everything works, settings included); System menu → "Install on this PC"
(QML `installMenu`, visible if `/api/install` says `available`: disk of `/` on USB / removable, and image with
the installer) → internal disks of 16 GB or more (model, size, what they contain) → confirmation → progress
→ "Remove the USB stick, then restart". `POST /api/install {disk}` → `systemctl start --no-block
stream-box-install@<disk>.service` (polkit rule `53-stream-box-install.rules`: media can only start this
service) → `/usr/local/lib/stream-box/install-to-disk` (root): rechecks the disk (not the box's own, internal,
16 GB), GPT (512 MB ESP + "root-x86-64" btrfs zstd partition on the rest), `cp -a --one-file-system /` (running
system as is, `/home/media` included: accounts, favorites, history), mount points recreated, copy of the stick's
ESP, `bootctl install` (firmware entry; otherwise fallback path EFI/BOOT/BOOTX64.EFI). No root=: systemd
finds the system partition by its type on the disk it booted from. State: `/run/stream-box-install.json`
(state running|done|error, step, percent, error). Tested in QEMU (usb-storage stick + blank NVMe, then NVMe alone).

### SSH access (System menu)
"SSH access" row (switch, QML `loadSsh`, visible if the unit exists): `GET /api/ssh` (`available`, `enabled`,
`active` of sshd.service), `POST /api/ssh {enabled}` → `systemctl start stream-box-ssh@enable|disable.service`
(root, `/usr/local/lib/stream-box/ssh-access`; polkit rule `54-stream-box-ssh.rules`, media can only start these
two). The image only allows SSH by key and media has no password: enabling generates a readable password
(3 × 4 characters), gives it to media, adds `sshd_config.d/10-stream-box-password.conf` (PasswordAuthentication yes)
and keeps it in `/var/lib/stream-box/ssh-password` (root:media 640); the menu shows `ssh media@<address>` and this
password (`/api/ssh` only gives it to requests from 127.0.0.1). Turning off: sshd disabled, password and authorization
removed (keys remain). Image: SSH off by default (mkosi.finalize.chroot). Script, unit and rule in `image/mkosi.extra`, also copied by install.sh. Turning SSH off does not close
open sessions (they are in their session scope, not in sshd.service).

### Developer mode (System menu)
The image has no root password, media has no sudo, the kernel (UKI) has a fixed command line: without this mode,
an installed box offers no root access. "Developer mode" (switch, confirmation on enabling):
`POST /api/dev {enabled}` → `stream-box-dev@enable|disable.service` → `/usr/local/lib/stream-box/dev-mode` (root):
`/etc/sudoers.d/90-stream-box-dev` (`media ALL=(ALL:ALL) NOPASSWD: ALL`, checked by visudo) + `ssh-access enable`
(password shown on the TV); marker readable by media `/var/lib/stream-box/dev-mode` (`GET /api/dev`). Turning off
removes sudo, SSH keeps its setting. `POST /api/ssh` and `/api/dev`: 403 outside 127.0.0.1 (only from the TV
menu, not from the network). Polkit rule `55-stream-box-dev.rules`.

### First setup (new box)
As long as `~/.config/stream-box/setup-done` is missing (and without history: a box that has already been used counts as
configured, the marker is then set), `/api/state` and the home screen state have `first_run`. TV: the home
screen shows "WELCOME" / "Continue on your phone" and the page's QR code large (330 px), without live streams or
schedules; stream-box.lua (`setup_pending`, same rule, read from the files) does not open the menu, neither at boot
nor on a key press (message "Continue the setup on your phone: scan the QR code"). Page: `#setup` screen instead of the
tabs (restore a backup; Wi-Fi and streamers sections of Settings moved into it; "Finish" →
`POST /api/setup` → marker + script-message `streambox-setup-done` → the TV opens the menu). A restore
(`backup.restore`) also sets the marker.

### Cursor
cage has an invisible cursor theme (`cursors/blank`, link `cursors/default`: wlroots ignores `XCURSOR_THEME` and
always loads the "default" theme, looked up first in the `XCURSOR_PATH` given by the session: image and install.sh): its pointer no longer appears during transitions without a window. start.sh removes these variables for
the apps (a real mouse keeps its pointer, hidden after 4 s).

Key wizard: Back on the page's virtual remote cancels it without saving anything (`learn_cancel`,
`cancel` phase of KeyWizard.qml).

### Bluetooth agent (btagent.py)
Xiaomi remotes start pairing themselves (and redo it on reconnection): without an agent, BlueZ refuses
("No agent available"), the remote reconnects in a loop every 10 s without working. btagent.py (started by
start.sh with media-venv's Python, dbus-fast) is the default agent (NoInputNoOutput): accepts trusted devices, and
all of them during a scan or pairing from the menu (btsetup.py touches
`$XDG_RUNTIME_DIR/stream-box-bt-pairing`, 120 s window), refuses the rest; re-registers if bluetoothd restarts.

### Pitfalls of the installed box
- Restarting the session: `sudo rm -f /run/greetd.run && sudo systemctl restart greetd` (without removing this file, greetd
  does not restart `initial_session` and falls back to the text login prompt on tty1).
- Dell OptiPlex in "RAID On" (Intel RST): the NVMe SSD is hidden from the Arch kernel ("remapped NVMe", only the
  CachyOS kernel has a patch); BIOS → SATA Operation → AHCI. The installer detects it (class 0x010400 controller,
  `raid_mode`) and says so.

### Boot screen (Plymouth, image)
`stream-box` theme of script type (repository files, `mkosi.extra/usr/share/plymouth/themes/stream-box/`: logo
`watermark.png` (rounded icon + "Stream Box"), spinning wheel `spinner.png`, `stream-box.script`): everything is scaled
to the screen height (drawn for 1080 lines), same rendering at 1080p, 4K or 1366 × 768 without forcing
a mode (no `video=`: a screen that does not accept it would stay black). Plymouth starts from the initrd
(`InitrdProfiles=plymouth`, theme and `/etc/plymouth` copied by `mkosi.initrd.conf/`), i915 in the initrd and loaded
right away (`rd.modules-load=i915`): seamless animation from ~1.7 s on the Dell (without `plymouth.use-simpledrm`,
which shows earlier but flickers when switching to i915). AMD / NVIDIA cards: drivers not in the initrd (firmware too
heavy), the animation appears there after switching to the system partition. Command line: `splash
plymouth.ignore-serial-consoles vt.global_cursor_default=0` (in a VM, systemd adds a serial console: without
ignore-serial-consoles, Plymouth switches to text). `plymouth-quit.service.d/10-retain-splash.conf`: `plymouth quit
--retain-splash`. Do not mask plymouth-quit: greetd waits for plymouth-quit-wait (boot stuck at "Hold until boot
process finishes up"). Then start.sh shows `boot-splash.png` with mpv (same background and same logo) while the
session starts, removed by ui.py at its first frame (player.sh for mpv alone, 30 s at most).

### VM tests (test image)
`bash image/build.sh test`: image `stream-box-test.raw` with SSH enabled by the key `image/test-key` (created on the first
run, never published: `/etc/ssh/stream-box-test-keys`). QEMU in the mkosi container (KVM, OVMF), stick as
`usb-storage` + blank NVMe for the installer, `-vga std`, QEMU monitor for screenshots (`screendump`).

### Regular keyboard
By default (input.py `DEFAULTS`, stream-box.lua `KEYS` fallback): arrows, Enter = OK, Esc / Backspace =
Back, Windows, Home or M = TV menu, O = options (≡), H = home screen, Space = play / pause (action `corner`),
+ / − (and numeric keypad) = volume, media keys (next / previous = → / ←, stop = Back). Linux codes are
positional (QWERTY): the M of an AZERTY keyboard arrives as KEY_SEMICOLON, mapped too.

### pacman (developer mode)
The official image has neither a pacman mirror nor keyring (mkosi leaves none, and that is intended: no packages
installed by hand on a normal box). In developer mode, over SSH: `bash ~/stream-box/dev-pacman.sh` (mirror
geo.mirror.pkgbuild.com, `pacman-key --init` + `--populate archlinux`). Prefer `pacman -Syu` to partial
updates (`pacman -Sy package` alone).


### "Device connected / disconnected" banner
input.py, for each new input device after the first scan (not those already there at boot): script-message
`streambox-notice "Device connected · {name}"` (and "Device disconnected · {name}" when its last input disappears), once per
device and per direction within 10 s (name without "Keyboard", "Consumer
Control"…: a Xiaomi remote appears as two inputs). stream-box.lua → `user-data/streambox/notice`
→ qml/Notice.qml (banner at the top, 4 s, over the menu); mpv alone: on-screen message.

### Slimmed initrd and D-Bus race
`KernelInitrdModules=default` + controllers (mkosi.conf): unified kernel of 111 MB instead of 491 (boot loader: ~3 s instead
of ~11 on the Dell). Side effect found on the real box (not in a VM): the initrd, now fast, starts D-Bus right
before switching to the system partition and asks it to stop one millisecond before it announces "Ready"; the
request is lost, systemd waits 90 s then kills it (PC logo frozen, initrd at 1 min 31). Fix:
`rd.systemd.mask=dbus.socket rd.systemd.mask=dbus-broker.service` (nothing uses D-Bus in the initrd). Full
boot on the Dell: 13.6 s. To try a boot option without rebuilding the kernel: systemd-stub add-on
(`ukify build --cmdline "…" --output x.addon.efi`, in `EFI/Linux/<uki>.efi.extra.d/`, Secure Boot disabled).

### Remembered subtitles (per video)
The choice made in the Subtitles / audio panel (Qt app) is kept for the current video in
`~/.local/state/stream-box/sub_prefs.json` (key: YouTube id `v=`, Jellyfin id from `/Videos/<id>/`,
otherwise the link; {lang, t}, 300 videos at most, the oldest go; `no` for off) and restored when it is
resumed (stream-box.lua `apply_sub_pref`, on `file-loaded` in media mode, then on each `track-list` change
for 20 s: Jellyfin's external subtitles arrive after opening; same language on the first two
letters, "forced" tracks last). A video without a choice keeps mpv's.

### Menu closed by playback started from elsewhere
`streambox-tvmenu-close` (script-message): listened to by ui.py (→ `box.closeRequested` → TvMenu
`close()`). Sent by stream-box.lua when a video arrives through `streambox-play` (phone, Cast, Home Assistant,
history…), when jellyfin-mpv-shim loads a file, when a channel arrives through `streambox-channel`, and by
the key wizard. Not for automatic live restarts (switch, frozen live stream).

### Info panel (video)
`qml/InfoPanel.qml`: slides in from the right, thumbnail (YouTube) or episode image (Jellyfin), title, channel or
series, date, views or rating, then the full description (`user-data/streambox/meta`: `overview` up to 3000
characters, `thumb`). Opened from the title: ↑ from the bar selects it (`title_focus`, published in `controls.title`,
"OK · Info" frame around the title in InfoBar.qml), OK opens the panel, ↓ goes back down to the buttons, ↑ closes the
bar, Back leaves the title without stopping the video; stream-box.lua `info_open` / `info_scroll` → `user-data/streambox/info` {open, scroll}; ↑ ↓ scroll by 4 lines (bounded by the
length of the text), Back / OK / ≡ close; closed at the end of the file.

### YouTube token server (stream-box-pot)
`systemd/stream-box-pot.service` runs `node build/main.js` (bgutil-ytdlp-pot-provider, port 4416) with the venv's Node
(install.sh, nodejs-wheel) or, failing that, the system's (image, nodejs package): `env PATH=…/media-venv/bin:/usr/bin`.
Without this server, yt-dlp has no GVS PO token and YouTube only offers format 18 (360p): check
`curl 127.0.0.1:4416/ping` when a YouTube video is blurry (boxes installed from the image were affected
until 2026-10-25).

### Quality selector (YouTube)
Separate "Quality" button (HD icon), present if YouTube offers several heights: same panel as the
subtitles in `quality` mode (`open_tracks("quality")`, `tracks_mode`); heights read from the yt-dlp response kept by ytdl_hook (`user-data/mpv/ytdl/json-subprocess-result`: no
new request; AV1 excluded, the chip does not decode it). "Auto (best)  ·  1440p" or a height ("720p60"):
capped `ytdl-format` (`bestvideo[height<=?H][vcodec!^=av01]+bestaudio/best`) and reload at the same second
(stream-box.lua, `quality` table: a single local, the main chunk is at Lua's limit of 200; list kept
once per video, the button row asks for it often). Applies to the
current video; another video goes back to the default format. Jellyfin: no choice (original file).
