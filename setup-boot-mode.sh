#!/usr/bin/env bash
# Stream Box : autologin seulement quand aucun clavier n'est branché au démarrage.
# À lancer avec sudo depuis le compte d'admin. Pour revenir à l'autologin permanent :
#   sudo systemctl disable stream-box-boot-mode.service
#   sudo cp /etc/plasmalogin.conf.bak-stream-box /etc/plasmalogin.conf
set -euo pipefail

# Copie en root : le service tourne en root, le script ne doit pas être modifiable par media
install -D -m 755 -o root -g root /home/media/stream-box/boot-mode.py /usr/local/lib/stream-box/boot-mode.py

cat > /etc/systemd/system/stream-box-boot-mode.service << 'EOF'
[Unit]
Description=Stream Box : connexion automatique seulement sans clavier
Before=plasmalogin.service
After=systemd-udevd.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I /usr/local/lib/stream-box/boot-mode.py

[Install]
WantedBy=graphical.target
EOF

# L'autologin quitte le fichier principal (il passerait avant le dossier .conf.d) : c'est le service qui le gère
[ -e /etc/plasmalogin.conf.bak-stream-box ] || cp /etc/plasmalogin.conf /etc/plasmalogin.conf.bak-stream-box
printf '# Autologin géré au démarrage par stream-box-boot-mode.service\n# (/etc/plasmalogin.conf.d/50-stream-box.conf, présent seulement sans clavier)\n' > /etc/plasmalogin.conf

systemctl daemon-reload
systemctl enable stream-box-boot-mode.service
/usr/bin/python3 -I /usr/local/lib/stream-box/boot-mode.py   # applique tout de suite selon ce qui est branché
echo "--- /etc/plasmalogin.conf.d/"
ls -la /etc/plasmalogin.conf.d/
