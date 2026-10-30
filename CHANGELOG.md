# Changelog

The important changes of each release, for the people who use the box. Each `## [x.y.z]` section becomes the text of
the GitHub release of tag `vx.y.z` (`.github/workflows/image.yml`). Versions follow [SemVer](https://semver.org/):
`x.y.Z` fixes, `x.Y.0` new features.

## [Unreleased]

### Changed
- Stream Box is now **Inlet**, with a new logo: TV menu, boot screen, companion app (its icon too), Cast and
  Jellyfin's "Play on" lists, Plex, Home Assistant. Settings, accounts and updates are untouched.
- Gamepads: Start (≡ on Xbox controllers) now opens the options and Select (View) the TV menu, the other way round
  from before; the middle button and the Steam Deck's "…" open the TV menu too.
- No more home screen shortcut on the keys (the Steam Deck's "…", the remote's Internet key, H on a keyboard): the
  TV menu's "Home screen" entry stays.

### Added
- PC link: a TV menu tab to play the games of PCs running Sunshine, with Moonlight. The box finds the PCs on the
  network, pairs with a code typed in Sunshine, shows each PC's games and streams them; hold Home to end the stream.
  The PCs are also managed in Settings → Accounts and links (pair, forget, search again).
- Inlet app (preview): the player as a Flatpak app, for SteamOS or a desktop, without the box's system settings
  (its OS runs itself). Built with `flatpak/build.sh`; Settings → "Quit" closes it. It opens in a window (F11 or a
  double click: full screen) and needs no first setup from a phone.
- Keyboard: Tab opens and closes the TV menu; in the search, the computer's keys type directly.

## [0.5.0]

### Changed
- YouTube account: no more Google app to create. Connecting the account (a code on google.com/device) is enough for
  the Subscriptions row, Recommended for you and the progress synced with your other screens; one sign-in instead of
  two. The subscriptions now come from the same feed as the YouTube app for TVs (Shorts left out, lives first).
- Twitch followed channels: no more Twitch app to create, the box has its own; authorizing with the code on
  twitch.tv/activate is enough. Your own app stays possible in the companion app.
- Gamepads: the middle button (Steam on the Steam Deck, Xbox, PlayStation) opens the TV menu, like Start; the Steam
  Deck's "…" button goes to the home screen.
- Steam Deck: its controller is used as a gamepad from the start (it acted as a keyboard and mouse until ☰ was held,
  and Steam or "…" did nothing).

### Added
- The battery level shows in the TV menu, on the home screen and in the companion app on devices that have one
  (Steam Deck, laptop).
- Developer mode: the direct update can follow any branch of the repository (◀ ▶ on "Direct update (source)", or the
  list in the companion app), forwards or backwards; choosing main again is the way back.

### Fixed
- YouTube: a video refused by YouTube ("Can't play this video", HTTP 403) is reloaded at the same second with
  another YouTube client, and the one that plays is kept for the next videos: which one YouTube accepts changes from
  one day to the next.
- Built-in screens mounted sideways (Steam Deck) show the box the right way up instead of on its side.
- Boot: when the system partition does not show up (a Steam Deck's SD card sometimes fails to start on a cold boot),
  the box restarts after about 30 s instead of freezing on the boot screen.
- A box running from its USB stick no longer offers to check for system updates it cannot install: Settings →
  Updates (and the companion app) say to install it on the PC to get them.
- README: flash the image with balenaEtcher or dd; a stick written with Rufus did not finish booting.

## [0.4.0]

### Changed
- Updates: the box checks every day whether a new version exists and the TV menu offers it ("Version X is available.
  Update now?"); nothing is downloaded until you accept. Settings → Updates shows the version and when it was last
  checked, with one button that checks, installs or restarts as needed; no more "next update" date.
- The tools that keep YouTube and Twitch working (yt-dlp, streamlink…) update themselves every day without a word;
  "Update dependencies" in Settings → Advanced forces it. The direct update of developer mode, renamed "Direct update
  (source)", has its own status in Settings → Updates.
- The same rules everywhere (TV menu, companion app, simplified version): disconnecting an account, forgetting the
  learned keys, turning SSH or developer mode off and leaving the Wi-Fi network ask first; restart and shut down ask
  a second OK; one name and one symbol per action (↻ Restart, ⏻ Shut down, ☾ Sleep…), and every dialog has a way out.
- TV menu: OK on a card plays at once when there is nothing to choose (Jellyfin, Plex), and ≡ opens the options of
  any card; OK on a ◀ ▶ setting no longer changes it by accident, the interface language is applied with OK like
  the resolution; rows that open a dialog show "›" and open with ▶ too; the chat corner moves both ways in one step.
- Companion app: a "Chat and playback" group with the TV's chat, subtitle, night mode, auto switch and polls
  settings; "Disconnect" for every account; a Plex sign-in code can be cancelled; installing or applying an update
  asks first.
- Every button shows at once that it was pressed (dialogs open right away, "Checking…", "In progress…") instead of
  changing a few seconds later: settings switches, favorite channels, reloading subscriptions, disconnecting a
  library, authorizing followed channels on the TV; in the companion app, account buttons, list rows, shutdown,
  backup download and image upload (greyed out until the box answers, no double press).
- TV menu: the Twitch account row says where to sign in (the companion app) instead of doing nothing.
- TV menu, Settings: each section says what it holds, and shows a notice only when something needs attention
  (update ready, no network…) instead of a few of its values.
- TV menu: entering YouTube, Jellyfin or Plex puts the focus on the first row of videos (the search is just above).
- TV menu, grids (Live, Following, History): ▶ on the last card of a line goes on to the next line.

### Fixed
- YouTube: videos resumed in the middle (history, Resume) failed with "Can't play this video": YouTube served only
  the start of the file to the client the box used; it now uses another one.
- TV menu: leaving the Bluetooth search with Back no longer lets its results replace the next dialog; the YouTube
  sign-in code no longer stays on screen after the menu is closed; a dialog without buttons no longer breaks on OK.
- An online system update and an update from a USB stick or a file can no longer run at the same time.
- Simplified version: its System menu offers the system update (check, install, restart to apply), as the full one.
- Companion app: errors stay visible instead of disappearing at once; "The box is restarting…" (or turned off,
  asleep) stays until the box is back instead of turning into "Box unreachable"; accounts, Jellyfin, Plex and the
  update from a file are reread each time Settings opens; a Wi-Fi connection shows its result.
- Texts that still pointed to the former System menu now point to Settings; the backup texts mention Plex.
- Bluetooth pairing: the "Pairing…" dialog closes as soon as the device is paired, instead of about a minute later.
- Install on this PC: the dialog opens at once and stays during the start of the installation; the percentage on its
  row keeps moving once the dialog is hidden.
- Playback bar: the buttons under it no longer disappear when the bar hides while one of them is chosen; the bar
  stays while the video title is chosen.
- Leaving a video with Back reopens the menu on the tab it was started from (YouTube…) instead of Live.
- A YouTube video refused by YouTube's robot check now says so, instead of "Can't play this video".

## [0.3.0]

### Changed
- Automatic updates no longer restart the box by themselves: at each start and wake-up, the TV menu offers to restart
  onto the waiting version ("Later" asks again next time, "Don't ask again" not for this version). "Update now"
  still applies at once when nothing plays; once installed, Settings → Updates → Update now and the companion app
  offer "Restart now".
- TV menu: Settings and System become one Settings tab, in sections (Picture and sound, Playback, Chat, Appearance,
  Accounts and libraries, Network, Devices, Updates, Backup and installation, Advanced), each with a summary of what
  it holds; sleep, restart and shut down stay on the list.
- Companion app: its Settings are grouped the same way, in folded groups (the open ones are remembered).
- System status: the Disk tile shows the space left for your data (the system partition aside).

### Added
- Local system update, without the Internet: a release's image (stream-box.raw.xz with its SHA256SUMS and
  SHA256SUMS.gpg) from a USB stick (TV menu: Settings → Updates) or sent from the companion app (Settings → Status and
  updates). Unsigned images only in developer mode.
- Developer mode: a "Direct update (main)" option (Settings → Updates) takes the box's files straight from the main branch (code and system
  files, not the system), shown as <version>+<commit> · dev. Otherwise the box updates as any other.
- YouTube: a "Recommended for you" row, your YouTube home's videos (when the YouTube account is connected for the
  progress sync).

## [0.2.0]

To get A/B system updates, a box installed with 0.1.x must be installed again from this version: save its settings
first (System → Backup and restore, on a USB stick), then restore them after the installation.

### Changed
- New installations prepare the disk for A/B system updates: two system partitions and a data partition that keeps
  your settings, accounts, Bluetooth pairings and Wi-Fi networks when the system is replaced. Boxes already installed
  keep working as they are.
- The streamer list moved into the settings folder (moved by itself, nothing to do).
- Releases now also contain the system partition and the kernel as separate files, with a signed checksum list, and
  the list of their packages.

### Added
- A/B system updates: on a box installed with this version, "Update now" and the weekly update install the whole
  system of the latest release (Arch packages, kernel and the box's code) next to the running one, then restart onto
  it when nothing is playing. If it doesn't work, the box goes back to the previous version by itself.
- A release rebuilt every month with the latest Arch packages (security fixes), when they changed.

### Fixed
- The playback bar no longer shows up empty for a moment, nor goes back to 0 while it disappears.

## [0.1.1]

### Fixed
- The system update no longer waits 2 minutes for the network before starting.

## [0.1.0]

First public release.

### Added
- Disk image to flash on a USB stick: the box runs from it right away, then "Install on this PC" (System menu) copies
  it to the internal disk, settings included. On a USB stick it writes as little as possible.
- TV menu: live streamers (their live in the background of the menu), followed channels, replays, YouTube
  (subscriptions, favorites, search), Jellyfin and Plex (resume, next up, libraries, series), history, settings and
  system.
- Jellyfin sign-in with Quick Connect and Plex sign-in with a code, from the TV or the companion app.
- Video playback: ← → pause and move a target on the bar (held key: bigger jumps), OK goes there; preview thumbnails
  for YouTube; subtitles and audio tracks; next episode.
- Companion app on the phone: remote, streamer list, playback, settings, backup and restore.
- Simplified version (mpv alone, for weak hardware): a quick menu with every feature, as text lists.
- Updates: "Update now" (System menu) and every week by itself: streamlink, yt-dlp and the other tools, then the box's
  code and system files from the latest release.
- Remotes, gamepads and keyboards, over Bluetooth or USB.
