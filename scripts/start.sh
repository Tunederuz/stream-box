#!/usr/bin/env bash
DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"   # the repository (this script is in its scripts/)
# streamlink is installed in a venv, linked in ~/.local/bin (not necessarily in the autostart PATH)
export PATH="$HOME/.local/bin:$PATH"
# Invisible cursor for cage only (assets/cursors/blank, see the session): otherwise its pointer shows up during transitions,
# when no window covers the screen. The apps go back to the normal theme (moving mouse)
unset XCURSOR_THEME XCURSOR_PATH
# Resolution saved from the companion app ("auto" by default: never 4K at 30 Hz), first: then the boot image (the same
# as the Plymouth screen) while everything starts, otherwise ~3 s of black. ui.py removes it on its first drawn frame
# (player.sh for mpv alone), and after 30 s anyway
python3 "$DIR/app/system/display.py" apply
SPLASH_PID="${XDG_RUNTIME_DIR:-/tmp}/stream-box-splash.pid"
mpv --no-config --really-quiet --fs --no-osc --osd-level=0 --no-input-default-bindings --input-vo-keyboard=no \
    --cursor-autohide=always \
    --no-audio --image-display-duration=inf --background=color --background-color='#0b0710' \
    "$DIR/assets/boot-splash.png" > /dev/null 2>&1 &
echo $! > "$SPLASH_PID"
( sleep 30; kill "$(cat "$SPLASH_PID" 2> /dev/null)" 2> /dev/null; rm -f "$SPLASH_PID" ) &
# Network: wait for it 20 s at most. Without network, the box starts anyway: home screen, and Wi-Fi setup mode (box
# hotspot, see netsetup.py) if there is a Wi-Fi card
for _ in $(seq 10); do getent hosts www.twitch.tv > /dev/null && break; sleep 2; done

python3 "$DIR/app/player/chat_overlay.py" &
python3 "$DIR/app/player/remote.py" &   # companion app, port 8080

# Sound output (see audio.py): the TV plugged in over HDMI / DisplayPort, or a USB / Bluetooth device, or the choice
# made in the settings; followed continuously (plugs, unplugs)
python3 "$DIR/app/system/audio.py" watch &
# Keys read at the source (remotes, gamepads, keyboards: see input.py); without permissions on /dev/input, it stops
# and the keys stay with the Qt app and mpv
python3 "$DIR/app/system/input.py" &
# Permanent Bluetooth agent (btagent.py: remotes that start pairing themselves), with dbus-fast
MEDIA_PY="$HOME/.local/share/media-venv/bin/python"
"$MEDIA_PY" -c "import dbus_fast" 2> /dev/null && "$MEDIA_PY" "$DIR/app/system/btagent.py" &
# YouTube Cast receiver (cast/cast.js: the box in the Cast button of the YouTube app), if its modules are installed
# (npm install in cast/)
if [ -d "$DIR/cast/node_modules" ]; then
  NODE="$HOME/.local/share/media-venv/bin/node"; [ -x "$NODE" ] || NODE=node
  "$NODE" "$DIR/cast/cast.js" &
fi

# Permanent player (mpv, or the Qt app embedding it): see player.sh
exec "$DIR/scripts/player.sh"
