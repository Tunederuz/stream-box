#!/usr/bin/env bash
# Compile les shaders des fonds animés (qml/Backdrop.qml) en .qsb, dans Docker : PySide6-Essentials, installé sur la
# box, n'a pas l'outil qsb. Même version de Qt que la box (install.sh, ui-venv). À relancer après chaque modification
# d'un .frag ; les .qsb sont versionnés.
set -euo pipefail
cd "$(dirname "$0")"
docker run --rm -v "$PWD:/s" -w /s python:3.13-slim bash -c '
  apt-get update -qq > /dev/null && apt-get install -y -qq libgl1 libegl1 libxkbcommon0 libfontconfig1 libglib2.0-0 libdbus-1-3 > /dev/null
  pip install -q --root-user-action=ignore PySide6==6.12.0
  for f in *.frag; do pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o "$f.qsb" "$f"; done
  chown '"$(id -u):$(id -g)"' *.qsb'
