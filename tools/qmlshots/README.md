qmlshots: screenshots of the QML TV menu without a box, in Docker (Xvfb + Mesa, PySide6 of the box; nothing on the host).
`qmlshots.py` mocks ui.py (`box`, `pip`, `i18n` in French), serves `fixtures.json` as the remote.py API on 127.0.0.1:8080, then plays `STEPS` (keys through every tab, rows, dialogs, keyboard), one PNG per step plus `console.log` (QML warnings, requests).
Before/after a QML change: `tools/qmlshots/run.sh shoot /tmp/a HEAD` then `tools/qmlshots/run.sh shoot /tmp/b` (working tree), and `tools/qmlshots/run.sh diff /tmp/a /tmp/b`; compare the console.log files too.
`tools/qmlshots/run.sh lint`: pyside6-qmllint on every QML file. Options: `QMLSHOTS_STEPS=n` (first n steps), `QMLSHOTS_WAIT=ms` (900), `QMLSHOTS_DEBUG=1`, `QMLSHOTS_NOSHOTS=1` (the scenario and console.log, no screenshot: `tools/check.sh qml`).
Deterministic on purpose: clock fixed at 12:00, dates relative to today ("@-3d"), short titles (no scrolling text), plain background (`backdrop` none).
