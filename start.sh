#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
# streamlink est installé dans un venv, lien dans ~/.local/bin (pas forcément dans le PATH de l'autostart)
export PATH="$HOME/.local/bin:$PATH"
# Réseau : on l'attend 20 s au plus. Sans réseau, la box démarre quand même : écran d'accueil, et mode configuration
# Wi-Fi (point d'accès de la box, voir netsetup.py) s'il y a une carte Wi-Fi
for _ in $(seq 10); do getent hosts www.twitch.tv > /dev/null && break; sleep 2; done

python3 "$DIR/chat_overlay.py" &
python3 "$DIR/remote.py" &   # télécommande web, port 8080

# Résolution enregistrée depuis la télécommande (« auto » par défaut : jamais de 4K à 30 Hz)
python3 "$DIR/display.py" apply
# Sortie son (voir audio.py) : la TV branchée en HDMI / DisplayPort, ou un appareil USB / Bluetooth, ou le choix fait
# dans les réglages ; suivie en continu (branchements, débranchements)
python3 "$DIR/audio.py" watch &
# Touches lues à la source (télécommandes, manettes, claviers : voir input.py) ; sans droits sur /dev/input, il
# s'arrête et les touches restent à l'appli Qt et à mpv
python3 "$DIR/input.py" &
# Récepteur YouTube Cast (cast/cast.js : la box dans le bouton Caster de l'appli YouTube), si ses modules sont
# installés (npm install dans cast/)
if [ -d "$DIR/cast/node_modules" ]; then
  NODE="$HOME/.local/share/media-venv/bin/node"; [ -x "$NODE" ] || NODE=node
  "$NODE" "$DIR/cast/cast.js" &
fi

# Lecteur permanent (mpv, ou l'appli Qt qui l'embarque) : voir player.sh
exec "$DIR/player.sh"
