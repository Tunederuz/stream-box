#!/usr/bin/env bash
# Stream Box: builds the disk image (image/mkosi.output/stream-box.raw) in an Arch container with mkosi, without
# installing anything on the machine. Docker required; the container is privileged (mounts, systemd-repart).
#   bash image/build.sh            builds the image
#   bash image/build.sh vm         boots it in a virtual machine (QEMU, UEFI) to try it
#   bash image/build.sh xz         stream-box.raw.xz, the downloadable version
#   bash image/build.sh test       test image (stream-box-test.raw): simulated Wi-Fi, test SSH key
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
docker build -q -t stream-box-mkosi - > /dev/null << 'DOCKERFILE'
FROM archlinux:latest
RUN pacman -Syu --noconfirm --needed mkosi systemd dosfstools mtools e2fsprogs cpio zstd edk2-ovmf qemu-base \
    arch-install-scripts git python python-pefile systemd-ukify btrfs-progs xz && pacman -Scc --noconfirm
DOCKERFILE
case "${1:-build}" in
  build) docker run --rm --privileged -v "$HERE/..":/src -w /src/image stream-box-mkosi mkosi -f build ;;
  # Downloadable version: compressed (Etcher and Rufus decompress it themselves)
  xz) docker run --rm -v "$HERE/..":/src -w /src/image stream-box-mkosi \
        xz -T0 -6 -k -f -v mkosi.output/stream-box.raw ;;
  # Test SSH key: image/test-key(.pub), created on the first try, never published (.gitignore)
  test) [ -f "$HERE/test-key" ] || ssh-keygen -q -t ed25519 -N "" -C stream-box-test -f "$HERE/test-key"
        install -m 644 "$HERE/test-key.pub" "$HERE/mkosi.profiles/test/mkosi.extra/etc/ssh/stream-box-test-keys"
        docker run --rm --privileged -v "$HERE/..":/src -w /src/image stream-box-mkosi \
          mkosi --profile=test --output=stream-box-test -f build ;;
  vm) docker run --rm -it --privileged --device /dev/kvm -v "$HERE/..":/src -w /src/image stream-box-mkosi \
        mkosi vm -m 4G ;;
  *) echo "usage: $0 [build|xz|test|vm]" >&2; exit 2 ;;
esac
