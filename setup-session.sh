#!/usr/bin/env bash
# Session graphique dédiée à la Stream Box, sur un utilisateur dédié « media » :
# cage (compositeur Wayland « kiosque ») + start.sh, sans Plasma.
# À lancer avec sudo depuis le compte d'admin. Retour à Plasma (compte d'admin) :
#   sudo cp /etc/plasmalogin.conf.bak-plasma /etc/plasmalogin.conf
set -euo pipefail

BOX_USER=media
BOX_HOME=/home/$BOX_USER
ADMIN_USER="${SUDO_USER:?à lancer avec sudo depuis le compte administrateur}"
SRC_HOME=$(getent passwd "$ADMIN_USER" | cut -d: -f6)

pacman -S --needed --noconfirm cage

# Utilisateur dédié, sans mot de passe utilisable (« * » et non « ! », pour que la connexion SSH par clé
# reste possible). Même clé SSH que le compte d'admin pour la maintenance : ssh media@<box>
if ! id "$BOX_USER" &> /dev/null; then
  useradd -m -s /bin/bash "$BOX_USER"
fi
usermod -p '*' "$BOX_USER"
install -d -m 700 -o "$BOX_USER" -g "$BOX_USER" "$BOX_HOME/.ssh"
install -m 600 -o "$BOX_USER" -g "$BOX_USER" "$SRC_HOME/.ssh/authorized_keys" "$BOX_HOME/.ssh/authorized_keys"

# Fichiers de la box et réglages (dernier streamer, coin et affichage du chat)
install -d -o "$BOX_USER" -g "$BOX_USER" "$BOX_HOME/stream-box" "$BOX_HOME/.local" "$BOX_HOME/.local/state"
cp "$SRC_HOME"/stream-box/{start.sh,chat_overlay.py,stream-box.lua,streamers.txt,CLAUDE.md} "$BOX_HOME/stream-box/"
if [ -d "$SRC_HOME/.local/state/stream-box" ]; then
  cp -r "$SRC_HOME/.local/state/stream-box" "$BOX_HOME/.local/state/"
fi
chown -R "$BOX_USER:$BOX_USER" "$BOX_HOME/stream-box" "$BOX_HOME/.local"
chmod +x "$BOX_HOME/stream-box/start.sh" "$BOX_HOME/stream-box/chat_overlay.py"

# streamlink dans un venv à lui (même principe que pour le compte d'admin)
sudo -u "$BOX_USER" -H bash -c '
  python3 -m venv ~/.local/share/streamlink-venv
  ~/.local/share/streamlink-venv/bin/pip install -q -U streamlink
  mkdir -p ~/.local/bin
  ln -sf ~/.local/share/streamlink-venv/bin/streamlink ~/.local/bin/streamlink
  ~/.local/bin/streamlink --version
'

# -s : garde Ctrl+Alt+F2… pour passer sur une console texte en cas de besoin
cat > /usr/share/wayland-sessions/stream-box.desktop << EOF
[Desktop Entry]
Name=Stream Box
Comment=Stream Twitch en plein écran (cage + mpv), sans bureau
Exec=cage -s -- $BOX_HOME/stream-box/start.sh
Type=Application
DesktopNames=StreamBox
EOF

[ -e /etc/plasmalogin.conf.bak-plasma ] || cp /etc/plasmalogin.conf /etc/plasmalogin.conf.bak-plasma
sed -i -e 's/^Session=.*/Session=stream-box.desktop/' -e "s/^User=.*/User=$BOX_USER/" /etc/plasmalogin.conf

echo "--- /etc/plasmalogin.conf"
cat /etc/plasmalogin.conf
echo "Session Stream Box installée pour l'utilisateur $BOX_USER. Redémarre la box pour l'utiliser."
