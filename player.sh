#!/usr/bin/env bash
# Stream Box: permanent player, restarted if it closes (started by start.sh, in the cage session).
#
# Player: the Qt Quick app embedding mpv (ui.py, ui-venv venv) if ~/.config/stream-box/player contains "qt", otherwise
# mpv alone. The file is read again on each restart: to switch, write it then quit the player (quit command through
# the IPC). Safety net: if the Qt app stops three times in a row in less than 30 s, back to mpv alone until the next
# session start.
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"
UI_PYTHON="$HOME/.local/share/ui-venv/bin/python"

# Format of videos sent as a link (yt-dlp). By default 1440p at most and no AV1, which many iGPUs can't decode in
# hardware (everything would fall back to the CPU); another rule can be put in this file.
YTDL_FORMAT='bestvideo[height<=?1440][vcodec!^=av01]+bestaudio/best'
[ -s "$HOME/.config/stream-box/ytdl-format" ] && YTDL_FORMAT=$(head -1 "$HOME/.config/stream-box/ytdl-format")

# hwdec: hardware decoding when it is safe (VA-API, NVDEC…). French and English subtitles, manual and automatic,
# without the automatic translations ("French from Arabic"… over 100 tracks).
# player_client: the TV client chosen by default gets refused streams (403); tv_simply and android_vr work.
# fetch_pot: anti-bot token (stream-box-pot service) for every request, otherwise YouTube blocks the subtitles
MPV_ARGS=(
  --idle=yes --force-window=yes --fs --osc=no --cursor-autohide=4000
  --input-ipc-server=/tmp/stream-box-mpv.sock --script="$DIR/stream-box.lua"
  --cache=yes --hwdec=auto-safe
  --ytdl-format="$YTDL_FORMAT"
  --ytdl-raw-options-append=sub-langs=fr,fr-FR,fr-orig,en,en-US,en-GB,en-orig
  --ytdl-raw-options-append=write-subs= --ytdl-raw-options-append=write-auto-subs=
  --ytdl-raw-options-append=cookies="$HOME/.config/stream-box/twitch-cookies.txt"
  --ytdl-raw-options-append='extractor-args=youtube:player_client=tv_simply,android_vr;fetch_pot=always'
)
# YouTube JavaScript challenges: deno if installed (install.sh), otherwise the system Node (image)
[ -x "$HOME/.local/bin/deno" ] || MPV_ARGS+=(--ytdl-raw-options-append=js-runtimes=node)

quick_fails=0 last_choice=""
while true; do
  choice=$(head -1 "$HOME/.config/stream-box/player" 2>/dev/null)
  # Player chosen by hand (companion app setting, which rewrites the file even without a change): the Qt app's past
  # failures are forgotten, which allows trying it again after an automatic fallback to mpv
  stamp="$(stat -c %Y "$HOME/.config/stream-box/player" 2>/dev/null)$choice"
  [ "$stamp" != "$last_choice" ] && quick_fails=0 && last_choice=$stamp
  pkill -u "$USER" -f 'streamlink .*--player-external-http'   # leftovers from a previous player
  # Jellyfin: "Play on → Stream Box". The shim drives this player through its socket (config in
  # ~/.config/jellyfin-mpv-shim/) and doesn't reattach on its own to a restarted player: restart it along. It gives
  # up if the socket doesn't exist yet (the Qt app takes longer than mpv to open it): it waits for it.
  pkill -u "$USER" -f '[j]ellyfin-mpv-shim'
  rm -f /tmp/stream-box-mpv.sock
  (
    for _ in $(seq 120); do [ -S /tmp/stream-box-mpv.sock ] && break; sleep 0.5; done
    exec jellyfin-mpv-shim --no-gui < /dev/null > /tmp/jellyfin-shim.log 2>&1
  ) &
  if [ "$choice" = qt ] && [ -x "$UI_PYTHON" ] && [ "$quick_fails" -lt 3 ]; then
    started=$(date +%s)
    QT_QPA_PLATFORM=wayland "$UI_PYTHON" "$DIR/ui.py" "${MPV_ARGS[@]}" >> /tmp/stream-box-ui.log 2>&1
    code=$?
    if [ "$code" -ne 0 ] && [ $(( $(date +%s) - started )) -lt 30 ]; then
      quick_fails=$((quick_fails + 1))
      echo "$(date '+%F %T') ui.py stopped (code $code), quick failure #$quick_fails" >> /tmp/stream-box-ui.log
    else
      quick_fails=0
    fi
  else
    kill "$(cat "${XDG_RUNTIME_DIR:-/tmp}/stream-box-splash.pid" 2> /dev/null)" 2> /dev/null   # boot image
    mpv "${MPV_ARGS[@]}"
  fi
  sleep 2
done
