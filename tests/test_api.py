"""remote.py (companion app server and API): started for real with a throwaway HOME and a fake mpv IPC socket that
records the commands it receives. Skipped when port 8080 or the mpv socket are already taken (a running box). Run twice:
from the repository (Inlet OS), and from a copy without app/system (Inlet app)."""
import http.client, json, os, shutil, socket, subprocess, sys, tempfile, threading, time, unittest

from tests.helpers import REPO, temp_home

SOCK = "/tmp/stream-box-mpv.sock"   # common.MPV_SOCKET
PORT = 8080                         # common.PORT


def port_taken():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.5).close()
        return True
    except OSError:
        return False


class FakeMpv:
    """Answers get_property with None, records every other command"""
    def __init__(self):
        self.commands = []
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(SOCK)
        self.server.listen(16)
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while True:
            try:
                c, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self.client, args=(c,), daemon=True).start()

    def client(self, c):
        buf = b""
        with c:
            while True:
                data = c.recv(65536)
                if not data:
                    return
                *lines, buf = (buf + data).split(b"\n")
                for line in lines:
                    msg = json.loads(line)
                    if msg["command"][0] != "get_property":
                        self.commands.append(msg["command"])
                    c.sendall((json.dumps({"request_id": msg.get("request_id", 0), "data": None,
                                           "error": "success"}) + "\n").encode())

    def close(self):
        self.server.close()
        os.remove(SOCK)


@unittest.skipIf(port_taken() or os.path.exists(SOCK), "port 8080 or the mpv socket already in use")
class Api(unittest.TestCase):
    SYSTEM = True   # the system part is there (Inlet OS)

    @classmethod
    def root(cls):
        """The repository the server runs from"""
        return REPO

    @classmethod
    def setUpClass(cls):
        cls.mpv = FakeMpv()
        cls.home = temp_home()
        root = cls.root()
        cls.server = subprocess.Popen([sys.executable, os.path.join(root, "app", "player", "remote.py")], cwd=root,
                                      env=dict(os.environ, HOME=cls.home),
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if port_taken():
                break
            time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(10)
        cls.mpv.close()

    def request(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        data = json.dumps(body).encode() if body is not None else None
        c.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
        r = c.getresponse()
        out = r.read()
        c.close()
        try:
            return r.status, json.loads(out)
        except ValueError:
            return r.status, out

    def test_page_and_locales(self):
        status, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", page)
        status, fr = self.request("GET", "/locales/fr.json")
        self.assertEqual((status, fr.get("Language")), (200, "Langue"))

    def test_state(self):
        status, st = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertIn("fr", st["languages"])
        self.assertIn("streamers", st)

    def test_language(self):
        self.assertEqual(self.request("POST", "/api/language", {"lang": "fr"})[0], 200)
        self.assertEqual(self.request("GET", "/api/state")[1]["lang"], "fr")
        self.assertIn(["script-message", "streambox-language", "fr"], self.mpv.commands)
        self.assertEqual(self.request("POST", "/api/language", {"lang": "xx"})[0], 400)
        self.request("POST", "/api/language", {"lang": "en"})

    def test_action_reaches_mpv(self):
        self.assertEqual(self.request("POST", "/api/corner", {})[0], 200)
        self.assertIn(["script-message", "streambox-cycle-corner"], self.mpv.commands)

    def test_libraries(self):
        # nothing connected: no library tab (the TV menu shows the "Libraries" tab instead)
        self.assertEqual(self.request("GET", "/api/state")[1]["libraries"], {"jellyfin": False, "plex": False})
        self.assertEqual(self.request("GET", "/api/plex"), (200, {"configured": False}))
        status, body = self.request("POST", "/api/plex", {"address": "127.0.0.1:9"})   # nothing listens there
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        self.assertEqual(self.request("GET", "/api/jellyfin_link"),
                         (200, {"configured": False, "address": "", "name": "", "pending": None}))
        # Quick Connect: the server is checked before the shim is touched
        status, body = self.request("POST", "/api/jellyfin_link", {"address": "127.0.0.1:9"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_features(self):
        self.assertEqual(self.request("GET", "/api/features"), (200, {"system": self.SYSTEM, "gamestream": False}))   # (no Moonlight here)

    def test_unknown_action(self):
        self.assertGreaterEqual(self.request("POST", "/api/no_such_action", {})[0], 400)

    def test_history_empty(self):
        self.assertEqual(self.request("GET", "/api/history"), (200, []))

    def test_twitch_login_answers(self):
        # used to crash (UnboundLocalError in the old action dispatcher): a bad token is now refused cleanly
        status, body = self.request("POST", "/api/login", {"token": "not a token"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()


class PlayerOnly(Api):
    """The same server and tests from a copy of the repository without app/system: the Inlet app, whose OS runs
    itself. It starts, serves the page and the player's API, and has none of the system's routes and actions."""
    SYSTEM = False

    @classmethod
    def root(cls):
        cls.copy = tempfile.mkdtemp()
        skip = lambda d, names: [n for n in names if n in (".git", "node_modules", "__pycache__")
                                 or (os.path.basename(d) == "app" and n == "system")]
        shutil.copytree(REPO, os.path.join(cls.copy, "repo"), ignore=skip, symlinks=True)
        return os.path.join(cls.copy, "repo")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(cls.copy, ignore_errors=True)

    def test_no_system_routes(self):
        for path in ("/api/health", "/api/wifi", "/api/bluetooth", "/api/dev", "/api/display", "/api/ssh"):
            self.assertEqual(self.request("GET", path)[0], 404, path)
        for name in ("poweroff", "reboot", "update", "wifi", "ssh", "install"):
            self.assertEqual(self.request("POST", f"/api/{name}", {})[0], 400, name)   # unknown action
