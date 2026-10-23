#!/usr/bin/env bash
# Stream Box : sauvegarde des réglages et connexions, pour les remettre après une réinstallation :
#
#   sudo bash backup.sh [archive.tar.gz]      puis, sur la machine réinstallée :
#   sudo bash install.sh --restore archive.tar.gz …
#
# Contient la liste des streamers, les réglages de la box, le jeton Twitch, la connexion Jellyfin, la config MQTT et
# météo, les réglages du son et les appairages Bluetooth. Ce sont des secrets : l'archive n'est lisible que par celui
# qui lance le script, et n'a rien à faire dans le dépôt.
set -euo pipefail

BOX_HOME=/home/media
OUT=${1:-stream-box-backup-$(date +%F).tar.gz}

[ "$(id -u)" -eq 0 ] || { echo "Erreur : à lancer avec sudo" >&2; exit 1; }

# Chemins relatifs à /, gardés seulement s'ils existent (même liste que la restauration dans install.sh)
PATHS=(
  "${BOX_HOME#/}/stream-box/streamers.txt"
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
[ ${#present[@]} -gt 0 ] || { echo "Rien à sauvegarder (box pas encore installée ?)" >&2; exit 1; }

umask 077
tar -czf "$OUT" -C / --exclude='*/fonts' --exclude='*/scripts' --exclude='*.lock*' --exclude='*.bak' "${present[@]}"
[ -n "${SUDO_USER:-}" ] && chown "$SUDO_USER:" "$OUT"
chmod 600 "$OUT"
echo "Sauvegarde : $OUT ($(du -h "$OUT" | cut -f1)), avec :"
printf '  /%s\n' "${present[@]}"
