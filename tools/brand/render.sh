#!/usr/bin/env bash
# Inlet: the PNGs made from assets/brand/*.svg (tools/brand/make.py writes those), in Docker (librsvg, the Jost font for
# the name): companion app icons, boot screen of start.sh, Plymouth watermark. tools/brand/render.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
docker run --rm -v "$PWD":/r -w /r alpine:3.20 sh -euc '
  apk add -q rsvg-convert fontconfig > /dev/null
  mkdir -p /usr/share/fonts/jost
  wget -q -O /usr/share/fonts/jost/Jost.ttf "https://github.com/google/fonts/raw/main/ofl/jost/Jost%5Bwght%5D.ttf"
  fc-cache -f > /dev/null
  for s in 180 192 512; do rsvg-convert -w $s -h $s assets/brand/inlet-icon-maskable.svg -o web/icon-$s.png; done
  rsvg-convert -w 1920 -h 1080 assets/brand/inlet-splash.svg -o assets/boot-splash.png
  rsvg-convert -w 640 -h 330 assets/brand/inlet-watermark.svg -o image/mkosi.extra/usr/share/plymouth/themes/stream-box/watermark.png
  chown -R "$(stat -c %u:%g .)" web assets image/mkosi.extra/usr/share/plymouth'
