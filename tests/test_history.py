"""history.py: one key per video whatever the form of its link, and the "finished" rule."""
import sys, unittest

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

    def test_other_link(self):
        self.assertEqual(history.media_key("https://example.org/a.mp4"), ("https://example.org/a.mp4", "link", None))

    def test_finished(self):
        self.assertFalse(history.finished(10, 0))
        self.assertFalse(history.finished(50, 100))
        self.assertTrue(history.finished(96, 100))
        self.assertTrue(history.finished(3500, 3600))


if __name__ == "__main__":
    unittest.main()
