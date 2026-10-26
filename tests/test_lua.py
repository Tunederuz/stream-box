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

    def test_keys_and_messages(self):
        for args in (["streambox-input", "TEST", "home"], ["streambox-input", "TEST", "down"],
                     ["streambox-input", "TEST", "back"], ["streambox-language"], ["streambox-keymap-wizard"],
                     ["streambox-input", "VIRTUAL", "back"], ["streambox-flag", "night", "yes"],
                     ["streambox-qr", "timed"]):
            self.ipc("script-message", *args)
        time.sleep(1.5)
        self.assertEqual(self.ipc("get_property", "user-data/streambox/night").get("data"), True)
        self.assertEqual(self.lua_errors(), [])


if __name__ == "__main__":
    unittest.main()
