#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
# streamlink est installé dans un venv, lien dans ~/.local/bin (pas forcément dans le PATH de l'autostart)
export PATH="$HOME/.local/bin:$PATH"
until getent hosts www.twitch.tv >/dev/null; do sleep 2; done

python3 "$DIR/chat_overlay.py" &
python3 "$DIR/remote.py" &   # télécommande web, port 8080

# Résolution enregistrée depuis la télécommande (« auto » par défaut : jamais de 4K à 30 Hz)
python3 "$DIR/display.py" apply

# mpv reste ouvert en permanence : stream-box.lua lance streamlink (serveur HTTP local) pour la
# chaîne choisie et affiche le menu quand la souris bouge. La boucle relance mpv s'il est fermé.
while true; do
  pkill -u "$USER" -f 'streamlink .*--player-external-http'   # restes d'un mpv précédent
  # Jellyfin : « Lire sur → Stream Box ». Le shim pilote ce mpv (config dans ~/.config/jellyfin-mpv-shim/) et ne
  # se raccroche pas tout seul à un mpv relancé : on le relance avec, il attend que le socket apparaisse
  pkill -u "$USER" -f '[j]ellyfin-mpv-shim'
  jellyfin-mpv-shim --no-gui < /dev/null > /tmp/jellyfin-shim.log 2>&1 &
  # hwdec : décodage par l'iGPU Intel (HEVC 10 bits, VP9). ytdl-format : vidéos envoyées par lien, 1440p max et
  # pas d'AV1 (l'UHD 630 ne le décode pas : tout retomberait sur le processeur). Sous-titres français et anglais,
  # manuels et automatiques, sans les traductions automatiques (« French from Arabic »… plus de 100 pistes).
  # fetch_pot : jeton anti-robot (service stream-box-pot) pour chaque requête, sans quoi YouTube bloque les sous-titres
  mpv --idle=yes --force-window=yes --fs --osc=no --cursor-autohide=4000 \
    --input-ipc-server=/tmp/stream-box-mpv.sock --script="$DIR/stream-box.lua" \
    --cache=yes --hwdec=auto-safe \
    --ytdl-format='bestvideo[height<=?1440][vcodec!^=av01]+bestaudio/best' \
    --ytdl-raw-options-append=sub-langs=fr,fr-FR,fr-orig,en,en-US,en-GB,en-orig \
    --ytdl-raw-options-append=write-subs= --ytdl-raw-options-append=write-auto-subs= \
    --ytdl-raw-options-append=cookies="$HOME/.config/stream-box/twitch-cookies.txt" \
    --ytdl-raw-options-append=extractor-args=youtube:fetch_pot=always
  sleep 2
done
