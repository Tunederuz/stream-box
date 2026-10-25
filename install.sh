#!/usr/bin/env bash
# Stream Box : installation, ou mise à jour d'une installation existante (le script peut être relancé).
#
#   sudo bash install.sh [options]
#
# À lancer depuis un compte d'admin, sur une distribution Arch avec Plasma Login ou SDDM comme gestionnaire de
# connexion. Crée l'utilisateur « media » qui fait tourner la box, y installe ce dépôt et tout ce dont il a besoin,
# et met en place la session sans bureau (connexion automatique quand aucun clavier n'est branché au démarrage).
#   --restore ARCHIVE      remet les réglages et connexions sauvegardés par backup.sh
#   --city VILLE           météo de l'écran d'ambiance (coordonnées trouvées par Open-Meteo)
#   --remote-url URL       adresse de la télécommande web montrée en QR code sur la TV (celle du reverse proxy
#                          HTTPS, par exemple ; sinon http://<IP de la box>:8080)
#   --streamers a,b,c      liste de départ des streamers (sinon : liste vide, à remplir depuis la télécommande web)
#   --allow-from IP        ouvre le port 8080 (télécommande web) à cette adresse si le pare-feu ufw est actif,
#                          typiquement celle du reverse proxy HTTPS
#   --static-ip IP/PRÉFIXE --gateway IP [--dns IP]
#                          IP fixe sur la connexion Ethernet active (appliquée au prochain démarrage)
#   --wol                  Wake-on-LAN sur la connexion Ethernet active (à activer aussi dans le BIOS)
#   --skip-system          ne touche ni à la session, ni au gestionnaire de connexion, ni à polkit, ni au réseau
#                          (tests, conteneurs)
set -euo pipefail

BOX_USER=media
BOX_HOME=/home/$BOX_USER
BOX_DIR=$BOX_HOME/stream-box
SRC=$(cd "$(dirname "$0")" && pwd)
MEDIA_VENV_PACKAGES="yt-dlp[default] deno nodejs-wheel bgutil-ytdlp-pot-provider jellyfin-mpv-shim paho-mqtt segno"
POT_REPO=https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git

CITY="" REMOTE_URL="" STREAMERS="" SKIP_SYSTEM=0 RESTORE="" ALLOW_FROM="" STATIC_IP="" GATEWAY="" DNS="" WOL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --restore) RESTORE=$(realpath "${2:?--restore attend une archive}"); shift 2 ;;
    --city) CITY=${2:?--city attend un nom de ville}; shift 2 ;;
    --remote-url) REMOTE_URL=${2:?--remote-url attend une adresse}; shift 2 ;;
    --streamers) STREAMERS=${2:?--streamers attend une liste}; shift 2 ;;
    --allow-from) ALLOW_FROM=${2:?--allow-from attend une adresse}; shift 2 ;;
    --static-ip) STATIC_IP=${2:?--static-ip attend IP/PRÉFIXE}; shift 2 ;;
    --gateway) GATEWAY=${2:?--gateway attend une adresse}; shift 2 ;;
    --dns) DNS=${2:?--dns attend une adresse}; shift 2 ;;
    --wol) WOL=1; shift ;;
    --skip-system) SKIP_SYSTEM=1; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Option inconnue : $1 (voir --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { echo "Erreur : $*" >&2; exit 1; }
# Commande en tant que media, depuis son dossier (celui de root, où l'on est peut-être, lui est interdit)
as_box() { (cd "$BOX_HOME" && runuser -u "$BOX_USER" -- env HOME="$BOX_HOME" bash -c "$1"); }

[ "$(id -u)" -eq 0 ] || die "à lancer avec sudo"
command -v pacman > /dev/null || die "pensé pour une distribution Arch (pacman introuvable)"
[ -z "$RESTORE" ] || [ -f "$RESTORE" ] || die "archive introuvable : $RESTORE"
[ -z "$REMOTE_URL" ] || [[ "$REMOTE_URL" =~ ^https?:// ]] || die "--remote-url attend une adresse http(s)://…"
[ -z "$STATIC_IP" ] || [[ "$STATIC_IP" == */* ]] || die "--static-ip attend une adresse avec son préfixe, par exemple 192.168.1.50/24"
[ -z "$STATIC_IP" ] || [ -n "$GATEWAY" ] || die "--static-ip demande aussi --gateway"

# Gestionnaire de connexion : la connexion automatique passe par son dossier .conf.d
DM="" DM_CONF="" DM_DIR=""
if [ "$SKIP_SYSTEM" -eq 0 ]; then
  if systemctl list-unit-files plasmalogin.service > /dev/null 2>&1 && [ -e /usr/bin/plasmalogin ]; then
    DM=plasmalogin DM_CONF=/etc/plasmalogin.conf DM_DIR=/etc/plasmalogin.conf.d
  elif [ -e /usr/bin/sddm ]; then
    DM=sddm DM_CONF=/etc/sddm.conf DM_DIR=/etc/sddm.conf.d
  else
    die "gestionnaire de connexion non pris en charge (Plasma Login ou SDDM attendu) ; --skip-system pour l'ignorer"
  fi
fi

step "Paquets système"
pacman -S --needed --noconfirm mpv ffmpeg grim cage wlr-randr python git curl polkit libpulse bluez bluez-utils udisks2

step "Utilisateur $BOX_USER"
id "$BOX_USER" > /dev/null 2>&1 || useradd -m -s /bin/bash "$BOX_USER"
# Pas de mot de passe utilisable (« * » et non « ! », pour que la connexion SSH par clé reste possible)
usermod -p '*' "$BOX_USER"
# Groupe input : input.py lit les télécommandes, manettes et claviers à la source (/dev/input)
usermod -aG input "$BOX_USER"
ADMIN_HOME=$( [ -n "${SUDO_USER:-}" ] && getent passwd "$SUDO_USER" | cut -d: -f6 || true)
if [ -n "$ADMIN_HOME" ] && [ -f "$ADMIN_HOME/.ssh/authorized_keys" ] && [ ! -f "$BOX_HOME/.ssh/authorized_keys" ]; then
  # Même clé SSH que le compte d'admin, pour la maintenance : ssh media@<box>
  install -d -m 700 -o "$BOX_USER" -g "$BOX_USER" "$BOX_HOME/.ssh"
  install -m 600 -o "$BOX_USER" -g "$BOX_USER" "$ADMIN_HOME/.ssh/authorized_keys" "$BOX_HOME/.ssh/authorized_keys"
fi

step "Code de la box ($BOX_DIR)"
if [ "$SRC" != "$BOX_DIR" ]; then
  if [ -d "$BOX_DIR/.git" ] && [ -d "$SRC/.git" ]; then
    git -c safe.directory='*' -C "$BOX_DIR" pull --ff-only "$SRC" HEAD
  elif [ -d "$SRC/.git" ]; then
    git -c safe.directory='*' clone -q "$SRC" "$BOX_DIR"
  else   # dépôt téléchargé en archive, sans git
    install -d "$BOX_DIR" && cp -r "$SRC"/. "$BOX_DIR"/
  fi
fi
if [ -n "$RESTORE" ]; then
  step "Restauration ($RESTORE)"
  # Seuls les chemins que backup.sh sauvegarde sont extraits, et jamais en dehors de / (filtre « data » de tarfile)
  python3 -I - "$RESTORE" "$BOX_HOME" << 'PY'
import sys, tarfile
archive, home = sys.argv[1], sys.argv[2].lstrip("/")
allowed = (f"{home}/stream-box/streamers.txt", f"{home}/.local/state/stream-box", f"{home}/.config/stream-box",
           f"{home}/.config/streamlink", f"{home}/.config/jellyfin-mpv-shim", f"{home}/.local/state/wireplumber",
           "var/lib/bluetooth")
with tarfile.open(archive) as tar:
    members = [m for m in tar.getmembers() if any(m.name == a or m.name.startswith(a + "/") for a in allowed)]
    tar.extractall("/", members=members, filter="data")
print(f"{len(members)} éléments restaurés")
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

step "streamlink, yt-dlp, jellyfin-mpv-shim… (venvs de $BOX_USER)"
as_box '
  set -e
  mkdir -p ~/.local/bin ~/.local/share ~/.local/state/stream-box
  [ -x ~/.local/share/streamlink-venv/bin/pip ] || python3 -m venv ~/.local/share/streamlink-venv
  ~/.local/share/streamlink-venv/bin/pip install -q -U pip streamlink
  # Appli Qt Quick qui embarque mpv (ui.py, lecteur choisi dans ~/.config/stream-box/player, voir player.sh)
  [ -x ~/.local/share/ui-venv/bin/pip ] || python3 -m venv ~/.local/share/ui-venv
  ~/.local/share/ui-venv/bin/pip install -q -U pip PySide6-Essentials python-mpv
  [ -x ~/.local/share/media-venv/bin/pip ] || python3 -m venv ~/.local/share/media-venv
  ~/.local/share/media-venv/bin/pip install -q -U pip '"$MEDIA_VENV_PACKAGES"'
  ln -sf ~/.local/share/streamlink-venv/bin/streamlink ~/.local/bin/streamlink
  for tool in yt-dlp deno jellyfin-mpv-shim; do ln -sf ~/.local/share/media-venv/bin/$tool ~/.local/bin/$tool; done
  echo "streamlink $(~/.local/bin/streamlink --version | cut -d" " -f2), yt-dlp $(~/.local/bin/yt-dlp --version)"
'

step "Serveur de jetons anti-robot YouTube"
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
    echo "version $want compilée"
  else
    echo "version $want déjà en place"
  fi
'

step "Récepteur YouTube Cast"
# cast/cast.js : la box dans le bouton Caster de l'appli YouTube (versions figées par cast/package-lock.json)
as_box '
  set -e
  export PATH="$HOME/.local/share/media-venv/bin:$PATH"
  cd ~/stream-box/cast && npm ci --omit=dev --no-audit --no-fund --loglevel=error
'

step "Configuration de $BOX_USER"
as_box 'install -d -m 700 ~/.config/stream-box ~/.config/jellyfin-mpv-shim'
if [ ! -f "$BOX_HOME/.config/jellyfin-mpv-shim/conf.json" ]; then
  # jellyfin-mpv-shim pilote le mpv de la box au lieu d'ouvrir le sien ; connexion à faire à la main (voir CLAUDE.md)
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
  # Coordonnées et fuseau de la ville pour la météo de l'écran d'ambiance
  CITY="$CITY" as_box 'python3 -I -' << 'PY'
import json, os, urllib.parse, urllib.request
city = os.environ["CITY"]
url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": city, "count": 1, "language": "fr"})
found = (json.load(urllib.request.urlopen(url, timeout=15)).get("results") or [None])[0]
if not found:
    raise SystemExit(f"Ville introuvable : {city}")
conf = {"city": found["name"], "latitude": found["latitude"], "longitude": found["longitude"], "timezone": found["timezone"]}
path = os.path.expanduser("~/.config/stream-box/ambient.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(conf, f, ensure_ascii=False)
print(f"météo : {found['name']} ({found.get('country', '')}), {found['latitude']:.2f}, {found['longitude']:.2f}, {found['timezone']}")
PY
fi

if [ -n "$REMOTE_URL" ]; then
  REMOTE_URL="$REMOTE_URL" as_box 'printf "%s\n" "$REMOTE_URL" > ~/.config/stream-box/remote-url'
fi

step "Services utilisateur (mises à jour, jetons YouTube, pont MQTT)"
as_box '
  set -e
  units=~/.config/systemd/user
  mkdir -p "$units/default.target.wants" "$units/timers.target.wants"
  cp ~/stream-box/systemd/*.service ~/stream-box/systemd/*.timer "$units/"
  # Activation sans gestionnaire utilisateur en marche : les liens que créerait « systemctl --user enable »
  ln -sf "$units/stream-box-pot.service" "$units/default.target.wants/"
  ln -sf "$units/stream-box-mqtt.service" "$units/default.target.wants/"
  ln -sf "$units/stream-box-update.timer" "$units/timers.target.wants/"
'
# Box déjà en service : on recharge ses services tout de suite
if systemctl --user --machine="$BOX_USER@" daemon-reload 2> /dev/null; then
  systemctl --user --machine="$BOX_USER@" restart stream-box-pot.service stream-box-mqtt.service 2> /dev/null || true
fi

if [ "$SKIP_SYSTEM" -eq 1 ]; then
  step "Partie système ignorée (--skip-system)"
else
  step "Session sans bureau et connexion automatique ($DM)"
  # -s : garde Ctrl+Alt+F2… pour passer sur une console texte
  cat > /usr/share/wayland-sessions/stream-box.desktop << DESKTOP
[Desktop Entry]
Name=Stream Box
Comment=Stream Twitch en plein écran (cage + mpv), sans bureau
Exec=cage -s -- $BOX_DIR/start.sh
Type=Application
DesktopNames=StreamBox
DESKTOP

  # Le mode (connexion automatique ou écran de connexion) se décide au démarrage selon qu'un clavier est branché.
  # Copie en root : le service tourne en root, le script ne doit pas être modifiable par media.
  install -D -m 755 -o root -g root "$BOX_DIR/boot-mode.py" /usr/local/lib/stream-box/boot-mode.py
  install -d "$DM_DIR"
  cat > /etc/systemd/system/stream-box-boot-mode.service << UNIT
[Unit]
Description=Stream Box : connexion automatique seulement sans clavier
Before=$DM.service
After=systemd-udevd.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I /usr/local/lib/stream-box/boot-mode.py --dropin $DM_DIR/50-stream-box.conf

[Install]
WantedBy=graphical.target
UNIT
  # Une section [Autologin] dans le fichier principal passerait avant le dossier .conf.d : on la retire
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
    || echo "Attention : $DM.service n'a pas pu être activé (un autre gestionnaire de connexion l'est déjà ?)" >&2
  systemctl enable stream-box-boot-mode.service
  /usr/bin/python3 -I /usr/local/lib/stream-box/boot-mode.py --dropin "$DM_DIR/50-stream-box.conf"

  step "Extinction depuis la télécommande web (polkit)"
  install -d /etc/polkit-1/rules.d
  cat > /etc/polkit-1/rules.d/50-stream-box.rules << 'RULES'
// Stream Box : extinction et mise en veille depuis la télécommande et Home Assistant (utilisateur media)
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
  # Clés USB : sauvegarde et restauration depuis le menu de la TV (backup.py)
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
  # Accès SSH activé ou coupé depuis le menu Système de la TV (mêmes fichiers que l'image)
  install -m 644 "$BOX_DIR/image/mkosi.extra/usr/lib/systemd/system/stream-box-ssh@.service" /etc/systemd/system/
  install -m 644 "$BOX_DIR/image/mkosi.extra/etc/polkit-1/rules.d/54-stream-box-ssh.rules" /etc/polkit-1/rules.d/
  systemctl daemon-reload

  step "Bluetooth et réseau"
  systemctl enable --now bluetooth.service 2> /dev/null || echo "(pas de Bluetooth sur cette machine)"
  if [ -n "$RESTORE" ]; then systemctl restart bluetooth.service 2> /dev/null || true; fi   # appairages restaurés
  if [ -n "$ALLOW_FROM" ]; then
    if command -v ufw > /dev/null && ufw status | grep -q "Status: active"; then
      ufw allow from "$ALLOW_FROM" to any port 8080 proto tcp
    else
      echo "ufw inactif : rien à ouvrir pour $ALLOW_FROM"
    fi
  fi
  if [ -n "$STATIC_IP" ] || [ "$WOL" -eq 1 ]; then
    command -v nmcli > /dev/null || die "--static-ip et --wol passent par NetworkManager (nmcli introuvable)"
    CON=$(nmcli -t -f NAME,TYPE connection show --active | awk -F: '$2 == "802-3-ethernet" {print $1; exit}')
    [ -n "$CON" ] || die "aucune connexion Ethernet active pour --static-ip / --wol"
    if [ -n "$STATIC_IP" ]; then
      nmcli connection modify "$CON" ipv4.method manual ipv4.addresses "$STATIC_IP" ipv4.gateway "$GATEWAY" \
        ipv4.dns "${DNS:-$GATEWAY}"
      echo "IP fixe $STATIC_IP sur « $CON » (au prochain démarrage)"
    fi
    if [ "$WOL" -eq 1 ]; then
      nmcli connection modify "$CON" 802-3-ethernet.wake-on-lan magic
      echo "Wake-on-LAN activé sur « $CON » (à activer aussi dans le BIOS)"
    fi
  fi
fi

step "Terminé"
if [ "$SKIP_SYSTEM" -eq 0 ] && [ -z "$ALLOW_FROM" ] && command -v ufw > /dev/null && ufw status | grep -q "Status: active"; then
  echo "Attention : ufw est actif et bloque la télécommande web (port 8080). Relance avec --allow-from <IP> ou ouvre-le."
fi
cat << END
La box est installée dans $BOX_DIR. Redémarre la machine : sans clavier branché, elle démarre directement sur le stream.

Ensuite, selon les besoins (détails dans CLAUDE.md et docs/) :
  - streamers et compte Twitch : télécommande web, http://<box>:8080 (onglet Réglages)
  - HTTPS (installation de la télécommande sur Android) : reverse proxy vers le port 8080
  - Jellyfin : en tant que $BOX_USER, jellyfin-mpv-shim --no-gui --server <url> --quick-connect
  - Home Assistant : ~/.config/stream-box/mqtt.json et mqtt-password chez $BOX_USER (docs/home-assistant.md)
  - Wake-on-LAN : BIOS, puis nmcli connection modify <connexion> 802-3-ethernet.wake-on-lan magic
END
