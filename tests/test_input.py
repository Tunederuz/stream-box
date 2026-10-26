"""input.py: keys read at the source, turned into actions; held keys repeated by input.py itself."""
import json, os, subprocess, sys, unittest

from tests.helpers import REPO, temp_home

KEY_DOWN, KEY_ENTER, KEY_UP = 108, 28, 103


def run(events):
    """Actions sent for these events ([delay, code, value]: 1 press, 2 kernel repeat, 0 release)"""
    out = subprocess.run([sys.executable, os.path.join(REPO, "tests", "input_device.py"), json.dumps(events)],
                         capture_output=True, text=True, timeout=30, env=dict(os.environ, HOME=temp_home()))
    return json.loads(out.stdout.strip().splitlines()[-1])


class Input(unittest.TestCase):
    def test_held_arrow_repeats_until_release(self):
        sent = run([[0.2, KEY_DOWN, 1], [1.0, KEY_DOWN, 0]])
        self.assertTrue(all(s[2] == "down" for s in sent))
        # one press, then repeats from 0.4 s every 0.08 s while held (1 s): about 8
        self.assertGreaterEqual(len(sent), 6)
        self.assertLessEqual(len(sent), 11)
        self.assertGreaterEqual(sent[1][0] - sent[0][0], 0.35)

    def test_ok_does_not_repeat(self):
        sent = run([[0.2, KEY_ENTER, 1], [0.9, KEY_ENTER, 0]])
        self.assertEqual([s[2] for s in sent], ["ok"])

    def test_kernel_repeats_ignored(self):
        sent = run([[0.2, KEY_UP, 1], [0.03, KEY_UP, 2], [0.03, KEY_UP, 2], [0.1, KEY_UP, 0]])
        self.assertEqual([s[2] for s in sent], ["up"])


if __name__ == "__main__":
    unittest.main()
