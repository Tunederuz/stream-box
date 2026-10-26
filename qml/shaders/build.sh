#!/usr/bin/env bash
# Compiles the animated background shaders (qml/Backdrop.qml) to .qsb, in Docker: PySide6-Essentials, installed on the
# box, does not have the qsb tool. Same Qt version as the box (install.sh, ui-venv). Run again after each change
# to a .frag; the .qsb files are versioned.
set -euo pipefail
cd "$(dirname "$0")"
docker run --rm -v "$PWD:/s" -w /s python:3.13-slim bash -c '
  apt-get update -qq > /dev/null && apt-get install -y -qq libgl1 libegl1 libxkbcommon0 libfontconfig1 libglib2.0-0 libdbus-1-3 > /dev/null
  pip install -q --root-user-action=ignore PySide6==6.12.0
  for f in *.frag; do pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o "$f.qsb" "$f"; done
  chown '"$(id -u):$(id -g)"' *.qsb'
