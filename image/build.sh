#!/usr/bin/env bash
# Stream Box: builds the disk image (image/mkosi.output/stream-box.raw) in an Arch container with mkosi, without
# installing anything on the machine. Docker required; the container is privileged (mounts, systemd-repart).
#   bash image/build.sh            builds the image
#   bash image/build.sh vm         boots it in a virtual machine (QEMU, UEFI) to try it
#   bash image/build.sh xz         stream-box.raw.xz, the downloadable version
#   bash image/build.sh test       test image (stream-box-test.raw): simulated Wi-Fi, test SSH key
#   bash image/build.sh release    release files (mkosi.output/release), after build
#   VERSION=0.2.0 bash image/build.sh …   version of the image (default: from git describe)
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
docker build -q -t stream-box-mkosi - > /dev/null << 'DOCKERFILE'
FROM archlinux:latest
RUN pacman -Syu --noconfirm --needed mkosi systemd dosfstools mtools e2fsprogs cpio zstd edk2-ovmf qemu-base \
    arch-install-scripts git python python-pefile systemd-ukify btrfs-progs xz && pacman -Scc --noconfirm
DOCKERFILE
# Version of the image (os-release IMAGE_VERSION, system partition label, UKI): $VERSION (the release workflow: the tag
# without its v), otherwise from git (0.1.1-15-gabcdef: after 0.1.1, before the next one)
VERSION=${VERSION:-$(git -C "$HERE" describe --tags --match 'v[0-9]*' 2> /dev/null | sed 's/^v//')}
VERSION=${VERSION:-0.0.0}
case "${1:-build}" in
  build) docker run --rm --privileged -v "$HERE/..":/src -w /src/image stream-box-mkosi \
           mkosi --image-version="$VERSION" -f build ;;
  # Release files in mkosi.output/release: the disk image (stream-box.raw.xz, to install), the system partition and the
  # UKI for A/B updates (stream-box_<version>.root-x86-64.raw.xz, stream-box_<version>.efi: systemd-sysupdate, see
  # /usr/lib/sysupdate.d) and SHA256SUMS (signed by the workflow: SHA256SUMS.gpg)
  # (FROM=stream-box-test: the files of the test image, for update tests in a virtual machine)
  release) docker run --rm -e VERSION="$VERSION" -e FROM="${FROM:-stream-box}" -v "$HERE/..":/src \
             -w /src/image/mkosi.output stream-box-mkosi sh -euc '
        rm -rf release && mkdir release
        xz -T0 -6 -c "$FROM.raw" > release/stream-box.raw.xz
        xz -T0 -6 -c "$FROM.root-x86-64.raw" > "release/stream-box_$VERSION.root-x86-64.raw.xz"
        cp "$FROM.efi" "release/stream-box_$VERSION.efi"
        if [ -f "$FROM.manifest" ]; then cp "$FROM.manifest" "release/stream-box_$VERSION.manifest.json"; fi
        cd release && sha256sum -- * > SHA256SUMS && cat SHA256SUMS' ;;
  # Downloadable version: compressed (Etcher and Rufus decompress it themselves)
  xz) docker run --rm -v "$HERE/..":/src -w /src/image stream-box-mkosi \
        xz -T0 -6 -k -f -v mkosi.output/stream-box.raw ;;
  # Test SSH key: image/test-key(.pub), created on the first try, never published (.gitignore)
  test) [ -f "$HERE/test-key" ] || ssh-keygen -q -t ed25519 -N "" -C stream-box-test -f "$HERE/test-key"
        install -m 644 "$HERE/test-key.pub" "$HERE/mkosi.profiles/test/mkosi.extra/etc/ssh/stream-box-test-keys"
        docker run --rm --privileged -v "$HERE/..":/src -w /src/image stream-box-mkosi \
          mkosi --profile=test --output=stream-box-test --image-version="$VERSION" -f build ;;
  vm) docker run --rm -it --privileged --device /dev/kvm -v "$HERE/..":/src -w /src/image stream-box-mkosi \
        mkosi vm -m 4G ;;
  *) echo "usage: $0 [build|xz|test|vm|release]" >&2; exit 2 ;;
esac
