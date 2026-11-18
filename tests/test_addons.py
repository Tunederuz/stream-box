"""addons/ (the box's integrations): turning an add-on off takes away what it brings, Twitch (the base) stays on."""
import io, os, re, tempfile, tokenize, unittest

from tests.helpers import REPO, temp_home, tracked_files

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


class CoreNamesNoAddon(unittest.TestCase):
    """The core's code (app/player/*.py, app/system, lua/, qml/, web/) names no add-on but Twitch, the base: what an
    add-on brings goes through addons/ (its Addon, its player part, its part of the companion app). Comments may give
    them as examples; the YouTube receiver (cast/) and the packaging (scripts/, image/) are not checked."""
    CORE = re.compile(r"^(app/player/[^/]+\.py|app/system/[^/]+\.py|lua/.+\.lua|qml/.+\.(qml|js)|web/.+\.(html|js))$")
    NAMES = re.compile(r"youtube|jellyfin|(?<![a-z])plex|gamestream|moonlight|sunshine|\byt_", re.I)

    @staticmethod
    def python_code(src):
        """(line, text) of the names and strings of Python code (docstrings and comments left out)"""
        out, statement_start, depth = [], True, 0
        for t in tokenize.generate_tokens(io.StringIO(src).readline):
            if t.type == tokenize.NAME or (t.type == tokenize.STRING and not statement_start):
                out.append((t.start[0], t.string))
            if t.type == tokenize.OP:
                depth += (t.string in "([{") - (t.string in ")]}")
            if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.INDENT, tokenize.DEDENT):
                statement_start = t.type == tokenize.NEWLINE
            elif t.type == tokenize.NL and depth:
                statement_start = False
        return out

    @staticmethod
    def other_code(src, comment):
        """(line, text) of Lua, QML or JavaScript without its comments (comment: "--" or "//"; /* */ too)"""
        if comment == "//":   # (and /* */, <!-- -->)
            src = re.sub(r"/\*.*?\*/|<!--.*?-->", lambda m: "\n" * m.group().count("\n"), src, flags=re.S)
        out = []
        for n, line in enumerate(src.split("\n"), 1):
            code, quote, i = "", None, 0
            while i < len(line):
                c = line[i]
                if quote:
                    if c == "\\":
                        code, i = code + line[i:i + 2], i + 2
                        continue
                    quote = None if c == quote else quote
                elif c in "\"'":
                    quote = c
                elif line.startswith(comment, i):
                    break
                code, i = code + c, i + 1
            out.append((n, code))
        return out

    def test_core_names_no_addon(self):
        found = []
        for path in tracked_files(self.CORE.pattern):
            rel = os.path.relpath(path, REPO)
            with open(path, encoding="utf-8") as f:
                src = f.read()
            code = self.python_code(src) if rel.endswith(".py") else self.other_code(src, "--" if rel.endswith(".lua") else "//")
            found += [f"{rel}:{n}: {text.strip()[:100]}" for n, text in code if self.NAMES.search(text)]
        self.assertEqual(found, [], "the core names an add-on: give it to the add-on through addons/ instead")


class Contract(unittest.TestCase):
    def test_same_number_both_sides(self):
        with open(os.path.join(REPO, "lua", "stream-box.lua"), encoding="utf-8") as f:
            lua = int(re.search(r"^local ADDON_CONTRACT = (\d+)", f.read(), re.M).group(1))
        self.assertEqual(lua, addons.CONTRACT)

    def test_every_addon_loaded(self):   # (written for this contract)
        here = os.path.join(REPO, "app", "player", "addons")
        self.assertEqual(sorted(a.id for a in addons.ADDONS),
                         sorted(n for n in os.listdir(here) if os.path.isfile(os.path.join(here, n, "__init__.py"))))
