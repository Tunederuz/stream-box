"""quickmenu.py (quick menu of the simplified version): navigation and what it publishes for stream-box.lua, with the
services stubbed, mpv recorded and the threads run right away."""
import os, unittest

from tests.helpers import temp_home

HOME = os.environ.get("HOME", "")
os.environ["HOME"] = temp_home()   # while importing: the modules read their paths from it
import quickmenu as qm   # noqa: E402
import twitch            # noqa: E402
os.environ["HOME"] = HOME


class Now:
    """threading stand-in: the menu's threads run at once"""
    RLock = staticmethod(qm.threading.RLock)

    class Thread:
        def __init__(self, target, args=(), daemon=None):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)


class QuickMenu(unittest.TestCase):
    def setUp(self):
        self.commands, self.shown = [], None
        self.saved = {name: getattr(qm, name) for name in ("mpv", "threading")}
        qm.mpv, qm.threading = self.fake_mpv, Now
        self.patch(twitch, read_streamers=lambda: ["a", "b"], follows_logins=lambda: [],
                   live_now={"b": {"viewers": 1500, "game": "Chess"}})
        self.patch(qm.jellyfin, jf_server=lambda: {"address": "http://jf"})
        self.patch(qm.plex, px_config=lambda: None)
        qm.close()

    def patch(self, module, **values):
        for name, value in values.items():
            old = getattr(module, name)
            setattr(module, name, value)
            self.addCleanup(setattr, module, name, old)

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(qm, name, value)

    def fake_mpv(self, *commands):
        out = []
        for c in commands:
            if c[:2] == ["set_property", qm.STATE]:
                self.shown = c[2]
            elif c[0] != "get_property":
                self.commands.append(c)
            out.append({"mode": "twitch", "channel": "a"} if c[0] == "get_property" else None)
        return out

    def labels(self):
        return [i["label"] for i in self.shown["items"]]

    def go(self, label):
        """Selects the item with this label (↓ until it), then OK"""
        for _ in range(len(self.shown["items"])):
            if self.shown["items"][self.shown["sel"]]["label"] == label:
                return qm.on_message(["streambox-qm", "key", "ok"])
            qm.on_message(["streambox-qm", "key", "down"])
        self.fail(f"{label} not in {self.labels()}")

    def test_root_and_back(self):
        qm.on_message(["streambox-qm", "open"])
        self.assertIn("Jellyfin", self.labels())
        self.assertNotIn("Plex", self.labels())   # not connected
        self.assertNotIn("Following", self.labels())
        qm.on_message(["streambox-qm", "key", "back"])
        self.assertEqual(self.shown, {})   # root: Back closes

    def test_live_plays_channel(self):
        qm.on_message(["streambox-qm", "open"])
        self.go("Live")
        self.assertEqual(self.shown["title"], "Live")
        self.assertEqual(self.labels()[:2], ["b", "a"])   # live first
        self.assertEqual(self.shown["items"][0]["info"], "● 1.5 k · Chess")
        self.assertTrue(self.shown["items"][1]["on"] and self.shown["items"][1]["dim"])   # watched, offline
        self.go("b")
        self.assertIn(["script-message", "streambox-channel", "b"], self.commands)
        self.assertEqual(self.shown, {})   # closed when it plays

    def test_library_resume_choice(self):
        card = {"id": "m1", "title": "Movie", "type": "Movie", "year": 2001, "seconds": 5400, "position": 1200}
        played = []
        self.patch(qm, LIBS={"jellyfin": (lambda: {"resume": [card], "libraries": [{"name": "Movies", "items": []}]},
                                          None, lambda i, from_start: played.append((i, from_start)))})
        qm.on_message(["streambox-qm", "open"])
        self.go("Jellyfin")
        self.assertEqual(self.labels(), ["Continue watching"])   # empty library row left out
        self.go("Continue watching")
        self.assertEqual(self.shown["items"][0]["info"], "2001 · 1:30:00")
        self.go("Movie")
        self.assertEqual(self.labels(), ["▶  Resume at 20:00", "↺  From the beginning"])
        self.go("↺  From the beginning")
        self.assertEqual(played, [("m1", True)])

    def test_service_error_stays_usable(self):
        def broken():
            raise OSError("down")
        self.patch(qm, LIBS={"jellyfin": (broken, None, None)})
        qm.on_message(["streambox-qm", "open"])
        self.go("Jellyfin")
        self.assertEqual(self.labels(), ["Unavailable: down"])
        qm.on_message(["streambox-qm", "key", "left"])
        self.assertEqual(self.shown["title"], "Menu")


if __name__ == "__main__":
    unittest.main()
