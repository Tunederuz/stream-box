#!/usr/bin/env bash
# Stream Box : construit l'image disque (image/mkosi.output/stream-box.raw) dans un conteneur Arch avec mkosi,
# sans rien installer sur la machine. Docker requis ; le conteneur est privilégié (montages, systemd-repart).
#   bash image/build.sh            construit l'image
#   bash image/build.sh vm         la démarre dans une machine virtuelle (QEMU, UEFI) pour essayer
#   bash image/build.sh xz         stream-box.raw.xz, la version à télécharger
#   bash image/build.sh test       image de test (stream-box-test.raw) : Wi-Fi simulé, clé SSH de test
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
docker build -q -t stream-box-mkosi - > /dev/null << 'DOCKERFILE'
FROM archlinux:latest
RUN pacman -Syu --noconfirm --needed mkosi systemd dosfstools mtools e2fsprogs cpio zstd edk2-ovmf qemu-base \
    arch-install-scripts git python python-pefile systemd-ukify btrfs-progs xz && pacman -Scc --noconfirm
DOCKERFILE
case "${1:-build}" in
  build) docker run --rm --privileged -v "$HERE/..":/src -w /src/image stream-box-mkosi mkosi -f build ;;
  # Version à télécharger : compressée (Etcher et Rufus la décompressent eux-mêmes)
  xz) docker run --rm -v "$HERE/..":/src -w /src/image stream-box-mkosi \
        xz -T0 -6 -k -f -v mkosi.output/stream-box.raw ;;
  test) docker run --rm --privileged -v "$HERE/..":/src -w /src/image stream-box-mkosi \
          mkosi --profile=test --output=stream-box-test -f build ;;
  vm) docker run --rm -it --privileged --device /dev/kvm -v "$HERE/..":/src -w /src/image stream-box-mkosi \
        mkosi vm -m 4G ;;
  *) echo "usage : $0 [build|xz|test|vm]" >&2; exit 2 ;;
esac
