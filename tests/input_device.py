"""Helper of test_input.py: runs input.py's main loop on a fake input device (a FIFO) and prints, as JSON, the actions
it sends to mpv with their time. Usage: input_device.py EVENTS_JSON ([[delay, code, value], …], times in seconds)"""
import json, os, sys, tempfile, threading, time

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path[:0] = [os.path.join(APP, "player"), os.path.join(APP, "system")]
import input as inp   # noqa: E402

events = json.loads(sys.argv[1])
fifo = os.path.join(tempfile.mkdtemp(), "event0")
os.mkfifo(fifo)
sent, t0 = [], time.time()


class FakeMpv:
    def send(self, *args):
        if args[:2] == ("script-message", "streambox-input"):
            sent.append([round(time.time() - t0, 2), args[2], args[3]])


def feed():
    with open(fifo, "wb", buffering=0) as f:
        for delay, code, value in events:
            time.sleep(delay)
            f.write(inp.EVENT.pack(0, 0, inp.EV_KEY, code, value))
        time.sleep(0.4)
    print(json.dumps(sent), flush=True)
    os._exit(0)


inp.Mpv = FakeMpv
inp.keyboards = lambda: {fifo: "Fake RC Consumer Control"}
threading.Thread(target=feed, daemon=True).start()
inp.main()
