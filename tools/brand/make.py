#!/usr/bin/env python3
# Inlet logo: a screen open on its left side, a wave flowing into it. Writes the SVG sources of assets/brand/
# (tools/brand/render.sh then makes the PNGs from them): python3 tools/brand/make.py
import os, sys
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "brand")
INK_DARK, INK_LIGHT, WATER, WATER_DEEP, NIGHT = "#e8eef0", "#142026", "#6fc3d9", "#1c7a93", "#101417"
SCREEN = "M36 22 H74 A14 14 0 0 1 88 36 V64 A14 14 0 0 1 74 78 H36"      # open on the left
WAVE = "M10 50 Q19.5 39 29 50 T48 50 T67 50"                             # three half-waves, ends inside

def mark(ink, water, w=8):
    return (f'<path d="{SCREEN}" stroke="{ink}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round" fill="none"/>\n'
            f'  <path d="{WAVE}" stroke="{water}" stroke-width="{w}" stroke-linecap="round" fill="none"/>')

# The name, lowercase, in Jost (render.sh installs it to draw the PNGs)
WORD = ('<text x="{x}" y="{y}" text-anchor="middle" font-family="Jost, sans-serif" font-weight="500" font-size="80" '
        f'letter-spacing="2.4" fill="{INK_DARK}">inlet</text>')

def svg(body, vb="0 0 100 100"):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">\n  {body}\n</svg>\n'

files = {
    "inlet-mark.svg": svg(mark(INK_DARK, WATER)),                  # dark backgrounds (TV)
    "inlet-mark-light.svg": svg(mark(INK_LIGHT, WATER_DEEP)),      # light backgrounds
    "inlet-mono.svg": svg(mark("currentColor", "currentColor")),   # one color
    # App icon: night rounded square, the mark inside
    "inlet-icon.svg": svg(f'<rect width="100" height="100" rx="22" fill="{NIGHT}"/>\n  <g transform="translate(14 14) scale(.72)">\n  '
                          + mark(INK_DARK, WATER, 9) + "\n  </g>"),
    # Companion app (Android masks it): full-bleed square, the mark in the safe zone
    "inlet-icon-maskable.svg": svg(f'<rect width="100" height="100" fill="{NIGHT}"/>\n  <g transform="translate(20 20) scale(.6)">\n  '
                                   + mark(INK_DARK, WATER, 9) + "\n  </g>"),
    # 16-32 px: thicker strokes, the wave reduced to two half-waves
    "inlet-favicon.svg": svg(f'<rect width="100" height="100" rx="20" fill="{NIGHT}"/>\n  '
                             '<path d="M40 18 H72 A16 16 0 0 1 88 34 V66 A16 16 0 0 1 72 82 H40" stroke="#e8eef0" stroke-width="13" stroke-linecap="round" fill="none"/>\n  '
                             '<path d="M12 50 Q24 36 36 50 T60 50" stroke="#6fc3d9" stroke-width="13" stroke-linecap="round" fill="none"/>'),
    # Boot screen of start.sh (1920 × 1080) and the Plymouth watermark (640 × 330): the mark and the name, on the home
    # screen's background (#0b0710, the same in the Plymouth script)
    "inlet-splash.svg": svg('<rect width="1920" height="1080" fill="#0b0710"/>\n  <g transform="translate(850 290) scale(2.2)">\n  '
                            + mark(INK_DARK, WATER) + '\n  </g>\n  ' + WORD.format(x=960, y=610), "0 0 1920 1080"),
    "inlet-watermark.svg": svg('<g transform="translate(210 0) scale(2.2)">\n  ' + mark(INK_DARK, WATER) + '\n  </g>\n  '
                               + WORD.format(x=320, y=310), "0 0 640 330"),
}
os.makedirs(OUT, exist_ok=True)
for name, content in files.items():
    with open(os.path.join(OUT, name), "w") as f:
        f.write(content)
