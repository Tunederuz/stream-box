# Changelog

The important changes of each release, for the people who use the box. Each `## [x.y.z]` section becomes the text of
the GitHub release of tag `vx.y.z` (`.github/workflows/image.yml`). Versions follow [SemVer](https://semver.org/):
`x.y.Z` fixes, `x.Y.0` new features.

## [Unreleased]

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
