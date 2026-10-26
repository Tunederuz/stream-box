"""Shared by the tests: repository path, a throwaway HOME, files of the repository by language."""
import os, re, subprocess, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def temp_home(language=None):
    """New HOME with ~/.config/stream-box (and the interface language if given); returns its path"""
    home = tempfile.mkdtemp(prefix="stream-box-test-")
    os.makedirs(os.path.join(home, ".config", "stream-box"))
    os.makedirs(os.path.join(home, ".local", "state", "stream-box"))
    if language:
        with open(os.path.join(home, ".config", "stream-box", "language"), "w") as f:
            f.write(language + "\n")
    return home


def tracked_files(pattern):
    """Files tracked by git (or all files outside .git when git is missing) whose path matches pattern"""
    try:
        out = subprocess.run(["git", "-C", REPO, "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        out = [os.path.relpath(os.path.join(d, f), REPO) for d, _, fs in os.walk(REPO) if ".git" not in d for f in fs]
    return [os.path.join(REPO, f) for f in out if re.search(pattern, f) and os.path.exists(os.path.join(REPO, f))]
