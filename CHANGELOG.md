# Changelog

The important changes of each release, for the people who use the box. Each `## [x.y.z]` section becomes the text of
the GitHub release of tag `vx.y.z` (`.github/workflows/image.yml`). Versions follow [SemVer](https://semver.org/):
`x.y.Z` fixes, `x.Y.0` new features.

## [Unreleased]

### Changed
- Updates: the box checks every day whether a new version exists and the TV menu offers it ("Version X is available.
  Update now?"); nothing is downloaded until you accept. Settings → Updates shows the version and when it was last
  checked, with one button that checks, installs or restarts as needed; no more "next update" date.
- The tools that keep YouTube and Twitch working (yt-dlp, streamlink…) update themselves every day without a word;
  "Update dependencies" in Settings → Advanced forces it. The direct update of developer mode, renamed "Direct update
  (source)", has its own status in Settings → Updates.
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
- YouTube: videos resumed in the middle (history, Resume) failed with "Can't play this video": YouTube served only
  the start of the file to the client the box used; it now uses another one.

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
