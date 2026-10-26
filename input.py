#!/usr/bin/env python3
"""Stream Box: keys read at the source (Bluetooth remotes, gamepads, keyboards), turned into actions.

Reads /dev/input/event* (the user must be in the input group), with Linux's standard names (KEY_UP, KEY_SELECT,
BTN_SOUTH…), and sends to mpv, through its IPC:
  script-message streambox-input <key name> <action or empty>
stream-box.lua plays the action (or, during the "Set up keys" wizard, learns the key). Actions: up down left right ok
back home (TV menu) menu (options ≡) homescreen corner power volume_up volume_down mute.
Mapping: DEFAULTS below, then ~/.config/stream-box/keymap.json ({"KEY_…": "action"}, written by the wizard), read again
when it changes. While this service runs, it announces it (user-data/streambox/input) and the Qt app and mpv ignore the
keys they receive themselves (otherwise each one would count twice); without permissions on the devices, it stops and
the old path (keys received by the Qt app or mpv) takes over again. Started by start.sh.
"""
import json, os, re, select, socket, struct, sys, time

from i18n import tr

MPV_SOCKET = "/tmp/stream-box-mpv.sock"
KEYMAP_FILE = os.path.expanduser("~/.config/stream-box/keymap.json")
EVENT = struct.Struct("llHHi")   # input_event: time (2 longs), type, code, value
EV_KEY, EV_ABS = 1, 3
ABS_HAT0X, ABS_HAT0Y = 16, 17
REPEATABLE = {"up", "down", "left", "right", "volume_up", "volume_down"}
LONG_PRESS = 1   # seconds: power held → "sleep, restart, shut down" window (power_menu) instead of power
DEFAULTS = {
    # Remotes (including Xiaomi: OK = KEY_SELECT, ≡ = KEY_VIDEOPHONE, assistant = KEY_VOICECOMMAND), keyboards
    "KEY_UP": "up", "KEY_DOWN": "down", "KEY_LEFT": "left", "KEY_RIGHT": "right",
    "KEY_ENTER": "ok", "KEY_KPENTER": "ok", "KEY_SELECT": "ok", "KEY_OK": "ok",
    "KEY_BACK": "back", "KEY_ESC": "back", "KEY_BACKSPACE": "back",
    "KEY_HOMEPAGE": "home", "KEY_HOME": "home",
    "KEY_MENU": "menu", "KEY_COMPOSE": "menu", "KEY_VIDEOPHONE": "menu", "KEY_VOICECOMMAND": "menu", "KEY_INFO": "menu",
    "KEY_WWW": "homescreen", "KEY_PLAYPAUSE": "corner", "KEY_PLAY": "corner", "KEY_POWER": "power",
    "KEY_VOLUMEUP": "volume_up", "KEY_VOLUMEDOWN": "volume_down", "KEY_MUTE": "mute",
    # Regular keyboard: Space play / pause, Windows or M TV menu, O options, H home screen, + / − volume, media keys.
    # Linux codes are positional (QWERTY): the M of an AZERTY keyboard sends KEY_SEMICOLON
    "KEY_SPACE": "corner", "KEY_LEFTMETA": "home", "KEY_RIGHTMETA": "home", "KEY_M": "home", "KEY_SEMICOLON": "home", "KEY_O": "menu", "KEY_H": "homescreen",
    "KEY_KPPLUS": "volume_up", "KEY_KPMINUS": "volume_down", "KEY_EQUAL": "volume_up", "KEY_MINUS": "volume_down",
    "KEY_NEXTSONG": "right", "KEY_PREVIOUSSONG": "left", "KEY_STOPCD": "back",
    # Gamepads
    "BTN_DPAD_UP": "up", "BTN_DPAD_DOWN": "down", "BTN_DPAD_LEFT": "left", "BTN_DPAD_RIGHT": "right",
    "BTN_SOUTH": "ok", "BTN_EAST": "back", "BTN_START": "home", "BTN_SELECT": "menu", "BTN_MODE": "homescreen",
}
IGNORED = re.compile(r"HDA |Video Bus|PC Speaker|WMI hotkeys|Sleep Button|Lid Switch|ydotool|Power Button$")


def key_name(code):
    n = NAMES.get(code)
    return (n if n.startswith("BTN_") else "KEY_" + n) if n else f"KEY_{code}"


def keyboards():
    """Devices with keys (not the headphone jacks, the video card…): {path: name}"""
    found, name = {}, ""
    try:
        with open("/proc/bus/input/devices", encoding="utf-8", errors="replace") as f:
            blocks = f.read().split("\n\n")
    except OSError:
        return found
    for b in blocks:
        name = (re.search(r'^N: Name="(.*)"$', b, re.M) or [None, ""])[1]
        handlers = (re.search(r"^H: Handlers=(.*)$", b, re.M) or [None, ""])[1]
        ev = int((re.search(r"^B: EV=(\w+)$", b, re.M) or [None, "0"])[1], 16)
        event = re.search(r"\bevent\d+\b", handlers)
        if event and ev & (1 << EV_KEY) and not IGNORED.search(name):
            found[f"/dev/input/{event.group(0)}"] = name
    return found


class Keymap:
    def __init__(self):
        self.mtime, self.custom = None, {}

    def get(self, name):
        try:
            mtime = os.path.getmtime(KEYMAP_FILE)
        except OSError:
            mtime = None
        if mtime != self.mtime:
            self.mtime, self.custom = mtime, {}
            if mtime:
                try:
                    with open(KEYMAP_FILE, encoding="utf-8") as f:
                        self.custom = {k: v for k, v in json.load(f).items() if isinstance(v, str)}
                except (OSError, ValueError):
                    pass
        return self.custom.get(name) or DEFAULTS.get(name) or ""


class Mpv:
    def __init__(self):
        self.sock = None

    def send(self, *command):
        for _ in range(2):
            try:
                if self.sock is None:
                    self.sock = socket.socket(socket.AF_UNIX)
                    self.sock.connect(MPV_SOCKET)
                self.sock.sendall((json.dumps({"command": list(command)}) + "\n").encode())
                return True
            except OSError:
                self.sock = None   # player restarted: reconnect
                time.sleep(0.2)
        return False


def main():
    mpv, keymap = Mpv(), Keymap()
    devices = {}            # path -> open file
    hat = {}                # (path, axis) -> last value of the gamepad d-pad
    held = {}               # (path, code) -> [press time, name, window already open] for power keys
    last_scan = last_beat = 0
    allowed = None
    first_scan = True       # devices already there at startup: no notification
    noticed = {}            # base name -> last state announced (one device = often several entries)
    names = {}              # path -> device name, to announce its disconnection

    def base_name(name):   # "Xiaomi RC Keyboard" and "Xiaomi RC Consumer Control": the same remote
        return re.sub(r"\s+(Keyboard|Consumer Control|System Control|Mouse|Touchpad)$", "", name).strip()

    def notice(name, connected):
        """Banner on the TV (Notice.qml) when a device changes state: a quick disconnection then reconnection
        shows both, the several entries of one device only once"""
        base = base_name(name)
        if noticed.get(base) != connected:
            noticed[base] = connected
            mpv.send("script-message", "streambox-notice", tr("Device connected · {name}", name=base) if connected else
                     tr("Device disconnected · {name}", name=base))

    def drop(path):
        devices.pop(path).close()
        name = names.pop(path, "")
        if name and base_name(name) not in map(base_name, names.values()):   # no entry left for this device
            notice(name, False)
    while True:
        now = time.time()
        if now - last_scan > 2:   # plugs and Bluetooth reconnections
            last_scan = now
            present = keyboards()
            for path in list(devices):
                if path not in present:
                    drop(path)
            for path, name in present.items():
                if path not in devices:
                    try:
                        devices[path] = open(path, "rb", buffering=0)
                        allowed = True
                        print(f"input.py: {name} ({path})", flush=True)
                        names[path] = name
                        if not first_scan:   # remote, gamepad or keyboard connecting
                            notice(name, True)
                        else:                # already there at startup: known as connected, no banner
                            noticed[base_name(name)] = True
                    except PermissionError:
                        if allowed is None:
                            allowed = False
                    except OSError:
                        pass
            first_scan = False
            if allowed is False and not devices:
                # Not in the input group: leave the keys to the Qt app and mpv
                mpv.send("set_property", "user-data/streambox/input", "")
                sys.exit("input.py: no permissions on /dev/input (input group); keys left to the app and mpv")
        if now - last_beat > 5:   # "this service is running" (stream-box.lua and ui.py then ignore their keys)
            last_beat = now
            mpv.send("set_property", "user-data/streambox/input", f"evdev:{int(now)}")
        for k, h in held.items():   # power held long enough: box window, without waiting for the release
            if not h[2] and time.time() - h[0] >= LONG_PRESS:
                h[2] = True
                mpv.send("script-message", "streambox-input", h[1], "power_menu")
        ready, _, _ = select.select(list(devices.values()), [], [], 0.2 if held else 1)
        for f in ready:
            path = next(p for p, d in devices.items() if d is f)
            try:
                data = f.read(EVENT.size * 64)
            except OSError:   # device gone
                drop(path)
                continue
            for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _, _, etype, code, value = EVENT.unpack_from(data, i)
                if etype == EV_KEY and keymap.get(key_name(code)) == "power":
                    # power: action on release (short press), or window after LONG_PRESS (see above)
                    if value == 1:
                        held[(path, code)] = [time.time(), key_name(code), False]
                    elif value == 0:
                        h = held.pop((path, code), None)
                        if h and not h[2]:
                            mpv.send("script-message", "streambox-input", h[1], "power")
                elif etype == EV_KEY and value in (1, 2):   # press, or repeat of a held key
                    name = key_name(code)
                    action = keymap.get(name)
                    if value == 2 and action not in REPEATABLE:
                        continue
                    mpv.send("script-message", "streambox-input", name, action)
                elif etype == EV_ABS and code in (ABS_HAT0X, ABS_HAT0Y):   # gamepad d-pad
                    if value and hat.get((path, code)) != value:
                        names = {(ABS_HAT0X, -1): "HAT_LEFT", (ABS_HAT0X, 1): "HAT_RIGHT",
                                 (ABS_HAT0Y, -1): "HAT_UP", (ABS_HAT0Y, 1): "HAT_DOWN"}
                        name = names[(code, 1 if value > 0 else -1)]
                        mpv.send("script-message", "streambox-input", name,
                                 keymap.get(name) or name.split("_")[1].lower())
                    hat[(path, code)] = value


# Names of Linux key codes (linux/input-event-codes.h; "KEY_" removed except for BTN_)
NAMES = {
    1: "ESC", 2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0", 12: "MINUS",
    13: "EQUAL", 14: "BACKSPACE", 15: "TAB", 16: "Q", 17: "W", 18: "E", 19: "R", 20: "T", 21: "Y", 22: "U", 23: "I",
    24: "O", 25: "P", 26: "LEFTBRACE", 27: "RIGHTBRACE", 28: "ENTER", 29: "LEFTCTRL", 30: "A", 31: "S", 32: "D",
    33: "F", 34: "G", 35: "H", 36: "J", 37: "K", 38: "L", 39: "SEMICOLON", 40: "APOSTROPHE", 41: "GRAVE",
    42: "LEFTSHIFT", 43: "BACKSLASH", 44: "Z", 45: "X", 46: "C", 47: "V", 48: "B", 49: "N", 50: "M", 51: "COMMA",
    52: "DOT", 53: "SLASH", 54: "RIGHTSHIFT", 55: "KPASTERISK", 56: "LEFTALT", 57: "SPACE", 58: "CAPSLOCK", 59: "F1",
    60: "F2", 61: "F3", 62: "F4", 63: "F5", 64: "F6", 65: "F7", 66: "F8", 67: "F9", 68: "F10", 69: "NUMLOCK",
    70: "SCROLLLOCK", 71: "KP7", 72: "KP8", 73: "KP9", 74: "KPMINUS", 75: "KP4", 76: "KP5", 77: "KP6", 78: "KPPLUS",
    79: "KP1", 80: "KP2", 81: "KP3", 82: "KP0", 83: "KPDOT", 85: "ZENKAKUHANKAKU", 86: "102ND", 87: "F11", 88: "F12",
    89: "RO", 90: "KATAKANA", 91: "HIRAGANA", 92: "HENKAN", 93: "KATAKANAHIRAGANA", 94: "MUHENKAN", 95: "KPJPCOMMA",
    96: "KPENTER", 97: "RIGHTCTRL", 98: "KPSLASH", 99: "SYSRQ", 100: "RIGHTALT", 101: "LINEFEED", 102: "HOME",
    103: "UP", 104: "PAGEUP", 105: "LEFT", 106: "RIGHT", 107: "END", 108: "DOWN", 109: "PAGEDOWN", 110: "INSERT",
    111: "DELETE", 112: "MACRO", 113: "MUTE", 114: "VOLUMEDOWN", 115: "VOLUMEUP", 116: "POWER", 117: "KPEQUAL",
    118: "KPPLUSMINUS", 119: "PAUSE", 120: "SCALE", 121: "KPCOMMA", 122: "HANGEUL", 123: "HANJA", 124: "YEN",
    125: "LEFTMETA", 126: "RIGHTMETA", 127: "COMPOSE", 128: "STOP", 129: "AGAIN", 130: "PROPS", 131: "UNDO",
    132: "FRONT", 133: "COPY", 134: "OPEN", 135: "PASTE", 136: "FIND", 137: "CUT", 138: "HELP", 139: "MENU",
    140: "CALC", 141: "SETUP", 142: "SLEEP", 143: "WAKEUP", 144: "FILE", 145: "SENDFILE", 146: "DELETEFILE",
    147: "XFER", 148: "PROG1", 149: "PROG2", 150: "WWW", 151: "MSDOS", 152: "COFFEE", 153: "ROTATE_DISPLAY",
    154: "CYCLEWINDOWS", 155: "MAIL", 156: "BOOKMARKS", 157: "COMPUTER", 158: "BACK", 159: "FORWARD", 160: "CLOSECD",
    161: "EJECTCD", 162: "EJECTCLOSECD", 163: "NEXTSONG", 164: "PLAYPAUSE", 165: "PREVIOUSSONG", 166: "STOPCD",
    167: "RECORD", 168: "REWIND", 169: "PHONE", 170: "ISO", 171: "CONFIG", 172: "HOMEPAGE", 173: "REFRESH",
    174: "EXIT", 175: "MOVE", 176: "EDIT", 177: "SCROLLUP", 178: "SCROLLDOWN", 179: "KPLEFTPAREN",
    180: "KPRIGHTPAREN", 181: "NEW", 182: "REDO", 183: "F13", 184: "F14", 185: "F15", 186: "F16", 187: "F17",
    188: "F18", 189: "F19", 190: "F20", 191: "F21", 192: "F22", 193: "F23", 194: "F24", 200: "PLAYCD",
    201: "PAUSECD", 202: "PROG3", 203: "PROG4", 204: "ALL_APPLICATIONS", 205: "SUSPEND", 206: "CLOSE", 207: "PLAY",
    208: "FASTFORWARD", 209: "BASSBOOST", 210: "PRINT", 211: "HP", 212: "CAMERA", 213: "SOUND", 214: "QUESTION",
    215: "EMAIL", 216: "CHAT", 217: "SEARCH", 218: "CONNECT", 219: "FINANCE", 220: "SPORT", 221: "SHOP",
    222: "ALTERASE", 223: "CANCEL", 224: "BRIGHTNESSDOWN", 225: "BRIGHTNESSUP", 226: "MEDIA", 227: "SWITCHVIDEOMODE",
    228: "KBDILLUMTOGGLE", 229: "KBDILLUMDOWN", 230: "KBDILLUMUP", 231: "SEND", 232: "REPLY", 233: "FORWARDMAIL",
    234: "SAVE", 235: "DOCUMENTS", 236: "BATTERY", 237: "BLUETOOTH", 238: "WLAN", 239: "UWB", 240: "UNKNOWN",
    241: "VIDEO_NEXT", 242: "VIDEO_PREV", 243: "BRIGHTNESS_CYCLE", 244: "BRIGHTNESS_AUTO", 245: "DISPLAY_OFF",
    246: "WWAN", 247: "RFKILL", 248: "MICMUTE", 256: "BTN_0", 257: "BTN_1", 258: "BTN_2", 259: "BTN_3", 260: "BTN_4",
    261: "BTN_5", 262: "BTN_6", 263: "BTN_7", 264: "BTN_8", 265: "BTN_9", 272: "BTN_LEFT", 273: "BTN_RIGHT",
    274: "BTN_MIDDLE", 275: "BTN_SIDE", 276: "BTN_EXTRA", 277: "BTN_FORWARD", 278: "BTN_BACK", 279: "BTN_TASK",
    288: "BTN_TRIGGER", 289: "BTN_THUMB", 290: "BTN_THUMB2", 291: "BTN_TOP", 292: "BTN_TOP2", 293: "BTN_PINKIE",
    294: "BTN_BASE", 295: "BTN_BASE2", 296: "BTN_BASE3", 297: "BTN_BASE4", 298: "BTN_BASE5", 299: "BTN_BASE6",
    303: "BTN_DEAD", 304: "BTN_SOUTH", 305: "BTN_EAST", 306: "BTN_C", 307: "BTN_NORTH", 308: "BTN_WEST",
    309: "BTN_Z", 310: "BTN_TL", 311: "BTN_TR", 312: "BTN_TL2", 313: "BTN_TR2", 314: "BTN_SELECT", 315: "BTN_START",
    316: "BTN_MODE", 317: "BTN_THUMBL", 318: "BTN_THUMBR", 320: "BTN_TOOL_PEN", 321: "BTN_TOOL_RUBBER",
    322: "BTN_TOOL_BRUSH", 323: "BTN_TOOL_PENCIL", 324: "BTN_TOOL_AIRBRUSH", 325: "BTN_TOOL_FINGER",
    326: "BTN_TOOL_MOUSE", 327: "BTN_TOOL_LENS", 328: "BTN_TOOL_QUINTTAP", 329: "BTN_STYLUS3", 330: "BTN_TOUCH",
    331: "BTN_STYLUS", 332: "BTN_STYLUS2", 333: "BTN_TOOL_DOUBLETAP", 334: "BTN_TOOL_TRIPLETAP",
    335: "BTN_TOOL_QUADTAP", 336: "BTN_GEAR_DOWN", 337: "BTN_GEAR_UP", 352: "OK", 353: "SELECT", 354: "GOTO",
    355: "CLEAR", 356: "POWER2", 357: "OPTION", 358: "INFO", 359: "TIME", 360: "VENDOR", 361: "ARCHIVE",
    362: "PROGRAM", 363: "CHANNEL", 364: "FAVORITES", 365: "EPG", 366: "PVR", 367: "MHP", 368: "LANGUAGE",
    369: "TITLE", 370: "SUBTITLE", 371: "ANGLE", 372: "FULL_SCREEN", 373: "MODE", 374: "KEYBOARD",
    375: "ASPECT_RATIO", 376: "PC", 377: "TV", 378: "TV2", 379: "VCR", 380: "VCR2", 381: "SAT", 382: "SAT2",
    383: "CD", 384: "TAPE", 385: "RADIO", 386: "TUNER", 387: "PLAYER", 388: "TEXT", 389: "DVD", 390: "AUX",
    391: "MP3", 392: "AUDIO", 393: "VIDEO", 394: "DIRECTORY", 395: "LIST", 396: "MEMO", 397: "CALENDAR", 398: "RED",
    399: "GREEN", 400: "YELLOW", 401: "BLUE", 402: "CHANNELUP", 403: "CHANNELDOWN", 404: "FIRST", 405: "LAST",
    406: "AB", 407: "NEXT", 408: "RESTART", 409: "SLOW", 410: "SHUFFLE", 411: "BREAK", 412: "PREVIOUS",
    413: "DIGITS", 414: "TEEN", 415: "TWEN", 416: "VIDEOPHONE", 417: "GAMES", 418: "ZOOMIN", 419: "ZOOMOUT",
    420: "ZOOMRESET", 421: "WORDPROCESSOR", 422: "EDITOR", 423: "SPREADSHEET", 424: "GRAPHICSEDITOR",
    425: "PRESENTATION", 426: "DATABASE", 427: "NEWS", 428: "VOICEMAIL", 429: "ADDRESSBOOK", 430: "MESSENGER",
    431: "DISPLAYTOGGLE", 432: "SPELLCHECK", 433: "LOGOFF", 434: "DOLLAR", 435: "EURO", 436: "FRAMEBACK",
    437: "FRAMEFORWARD", 438: "CONTEXT_MENU", 439: "MEDIA_REPEAT", 440: "10CHANNELSUP", 441: "10CHANNELSDOWN",
    442: "IMAGES", 444: "NOTIFICATION_CENTER", 445: "PICKUP_PHONE", 446: "HANGUP_PHONE", 447: "LINK_PHONE",
    448: "DEL_EOL", 449: "DEL_EOS", 450: "INS_LINE", 451: "DEL_LINE", 464: "FN", 465: "FN_ESC", 466: "FN_F1",
    467: "FN_F2", 468: "FN_F3", 469: "FN_F4", 470: "FN_F5", 471: "FN_F6", 472: "FN_F7", 473: "FN_F8", 474: "FN_F9",
    475: "FN_F10", 476: "FN_F11", 477: "FN_F12", 478: "FN_1", 479: "FN_2", 480: "FN_D", 481: "FN_E", 482: "FN_F",
    483: "FN_S", 484: "FN_B", 485: "FN_RIGHT_SHIFT", 497: "BRL_DOT1", 498: "BRL_DOT2", 499: "BRL_DOT3",
    500: "BRL_DOT4", 501: "BRL_DOT5", 502: "BRL_DOT6", 503: "BRL_DOT7", 504: "BRL_DOT8", 505: "BRL_DOT9",
    506: "BRL_DOT10", 512: "NUMERIC_0", 513: "NUMERIC_1", 514: "NUMERIC_2", 515: "NUMERIC_3", 516: "NUMERIC_4",
    517: "NUMERIC_5", 518: "NUMERIC_6", 519: "NUMERIC_7", 520: "NUMERIC_8", 521: "NUMERIC_9", 522: "NUMERIC_STAR",
    523: "NUMERIC_POUND", 524: "NUMERIC_A", 525: "NUMERIC_B", 526: "NUMERIC_C", 527: "NUMERIC_D",
    528: "CAMERA_FOCUS", 529: "WPS_BUTTON", 530: "TOUCHPAD_TOGGLE", 531: "TOUCHPAD_ON", 532: "TOUCHPAD_OFF",
    533: "CAMERA_ZOOMIN", 534: "CAMERA_ZOOMOUT", 535: "CAMERA_UP", 536: "CAMERA_DOWN", 537: "CAMERA_LEFT",
    538: "CAMERA_RIGHT", 539: "ATTENDANT_ON", 540: "ATTENDANT_OFF", 541: "ATTENDANT_TOGGLE", 542: "LIGHTS_TOGGLE",
    544: "BTN_DPAD_UP", 545: "BTN_DPAD_DOWN", 546: "BTN_DPAD_LEFT", 547: "BTN_DPAD_RIGHT", 548: "BTN_GRIPL",
    549: "BTN_GRIPR", 550: "BTN_GRIPL2", 551: "BTN_GRIPR2", 560: "ALS_TOGGLE", 561: "ROTATE_LOCK_TOGGLE",
    562: "REFRESH_RATE_TOGGLE", 576: "BUTTONCONFIG", 577: "TASKMANAGER", 578: "JOURNAL", 579: "CONTROLPANEL",
    580: "APPSELECT", 581: "SCREENSAVER", 582: "VOICECOMMAND", 583: "ASSISTANT", 584: "KBD_LAYOUT_NEXT",
    585: "EMOJI_PICKER", 586: "DICTATE", 587: "CAMERA_ACCESS_ENABLE", 588: "CAMERA_ACCESS_DISABLE",
    589: "CAMERA_ACCESS_TOGGLE", 590: "ACCESSIBILITY", 591: "DO_NOT_DISTURB", 592: "BRIGHTNESS_MIN",
    593: "BRIGHTNESS_MAX", 594: "EPRIVACY_SCREEN_ON", 595: "EPRIVACY_SCREEN_OFF", 596: "ACTION_ON_SELECTION",
    597: "CONTEXTUAL_INSERT", 598: "CONTEXTUAL_QUERY", 608: "KBDINPUTASSIST_PREV", 609: "KBDINPUTASSIST_NEXT",
    610: "KBDINPUTASSIST_PREVGROUP", 611: "KBDINPUTASSIST_NEXTGROUP", 612: "KBDINPUTASSIST_ACCEPT",
    613: "KBDINPUTASSIST_CANCEL", 614: "RIGHT_UP", 615: "RIGHT_DOWN", 616: "LEFT_UP", 617: "LEFT_DOWN",
    618: "ROOT_MENU", 619: "MEDIA_TOP_MENU", 620: "NUMERIC_11", 621: "NUMERIC_12", 622: "AUDIO_DESC", 623: "3D_MODE",
    624: "NEXT_FAVORITE", 625: "STOP_RECORD", 626: "PAUSE_RECORD", 627: "VOD", 628: "UNMUTE", 629: "FASTREVERSE",
    630: "SLOWREVERSE", 631: "DATA", 632: "ONSCREEN_KEYBOARD", 633: "PRIVACY_SCREEN_TOGGLE",
    634: "SELECTIVE_SCREENSHOT", 635: "NEXT_ELEMENT", 636: "PREVIOUS_ELEMENT", 637: "AUTOPILOT_ENGAGE_TOGGLE",
    638: "MARK_WAYPOINT", 639: "SOS", 640: "NAV_CHART", 641: "FISHING_CHART", 642: "SINGLE_RANGE_RADAR",
    643: "DUAL_RANGE_RADAR", 644: "RADAR_OVERLAY", 645: "TRADITIONAL_SONAR", 646: "CLEARVU_SONAR",
    647: "SIDEVU_SONAR", 648: "NAV_INFO", 649: "BRIGHTNESS_MENU", 656: "MACRO1", 657: "MACRO2", 658: "MACRO3",
    659: "MACRO4", 660: "MACRO5", 661: "MACRO6", 662: "MACRO7", 663: "MACRO8", 664: "MACRO9", 665: "MACRO10",
    666: "MACRO11", 667: "MACRO12", 668: "MACRO13", 669: "MACRO14", 670: "MACRO15", 671: "MACRO16", 672: "MACRO17",
    673: "MACRO18", 674: "MACRO19", 675: "MACRO20", 676: "MACRO21", 677: "MACRO22", 678: "MACRO23", 679: "MACRO24",
    680: "MACRO25", 681: "MACRO26", 682: "MACRO27", 683: "MACRO28", 684: "MACRO29", 685: "MACRO30",
    688: "MACRO_RECORD_START", 689: "MACRO_RECORD_STOP", 690: "MACRO_PRESET_CYCLE", 691: "MACRO_PRESET1",
    692: "MACRO_PRESET2", 693: "MACRO_PRESET3", 696: "KBD_LCD_MENU1", 697: "KBD_LCD_MENU2", 698: "KBD_LCD_MENU3",
    699: "KBD_LCD_MENU4", 700: "KBD_LCD_MENU5", 701: "PERFORMANCE", 704: "BTN_TRIGGER_HAPPY1",
    705: "BTN_TRIGGER_HAPPY2", 706: "BTN_TRIGGER_HAPPY3", 707: "BTN_TRIGGER_HAPPY4", 708: "BTN_TRIGGER_HAPPY5",
    709: "BTN_TRIGGER_HAPPY6", 710: "BTN_TRIGGER_HAPPY7", 711: "BTN_TRIGGER_HAPPY8", 712: "BTN_TRIGGER_HAPPY9",
    713: "BTN_TRIGGER_HAPPY10", 714: "BTN_TRIGGER_HAPPY11", 715: "BTN_TRIGGER_HAPPY12", 716: "BTN_TRIGGER_HAPPY13",
    717: "BTN_TRIGGER_HAPPY14", 718: "BTN_TRIGGER_HAPPY15", 719: "BTN_TRIGGER_HAPPY16", 720: "BTN_TRIGGER_HAPPY17",
    721: "BTN_TRIGGER_HAPPY18", 722: "BTN_TRIGGER_HAPPY19", 723: "BTN_TRIGGER_HAPPY20", 724: "BTN_TRIGGER_HAPPY21",
    725: "BTN_TRIGGER_HAPPY22", 726: "BTN_TRIGGER_HAPPY23", 727: "BTN_TRIGGER_HAPPY24", 728: "BTN_TRIGGER_HAPPY25",
    729: "BTN_TRIGGER_HAPPY26", 730: "BTN_TRIGGER_HAPPY27", 731: "BTN_TRIGGER_HAPPY28", 732: "BTN_TRIGGER_HAPPY29",
    733: "BTN_TRIGGER_HAPPY30", 734: "BTN_TRIGGER_HAPPY31", 735: "BTN_TRIGGER_HAPPY32", 736: "BTN_TRIGGER_HAPPY33",
    737: "BTN_TRIGGER_HAPPY34", 738: "BTN_TRIGGER_HAPPY35", 739: "BTN_TRIGGER_HAPPY36", 740: "BTN_TRIGGER_HAPPY37",
    741: "BTN_TRIGGER_HAPPY38", 742: "BTN_TRIGGER_HAPPY39", 743: "BTN_TRIGGER_HAPPY40",}

if __name__ == "__main__":
    main()
