"""history.py: one key per video whatever the form of its link, and the "finished" rule."""
import os, sys, tempfile, unittest

from tests.helpers import REPO

sys.path.insert(0, REPO)
import history   # noqa: E402

YT = "dQw4w9WgXcQ"
JF = "0123456789abcdef0123456789abcdef"


class MediaKey(unittest.TestCase):
    def test_youtube_forms(self):
        for url in (f"https://www.youtube.com/watch?v={YT}", f"https://youtube.com/watch?feature=x&v={YT}",
                    f"https://youtu.be/{YT}?t=42", f"https://www.youtube.com/shorts/{YT}",
                    f"https://www.youtube.com/live/{YT}"):
            with self.subTest(url=url):
                self.assertEqual(history.media_key(url), (f"youtube:{YT}", "youtube", YT))

    def test_jellyfin(self):
        expected = (f"jellyfin:{JF}", "jellyfin", JF)
        self.assertEqual(history.media_key(f"jellyfin:{JF}"), expected)
        self.assertEqual(history.media_key(f"http://server:8096/Videos/{JF}/stream?static=true"), expected)

    def test_twitch(self):
        self.assertEqual(history.media_key("https://www.twitch.tv/videos/123456"),
                         ("twitch-vod:123456", "twitch-vod", "123456"))
        for url in ("https://clips.twitch.tv/FunnyClip-abc", "https://www.twitch.tv/someone/clip/FunnyClip-abc"):
            self.assertEqual(history.media_key(url), ("twitch-clip:FunnyClip-abc", "twitch-clip", "FunnyClip-abc"))

    def test_plex(self):
        self.assertEqual(history.media_key("plex:1234"), ("plex:1234", "plex", "1234"))
        # file of a Plex server: the kind is known (TV menu tab), not the item
        self.assertEqual(history.media_key("http://server:32400/library/parts/12/1793110935/file.mkv?X-Plex-Token=t")[1:],
                         ("plex", None))

    def test_other_link(self):
        self.assertEqual(history.media_key("https://example.org/a.mp4"), ("https://example.org/a.mp4", "link", None))

    def test_finished(self):
        self.assertFalse(history.finished(10, 0))
        self.assertFalse(history.finished(50, 100))
        self.assertTrue(history.finished(96, 100))
        self.assertTrue(history.finished(3500, 3600))


class UsbDrive(unittest.TestCase):
    # system on a USB drive: positions written at most once a minute, kept in memory in between
    def setUp(self):
        saved = {k: getattr(history, k) for k in ("HISTORY_FILE", "WRITE_EVERY", "pending", "last_write")}
        self.addCleanup(lambda: [setattr(history, k, v) for k, v in saved.items()])
        history.HISTORY_FILE = os.path.join(tempfile.mkdtemp(), "history.json")
        history.WRITE_EVERY, history.pending, history.last_write = 60, None, 0.0

    def written(self):
        with open(history.HISTORY_FILE) as f:
            return f.read()

    def test_positions_once_a_minute(self):
        video = {"key": "link:a", "url": "https://example.org/a.mp4", "kind": "link"}
        history.record(video, 100, 1000)   # first one: written
        self.assertIn('"position": 100', self.written())
        history.record(video, 110, 1000)   # within the minute: in memory only
        self.assertIn('"position": 100', self.written())
        self.assertEqual(history.read_history()[0]["position"], 110)
        history.flush()                    # not a minute yet
        self.assertIn('"position": 100', self.written())
        history.flush(force=True)          # stopping
        self.assertIn('"position": 110', self.written())
        history.record(video, 120, 1000)
        history.edit_history("clear")      # explicit action: written at once
        self.assertEqual(self.written(), "[]")


if __name__ == "__main__":
    unittest.main()
