#!/usr/bin/env bash
# Builds the Owlink app Flatpak in Docker (nothing installed on the host): flatpak/build.sh [output folder]
# → Owlink.flatpak (bundle to install with `flatpak install --user Owlink.flatpak`). Runtime, SDK and
# build cache in ~/.cache/stream-box-flatpak (kept between builds).
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$PWD
OUT=$(readlink -f "${1:-$HOME/.cache/stream-box-flatpak/out}")
CACHE=$HOME/.cache/stream-box-flatpak
mkdir -p "$OUT" "$CACHE/system" "$CACHE/build"
docker build -q -t stream-box-flatpak flatpak > /dev/null
# --privileged: flatpak-builder isolates each build step with bubblewrap
docker run --rm --privileged -v "$CACHE/system":/var/lib/flatpak -v "$CACHE/build":/build -v "$REPO":/src:ro \
  -v "$OUT":/out stream-box-flatpak sh -euc '
    flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
    cd /build
    flatpak-builder --force-clean --disable-rofiles-fuse --install-deps-from=flathub --state-dir=/build/state \
      --repo=/build/repo /build/app /src/flatpak/io.github.tunederuz.Owlink.yml
    flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo /build/repo \
      /out/Owlink.flatpak io.github.tunederuz.Owlink
    chown -R "$(stat -c %u:%g /out)" /out'
echo "$OUT/Owlink.flatpak"
