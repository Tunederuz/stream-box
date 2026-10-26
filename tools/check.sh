#!/usr/bin/env bash
# Runs the checks of the CI (.github/workflows/checks.yml) locally, in Docker: nothing is installed on the host.
#   tools/check.sh            everything
#   tools/check.sh python     only one part: python, lua, shell, qml
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$PWD
parts=${1:-python lua shell qml}
for part in $parts; do
  echo "== $part"
  case $part in
    python)   # ruff (pyflakes rules), then the tests that need neither mpv nor luajit
      docker run --rm --network none -v "$REPO":/src:ro python:3.13-slim sh -c '
        cp -r /src /r && cd /r && python3 -m compileall -q . > /dev/null &&
        python3 -m unittest discover -s tests -t . 2>&1 | tail -n 3'
      docker run --rm -v "$REPO":/r:ro python:3.13-slim sh -c \
        'pip install -q --root-user-action=ignore ruff > /dev/null && cd /r && ruff check --no-cache .'
      ;;
    lua)      # Lua modules (luajit) and stream-box.lua in the same mpv as the box
      docker build -q -t stream-box-checks-mpv -f tools/mpv.Dockerfile tools > /dev/null 2>&1 ||
        docker build -t stream-box-checks-mpv -f tools/mpv.Dockerfile tools   # (again, to show why it failed)
      docker run --rm --network none -v "$REPO":/r:ro stream-box-checks-mpv sh -c \
        'cd /r && python3 -m unittest tests.test_lua 2>&1 | tail -n 3'
      ;;
    shell)
      git ls-files '*.sh' | sed 's|^|/r/|' | xargs docker run --rm -v "$REPO":/r:ro koalaman/shellcheck:stable -S warning
      echo "shellcheck: ok"
      ;;
    qml)      # syntax (qmllint), then every step of the qmlshots scenario without QML errors
      lint=$(tools/qmlshots/run.sh lint 2>&1 || true)
      if grep -F "[syntax]" <<< "$lint"; then exit 1; fi
      out=$(mktemp -d)
      QMLSHOTS_WAIT=${QMLSHOTS_WAIT:-400} tools/qmlshots/run.sh shoot "$out" > /dev/null 2>&1
      if grep -E "ReferenceError|TypeError|is not defined|Binding loop|Cannot assign" "$out/console.log"; then exit 1; fi
      echo "qml: $(ls "$out"/*.png | wc -l) screens, no QML error"
      rm -rf "$out"
      ;;
    *) echo "unknown part: $part" >&2; exit 2 ;;
  esac
done
