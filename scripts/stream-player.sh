#!/usr/bin/env bash
# Inlet app: the player as an app, on a system that runs itself (SteamOS, a desktop…). No system part (app/system
# is not shipped: no Wi-Fi, Bluetooth, power, updates of the box) and no restart loop: closing the app (Steam's "Exit
# game", the window's close button) stops everything it started. The Flatpak's stream-player command; also works
# from a repository, with the tools on the PATH.
DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"   # the repository (this script is in its scripts/)
export PATH="$HOME/.local/bin:$PATH"
# shellcheck disable=SC2046  # (one PID per word)
trap 'kill $(jobs -p) 2> /dev/null' EXIT
trap 'exit 0' INT TERM HUP

# Python with PySide6 and python-mpv: the Flatpak's, or the box's ui-venv when started from a box's repository
UI_PYTHON=python3
[ -x "$HOME/.local/share/ui-venv/bin/python" ] && UI_PYTHON="$HOME/.local/share/ui-venv/bin/python"

# No first setup from the phone (the box's large QR code until it is done): the app is used with its own window
mkdir -p "$HOME/.config/stream-box" && touch "$HOME/.config/stream-box/setup-done"
python3 "$DIR/app/player/remote.py" &   # companion app, port 8080
# YouTube Cast receiver and "TV app" access (cast/cast.js), when its modules are there
[ -d "$DIR/cast/node_modules" ] && node "$DIR/cast/cast.js" &
# YouTube anti-bot tokens for yt-dlp (bgutil-ytdlp-pot-provider, port 4416; on the box, the stream-box-pot service)
POT_SERVER="${STREAM_PLAYER_POT:-$HOME/.local/share/bgutil-pot-provider/server}"
[ -f "$POT_SERVER/build/main.js" ] && (cd "$POT_SERVER" && exec node build/main.js > /dev/null 2>&1) &
# Jellyfin "Play on…" (see player.sh): once the player's socket exists
rm -f /tmp/stream-box-mpv.sock
(
  for _ in $(seq 120); do [ -S /tmp/stream-box-mpv.sock ] && break; sleep 0.5; done
  exec jellyfin-mpv-shim --no-gui < /dev/null > /tmp/jellyfin-shim.log 2>&1
) &

# shellcheck source=scripts/mpv-args.sh
. "$DIR/scripts/mpv-args.sh"
"$UI_PYTHON" "$DIR/app/player/ui.py" "${MPV_ARGS[@]}"
