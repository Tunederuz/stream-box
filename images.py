"""Stream Box: images for the TV: thumbnails prepared for the TV menu (tv_image), and the TV preview for the
companion app (preview). Standard library only.
"""
import hashlib, os, shutil, subprocess, threading, time, urllib.parse, urllib.request

import display   # display.py: environment of cage's Wayland session (grim)
import jellyfin  # jellyfin.py: images of the paired server are allowed
from common import mpv
from i18n import tr

# TV menu images (tv_menu.lua): over the video, mpv only shows raw images (overlay-add, BGRA with premultiplied
# alpha). They are downloaded, cropped and converted with ffmpeg, cached in /tmp. Only from Twitch's and YouTube's
# image servers: the address comes from the request.

TV_IMAGE_DIR = "/tmp/stream-box-images"


def tv_image(src, width, height, round_, radius=0):
    """Image ready for overlay-add: round_ = disc, otherwise rounded corners of radius pixels (0: square)."""
    host = urllib.parse.urlsplit(src).hostname or ""
    jf_host = urllib.parse.urlsplit((jellyfin.jf_server() or {}).get("address", "")).hostname
    if not (host.endswith(".jtvnw.net") or host in ("i.ytimg.com", "clips-media-assets2.twitch.tv") or host == jf_host):
        raise ValueError(tr("image refused"))
    width, height = max(8, min(1280, width)), max(8, min(1280, height))
    radius = max(0, min(radius, width // 2, height // 2))
    key = hashlib.sha1(f"{src}|{width}|{height}|{round_}|{radius}".encode()).hexdigest()[:24]
    path = os.path.join(TV_IMAGE_DIR, f"{key}.bgra")
    if not os.path.exists(path):
        os.makedirs(TV_IMAGE_DIR, exist_ok=True)
        with urllib.request.urlopen(src, timeout=10) as r:
            data = r.read(8_000_000)
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},format=rgba"
        # Smoothed edges: disc, or rounded corners (distance to the center of the nearest corner's quarter circle).
        # Premultiplied alpha: colors follow the opacity.
        alpha = None
        if round_:
            alpha = "clip(255*(W/2+0.5-hypot(X+0.5-W/2,Y+0.5-H/2)),0,255)"
        elif radius:
            r = radius
            alpha = (f"clip(255*({r}+0.5-hypot(max(0,max({r}-X-0.5,X+0.5-W+{r})),"
                     f"max(0,max({r}-Y-0.5,Y+0.5-H+{r})))),0,255)")
        if alpha:
            vf += (f",geq=a='{alpha}'"
                   ":r='r(X,Y)*alpha(X,Y)/255':g='g(X,Y)*alpha(X,Y)/255':b='b(X,Y)*alpha(X,Y)/255'")
        tmp = f"{path}.{threading.get_ident()}.tmp"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", "pipe:0", "-vf", vf, "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "bgra", tmp], input=data, capture_output=True, timeout=30, check=True)
        os.replace(tmp, path)
    return {"path": path, "w": width, "h": height}


# TV preview for the page, only when the page asks for it (section open): the whole screen, ambient screen and
# menus included, captured by grim through cage's wlr-screencopy protocol. Without grim, mpv capture (window, with
# the chat and the menu), which has nothing to capture when no video is playing (the page then shows a text).

PREVIEW_WIDTH = 960
preview_lock = threading.Lock()
preview_cache = {"at": 0.0, "data": None}


def preview():
    """JPEG of the screen, or None when there is no image to capture."""
    with preview_lock:   # one capture at a time; several phones share the last one for 1 s
        if time.time() - preview_cache["at"] < 1:
            return preview_cache["data"]
        data = None
        playing = mpv(["get_property", "video-params"])[0] is not None
        if shutil.which("grim"):
            try:
                width = mpv(["get_property", "osd-dimensions"])[0].get("w") or PREVIEW_WIDTH
                r = subprocess.run(["grim", "-t", "jpeg", "-q", "70", "-s", f"{min(1.0, PREVIEW_WIDTH / width):.3f}", "-"],
                                   capture_output=True, timeout=10, env=display.wlr_env())
                data = r.stdout if r.returncode == 0 and r.stdout else None
            except (OSError, subprocess.SubprocessError, AttributeError):
                data = None
            if data:
                preview_cache.update(at=time.time(), data=data)
                return data
        if playing:
            shot, small = "/tmp/stream-box-shot.jpg", "/tmp/stream-box-preview.jpg"
            for path in (shot, small):
                if os.path.exists(path):
                    os.remove(path)
            mpv(["screenshot-to-file", shot, "window"])
            for _ in range(30):   # mpv writes the file after replying
                if os.path.exists(shot) and os.path.getsize(shot) > 0:
                    size = os.path.getsize(shot)
                    time.sleep(0.05)
                    if os.path.getsize(shot) == size:
                        break
                time.sleep(0.05)
            if os.path.exists(shot):
                try:
                    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", shot, "-vf", f"scale={PREVIEW_WIDTH}:-2",
                                    "-q:v", "5", small], timeout=10, check=True)
                    shot = small
                except (OSError, subprocess.SubprocessError):
                    pass   # without ffmpeg: full-size capture
                with open(shot, "rb") as f:
                    data = f.read()
        preview_cache.update(at=time.time(), data=data)
        return data
