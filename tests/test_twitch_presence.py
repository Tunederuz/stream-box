"""addons/twitch presence: the "minute-watched" event the twitch.tv player sends, with the account and the live."""
import base64, json, os, unittest, urllib.parse
from unittest import mock

from tests.helpers import temp_home

HOME = os.environ.get("HOME", "")
os.environ["HOME"] = temp_home()   # while importing: the modules read their paths from it
from addons.twitch import service as twitch   # noqa: E402
os.environ["HOME"] = HOME


class Answer:
    status = 204

    def __init__(self, body=b""):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Presence(unittest.TestCase):
    def setUp(self):
        twitch.presence.update(spade=None, spade_at=0, user=None)
        self.sent = []

    def urlopen(self, req, timeout=None):
        url = req.full_url
        if url == "https://www.twitch.tv/twitch":
            return Answer(b'<script src="https://assets.twitch.tv/config/settings.abc123.js"></script>')
        if url == "https://assets.twitch.tv/config/settings.abc123.js":
            return Answer(b'window.__twilightSettings = {"spade_url":"https://spade.example/track","x":1}')
        self.sent.append((url, req.data))
        return Answer()

    def gql(self, query, variables=None):
        if "currentUser" in query:
            return {"currentUser": {"id": "42"}}
        return {"user": {"id": "1001", "stream": {"id": "555"} if variables["l"] == "live_one" else None}}

    def test_minute_watched(self):
        with mock.patch.object(twitch.urllib.request, "urlopen", self.urlopen), \
             mock.patch.object(twitch, "twitch_gql", self.gql):
            self.assertTrue(twitch.minute_watched("live_one"))
            self.assertFalse(twitch.minute_watched("offline_one"))   # not live: nothing sent
        self.assertEqual(len(self.sent), 1)
        url, body = self.sent[0]
        self.assertEqual(url, "https://spade.example/track")
        event = json.loads(base64.b64decode(urllib.parse.parse_qs(body.decode())["data"][0]))
        self.assertEqual(event, [{"event": "minute-watched", "properties": {
            "channel_id": "1001", "broadcast_id": "555", "player": "site", "user_id": "42", "live": True,
            "channel": "live_one"}}])


if __name__ == "__main__":
    unittest.main()
