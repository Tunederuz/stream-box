# Qt Quick renderer for qmlshots.py: PySide6 of the box, OpenGL through Mesa (llvmpipe) on a virtual X server (Xvfb:
# the offscreen platform has no OpenGL, its software fallback draws no shader: glows, rounded images), fonts
FROM python:3.13-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
      libgssapi-krb5-2 libglib2.0-0 libbrotli1 libegl1 libgl1 libgl1-mesa-dri libglx-mesa0 libxkbcommon0 \
      libxkbcommon-x11-0 libfontconfig1 libfreetype6 libdbus-1-3 libx11-6 libx11-xcb1 libxcb1 libxrender1 libxi6 \
      libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 \
      libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 libxcb-glx0 libsm6 libice6 xvfb xauth \
      fonts-dejavu-core fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*
# Xvfb run as the host user (screenshots owned by them): socket folder writable by everyone
RUN mkdir -p -m 1777 /tmp/.X11-unix
RUN pip install -q --no-cache-dir --root-user-action=ignore PySide6==6.12.0 pillow numpy
