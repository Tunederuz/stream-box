#!/usr/bin/env python3
# Owlink logo: TV screen with owl tufts, two eyes, a signal in the middle, a link as the stand. Writes the SVG sources
# of assets/brand/ (tools/brand/render.sh then makes the PNGs from them): python3 tools/brand/make.py
# One geometry, several color sets (the mono one cuts the pupils out with a mask: true transparency).
import math, os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "brand")
def arc(r, a0, a1, cx=50, cy=18.5):
    p = lambda a: (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
    (x0, y0), (x1, y1) = p(a0), p(a1)
    return f"M{x0:.2f} {y0:.2f} A{r} {r} 0 0 1 {x1:.2f} {y1:.2f}"
SCREEN = "M12 36 L7 13 L31 26 L69 26 L93 13 L88 36 L88 64 Q88 76 76 76 L24 76 Q12 76 12 64 Z"
CHAIN = ("M45 84 L32.5 84 A6.5 6.5 0 0 0 32.5 97 L45 97 "     # left link, open toward the middle
         "M55 84 L67.5 84 A6.5 6.5 0 0 1 67.5 97 L55 97 "      # right link
         "M40 90.5 L60 90.5")                                               # the bar that joins them

def mark(p, o, e, pupil, sig, eye_holes=False, bg=None):
    """p: id prefix; o: outline/chain color; e: eyes; pupil: pupils (None: cut out); sig: signal."""
    defs = ''
    if eye_holes:
        defs = f'''
    <mask id="{p}e" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><rect width="100" height="100" fill="#fff"/><circle cx="38" cy="50" r="5.5" fill="#000"/><circle cx="62" cy="50" r="5.5" fill="#000"/></mask>'''
    eyes = (f'<g{f" mask=\"url(#{p}e)\"" if eye_holes else ""}><circle cx="36" cy="49" r="12" fill="{e}"/><circle cx="64" cy="49" r="12" fill="{e}"/></g>'
            + ("" if eye_holes else f'\n  <circle cx="38" cy="50" r="5.5" fill="{pupil}"/><circle cx="62" cy="50" r="5.5" fill="{pupil}"/>'))
    return f'''<defs>
    {defs}
  </defs>{f"""
  {bg}""" if bg else ""}
  <path d="{SCREEN}" fill="none" stroke="{o}" stroke-width="7" stroke-linejoin="round"/>
  {eyes}
  <circle cx="50" cy="18.5" r="3" fill="{sig}"/>
  <path d="{arc(7.5, -138, -42)}" fill="none" stroke="{sig}" stroke-width="5" stroke-linecap="round"/>
  <path d="{arc(13.5, -136, -44)}" fill="none" stroke="{sig}" stroke-width="5" stroke-linecap="round" stroke-opacity=".5"/>
  <path d="{CHAIN}" fill="none" stroke="{o}" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>'''

def svg(body, extra=""):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"{extra}>\n  {body}\n</svg>\n'

files = {
    "owlink-mark.svg": svg(mark("d", "#c9b8ff", "#ffb547", "#14101f", "#ffb547")),          # dark backgrounds
    "owlink-mark-light.svg": svg(mark("l", "#2a1f45", "#ffb547", "#2a1f45", "#e08a00")),    # light backgrounds
    "owlink-mono.svg": svg(mark("m", "currentColor", "currentColor", None, "currentColor", eye_holes=True)),
    # App icon: the mark on a night rounded square (Flatpak, Steam, launchers)
    "owlink-icon.svg": svg('<rect width="100" height="100" rx="22" fill="#14101f"/>\n  <g transform="translate(11 10) scale(.78)">\n  '
                           + mark("i", "#c9b8ff", "#ffb547", "#14101f", "#ffb547") + "\n  </g>"),
    # Companion app icon (Android masks it into a circle or a squircle: full-bleed square, the mark in the safe zone)
    "owlink-icon-maskable.svg": svg('<rect width="100" height="100" fill="#14101f"/>\n  <g transform="translate(20 19) scale(.6)">\n  '
                                    + mark("k", "#c9b8ff", "#ffb547", "#14101f", "#ffb547") + "\n  </g>"),
    # Boot screen (start.sh, 1920 × 1080) and the Plymouth watermark (640 × 330): the mark and the name
    "owlink-splash.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">\n  <rect width="1920" height="1080" fill="#0b0710"/>\n'
        '  <g transform="translate(850 300) scale(2.2)">\n  ' + mark("s", "#c9b8ff", "#ffb547", "#0b0710", "#ffb547") + '\n  </g>\n'
        '  <text x="960" y="600" text-anchor="middle" font-family="Noto Sans, sans-serif" font-weight="700" font-size="64" fill="#ffffff">Owlink</text>\n</svg>\n',
    "owlink-watermark.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 330">\n'
        '  <g transform="translate(210 0) scale(2.2)">\n  ' + mark("w", "#c9b8ff", "#ffb547", "#0b0710", "#ffb547") + '\n  </g>\n'
        '  <text x="320" y="300" text-anchor="middle" font-family="Noto Sans, sans-serif" font-weight="700" font-size="64" fill="#ffffff">Owlink</text>\n</svg>\n',
    # Favicon (16-32 px): thicker screen, eyes without pupils, the signal reduced to a dot and one wave, no chain
    "owlink-favicon.svg": svg('''<rect width="100" height="100" rx="20" fill="#14101f"/>
  <path d="M12 44 L6 18 L30 32 L70 32 L94 18 L88 44 L88 74 Q88 90 72 90 L28 90 Q12 90 12 74 Z" fill="none" stroke="#c9b8ff" stroke-width="11" stroke-linejoin="round"/>
  <circle cx="36" cy="60" r="12" fill="#ffb547"/><circle cx="64" cy="60" r="12" fill="#ffb547"/>
  <circle cx="50" cy="17" r="5" fill="#ffb547"/>
  <path d="''' + arc(13, -140, -40, 50, 19) + '''" fill="none" stroke="#ffb547" stroke-width="7" stroke-linecap="round"/>'''),
}
for name, content in files.items():
    with open(os.path.join(OUT, name), "w") as f:
        f.write(content)
