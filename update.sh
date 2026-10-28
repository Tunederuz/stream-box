#!/usr/bin/env bash
# Stream Box: update of the dependencies, streamlink, yt-dlp, jellyfin-mpv-shim… (they break when Twitch or YouTube
# change something), every day by itself and without a word, or by hand (Settings → Advanced → "Update dependencies").
# Each venv is tested after the update; on failure, the exact previous versions are put back. Not the box's system
# (system-update: checked every day, installed when the user accepts). Started by stream-box-update.timer (systemd
# --user). Log: ~/.local/state/stream-box/update.log
set -uo pipefail

LOG="$HOME/.local/state/stream-box/update.log"
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1
echo "=== $(date '+%F %T')"

# venv | packages to update | test that must pass afterwards
update() {
  local venv="$HOME/.local/share/$1" packages="$2" test="$3"
  local before; before=$(mktemp)
  "$venv/bin/pip" freeze > "$before"
  if ! "$venv/bin/pip" install -q -U pip $packages; then
    echo "$1: pip failed, nothing changed?"
  fi
  if bash -c "$test" > /dev/null 2>&1; then
    # (comm and not diff: the image has no diffutils)
    local changed; changed=$(comm -13 <(sort "$before") <("$venv/bin/pip" freeze | sort) | sed "s/^/$1: /")
    echo "${changed:-$1: already up to date}"
  else
    echo "$1: the test fails after the update, back to the previous versions"
    "$venv/bin/pip" install -q -r "$before"
    bash -c "$test" > /dev/null 2>&1 && echo "$1: rollback OK" || echo "$1: FAILED even after rollback"
  fi
  rm -f "$before"
}

# 19 s YouTube video, stable since 2005; streamlink must at least recognize a Twitch URL
update streamlink-venv streamlink \
  "$HOME/.local/bin/streamlink --can-handle-url https://www.twitch.tv/twitch"
# Qt app embedding mpv (ui.py): Qt and python-mpv must load, and libmpv must be found
[ -x "$HOME/.local/share/ui-venv/bin/pip" ] && update ui-venv "PySide6-Essentials python-mpv" \
  "$HOME/.local/share/ui-venv/bin/python -c 'import mpv; from PySide6 import QtQuick'"
# deno and nodejs-wheel only if they are already there (installed by install.sh); the image does without: system Node
JS=""
[ -x "$HOME/.local/share/media-venv/bin/deno" ] && JS="deno nodejs-wheel"
JSARG=""
[ -z "$JS" ] && JSARG="--js-runtimes node"
update media-venv "yt-dlp[default] $JS bgutil-ytdlp-pot-provider jellyfin-mpv-shim paho-mqtt segno" \
  "$HOME/.local/bin/yt-dlp $JSARG --simulate --no-warnings https://www.youtube.com/watch?v=jNQXAC9IVRw && $HOME/.local/bin/jellyfin-mpv-shim --version"

# YouTube anti-bot token server: its version must follow the bgutil plugin's (rebuilt when it changes)
POT_DIR="$HOME/.local/share/bgutil-pot-provider"
want=$("$HOME/.local/share/media-venv/bin/pip" show bgutil-ytdlp-pot-provider | awk '/^Version/{print $2}')
have=$(git -C "$POT_DIR" describe --tags 2>/dev/null)
if [ -n "$want" ] && [ "$want" != "$have" ]; then
  echo "token server: $have → $want"
  export PATH="$HOME/.local/share/media-venv/bin:$PATH"
  if git clone -q --depth 1 --branch "$want" https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "$POT_DIR.new" \
     && (cd "$POT_DIR.new/server" && npm ci --no-audit --no-fund --loglevel=error && npx tsc \
         && npm prune --omit=dev --no-audit --no-fund --loglevel=error); then
    rm -rf "$POT_DIR" && mv "$POT_DIR.new" "$POT_DIR"
    systemctl --user restart stream-box-pot.service && echo "token server: restarted"
  else
    rm -rf "$POT_DIR.new"; echo "token server: build FAILED, old version kept"
  fi
fi

# YouTube Cast receiver (cast/): modules reinstalled if cast/package-lock.json changed (repository update)
CAST_DIR="$(dirname "$(readlink -f "$0")")/cast"
if [ -f "$CAST_DIR/package-lock.json" ] && [ "$CAST_DIR/package-lock.json" -nt "$CAST_DIR/node_modules/.package-lock.json" ]; then
  if (export PATH="$HOME/.local/share/media-venv/bin:$PATH"; cd "$CAST_DIR" && npm ci --omit=dev --no-audit --no-fund --loglevel=error); then
    echo "cast receiver: modules up to date (restarted at the next session start)"
  else
    echo "cast receiver: npm ci FAILED"
  fi
fi
