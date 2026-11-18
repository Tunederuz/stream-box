#!/usr/bin/env python3
"""Inlet: the image's extensions (systemd-sysext), split out at the end of its build (mkosi.finalize.chroot, inside the
image: pacman's database tells each package's files and dependencies). Each extension takes its packages' files, with
the dependencies nothing else in the image needs, into <out>/stream-box-<name>.tar.xz (usr/ and its
usr/lib/extension-release.d/extension-release.stream-box-<name>), then removes them from the image: the box downloads
it when its add-on is on (/usr/local/lib/stream-box/extensions), the release lists it in its SHA256SUMS (build.sh
release). Packages that were only there to build would be removed too (none so far).
    split-extensions.py <out dir>
"""
import io, os, subprocess, sys, tarfile

# name → (packages, packages removed without going into the extension: needed while building only)
EXTENSIONS = {
    "moonlight": (["moonlight-qt"], []),   # the PC link (addons/gamestream)
    # YouTube: its token server, the Cast receiver, yt-dlp's JavaScript; npm with it: update.sh updates their modules
    "node": (["nodejs", "npm"], []),
}


SPLIT_MARK = "/usr/lib/stream-box-extensions"   # the names of the extensions split out of this image

# Never in an extension: if one of these comes out of the computation, something is wrong (stop before removing)
# (not Qt: the interface has its own, PySide6's in its venv; the system's is Moonlight's)
ESSENTIAL = {"glibc", "bash", "coreutils", "pacman", "systemd", "python", "mpv", "ffmpeg", "tar", "grep", "sed",
             "util-linux", "openssl", "curl", "git", "xz", "gnupg", "mesa"}


def installed():
    return set(subprocess.run(["pacman", "-Qq"], capture_output=True, text=True, check=True).stdout.split())


def removable(pkgs):
    """pkgs and their dependencies nothing else needs, as pacman -Rs would remove them (it keeps what was installed
    explicitly, and refuses when another package needs one of them): printed only (-p), nothing removed here"""
    if not pkgs:
        return set()
    r = subprocess.run(["pacman", "-Rsp", "--print-format", "%n", *pkgs], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"split-extensions: pacman -Rsp {' '.join(pkgs)}: {r.stderr.strip()}")
    return set(r.stdout.split())


def files(pkgs):
    """The files of these packages (none: none, and not pacman -Qlq alone, which lists every file of the system)"""
    if not pkgs:
        return []
    return [f for f in subprocess.run(["pacman", "-Qlq", *pkgs], capture_output=True, text=True, check=True).stdout.split()
            if not f.endswith("/")]


def main(out_dir):
    have = installed()
    os.makedirs(out_dir, exist_ok=True)
    # the image's mark (the box's extensions script: without it, an image keeps those packages in itself)
    with open(SPLIT_MARK, "w") as f:
        f.write("\n".join(EXTENSIONS) + "\n")
    for name, (pkgs, build_only) in EXTENSIONS.items():
        if not set(pkgs) <= have:
            sys.exit(f"split-extensions: {pkgs} not in the image")
        # the build-only packages and what only they need go; the rest of what pkgs need nothing else needs, with them
        build_set = removable(build_only) - set(pkgs)
        ext = sorted(removable(pkgs + build_only) - build_set)
        bad = ESSENTIAL & (set(ext) | build_set)
        if bad:
            sys.exit(f"split-extensions: {name} would take essential packages: {' '.join(sorted(bad))}")
        paths = files(ext)
        outside = [f for f in paths if not f.startswith("/usr/")]
        if outside:   # sysext only covers /usr (and /opt)
            print(f"split-extensions: {name}: left in the image (outside /usr): {' '.join(outside)}")
        archive = os.path.join(out_dir, f"stream-box-{name}.tar.xz")
        with tarfile.open(archive, "w:xz", preset=6) as tar:
            for f in paths:
                if f.startswith("/usr/") and os.path.lexists(f):
                    tar.add(f, arcname=f.lstrip("/"), recursive=False)
            release = (f"ID={read_os_release().get('ID', 'arch')}\nIMAGE_ID={os.environ.get('IMAGE_ID', 'stream-box')}\n"
                       f"IMAGE_VERSION={os.environ.get('IMAGE_VERSION', '')}\nEXTENSION_RELOAD_MANAGER=1\n").encode()
            info = tarfile.TarInfo(f"usr/lib/extension-release.d/extension-release.stream-box-{name}")
            info.size, info.mode = len(release), 0o644
            tar.addfile(info, io.BytesIO(release))
        for f in paths + files(sorted(build_set)):
            if f.startswith("/usr/") and os.path.lexists(f) and not os.path.isdir(f):
                if os.environ.get("SPLIT_DRY"):   # (trying it: nothing removed, the files listed)
                    print("would remove", f)
                else:
                    os.remove(f)
        size = os.path.getsize(archive) / 1e6
        print(f"split-extensions: {name}: {len(ext)} packages ({' '.join(ext)}), {size:.0f} MB compressed; "
              f"removed only: {' '.join(sorted(build_set)) or '-'}")


def read_os_release():
    out = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        if os.path.exists(path):
            for line in open(path):
                k, _, v = line.strip().partition("=")
                if k:
                    out[k] = v.strip('"')
            break
    return out


if __name__ == "__main__":
    main(sys.argv[1])
