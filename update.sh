#!/usr/bin/env bash
# Stream Box : mise à jour hebdomadaire de streamlink, yt-dlp et jellyfin-mpv-shim (ils cassent quand Twitch ou
# YouTube changent quelque chose). Chaque venv est testé après la mise à jour ; en cas d'échec, on remet exactement
# les versions d'avant. Lancé par stream-box-update.timer (systemd --user). Journal : ~/.local/state/stream-box/update.log
set -uo pipefail

LOG="$HOME/.local/state/stream-box/update.log"
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1
echo "=== $(date '+%F %T')"

# venv | paquets à mettre à jour | test qui doit réussir après
update() {
  local venv="$HOME/.local/share/$1" packages="$2" test="$3"
  local before; before=$(mktemp)
  "$venv/bin/pip" freeze > "$before"
  if ! "$venv/bin/pip" install -q -U pip $packages; then
    echo "$1 : échec de pip, rien n'a changé ?"
  fi
  if bash -c "$test" > /dev/null 2>&1; then
    local changed; changed=$(diff <(sort "$before") <("$venv/bin/pip" freeze | sort) | grep '^>' | sed "s/^> /$1 : /")
    echo "${changed:-$1 : déjà à jour}"
  else
    echo "$1 : le test échoue après mise à jour, retour aux versions précédentes"
    "$venv/bin/pip" install -q -r "$before"
    bash -c "$test" > /dev/null 2>&1 && echo "$1 : retour OK" || echo "$1 : ÉCHEC même après retour arrière"
  fi
  rm -f "$before"
}

# Vidéo YouTube de 19 s, stable depuis 2005 ; streamlink doit au moins reconnaître une URL Twitch
update streamlink-venv streamlink \
  "$HOME/.local/bin/streamlink --can-handle-url https://www.twitch.tv/twitch"
update media-venv "yt-dlp[default] deno nodejs-wheel bgutil-ytdlp-pot-provider jellyfin-mpv-shim" \
  "$HOME/.local/bin/yt-dlp --simulate --no-warnings https://www.youtube.com/watch?v=jNQXAC9IVRw && $HOME/.local/bin/jellyfin-mpv-shim --version"

# Serveur de jetons anti-robot YouTube : sa version doit suivre celle du plugin bgutil (recompilé si elle change)
POT_DIR="$HOME/.local/share/bgutil-pot-provider"
want=$("$HOME/.local/share/media-venv/bin/pip" show bgutil-ytdlp-pot-provider | awk '/^Version/{print $2}')
have=$(git -C "$POT_DIR" describe --tags 2>/dev/null)
if [ -n "$want" ] && [ "$want" != "$have" ]; then
  echo "serveur de jetons : $have → $want"
  export PATH="$HOME/.local/share/media-venv/bin:$PATH"
  if git clone -q --depth 1 --branch "$want" https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "$POT_DIR.new" \
     && (cd "$POT_DIR.new/server" && npm ci --no-audit --no-fund --loglevel=error && npx tsc); then
    rm -rf "$POT_DIR" && mv "$POT_DIR.new" "$POT_DIR"
    systemctl --user restart stream-box-pot.service && echo "serveur de jetons : relancé"
  else
    rm -rf "$POT_DIR.new"; echo "serveur de jetons : ÉCHEC de la compilation, ancienne version conservée"
  fi
fi
