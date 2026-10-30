#!/usr/bin/env bash
# Owlink: the PNGs made from assets/brand/*.svg (tools/brand/make.py writes those), in Docker (librsvg, Noto Sans for
# the name): companion app icons, boot screen of start.sh, Plymouth watermark. tools/brand/render.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
docker run --rm -v "$PWD":/r -w /r alpine:3.20 sh -euc '
  apk add -q rsvg-convert font-noto > /dev/null
  for s in 180 192 512; do rsvg-convert -w $s -h $s assets/brand/owlink-icon-maskable.svg -o web/icon-$s.png; done
  rsvg-convert -w 1920 -h 1080 assets/brand/owlink-splash.svg -o assets/boot-splash.png
  rsvg-convert -w 640 -h 330 assets/brand/owlink-watermark.svg -o image/mkosi.extra/usr/share/plymouth/themes/stream-box/watermark.png
  chown -R "$(stat -c %u:%g .)" web assets image/mkosi.extra/usr/share/plymouth'
