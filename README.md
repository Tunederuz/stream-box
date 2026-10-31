# Inlet

<img src="assets/brand/inlet-mark-light.svg" alt="Inlet logo" width="120">

*Formerly Stream Box.* Two forms: **Inlet OS**, the system image of a box (below), and the **Inlet app**, a
Flatpak for SteamOS or a desktop, without the box's system settings.

A Linux mini PC plugged into the TV that shows your favorite streamers' Twitch streams full screen, with the chat as
an overlay, without a desktop or keyboard. It is controlled with a Bluetooth remote or a companion app
that can be installed on a phone (PWA).


## What it does

- **Full-screen Twitch streams** (streamlink + mpv, low latency, ads skipped), starts on the menu
  (Back returns to it, nothing playing behind), automatic switch to a live streamer if yours is offline, restart of a
  frozen live stream.
- **Twitch chat overlay** (anonymous, read-only), in the corner of your choice, with adjustable background and size,
  and Twitch, 7TV, BTTV and FFZ emotes (animated) with the Qt app.
- **Rewind the live stream** (a few minutes kept in memory), pause with time shifting.
- **Polls and predictions** shown on the TV, and voting or betting channel points from the phone.
- **Who is live** in the menu and the companion app, **notification** when a streamer from the list goes live.
- **Ambient screen** when nothing is playing: clock, date, weather and upcoming scheduled streams (Twitch schedules).
- **Polls and predictions** of the channel being watched shown on the TV, with the time left and the results.
- **Companion app QR code** on the ambient screen and in the menu, for guests: always, 30 seconds or never.
- **Night mode**: compressed sound (loud sounds softened, voices boosted) for watching at low volume.
- Optional **Twitch account**: no more ads on channels you are subscribed to, subscriber-only VODs.
- **History and resume**: each video resumes where you left off; Twitch replays are synced with the connected Twitch
  account.
- **Subtitles and audio track** selectable during a video (≡ button), including Jellyfin's external subtitles.
- **Video mode**: YouTube and other links (yt-dlp, subtitles), Twitch replays and clips, Android sharing
  "Share → Inlet", and **Jellyfin** ("Play on…") via jellyfin-mpv-shim.
- **YouTube**: list of channels with their latest videos, and search for videos and channels, on the TV (on-screen
  keyboard) and in the companion app, without an API key. Red playback bar for YouTube, blue for Jellyfin.
- **Jellyfin** in the TV menu and the companion app: continue watching, next up, recently added, search, episodes of a
  series; progress is reported back to the server (no configuration beyond "Play on…").
- **Plex** in the TV menu: the same rows, search and episodes, direct play, progress reported to the server (address
  of the server given in the companion app). Library tabs only show once connected.
- **Large TV menu** in the style of Android TV (Menu button of the remote), animated and rendered by the GPU:
  live streamers, followed channels, replays, YouTube, Jellyfin, history, settings, system.
- **Two streams at once**: picture-in-picture in a corner or side by side, swapped with one press.
- **Companion app**: on-demand screen preview, streamers and list order, chat, volume, playback bar, TV resolution,
  power off. **Bluetooth remote** (tested with the Xiaomi TV Stick one).
- **Dedicated session without a desktop** (cage compositor); normal login screen if a keyboard is plugged in at boot.
- **Home Assistant** through MQTT discovery: control from HA, and automatic power on (Wake-on-LAN) when a streamer
  goes live. See `docs/home-assistant.md`.
- **Weekly updates** of streamlink, yt-dlp and the rest, with rollback if a test fails. Box status (temperatures,
  network, playback, services) and on-demand update in the companion app.
- **English and French** interface on the TV and in the companion app: English by default, chosen first in the
  companion app's first-setup screen, then in TV Settings → Language → "Interface language" or companion app
  Settings → "Language".

## How it is built

| Folder | Role |
|---|---|
| `app/player/` | The player, portable: the Qt Quick app embedding mpv (`ui.py` + `ui.qml`), the companion app server `remote.py` and its modules (`api.py`, `actions.py`, `twitch.py`, `youtube.py`, `jellyfin.py`, `plex.py`, `quickmenu.py`, `playback.py`, `history.py`, …), the chat (`chat_overlay.py`, `chat_qt.py`), translations (`i18n.py`); `sysparts.py` takes the system part when it is there |
| `app/system/` | The box's system, Inlet OS only: power, updates, SSH and developer mode (`system.py`), resolution (`display.py`), sound (`audio.py`), keys at the source (`input.py`), Wi-Fi (`netsetup.py`), Bluetooth (`btsetup.py`, `btagent.py`), installer, local update, backup, boot mode, MQTT bridge. The modules of both folders import each other by name |
| `lua/` | mpv script `stream-box.lua` and its modules (`lua/streambox/`): streamlink, quick menu of the simplified version, Twitch / video modes, time shifting, playback bar, keys |
| `qml/`, `qml/menu/` | Large TV menu in the style of Android TV, in QML (animated, rendered by the GPU) |
| `web/` | Companion app page (`remote.html`), its PWA files and icons |
| `scripts/` | `start.sh` (launched by the session: chat, companion app, resolution, then the player), `player.sh` (player loop: Qt or mpv alone), `update.sh` (dependencies), `install.sh`, `backup.sh` |
| `assets/` | Boot image, invisible cursor of the session, example streamer list |
| `locales/` | Interface translations (English by default, French available), read by Python, QML and Lua |
| `cast/` | YouTube Cast receiver and the YouTube account's TV access (Node) |
| `systemd/` | User services: dependency updates, YouTube anti-bot tokens, MQTT bridge |
| `image/` | The disk image (mkosi): system configuration, A/B updates, installer |
| `tests/`, `tools/check.sh`, `tools/qmlshots/` | Automated tests and checks (also run on GitHub); screenshots of the TV menu without a box |
| `start.sh`, `update.sh`, `mqtt_bridge.py`, `cursors` (root) | Relays for boxes whose image (0.5.0 and older) still points there; to remove later |
| `CLAUDE.md` | Detailed technical documentation (decisions, pitfalls, how to test) |

## Installation

### What you need

- A small x86-64 PC that boots in UEFI, plugged into the TV over HDMI. Tested on an Intel mini PC (UHD 630 graphics);
  AMD and NVIDIA graphics drivers are in the image but untried.
- A USB stick of 8 GB or more, and an internal disk of 16 GB or more (it is entirely erased: two 5 GB system
  partitions for updates, the rest for your settings).
- Ethernet, or a Wi-Fi card (the box then offers its own Wi-Fi network to set it up from a phone).
- A phone for the first setup, and a Bluetooth remote, a gamepad or a keyboard to use it.

### 1. Get the image

Download `stream-box.raw.xz` from the [releases](https://github.com/Tunederuz/stream-box/releases), or build it
(Linux and Docker; nothing else is installed on the machine, everything happens in an Arch container):

```
git clone https://github.com/Tunederuz/stream-box.git && cd stream-box
bash image/build.sh        # image/mkosi.output/stream-box.raw (about 3 GB)
bash image/build.sh xz     # stream-box.raw.xz, the compressed version
bash image/build.sh vm     # optional: try it in a virtual machine first
```

### 2. Flash it on a USB stick

With [balenaEtcher](https://etcher.balena.io/) (takes the `.xz` as is), or on Linux:
`xzcat stream-box.raw.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync`. Not Rufus: a stick written with it
(0.4.0, Steam Deck) never finished booting (emergency mode), the same image written with dd did. If Windows offers to
format the stick afterwards (it cannot read the system partition), cancel.

### 3. Boot the PC on the stick

Choose the stick in the PC's boot menu. The box runs right away from the stick, everything works: you can try it
before installing anything. On a USB drive it writes as little as possible (journal and caches in memory, history once a
minute), but a cheap stick is still not meant to run it for good: install it on the PC's disk.

The first time, the TV shows QR codes: connect the phone to the box's Wi-Fi network if there is no cable, then open
the setup page (language, Wi-Fi, streamers). The companion app stays available at `http://<box address>:8080`.

### 4. Install it on the PC's disk

TV menu → Settings → Backup and installation → "Install on this PC" → choose the disk → confirm. Everything on that disk is erased; the settings
made from the stick come along. Then remove the stick and restart.

If the installer finds no disk while the PC has an NVMe SSD, the BIOS has the disk controller in RAID mode (Intel RST,
common on Dell): set it to AHCI (Dell: SATA Operation → AHCI). The installer says so when it detects it.

### Afterwards

- Twitch account, Jellyfin, Plex, YouTube account: from the TV menu (Settings → Accounts and links) or the companion app (Settings).
- Wake-on-LAN is on for Ethernet in the image: enable it in the BIOS too to wake the box from the network.
- Home Assistant: [docs/home-assistant.md](docs/home-assistant.md).
- Updates: the box checks every day for a new release and the TV menu offers it ("Update now?"); Settings → Updates
  checks at once. Accepted, the whole system is installed next to the running one and the box restarts onto it (it
  goes back to the previous version by itself if it doesn't work). streamlink, yt-dlp and the other tools update
  themselves every day (Settings → Advanced → "Update dependencies" to force it). A release is rebuilt every month with the
  latest Arch packages. Boxes installed before 0.2.0 only get the box's code and system files. Without the Internet:
  the image of a release (`stream-box.raw.xz` with `SHA256SUMS` and `SHA256SUMS.gpg`) from a USB stick (Settings →
  Updates) or sent from the companion app.
- Developer mode (TV menu → Settings → Advanced): passwordless sudo and SSH for the `media` user. The image has no other root
  access.

### Inlet app (preview): the app for SteamOS or a desktop
The same player as a Flatpak app, without the box's system settings (Wi-Fi, Bluetooth, power, updates: the OS
handles them). Build it with `flatpak/build.sh` (Docker), then `flatpak install --user Inlet.flatpak`. On
SteamOS, add it to Steam as a non-Steam game to launch it from Game mode.

### Advanced: on an existing Arch installation

`install.sh` installs the box on top of an Arch distribution with Plasma Login (SDDM is supported by the script but
untried) as the login manager. From an admin account, in a copy of the repository:

```
git clone https://github.com/Tunederuz/stream-box.git && cd stream-box
sudo bash scripts/install.sh --city "Your city" --streamers channel1,channel2
```

The script installs the packages, creates the `media` user that runs the box, copies the repository there, installs
streamlink, yt-dlp, jellyfin-mpv-shim and the rest in venvs, enables the services and sets up the desktop-less
session. It can be run again to update an installation (`git pull`, then `sudo bash scripts/install.sh`).
The options are optional (`sudo bash scripts/install.sh --help`):

| Option | Role |
|---|---|
| `--city CITY` | Weather on the ambient screen |
| `--remote-url URL` | Companion app address shown as a QR code (otherwise `http://<box IP>:8080`) |
| `--streamers a,b,c` | Initial list (it can also be filled from the companion app) |
| `--allow-from IP` | Opens port 8080 to this address (HTTPS reverse proxy) if the ufw firewall is active |
| `--static-ip IP/PREFIX --gateway IP [--dns IP]` | Static IP on the Ethernet connection |
| `--wol` | Wake-on-LAN on the Ethernet connection (must also be enabled in the BIOS) |
| `--restore ARCHIVE` | Restores the settings and connections saved by `scripts/backup.sh` |

At the end, it lists the remaining settings (Twitch account, HTTPS, Jellyfin, Home Assistant).

### Backup and reinstallation

The simplest way: TV menu → Settings → Backup and installation → "Backup and restore" (on a USB stick), or Settings → Backup in the companion app
(file downloaded to the phone). Restoring puts everything back, then the box restarts.

On the command line, `sudo bash scripts/backup.sh` creates an archive of everything specific to the box: streamer list,
settings, Twitch token, Jellyfin connection, MQTT and weather configuration, sound, Bluetooth pairings. It contains
secrets: it is readable only by whoever creates it, and does not belong in the repository. After reinstalling with
`install.sh`:

```
sudo bash scripts/install.sh --restore stream-box-backup-YYYY-MM-DD.tar.gz --static-ip … --gateway … --wol --allow-from …
```

The details, and the reasons behind each choice, are in `CLAUDE.md`.
