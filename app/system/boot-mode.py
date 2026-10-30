#!/usr/bin/env python3
"""Inlet: at boot, before the login screen, picks the mode depending on whether a keyboard is plugged in.

No keyboard: automatic login of "media" into the Inlet session.
With a keyboard: no automatic login, the login screen shows up (account and session of your choice).

Run as root by stream-box-boot-mode.service, from /usr/local/lib/stream-box/ (copy that media can't modify).
--dry-run: shows the decision without changing anything. --dropin <file>: autologin file to create or remove, in the
.conf.d directory of the login manager (Plasma Login by default, or SDDM).
"""
import os, re, subprocess, sys, time

DROPIN = (sys.argv[sys.argv.index("--dropin") + 1] if "--dropin" in sys.argv
          else "/etc/plasmalogin.conf.d/50-stream-box.conf")
AUTOLOGIN = "[Autologin]\nUser=media\nSession=stream-box.desktop\n"
WAIT = 3   # seconds given to USB keyboards to show up
# Devices that claim to be a keyboard without being one (some mouse receivers): name parts to ignore
IGNORE = []
LETTER_KEYS = (16, 30, 44, 57)   # KEY_Q, KEY_A, KEY_Z, KEY_SPACE: a real keyboard has letters


def keyboards():
    found = []
    with open("/proc/bus/input/devices") as f:
        blocks = f.read().strip().split("\n\n")
    for block in blocks:
        name = re.search(r'^N: Name="(.*)"$', block, re.M)
        bits = re.search(r"^B: KEY=(.*)$", block, re.M)
        if not (name and bits):
            continue
        keys = 0
        for i, word in enumerate(reversed(bits.group(1).split())):   # bitmap in 64-bit words, most significant first
            keys |= int(word, 16) << (64 * i)
        ignored = any(s.lower() in name.group(1).lower() for s in IGNORE)
        if all(keys >> k & 1 for k in LETTER_KEYS) and not ignored:
            found.append(name.group(1))
    return found


dry_run = "--dry-run" in sys.argv
if not dry_run:
    subprocess.run(["udevadm", "settle", "--timeout=10"], check=False)
deadline = time.monotonic() + (0 if dry_run else WAIT)
while not (found := keyboards()) and time.monotonic() < deadline:
    time.sleep(0.5)

if found:
    print(f"Keyboard detected ({', '.join(found)}): login screen")
    if not dry_run:
        try:
            os.remove(DROPIN)
        except FileNotFoundError:
            pass
else:
    print("No keyboard: automatic login into Inlet")
    if not dry_run:
        os.makedirs(os.path.dirname(DROPIN), exist_ok=True)
        with open(DROPIN, "w") as f:
            f.write(AUTOLOGIN)
