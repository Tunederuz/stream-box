# Changelog

The important changes of each release, for the people who use the box. Each `## [x.y.z]` section becomes the text of
the GitHub release of tag `vx.y.z` (`.github/workflows/image.yml`). Versions follow [SemVer](https://semver.org/):
`x.y.Z` fixes, `x.Y.0` new features.

## [Unreleased]

### Changed
- Automatic updates no longer restart the box by themselves: at each start and wake-up, the TV menu offers to restart
  onto the waiting version ("Later" asks again next time, "Don't ask again" not for this version). "Update now"
  still applies at once when nothing plays; once installed, System → Update now and the companion app offer "Restart
  now".
- System status: the Disk tile shows the space left for your data (the system partition aside).

### Added
- Local system update, without the Internet: a release's image (stream-box.raw.xz with its SHA256SUMS and
  SHA256SUMS.gpg) from a USB stick (System menu) or sent from the companion app (Settings → System). Unsigned images
  only in developer mode.
- Developer mode: "Update now" takes the box's files straight from the main branch (code and system files, not the
  system), shown as <version>+<commit> · dev.
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
