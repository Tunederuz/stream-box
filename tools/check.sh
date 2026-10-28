#!/usr/bin/env bash
# Runs the checks of the CI (.github/workflows/checks.yml) locally, in Docker: nothing is installed on the host.
#   tools/check.sh            everything
#   tools/check.sh python     only one part: python, page, lua, shell, qml
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$PWD
parts=${1:-python page lua shell qml}
for part in $parts; do
  echo "== $part"
  case $part in
    python)   # the tests that need neither mpv nor luajit, then ruff (pyflakes rules, syntax errors)
      docker run --rm --network none -v "$REPO":/src:ro python:3.13-slim sh -c '
        cp -r /src /r && cd /r && python3 -m unittest discover -s tests -t . > /tmp/log 2>&1; rc=$?
        if [ $rc -ne 0 ]; then cat /tmp/log; else tail -n 3 /tmp/log; fi; exit $rc'
      docker run --rm -v "$REPO":/r:ro python:3.13-slim sh -c \
        'pip install -q --root-user-action=ignore ruff > /dev/null && cd /r && ruff check --no-cache .'
      ;;
    page)     # companion app: remote.html in jsdom (tests/page; its modules installed in the container only)
      docker run --rm -e NPM_CONFIG_UPDATE_NOTIFIER=false -v "$REPO":/r:ro node:22-slim sh -c \
        'cp -r /r/tests/page /p && cd /p && rm -rf node_modules && npm ci --no-audit --no-fund --loglevel=error > /dev/null && node check-page.js /r'
      ;;
    lua)      # Lua modules (luajit) and stream-box.lua in the same mpv as the box
      docker build -q -t stream-box-checks-mpv -f tools/mpv.Dockerfile tools > /dev/null 2>&1 ||
        docker build -t stream-box-checks-mpv -f tools/mpv.Dockerfile tools   # (again, to show why it failed)
      docker run --rm --network none -v "$REPO":/r:ro stream-box-checks-mpv sh -c \
        'cd /r && python3 -m unittest tests.test_lua > /tmp/log 2>&1; rc=$?
         if [ $rc -ne 0 ]; then cat /tmp/log; else tail -n 3 /tmp/log; fi; exit $rc'
      ;;
    shell)
      # .sh files, and the image's scripts without an extension (system-update, install-to-disk…)
      { git ls-files '*.sh'; git grep -lE '^#!(/usr/bin/env bash|/bin/(ba)?sh)' -- image/mkosi.extra; } | sort -u |
        sed 's|^|/r/|' | xargs docker run --rm -v "$REPO":/r:ro koalaman/shellcheck:stable -S warning
      echo "shellcheck: ok"
      ;;
    qml)      # syntax (qmllint), then every step of the qmlshots scenario without QML errors
      lint=$(tools/qmlshots/run.sh lint 2>&1 || true)
      if grep -F "[syntax]" <<< "$lint"; then exit 1; fi
      out=$(mktemp -d)
      # the scenario without screenshots (nobody looks at them here): only the QML errors of its console
      QMLSHOTS_NOSHOTS=1 QMLSHOTS_WAIT=${QMLSHOTS_WAIT:-400} tools/qmlshots/run.sh shoot "$out" > /dev/null 2>&1
      steps=$(grep -c '^--- step' "$out/console.log" 2> /dev/null || true)
      if [ "${steps:-0}" -eq 0 ]; then echo "qml: the scenario did not run"; exit 1; fi
      if grep -E "ReferenceError|TypeError|is not defined|Binding loop|Cannot assign" "$out/console.log"; then exit 1; fi
      echo "qml: $steps steps, no QML error"
      rm -rf "$out"
      ;;
    *) echo "unknown part: $part" >&2; exit 2 ;;
  esac
done
