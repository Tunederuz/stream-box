#!/usr/bin/env bash
# Screenshots of the QML TV menu in Docker (see README.md): Xvfb, Mesa, nothing installed on the host.
#   tools/qmlshots/run.sh shoot <out dir> [git rev]   qml/ of the working tree, or of a commit
#   tools/qmlshots/run.sh diff <dir A> <dir B>
#   tools/qmlshots/run.sh lint                        pyside6-qmllint on every QML file
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
docker build -q -t stream-box-qmlshots "$here" > /dev/null
run() { docker run --rm --init --user "$(id -u):$(id -g)" -e HOME=/tmp -e QT_QPA_PLATFORM=xcb \
          -e LIBGL_ALWAYS_SOFTWARE=1 \
          -e QMLSHOTS_DEBUG -e QMLSHOTS_STEPS -e QMLSHOTS_WAIT -e QMLSHOTS_NOSHOTS -e QMLSHOTS_PLAYER -e QMLSHOTS_SIZE -e QMLSHOTS_PENDING -v "$repo:/src:ro" "$@"; }
case "$1" in
  shoot)
    out="$(mkdir -p "$2" && cd "$2" && pwd)"
    qml=/src/qml
    if [ -n "${3:-}" ]; then   # qml/ of a commit, next to the screenshots
      rm -rf "$out/.qml" && mkdir -p "$out/.qml" && git -C "$repo" archive "$3" qml | tar -x -C "$out/.qml"
      qml=/out/.qml/qml
    fi
    run -v "$out:/out" stream-box-qmlshots xvfb-run -a -s "-screen 0 1920x1080x24" python /src/tools/qmlshots/qmlshots.py shoot "$qml" /out ;;
  diff)
    a="$(cd "$2" && pwd)"; b="$(cd "$3" && pwd)"
    run -v "$a:/a:ro" -v "$b:/b:ro" stream-box-qmlshots python /src/tools/qmlshots/qmlshots.py diff /a /b ;;
  lint)
    run stream-box-qmlshots sh -c 'cd /src/qml && pyside6-qmllint -I . $(find . -name "*.qml")' ;;
esac
