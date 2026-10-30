#!/usr/bin/env bash
# Owlink: backup of settings and connections, to put them back after a reinstallation:
#
#   sudo bash backup.sh [archive.tar.gz]      then, on the reinstalled machine:
#   sudo bash install.sh --restore archive.tar.gz …
#
# Contains the streamer list, the box settings, the Twitch token, the Jellyfin connection, the MQTT and weather config,
# the sound settings and the Bluetooth pairings. These are secrets: the archive is only readable by whoever runs the
# script, and has nothing to do in the repository.
set -euo pipefail

BOX_HOME=/home/media
OUT=${1:-stream-box-backup-$(date +%F).tar.gz}

[ "$(id -u)" -eq 0 ] || { echo "Error: run with sudo" >&2; exit 1; }

# Paths relative to /, kept only if they exist (same list as the restore in install.sh)
PATHS=(
  "${BOX_HOME#/}/.local/state/stream-box"
  "${BOX_HOME#/}/.config/stream-box"
  "${BOX_HOME#/}/.config/streamlink/config.twitch"
  "${BOX_HOME#/}/.config/jellyfin-mpv-shim"
  "${BOX_HOME#/}/.local/state/wireplumber"
  "var/lib/bluetooth"
)
present=()
for p in "${PATHS[@]}"; do
  if [ -e "/$p" ]; then present+=("$p"); fi
done
[ ${#present[@]} -gt 0 ] || { echo "Nothing to back up (box not installed yet?)" >&2; exit 1; }

umask 077
tar -czf "$OUT" -C / --exclude='*/fonts' --exclude='*/scripts' --exclude='*.lock*' --exclude='*.bak' "${present[@]}"
[ -n "${SUDO_USER:-}" ] && chown "$SUDO_USER:" "$OUT"
chmod 600 "$OUT"
echo "Backup: $OUT ($(du -h "$OUT" | cut -f1)), with:"
printf '  /%s\n' "${present[@]}"
