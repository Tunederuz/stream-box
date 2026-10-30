#!/usr/bin/env bash
# Owlink: prepares pacman on a box installed from the image, in developer mode (sudo without password):
#   ssh media@<box>  then  bash ~/stream-box/scripts/dev-pacman.sh
# The official image deliberately has neither mirror nor keyring: no packages added outside developer mode.
set -euo pipefail
sudo -n true 2> /dev/null || { echo "Enable developer mode first (TV System menu)." >&2; exit 1; }
if ! grep -q '^Server' /etc/pacman.d/mirrorlist 2> /dev/null; then
  echo 'Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch' | sudo tee /etc/pacman.d/mirrorlist > /dev/null
  echo "Mirror: geo.mirror.pkgbuild.com"
fi
if [ ! -f /etc/pacman.d/gnupg/trustdb.gpg ]; then
  sudo pacman-key --init
  sudo pacman-key --populate archlinux
fi
sudo pacman -Sy
echo "pacman ready. Install: sudo pacman -S package; update everything: sudo pacman -Syu"
