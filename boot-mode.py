#!/usr/bin/env python3
"""Stream Box : au démarrage, avant l'écran de connexion, choisit le mode selon qu'un clavier est branché.

Sans clavier : connexion automatique de « media » dans la session Stream Box.
Avec clavier : pas de connexion automatique, l'écran de connexion s'affiche (compte et session au choix).

Lancé en root par stream-box-boot-mode.service, depuis /usr/local/lib/stream-box/ (copie non modifiable
par media). --dry-run : affiche la décision sans rien changer. --dropin <fichier> : fichier d'autologin à créer ou
supprimer, dans le dossier .conf.d du gestionnaire de connexion (Plasma Login par défaut, ou SDDM).
"""
import os, re, subprocess, sys, time

DROPIN = (sys.argv[sys.argv.index("--dropin") + 1] if "--dropin" in sys.argv
          else "/etc/plasmalogin.conf.d/50-stream-box.conf")
AUTOLOGIN = "[Autologin]\nUser=media\nSession=stream-box.desktop\n"
WAIT = 3   # secondes laissées aux claviers USB pour apparaître
# Périphériques qui se déclarent clavier sans en être un (certains récepteurs de souris) : morceaux de nom à ignorer
IGNORE = []
LETTER_KEYS = (16, 30, 44, 57)   # KEY_Q, KEY_A, KEY_Z, KEY_SPACE : un vrai clavier a des lettres


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
        for i, word in enumerate(reversed(bits.group(1).split())):   # bitmap en mots de 64 bits, poids fort d'abord
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
    print(f"Clavier détecté ({', '.join(found)}) : écran de connexion")
    if not dry_run:
        try:
            os.remove(DROPIN)
        except FileNotFoundError:
            pass
else:
    print("Pas de clavier : connexion automatique dans la Stream Box")
    if not dry_run:
        os.makedirs(os.path.dirname(DROPIN), exist_ok=True)
        with open(DROPIN, "w") as f:
            f.write(AUTOLOGIN)
