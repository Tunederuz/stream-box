"""addons/ (the box's integrations): turning an add-on off takes away what it brings, Twitch (the base) stays on."""
import os, tempfile, unittest

from tests.helpers import temp_home

HOME = os.environ.get("HOME", "")
os.environ["HOME"] = temp_home()   # while importing: the modules read their paths from it
import addons   # noqa: E402
os.environ["HOME"] = HOME


class Addons(unittest.TestCase):
    def setUp(self):
        self.saved = addons.CONF
        addons.CONF = os.path.join(tempfile.mkdtemp(), "addons.json")
        self.addCleanup(setattr, addons, "CONF", self.saved)

    def test_all_on_by_default(self):
        self.assertEqual([a.id for a in addons.enabled()], [a.id for a in addons.ADDONS])
        self.assertIsNotNone(addons.route("/api/youtube"))

    def test_turned_off(self):
        addons.set_enabled({"id": "youtube", "enabled": False})
        self.assertNotIn("youtube", [a.id for a in addons.enabled()])
        self.assertIsNone(addons.route("/api/youtube"))   # its routes answer 404
        self.assertIsNone(addons.more_source("yt_search"))
        self.assertIsNone(addons.for_kind("youtube"))
        self.assertNotIn("youtube", addons.state()["addons"])
        with self.assertRaises(ValueError):   # its actions are refused
            addons.actions()["youtube_sync"]({})
        with self.assertRaises(ValueError):   # no rows
            addons.rows({"addon": "youtube"})
        self.assertFalse(next(a for a in addons.listing()["addons"] if a["id"] == "youtube")["enabled"])
        addons.set_enabled({"id": "youtube", "enabled": True})
        self.assertIsNotNone(addons.route("/api/youtube"))

    def test_base_stays_on(self):
        with self.assertRaises(ValueError):
            addons.set_enabled({"id": "twitch", "enabled": False})
        self.assertTrue(next(a for a in addons.listing()["addons"] if a["id"] == "twitch")["base"])


if __name__ == "__main__":
    unittest.main()
