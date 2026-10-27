"""stream-box.lua and its modules (lua/streambox/): modules outside mpv, then the whole script loaded in a real mpv
(no window), in French, driven through its IPC socket. Skipped when luajit or mpv are missing."""
import json, os, shutil, socket, subprocess, tempfile, time, unittest

from tests.helpers import REPO, temp_home

LUA = shutil.which("luajit") or shutil.which("lua5.1")


@unittest.skipUnless(LUA, "luajit missing")
class Modules(unittest.TestCase):
    def test_units(self):
        out = subprocess.run([LUA, os.path.join(REPO, "tests", "lua", "units.lua"), REPO], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("units ok", out.stdout)


@unittest.skipUnless(shutil.which("mpv"), "mpv missing")
class Script(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.sock = os.path.join(cls.dir, "mpv.sock")
        cls.log = os.path.join(cls.dir, "mpv.log")
        home = temp_home("fr")   # the non-English code paths run at load time
        open(os.path.join(home, ".config", "stream-box", "setup-done"), "w").close()
        cls.mpv = subprocess.Popen(["mpv", "--no-config", "--idle=yes", "--vo=null", "--ao=null",
                                    "--input-ipc-server=" + cls.sock, "--log-file=" + cls.log,
                                    "--script=" + os.path.join(REPO, "stream-box.lua")],
                                   env=dict(os.environ, HOME=home), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if os.path.exists(cls.sock):
                break
            time.sleep(0.1)
        time.sleep(1)

    @classmethod
    def tearDownClass(cls):
        cls.mpv.terminate()
        cls.mpv.wait(10)

    def ipc(self, *command):
        s = socket.socket(socket.AF_UNIX)
        s.connect(self.sock)
        s.sendall((json.dumps({"command": list(command)}) + "\n").encode())
        data = b""
        while b"\n" not in data:
            data += s.recv(4096)
        s.close()
        return json.loads(data.split(b"\n")[0])

    def lua_errors(self):
        with open(self.log, encoding="utf-8", errors="replace") as f:
            return [line for line in f if "[stream_box]" in line and ("[e]" in line or "[f]" in line)]

    def test_loaded_to_the_end(self):
        # the last lines of the script publish the state: they ran
        self.assertEqual(self.ipc("get_property", "user-data/streambox/corner").get("data"), "bl")
        self.assertEqual(self.lua_errors(), [])

    def test_mpv_keys_ignored_while_input_py_runs(self):
        # input.py announces itself (user-data/streambox/input = "evdev:<time>"): the same key received by mpv must not
        # count a second time (mute shows it)
        self.ipc("set_property", "user-data/streambox/input", f"evdev:{int(time.time())}")
        self.ipc("set_property", "mute", False)
        time.sleep(0.3)
        self.ipc("keypress", "MUTE")
        time.sleep(0.5)
        self.assertEqual(self.ipc("get_property", "mute")["data"], False)
        self.ipc("script-message", "streambox-input", "KEY_MUTE", "mute")
        time.sleep(0.5)
        self.assertEqual(self.ipc("get_property", "mute")["data"], True)
        self.ipc("set_property", "user-data/streambox/input", "")

    def test_keys_and_messages(self):
        for args in (["streambox-input", "TEST", "home"], ["streambox-input", "TEST", "down"],
                     ["streambox-input", "TEST", "back"], ["streambox-language"], ["streambox-flag", "night", "yes"],
                     ["streambox-qr", "timed"], ["streambox-keymap-wizard"]):
            self.ipc("script-message", *args)
        time.sleep(1)   # the wizard listens after 0.8 s; Back of the page's virtual remote then quits it
        self.ipc("script-message", "streambox-input", "VIRTUAL", "back")
        time.sleep(1.5)
        self.assertEqual(self.ipc("get_property", "user-data/streambox/night").get("data"), True)
        self.assertEqual(self.lua_errors(), [])

    def test_scrub(self):
        # ← → in a video pause it and move a target; OK goes there and plays, Back gives up
        def get(name):
            return self.ipc("get_property", name).get("data")
        for _ in range(50):   # the startup's home screen (after 3 s) would stop the video
            if get("user-data/streambox/mode") == "home":
                break
            time.sleep(0.2)
        video = os.path.join(self.dir, "video.mkv")   # a real file: lavfi sources report no usable duration
        subprocess.run(["mpv", "--no-config", "av://lavfi:testsrc=duration=600:size=64x36:rate=2", "--o=" + video],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        self.ipc("loadfile", video)
        for _ in range(50):
            if get("time-pos") is not None and get("user-data/streambox/mode") == "media":
                break
            time.sleep(0.1)
        start = get("time-pos")
        for _ in range(2):
            self.ipc("script-message", "streambox-input", "TEST", "right")
            time.sleep(0.3)
        fx = get("user-data/streambox/seekfx")
        self.assertTrue(get("pause"))
        self.assertAlmostEqual(fx["target"], start + 20, delta=1.5)
        self.assertEqual(fx["text"], "+20 s")
        self.ipc("script-message", "streambox-input", "TEST", "ok")
        time.sleep(0.8)
        self.assertFalse(get("pause"))
        self.assertAlmostEqual(get("time-pos"), fx["target"], delta=2)
        there = get("time-pos")
        time.sleep(1.6)   # a new streak
        self.ipc("script-message", "streambox-input", "TEST", "left")
        time.sleep(0.3)
        self.assertTrue(get("pause"))
        self.ipc("script-message", "streambox-input", "TEST", "back")
        time.sleep(0.5)
        self.assertFalse(get("pause"))   # playing again, where it was
        self.assertAlmostEqual(get("time-pos"), there, delta=3)
        self.assertEqual(get("user-data/streambox/mode"), "media")   # Back gave up the scrub, did not stop the video
        time.sleep(1.6)   # a new streak
        # quick presses: 10 s each, however fast
        before = get("time-pos")
        for _ in range(4):
            self.ipc("script-message", "streambox-input", "TEST", "right")
            time.sleep(0.25)
        self.assertAlmostEqual(get("user-data/streambox/seekfx")["target"] - before, 40, delta=1)
        self.ipc("script-message", "streambox-input", "TEST", "back")
        time.sleep(1)
        # held key (repeats every 0.08 s, at most 8 jumps/s kept): 10 s the first second, then 30 s, then 1 min
        before = get("time-pos")
        for _ in range(20):
            self.ipc("script-message", "streambox-input", "TEST", "right")
            time.sleep(0.13)
        held = get("user-data/streambox/seekfx")["target"] - before
        self.assertGreaterEqual(held, 300)   # against 200 with 10 s jumps
        self.ipc("script-message", "streambox-input", "TEST", "back")
        time.sleep(0.5)
        self.ipc("stop")
        self.assertEqual(self.lua_errors(), [])


if __name__ == "__main__":
    unittest.main()
