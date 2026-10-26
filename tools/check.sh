#!/usr/bin/env bash
# Runs the checks of the CI (.github/workflows/checks.yml) locally, in Docker: nothing is installed on the host.
#   tools/check.sh            everything
#   tools/check.sh python     only one part: python, lua, shell
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$PWD
parts=${1:-python lua shell}
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
    *) echo "unknown part: $part" >&2; exit 2 ;;
  esac
done
