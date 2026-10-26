# Same mpv as the box image (Arch), luajit and Python: runs tests/test_lua.py (tools/check.sh, CI)
FROM archlinux:latest
RUN pacman -Syu --noconfirm --needed mpv luajit python git && pacman -Scc --noconfirm
