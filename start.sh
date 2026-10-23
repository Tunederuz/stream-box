#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
# streamlink est installé dans un venv, lien dans ~/.local/bin (pas forcément dans le PATH de l'autostart)
export PATH="$HOME/.local/bin:$PATH"
until getent hosts www.twitch.tv >/dev/null; do sleep 2; done

python3 "$DIR/chat_overlay.py" &
python3 "$DIR/remote.py" &   # télécommande web, port 8080

# Résolution enregistrée depuis la télécommande (« auto » par défaut : jamais de 4K à 30 Hz)
python3 "$DIR/display.py" apply
# Son sur l'HDMI de la TV, si rien d'autre n'a été choisi (voir audio.py)
python3 "$DIR/audio.py"

# Format des vidéos envoyées par lien (yt-dlp). Par défaut 1440p maximum et pas d'AV1, que beaucoup d'iGPU ne décodent
# pas en matériel (tout retomberait sur le processeur) ; une autre règle peut être mise dans ce fichier.
YTDL_FORMAT='bestvideo[height<=?1440][vcodec!^=av01]+bestaudio/best'
[ -s "$HOME/.config/stream-box/ytdl-format" ] && YTDL_FORMAT=$(head -1 "$HOME/.config/stream-box/ytdl-format")

# mpv reste ouvert en permanence : stream-box.lua lance streamlink (serveur HTTP local) pour la
# chaîne choisie et affiche le menu quand la souris bouge. La boucle relance mpv s'il est fermé.
while true; do
  pkill -u "$USER" -f 'streamlink .*--player-external-http'   # restes d'un mpv précédent
  # Jellyfin : « Lire sur → Stream Box ». Le shim pilote ce mpv (config dans ~/.config/jellyfin-mpv-shim/) et ne
  # se raccroche pas tout seul à un mpv relancé : on le relance avec, il attend que le socket apparaisse
  pkill -u "$USER" -f '[j]ellyfin-mpv-shim'
  jellyfin-mpv-shim --no-gui < /dev/null > /tmp/jellyfin-shim.log 2>&1 &
  # hwdec : décodage matériel quand il est sûr (VA-API, NVDEC…). Sous-titres français et anglais,
  # manuels et automatiques, sans les traductions automatiques (« French from Arabic »… plus de 100 pistes).
  # player_client : le client TV choisi par défaut reçoit des flux refusés (403) ; tv_simply et android_vr passent.
  # fetch_pot : jeton anti-robot (service stream-box-pot) pour chaque requête, sans quoi YouTube bloque les sous-titres
  mpv --idle=yes --force-window=yes --fs --osc=no --cursor-autohide=4000 \
    --input-ipc-server=/tmp/stream-box-mpv.sock --script="$DIR/stream-box.lua" --script="$DIR/tv_menu.lua" \
    --cache=yes --hwdec=auto-safe \
    --ytdl-format="$YTDL_FORMAT" \
    --ytdl-raw-options-append=sub-langs=fr,fr-FR,fr-orig,en,en-US,en-GB,en-orig \
    --ytdl-raw-options-append=write-subs= --ytdl-raw-options-append=write-auto-subs= \
    --ytdl-raw-options-append=cookies="$HOME/.config/stream-box/twitch-cookies.txt" \
    --ytdl-raw-options-append='extractor-args=youtube:player_client=tv_simply,android_vr;fetch_pot=always'
  sleep 2
done
