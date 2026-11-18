"""btsetup.py (Bluetooth pairing) against a fake bluetoothctl: devices show up during the scan, the first gamepad seen
gets paired by itself, a device already paired here (its bond lost) is removed and paired again."""
import json, os, stat, sys, tempfile, time, unittest

from tests.helpers import REPO

sys.path.insert(0, os.path.join(REPO, "app", "system"))
import btsetup   # noqa: E402

XBOX, TV = "3C:FA:06:20:D9:17", "70:B1:3D:A7:AA:39"

FAKE = r'''#!/usr/bin/env python3
import fcntl, json, os, sys, time
path = os.environ["FAKE_BT"]


def change(fn):
    # read, change and write the fake's state under a lock (several bluetoothctl run at once)
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        st = json.load(open(path))
        out = fn(st)
        with open(path + ".tmp", "w") as f:
            json.dump(st, f)
        os.replace(path + ".tmp", path)   # (the test reads it meanwhile)
        return out


a = sys.argv[1:]
while a[:1] in (["--timeout"], ["--agent"]):
    a = a[2:]
air = change(lambda st: st["log"].append(" ".join(a)) or st["air"])
if a == ["scan", "on"]:
    print("Discovery started", flush=True)
    for mac, d in air.items():
        time.sleep(0.05)
        change(lambda st: st["devices"].setdefault(mac, {}).update(name=d["name"]))
        print("\x1b[0;93m[NEW]\x1b[0m Device %s %s" % (mac, mac.replace(":", "-")), flush=True)
        print("[CHG] Device %s Name: %s" % (mac, d["name"]), flush=True)
        print("[CHG] Device %s Icon: %s" % (mac, d["icon"]), flush=True)
    time.sleep(30)
elif a[:1] == ["info"]:
    d = change(lambda st: st["devices"].get(a[1]))
    if d is None:
        print("Device %s not available" % a[1])
    else:
        print("Device %s (public)\n\tName: %s\n\tIcon: %s\n\tPaired: %s\n\tConnected: %s\n\tTrusted: %s" % (
            a[1], d.get("name", ""), air.get(a[1], {}).get("icon", ""), "yes" if d.get("paired") else "no",
            "yes" if d.get("connected") else "no", "yes" if d.get("trusted") else "no"))
elif a[:1] == ["pair"]:
    def pair(st):
        d = st["devices"].get(a[1])
        if d is not None and not d.get("paired") and not st["air"].get(a[1], {}).get("stale"):
            d["paired"] = True
    change(pair)
elif a[:1] == ["remove"]:
    change(lambda st: st["devices"].pop(a[1], None))
elif a[:1] in (["trust"], ["connect"]):
    change(lambda st: st["devices"].setdefault(a[1], {}).update({"trusted" if a[0] == "trust" else "connected": True}))
elif a[:2] == ["devices", "Paired"]:
    for m, d in change(lambda st: dict(st["devices"])).items():
        if d.get("paired"):
            print("Device %s %s" % (m, d.get("name", m)))
'''


class Pairing(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        tool = os.path.join(d, "bluetoothctl")
        with open(tool, "w") as f:
            f.write(FAKE)
        os.chmod(tool, stat.S_IRWXU)
        self.state = os.path.join(d, "state.json")
        self.write({"air": {TV: {"name": "TV Salon", "icon": ""},
                            XBOX: {"name": "Xbox Wireless Controller", "icon": "input-gaming"}},
                    "devices": {}, "log": []})
        env = {"PATH": d + os.pathsep + os.environ["PATH"], "FAKE_BT": self.state,
               "XDG_RUNTIME_DIR": d}
        self.addCleanup(os.environ.update, dict(os.environ))
        os.environ.update(env)
        btsetup.PAIRING_FLAG = os.path.join(d, "flag")
        btsetup.state.update(scanning=False, busy=None, message=None, found={}, auto=False, error=False)
        self.addCleanup(btsetup.stop_scan)

    def write(self, st):
        with open(self.state, "w") as f:
            json.dump(st, f)

    def read(self):
        with open(self.state) as f:
            return json.load(f)

    def wait(self, cond, seconds=10):
        end = time.time() + seconds
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.05)
        return False

    def test_parse(self):
        seen = {}
        self.assertEqual(btsetup.parse("[NEW] Device %s %s" % (XBOX, XBOX.replace(":", "-")), seen), XBOX)
        self.assertEqual(btsetup.parse("[CHG] Device %s Name: Xbox Wireless Controller" % XBOX, seen), XBOX)
        self.assertEqual(seen[XBOX]["name"], "Xbox Wireless Controller")
        self.assertIsNone(btsetup.parse("[CHG] Device %s Connected: yes" % XBOX, seen))
        self.assertIsNone(btsetup.parse("  42 04 01 20 67", seen))
        btsetup.parse("[DEL] Device %s" % XBOX, seen)
        self.assertNotIn(XBOX, seen)

    def test_auto_pairs_the_gamepad(self):
        btsetup.scan(auto=True)
        self.assertTrue(self.wait(lambda: self.read()["devices"].get(XBOX, {}).get("connected")))
        self.assertTrue(self.wait(lambda: not btsetup.state["busy"]))
        st = btsetup.status()
        self.assertFalse(st["error"])
        self.assertIn("Xbox Wireless Controller", st["message"])
        self.assertNotIn("pair " + TV, self.read()["log"])   # the TV is not an input device

    def test_already_paired_is_paired_again(self):
        st = self.read()
        st["devices"][XBOX] = {"name": "Xbox Wireless Controller", "paired": True, "trusted": True}
        self.write(st)
        btsetup.scan()
        self.assertTrue(self.wait(lambda: XBOX in btsetup.state["found"]))
        self.assertTrue(btsetup.state["found"][XBOX]["paired"])   # offered again ("pair again")
        btsetup.pair(XBOX)
        self.assertTrue(self.wait(lambda: not btsetup.state["busy"] and btsetup.state["message"]
                                  and "connected" in btsetup.state["message"]))
        log = self.read()["log"]
        self.assertLess(log.index("remove " + XBOX), log.index("pair " + XBOX))

    def test_failure_says_so(self):
        st = self.read()
        st["air"][XBOX]["stale"] = True
        st["devices"][XBOX] = {"name": "Xbox Wireless Controller", "stale": True}
        self.write(st)
        btsetup.PAIR_SECONDS, btsetup.FIND_AGAIN_SECONDS = 2, 2
        self.addCleanup(setattr, btsetup, "PAIR_SECONDS", 30)
        self.addCleanup(setattr, btsetup, "FIND_AGAIN_SECONDS", 15)
        btsetup.pair(XBOX)
        self.assertTrue(self.wait(lambda: not btsetup.state["busy"] and btsetup.state["error"], 20))


if __name__ == "__main__":
    unittest.main()
