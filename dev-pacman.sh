#!/usr/bin/env bash
# Stream Box : prépare pacman sur une box installée depuis l'image, en mode développeur (sudo sans mot de passe) :
#   ssh media@<box>  puis  bash ~/stream-box/dev-pacman.sh
# L'image officielle n'a volontairement ni miroir ni trousseau de clés : pas de paquets ajoutés hors mode développeur.
set -euo pipefail
sudo -n true 2> /dev/null || { echo "Active d'abord le mode développeur (menu Système de la TV)." >&2; exit 1; }
if ! grep -q '^Server' /etc/pacman.d/mirrorlist 2> /dev/null; then
  echo 'Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch' | sudo tee /etc/pacman.d/mirrorlist > /dev/null
  echo "Miroir : geo.mirror.pkgbuild.com"
fi
if [ ! -f /etc/pacman.d/gnupg/trustdb.gpg ]; then
  sudo pacman-key --init
  sudo pacman-key --populate archlinux
fi
sudo pacman -Sy
echo "pacman prêt. Installer : sudo pacman -S paquet ; tout mettre à jour : sudo pacman -Syu"
