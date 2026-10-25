#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
# streamlink est installé dans un venv, lien dans ~/.local/bin (pas forcément dans le PATH de l'autostart)
export PATH="$HOME/.local/bin:$PATH"
# Curseur invisible pour cage seul (cursors/blank, voir la session) : sinon son pointeur apparaît pendant les
# transitions, quand aucune fenêtre ne couvre l'écran. Les applis reprennent le thème normal (souris qui bouge)
unset XCURSOR_THEME XCURSOR_PATH
# Résolution enregistrée depuis la télécommande (« auto » par défaut : jamais de 4K à 30 Hz), d'abord : puis image de
# démarrage (la même que l'écran de Plymouth) le temps que tout se lance, sinon ~3 s de noir. ui.py la retire à sa
# première image dessinée (player.sh pour mpv seul), et de toute façon au bout de 30 s
python3 "$DIR/display.py" apply
SPLASH_PID="${XDG_RUNTIME_DIR:-/tmp}/stream-box-splash.pid"
mpv --no-config --really-quiet --fs --no-osc --osd-level=0 --no-input-default-bindings --input-vo-keyboard=no \
    --cursor-autohide=always \
    --no-audio --image-display-duration=inf --background=color --background-color='#0b0710' \
    "$DIR/boot-splash.png" > /dev/null 2>&1 &
echo $! > "$SPLASH_PID"
( sleep 30; kill "$(cat "$SPLASH_PID" 2> /dev/null)" 2> /dev/null; rm -f "$SPLASH_PID" ) &
# Réseau : on l'attend 20 s au plus. Sans réseau, la box démarre quand même : écran d'accueil, et mode configuration
# Wi-Fi (point d'accès de la box, voir netsetup.py) s'il y a une carte Wi-Fi
for _ in $(seq 10); do getent hosts www.twitch.tv > /dev/null && break; sleep 2; done

python3 "$DIR/chat_overlay.py" &
python3 "$DIR/remote.py" &   # télécommande web, port 8080

# Sortie son (voir audio.py) : la TV branchée en HDMI / DisplayPort, ou un appareil USB / Bluetooth, ou le choix fait
# dans les réglages ; suivie en continu (branchements, débranchements)
python3 "$DIR/audio.py" watch &
# Touches lues à la source (télécommandes, manettes, claviers : voir input.py) ; sans droits sur /dev/input, il
# s'arrête et les touches restent à l'appli Qt et à mpv
python3 "$DIR/input.py" &
# Agent Bluetooth permanent (btagent.py : les télécommandes qui lancent elles-mêmes l'appairage), avec dbus-fast
MEDIA_PY="$HOME/.local/share/media-venv/bin/python"
"$MEDIA_PY" -c "import dbus_fast" 2> /dev/null && "$MEDIA_PY" "$DIR/btagent.py" &
# Récepteur YouTube Cast (cast/cast.js : la box dans le bouton Caster de l'appli YouTube), si ses modules sont
# installés (npm install dans cast/)
if [ -d "$DIR/cast/node_modules" ]; then
  NODE="$HOME/.local/share/media-venv/bin/node"; [ -x "$NODE" ] || NODE=node
  "$NODE" "$DIR/cast/cast.js" &
fi

# Lecteur permanent (mpv, ou l'appli Qt qui l'embarque) : voir player.sh
exec "$DIR/player.sh"
