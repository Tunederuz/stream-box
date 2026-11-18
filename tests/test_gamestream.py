"""addons/gamestream: the pairing's dialog goes as soon as Sunshine lists its games to the box, even when moonlight
pair does not end by itself."""
import os, subprocess, time, unittest
from unittest import mock

from tests.helpers import temp_home

HOME = os.environ.get("HOME", "")
os.environ["HOME"] = temp_home()   # while importing: the modules read their paths from it
from addons.gamestream import service as gs   # noqa: E402
os.environ["HOME"] = HOME


class Pairing(unittest.TestCase):
    def test_paired_while_moonlight_hangs(self):
        hung = subprocess.Popen(["sleep", "30"])
        self.addCleanup(hung.kill)
        answers = iter([None, [{"name": "Desktop", "id": "1", "art": ""}]])   # code not typed yet, then typed
        with mock.patch.object(gs, "available", return_value=True), \
             mock.patch.object(gs, "moonlight", return_value="moonlight"), \
             mock.patch.object(gs, "serverinfo", return_value={"name": "PC", "playing": False}), \
             mock.patch.object(gs, "look_for_pcs"), mock.patch.object(gs, "refresh"), \
             mock.patch.object(gs.subprocess, "Popen", return_value=hung), \
             mock.patch.object(gs, "load_apps", side_effect=lambda host: next(answers)), \
             mock.patch.object(gs.time, "sleep", lambda s, sleep=time.sleep: sleep(0.01)), \
             mock.patch.object(gs, "PAIR_GRACE", 0.2), \
             mock.patch.object(gs, "state", {"apps": {}, "apps_at": {}, "busy": set(), "found": ["10.0.0.5"],
                                             "found_at": time.time()}):
            gs.pair({"host": "10.0.0.5"})
            self.assertEqual(gs.status()["pairing"]["pin"], gs.proc["pair"]["pin"])   # code on the TV
            for _ in range(100):
                if gs.proc["pair"]["paired"]:
                    break
                gs.time.sleep(0)
            st = gs.status()
            self.assertIsNone(st["pairing"])   # the dialog goes
            self.assertIn("10.0.0.5", gs.paired_hosts())
            self.assertEqual([a["name"] for a in st["pcs"][0]["apps"]], ["Desktop"])
            hung.wait(5)   # moonlight pair stopped after its grace
            self.assertIsNone(gs.proc["pair"])


if __name__ == "__main__":
    unittest.main()
