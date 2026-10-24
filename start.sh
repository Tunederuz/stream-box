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
# Son sur l'HDMI de la TV, si rien d'autre n'a été choisi (voir audio.py)
python3 "$DIR/audio.py"

# Lecteur permanent (mpv, ou l'appli Qt qui l'embarque) : voir player.sh
exec "$DIR/player.sh"
