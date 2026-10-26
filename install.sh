#!/usr/bin/env bash
# Stream Box: installation, or update of an existing installation (the script can be run again).
#
#   sudo bash install.sh [options]
#
# Run from an admin account, on an Arch distribution with Plasma Login or SDDM as the login manager. Creates the
# "media" user that runs the box, installs this repository and everything it needs there, and sets up the desktop-less
# session (automatic login when no keyboard is plugged in at boot).
#   --restore ARCHIVE      puts back the settings and connections saved by backup.sh
#   --city CITY            weather for the ambient screen (coordinates found through Open-Meteo)
#   --remote-url URL       companion app address shown as a QR code on the TV (the HTTPS reverse proxy's, for
#                          example; otherwise http://<box IP>:8080)
#   --streamers a,b,c      initial streamer list (otherwise: empty list, to fill from the companion app)
#   --allow-from IP        opens port 8080 (companion app) to this address if the ufw firewall is active,
#                          typically the HTTPS reverse proxy's
#   --static-ip IP/PREFIX --gateway IP [--dns IP]
#                          static IP on the active Ethernet connection (applied at the next boot)
#   --wol                  Wake-on-LAN on the active Ethernet connection (to enable in the BIOS too)
#   --skip-system          touches neither the session, nor the login manager, nor polkit, nor the network
#                          (tests, containers)
set -euo pipefail

BOX_USER=media
BOX_HOME=/home/$BOX_USER
BOX_DIR=$BOX_HOME/stream-box
SRC=$(cd "$(dirname "$0")" && pwd)
MEDIA_VENV_PACKAGES="yt-dlp[default] deno nodejs-wheel bgutil-ytdlp-pot-provider jellyfin-mpv-shim paho-mqtt segno dbus-fast"
POT_REPO=https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git

CITY="" REMOTE_URL="" STREAMERS="" SKIP_SYSTEM=0 RESTORE="" ALLOW_FROM="" STATIC_IP="" GATEWAY="" DNS="" WOL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --restore) RESTORE=$(realpath "${2:?--restore expects an archive}"); shift 2 ;;
    --city) CITY=${2:?--city expects a city name}; shift 2 ;;
    --remote-url) REMOTE_URL=${2:?--remote-url expects an address}; shift 2 ;;
    --streamers) STREAMERS=${2:?--streamers expects a list}; shift 2 ;;
    --allow-from) ALLOW_FROM=${2:?--allow-from expects an address}; shift 2 ;;
    --static-ip) STATIC_IP=${2:?--static-ip expects IP/PREFIX}; shift 2 ;;
    --gateway) GATEWAY=${2:?--gateway expects an address}; shift 2 ;;
    --dns) DNS=${2:?--dns expects an address}; shift 2 ;;
    --wol) WOL=1; shift ;;
    --skip-system) SKIP_SYSTEM=1; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { echo "Error: $*" >&2; exit 1; }
# Command as media, from its home directory (root's, where we may be, is forbidden to it)
as_box() { (cd "$BOX_HOME" && runuser -u "$BOX_USER" -- env HOME="$BOX_HOME" bash -c "$1"); }

[ "$(id -u)" -eq 0 ] || die "run with sudo"
command -v pacman > /dev/null || die "meant for an Arch distribution (pacman not found)"
[ -z "$RESTORE" ] || [ -f "$RESTORE" ] || die "archive not found: $RESTORE"
[ -z "$REMOTE_URL" ] || [[ "$REMOTE_URL" =~ ^https?:// ]] || die "--remote-url expects an http(s):// address…"
[ -z "$STATIC_IP" ] || [[ "$STATIC_IP" == */* ]] || die "--static-ip expects an address with its prefix, for example 192.168.1.50/24"
[ -z "$STATIC_IP" ] || [ -n "$GATEWAY" ] || die "--static-ip also requires --gateway"

# Login manager: automatic login goes through its .conf.d directory
DM="" DM_CONF="" DM_DIR=""
if [ "$SKIP_SYSTEM" -eq 0 ]; then
  if systemctl list-unit-files plasmalogin.service > /dev/null 2>&1 && [ -e /usr/bin/plasmalogin ]; then
    DM=plasmalogin DM_CONF=/etc/plasmalogin.conf DM_DIR=/etc/plasmalogin.conf.d
  elif [ -e /usr/bin/sddm ]; then
    DM=sddm DM_CONF=/etc/sddm.conf DM_DIR=/etc/sddm.conf.d
  else
    die "unsupported login manager (Plasma Login or SDDM expected); --skip-system to ignore it"
  fi
fi

step "System packages"
pacman -S --needed --noconfirm mpv ffmpeg grim cage wlr-randr python git curl polkit libpulse bluez bluez-utils udisks2

step "User $BOX_USER"
id "$BOX_USER" > /dev/null 2>&1 || useradd -m -s /bin/bash "$BOX_USER"
# No usable password ("*" and not "!", so that SSH key login stays possible)
usermod -p '*' "$BOX_USER"
# input group: input.py reads remotes, gamepads and keyboards at the source (/dev/input)
usermod -aG input "$BOX_USER"
ADMIN_HOME=$( [ -n "${SUDO_USER:-}" ] && getent passwd "$SUDO_USER" | cut -d: -f6 || true)
if [ -n "$ADMIN_HOME" ] && [ -f "$ADMIN_HOME/.ssh/authorized_keys" ] && [ ! -f "$BOX_HOME/.ssh/authorized_keys" ]; then
  # Same SSH key as the admin account, for maintenance: ssh media@<box>
  install -d -m 700 -o "$BOX_USER" -g "$BOX_USER" "$BOX_HOME/.ssh"
  install -m 600 -o "$BOX_USER" -g "$BOX_USER" "$ADMIN_HOME/.ssh/authorized_keys" "$BOX_HOME/.ssh/authorized_keys"
fi

step "Box code ($BOX_DIR)"
if [ "$SRC" != "$BOX_DIR" ]; then
  if [ -d "$BOX_DIR/.git" ] && [ -d "$SRC/.git" ]; then
    git -c safe.directory='*' -C "$BOX_DIR" pull --ff-only "$SRC" HEAD
  elif [ -d "$SRC/.git" ]; then
    git -c safe.directory='*' clone -q "$SRC" "$BOX_DIR"
  else   # repository downloaded as an archive, without git
    install -d "$BOX_DIR" && cp -r "$SRC"/. "$BOX_DIR"/
  fi
fi
if [ -n "$RESTORE" ]; then
  step "Restore ($RESTORE)"
  # Only the paths backup.sh saves are extracted, and never outside / (tarfile "data" filter)
  python3 -I - "$RESTORE" "$BOX_HOME" << 'PY'
import sys, tarfile
archive, home = sys.argv[1], sys.argv[2].lstrip("/")
allowed = (f"{home}/stream-box/streamers.txt", f"{home}/.local/state/stream-box", f"{home}/.config/stream-box",
           f"{home}/.config/streamlink", f"{home}/.config/jellyfin-mpv-shim", f"{home}/.local/state/wireplumber",
           "var/lib/bluetooth")
with tarfile.open(archive) as tar:
    members = [m for m in tar.getmembers() if any(m.name == a or m.name.startswith(a + "/") for a in allowed)]
    tar.extractall("/", members=members, filter="data")
print(f"{len(members)} items restored")
PY
  chown -R "$BOX_USER:$BOX_USER" "$BOX_HOME/.config" "$BOX_HOME/.local" 2> /dev/null || true
  [ -f "$BOX_DIR/streamers.txt" ] && chown "$BOX_USER:$BOX_USER" "$BOX_DIR/streamers.txt"
  if [ -d /var/lib/bluetooth ]; then
    chown -R root:root /var/lib/bluetooth && chmod 700 /var/lib/bluetooth
  fi
fi
if [ ! -f "$BOX_DIR/streamers.txt" ]; then
  cp "$BOX_DIR/streamers.example.txt" "$BOX_DIR/streamers.txt"
  [ -n "$STREAMERS" ] && tr ',' '\n' <<< "$STREAMERS" | tr -d ' ' | tr '[:upper:]' '[:lower:]' | grep . >> "$BOX_DIR/streamers.txt"
fi
chown -R "$BOX_USER:$BOX_USER" "$BOX_DIR"
chmod +x "$BOX_DIR"/*.sh "$BOX_DIR"/*.py
# These permissions are not changes for git (otherwise git pull refuses to update)
git -c safe.directory='*' -C "$BOX_DIR" config core.fileMode false 2> /dev/null || true

step "streamlink, yt-dlp, jellyfin-mpv-shim… ($BOX_USER venvs)"
as_box '
  set -e
  mkdir -p ~/.local/bin ~/.local/share ~/.local/state/stream-box
  [ -x ~/.local/share/streamlink-venv/bin/pip ] || python3 -m venv ~/.local/share/streamlink-venv
  ~/.local/share/streamlink-venv/bin/pip install -q -U pip streamlink
  # Qt Quick app embedding mpv (ui.py, player chosen in ~/.config/stream-box/player, see player.sh)
  [ -x ~/.local/share/ui-venv/bin/pip ] || python3 -m venv ~/.local/share/ui-venv
  ~/.local/share/ui-venv/bin/pip install -q -U pip PySide6-Essentials python-mpv
  [ -x ~/.local/share/media-venv/bin/pip ] || python3 -m venv ~/.local/share/media-venv
  ~/.local/share/media-venv/bin/pip install -q -U pip '"$MEDIA_VENV_PACKAGES"'
  ln -sf ~/.local/share/streamlink-venv/bin/streamlink ~/.local/bin/streamlink
  for tool in yt-dlp deno jellyfin-mpv-shim; do ln -sf ~/.local/share/media-venv/bin/$tool ~/.local/bin/$tool; done
  echo "streamlink $(~/.local/bin/streamlink --version | cut -d" " -f2), yt-dlp $(~/.local/bin/yt-dlp --version)"
'

step "YouTube anti-bot token server"
as_box '
  set -e
  export PATH="$HOME/.local/share/media-venv/bin:$PATH"
  dir=~/.local/share/bgutil-pot-provider
  want=$(pip show bgutil-ytdlp-pot-provider | awk "/^Version/{print \$2}")
  have=$(git -C "$dir" describe --tags 2>/dev/null || true)
  if [ "$want" != "$have" ]; then
    rm -rf "$dir.new"
    git clone -q --depth 1 --branch "$want" '"$POT_REPO"' "$dir.new"
    (cd "$dir.new/server" && npm ci --no-audit --no-fund --loglevel=error && npx tsc)
    rm -rf "$dir" && mv "$dir.new" "$dir"
    echo "version $want built"
  else
    echo "version $want already in place"
  fi
'

step "YouTube Cast receiver"
# cast/cast.js: the box in the Cast button of the YouTube app (versions pinned by cast/package-lock.json)
as_box '
  set -e
  export PATH="$HOME/.local/share/media-venv/bin:$PATH"
  cd ~/stream-box/cast && npm ci --omit=dev --no-audit --no-fund --loglevel=error
'

step "$BOX_USER configuration"
as_box 'install -d -m 700 ~/.config/stream-box ~/.config/jellyfin-mpv-shim'
if [ ! -f "$BOX_HOME/.config/jellyfin-mpv-shim/conf.json" ]; then
  # jellyfin-mpv-shim drives the box's mpv instead of opening its own; login to do by hand (see CLAUDE.md)
  as_box 'cat > ~/.config/jellyfin-mpv-shim/conf.json' << 'JSON'
{
  "player_name": "Stream Box",
  "enable_gui": false,
  "headless": true,
  "fullscreen": true,
  "hwdec": "auto-safe",
  "mpv_ext": true,
  "mpv_ext_start": false,
  "mpv_ext_ipc": "/tmp/stream-box-mpv.sock",
  "mpv_ext_no_ovr": true,
  "mpv_idle_quit": false
}
JSON
fi
if [ -n "$CITY" ]; then
  # City coordinates and time zone for the ambient screen weather
  CITY="$CITY" as_box 'python3 -I -' << 'PY'
import json, os, urllib.parse, urllib.request
city = os.environ["CITY"]
url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": city, "count": 1, "language": "fr"})
found = (json.load(urllib.request.urlopen(url, timeout=15)).get("results") or [None])[0]
if not found:
    raise SystemExit(f"City not found: {city}")
conf = {"city": found["name"], "latitude": found["latitude"], "longitude": found["longitude"], "timezone": found["timezone"]}
path = os.path.expanduser("~/.config/stream-box/ambient.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(conf, f, ensure_ascii=False)
print(f"weather: {found['name']} ({found.get('country', '')}), {found['latitude']:.2f}, {found['longitude']:.2f}, {found['timezone']}")
PY
fi

if [ -n "$REMOTE_URL" ]; then
  REMOTE_URL="$REMOTE_URL" as_box 'printf "%s\n" "$REMOTE_URL" > ~/.config/stream-box/remote-url'
fi

step "User services (updates, YouTube tokens, MQTT bridge)"
as_box '
  set -e
  units=~/.config/systemd/user
  mkdir -p "$units/default.target.wants" "$units/timers.target.wants"
  cp ~/stream-box/systemd/*.service ~/stream-box/systemd/*.timer "$units/"
  # Enabling without a running user manager: the links "systemctl --user enable" would create
  ln -sf "$units/stream-box-pot.service" "$units/default.target.wants/"
  ln -sf "$units/stream-box-mqtt.service" "$units/default.target.wants/"
  ln -sf "$units/stream-box-update.timer" "$units/timers.target.wants/"
'
# Box already running: reload its services right away
if systemctl --user --machine="$BOX_USER@" daemon-reload 2> /dev/null; then
  systemctl --user --machine="$BOX_USER@" restart stream-box-pot.service stream-box-mqtt.service 2> /dev/null || true
fi

if [ "$SKIP_SYSTEM" -eq 1 ]; then
  step "System part skipped (--skip-system)"
else
  step "Desktop-less session and automatic login ($DM)"
  # -s: keeps Ctrl+Alt+F2… to switch to a text console
  cat > /usr/share/wayland-sessions/stream-box.desktop << DESKTOP
[Desktop Entry]
Name=Stream Box
Comment=Full-screen Twitch stream (cage + mpv), without a desktop
Exec=env XCURSOR_PATH=$BOX_DIR/cursors XCURSOR_THEME=blank cage -s -- $BOX_DIR/start.sh
Type=Application
DesktopNames=StreamBox
DESKTOP

  # The mode (automatic login or login screen) is decided at boot depending on whether a keyboard is plugged in.
  # Root-owned copy: the service runs as root, the script must not be modifiable by media.
  install -D -m 755 -o root -g root "$BOX_DIR/boot-mode.py" /usr/local/lib/stream-box/boot-mode.py
  install -d "$DM_DIR"
  cat > /etc/systemd/system/stream-box-boot-mode.service << UNIT
[Unit]
Description=Stream Box: automatic login only without a keyboard
Before=$DM.service
After=systemd-udevd.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I /usr/local/lib/stream-box/boot-mode.py --dropin $DM_DIR/50-stream-box.conf

[Install]
WantedBy=graphical.target
UNIT
  # An [Autologin] section in the main file would take precedence over the .conf.d directory: remove it
  if [ -f "$DM_CONF" ] && grep -q '^\[Autologin\]' "$DM_CONF"; then
    [ -e "$DM_CONF.bak-stream-box" ] || cp "$DM_CONF" "$DM_CONF.bak-stream-box"
    python3 -I - "$DM_CONF" << 'PY'
import re, sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
text = re.sub(r"^\[Autologin\]\n(?:(?!\[).*\n?)*", "", text, flags=re.M)
open(path, "w", encoding="utf-8").write(text)
PY
  fi
  systemctl daemon-reload
  systemctl is-enabled --quiet "$DM.service" || systemctl enable "$DM.service" \
    || echo "Warning: $DM.service could not be enabled (another login manager already is?)" >&2
  systemctl enable stream-box-boot-mode.service
  /usr/bin/python3 -I /usr/local/lib/stream-box/boot-mode.py --dropin "$DM_DIR/50-stream-box.conf"

  step "Power off from the companion app (polkit)"
  install -d /etc/polkit-1/rules.d
  cat > /etc/polkit-1/rules.d/50-stream-box.rules << 'RULES'
// Stream Box: power off and sleep from the companion app and Home Assistant (media user)
polkit.addRule(function (action, subject) {
    if (subject.user == "media" &&
        (action.id == "org.freedesktop.login1.power-off" ||
         action.id == "org.freedesktop.login1.power-off-multiple-sessions" ||
         action.id == "org.freedesktop.login1.power-off-ignore-inhibit" ||
         action.id == "org.freedesktop.login1.suspend" ||
         action.id == "org.freedesktop.login1.suspend-multiple-sessions" ||
         action.id == "org.freedesktop.login1.suspend-ignore-inhibit" ||
         action.id == "org.freedesktop.login1.reboot" ||
         action.id == "org.freedesktop.login1.reboot-multiple-sessions" ||
         action.id == "org.freedesktop.login1.reboot-ignore-inhibit")) {
        return polkit.Result.YES;
    }
});
RULES
  chmod 644 /etc/polkit-1/rules.d/50-stream-box.rules
  # USB drives: backup and restore from the TV menu (backup.py)
  cat > /etc/polkit-1/rules.d/52-stream-box-usb.rules << 'RULES'
polkit.addRule(function (action, subject) {
    if (subject.user == "media" &&
        (action.id == "org.freedesktop.udisks2.filesystem-mount" ||
         action.id == "org.freedesktop.udisks2.filesystem-mount-other-seat" ||
         action.id == "org.freedesktop.udisks2.filesystem-unmount-others")) {
        return polkit.Result.YES;
    }
});
RULES
  chmod 644 /etc/polkit-1/rules.d/52-stream-box-usb.rules
  # SSH access enabled or disabled from the TV System menu (same files as the image)
  install -d /usr/local/lib/stream-box
  # and developer mode (sudo for media)
  for f in ssh-access dev-mode; do
    install -m 755 "$BOX_DIR/image/mkosi.extra/usr/local/lib/stream-box/$f" /usr/local/lib/stream-box/
  done
  for u in ssh dev; do
    install -m 644 "$BOX_DIR/image/mkosi.extra/usr/lib/systemd/system/stream-box-$u@.service" /etc/systemd/system/
  done
  install -m 644 "$BOX_DIR/image/mkosi.extra/etc/polkit-1/rules.d/"5[45]-stream-box-*.rules /etc/polkit-1/rules.d/
  systemctl daemon-reload

  step "Bluetooth and network"
  systemctl enable --now bluetooth.service 2> /dev/null || echo "(no Bluetooth on this machine)"
  if [ -n "$RESTORE" ]; then systemctl restart bluetooth.service 2> /dev/null || true; fi   # restored pairings
  if [ -n "$ALLOW_FROM" ]; then
    if command -v ufw > /dev/null && ufw status | grep -q "Status: active"; then
      ufw allow from "$ALLOW_FROM" to any port 8080 proto tcp
    else
      echo "ufw inactive: nothing to open for $ALLOW_FROM"
    fi
  fi
  if [ -n "$STATIC_IP" ] || [ "$WOL" -eq 1 ]; then
    command -v nmcli > /dev/null || die "--static-ip and --wol go through NetworkManager (nmcli not found)"
    CON=$(nmcli -t -f NAME,TYPE connection show --active | awk -F: '$2 == "802-3-ethernet" {print $1; exit}')
    [ -n "$CON" ] || die "no active Ethernet connection for --static-ip / --wol"
    if [ -n "$STATIC_IP" ]; then
      nmcli connection modify "$CON" ipv4.method manual ipv4.addresses "$STATIC_IP" ipv4.gateway "$GATEWAY" \
        ipv4.dns "${DNS:-$GATEWAY}"
      echo "Static IP $STATIC_IP on \"$CON\" (at the next boot)"
    fi
    if [ "$WOL" -eq 1 ]; then
      nmcli connection modify "$CON" 802-3-ethernet.wake-on-lan magic
      echo "Wake-on-LAN enabled on \"$CON\" (to enable in the BIOS too)"
    fi
  fi
fi

step "Done"
if [ "$SKIP_SYSTEM" -eq 0 ] && [ -z "$ALLOW_FROM" ] && command -v ufw > /dev/null && ufw status | grep -q "Status: active"; then
  echo "Warning: ufw is active and blocks the companion app (port 8080). Run again with --allow-from <IP> or open it."
fi
cat << END
The box is installed in $BOX_DIR. Restart the machine: with no keyboard plugged in, it boots straight to the stream.

Then, as needed (details in CLAUDE.md and docs/):
  - streamers and Twitch account: companion app, http://<box>:8080 (Settings tab)
  - HTTPS (installing the companion app on Android): reverse proxy to port 8080
  - Jellyfin: as $BOX_USER, jellyfin-mpv-shim --no-gui --server <url> --quick-connect
  - Home Assistant: ~/.config/stream-box/mqtt.json and mqtt-password for $BOX_USER (docs/home-assistant.md)
  - Wake-on-LAN: BIOS, then nmcli connection modify <connection> 802-3-ethernet.wake-on-lan magic
END
