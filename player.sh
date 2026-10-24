#!/usr/bin/env bash
# Stream Box : lecteur permanent, relancé s'il se ferme (lancé par start.sh, dans la session cage).
#
# Lecteur : l'appli Qt Quick qui embarque mpv (ui.py, venv ui-venv) si ~/.config/stream-box/player contient « qt »,
# sinon mpv seul. Le fichier est relu à chaque relance : pour changer, l'écrire puis quitter le lecteur (commande quit
# par l'IPC). Filet de sécurité : si l'appli Qt s'arrête trois fois de suite en moins de 30 s, retour à mpv seul
# jusqu'au prochain démarrage de la session.
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"
UI_PYTHON="$HOME/.local/share/ui-venv/bin/python"

# Format des vidéos envoyées par lien (yt-dlp). Par défaut 1440p maximum et pas d'AV1, que beaucoup d'iGPU ne décodent
# pas en matériel (tout retomberait sur le processeur) ; une autre règle peut être mise dans ce fichier.
YTDL_FORMAT='bestvideo[height<=?1440][vcodec!^=av01]+bestaudio/best'
[ -s "$HOME/.config/stream-box/ytdl-format" ] && YTDL_FORMAT=$(head -1 "$HOME/.config/stream-box/ytdl-format")

# hwdec : décodage matériel quand il est sûr (VA-API, NVDEC…). Sous-titres français et anglais,
# manuels et automatiques, sans les traductions automatiques (« French from Arabic »… plus de 100 pistes).
# player_client : le client TV choisi par défaut reçoit des flux refusés (403) ; tv_simply et android_vr passent.
# fetch_pot : jeton anti-robot (service stream-box-pot) pour chaque requête, sans quoi YouTube bloque les sous-titres
MPV_ARGS=(
  --idle=yes --force-window=yes --fs --osc=no --cursor-autohide=4000
  --input-ipc-server=/tmp/stream-box-mpv.sock --script="$DIR/stream-box.lua" --script="$DIR/tv_menu.lua"
  --cache=yes --hwdec=auto-safe
  --ytdl-format="$YTDL_FORMAT"
  --ytdl-raw-options-append=sub-langs=fr,fr-FR,fr-orig,en,en-US,en-GB,en-orig
  --ytdl-raw-options-append=write-subs= --ytdl-raw-options-append=write-auto-subs=
  --ytdl-raw-options-append=cookies="$HOME/.config/stream-box/twitch-cookies.txt"
  --ytdl-raw-options-append='extractor-args=youtube:player_client=tv_simply,android_vr;fetch_pot=always'
)
# Défis JavaScript de YouTube : deno s'il est installé (install.sh), sinon le Node du système (image)
[ -x "$HOME/.local/bin/deno" ] || MPV_ARGS+=(--ytdl-raw-options-append=js-runtimes=node)

quick_fails=0 last_choice=""
while true; do
  choice=$(head -1 "$HOME/.config/stream-box/player" 2>/dev/null)
  # Lecteur choisi à la main (réglage de la télécommande, qui réécrit le fichier même sans changement) : les échecs
  # passés de l'appli Qt sont oubliés, ce qui permet de la réessayer après un retour automatique à mpv
  stamp="$(stat -c %Y "$HOME/.config/stream-box/player" 2>/dev/null)$choice"
  [ "$stamp" != "$last_choice" ] && quick_fails=0 && last_choice=$stamp
  pkill -u "$USER" -f 'streamlink .*--player-external-http'   # restes d'un lecteur précédent
  # Jellyfin : « Lire sur → Stream Box ». Le shim pilote ce lecteur par son socket (config dans
  # ~/.config/jellyfin-mpv-shim/) et ne se raccroche pas tout seul à un lecteur relancé : on le relance avec. Il
  # abandonne si le socket n'existe pas encore (l'appli Qt met plus de temps que mpv à l'ouvrir) : il l'attend.
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
      echo "$(date '+%F %T') ui.py arrêté (code $code), échec rapide n°$quick_fails" >> /tmp/stream-box-ui.log
    else
      quick_fails=0
    fi
  else
    mpv "${MPV_ARGS[@]}"
  fi
  sleep 2
done
