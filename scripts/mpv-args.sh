# Inlet: mpv options of the player (sourced by player.sh and stream-player.sh, which set DIR): MPV_ARGS.
# shellcheck shell=bash

# Format of videos sent as a link (yt-dlp). By default 1440p at most and no AV1, which many iGPUs can't decode in
# hardware (everything would fall back to the CPU); another rule can be put in this file.
YTDL_FORMAT='bestvideo[height<=?1440][vcodec!^=av01]+bestaudio/best'
[ -s "$HOME/.config/stream-box/ytdl-format" ] && YTDL_FORMAT=$(head -1 "$HOME/.config/stream-box/ytdl-format")

# hwdec: hardware decoding when it is safe (VA-API, NVDEC…). French and English subtitles, manual and automatic,
# without the automatic translations ("French from Arabic"… over 100 tracks).
# player_client: mweb first, tv_simply as a fallback; which client's streams YouTube serves changes from day to day
# (tv_simply cut after the first megabytes on 2026-10-28, mweb refused on 2026-10-29): stream-box.lua reloads a video
# refused with HTTP 403 with the next client
# fetch_pot: anti-bot token (stream-box-pot service) for every request, otherwise YouTube blocks the subtitles
# shellcheck disable=SC2054  # (commas inside mpv option values, not array separators)
MPV_ARGS=(
  --idle=yes --force-window=yes --fs --osc=no --cursor-autohide=4000
  --input-ipc-server=/tmp/stream-box-mpv.sock --script="$DIR/lua/stream-box.lua"
  --cache=yes --hwdec=auto-safe
  --ytdl-format="$YTDL_FORMAT"
  --ytdl-raw-options-append=sub-langs=fr,fr-FR,fr-orig,en,en-US,en-GB,en-orig
  --ytdl-raw-options-append=write-subs= --ytdl-raw-options-append=write-auto-subs=
  --ytdl-raw-options-append=cookies="$HOME/.config/stream-box/twitch-cookies.txt"
  --ytdl-raw-options-append='extractor-args=youtube:player_client=mweb,tv_simply;fetch_pot=always'
)
# YouTube JavaScript challenges: deno if installed (install.sh), otherwise the system Node (image)
[ -x "$HOME/.local/bin/deno" ] || MPV_ARGS+=(--ytdl-raw-options-append=js-runtimes=node)
