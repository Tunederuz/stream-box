"""Translations (locales/<lang>.json, and each add-on's app/player/addons/<id>/locales/<lang>.json, keyed by the English
text): same placeholders, nothing missing, nothing stale, an add-on's own texts in its folder."""
import ast, json, os, re, unittest
from html.parser import HTMLParser

from tests.helpers import REPO, tracked_files

# Code, shell scripts, and the scripts of the image (no extension: installer, session)
CODE = r"(\.(py|lua|qml|js|html|sh)$|^image/mkosi\.extra/usr/local/)"
# Quoted literals of the non-Python files (Lua, QML, JavaScript, HTML)
LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'')
# Keys used in a way the scan below cannot see
USED_ELSEWHERE = {"Preparing"}   # install-to-disk: default step "${STEP:-Preparing}"
TR_CALL = re.compile(r'\btr\(\s*(?:"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\')')


def unescape(s):
    return s.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8") if "\\" in s else s


def python_strings(path):
    """(every string constant, strings passed literally to tr()) of a Python file; implicit concatenations are
    joined by the parser"""
    tree = ast.parse(read(path))
    consts, calls = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            consts.add(node.value)
        if (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "tr"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            calls.add(node.args[0].value)
    return consts, calls


class StaticTexts(HTMLParser):
    """Texts of an HTML page that remote.html translates by itself: trimmed text nodes (outside script and style)
    and the placeholder / title / aria-label attributes"""
    def __init__(self):
        super().__init__()
        self.texts, self.skip = set(), 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        self.texts |= {v.strip() for k, v in attrs if k in ("placeholder", "title", "aria-label") and v}

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.texts.add(data.strip())


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def code_strings():
    """{file (from the repository): (every string constant, strings passed literally to tr())}"""
    out = {}
    for path in tracked_files(CODE):
        rel = os.path.relpath(path, REPO)
        if path.endswith(".py"):
            out[rel] = python_strings(path)
            continue
        src = read(path)
        consts = {unescape(a or b) for a, b in LITERAL.findall(src)}
        if path.endswith(".html"):
            page = StaticTexts()
            page.feed(src)
            consts |= page.texts
        out[rel] = (consts, {unescape(a or b) for a, b in TR_CALL.findall(src)})
    return out


def addon_of(rel):
    """The add-on whose folder holds this file, None for the core"""
    m = re.match(r"app/player/addons/([^/]+)/", rel)
    return m and m.group(1)


class Locales(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # (add-on or None, language file) → its table
        cls.tables = {}
        addons = os.path.join(REPO, "app", "player", "addons")
        dirs = [(None, os.path.join(REPO, "locales"))] + [(a, os.path.join(addons, a, "locales")) for a in sorted(os.listdir(addons))]
        for addon, d in dirs:
            for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                with open(os.path.join(d, name), encoding="utf-8") as f:
                    cls.tables[(addon, name)] = json.load(f)
        cls.files = code_strings()
        cls.consts = set().union(*(c for c, _ in cls.files.values()))
        cls.calls = set().union(*(t for _, t in cls.files.values()))

    def merged(self, name):
        out = {}
        for (addon, n), table in self.tables.items():
            if n == name:
                out.update(table)
        return out

    def test_placeholders(self):
        for (addon, name), table in self.tables.items():
            for key, value in table.items():
                with self.subTest(addon=addon, locale=name, key=key):
                    self.assertEqual(sorted(re.findall(r"\{(\w+)\}", key)), sorted(re.findall(r"\{(\w+)\}", value)))

    def test_every_literal_translated(self):
        for name in {n for _, n in self.tables}:
            table = self.merged(name)
            missing = sorted(s for s in self.calls if s not in table)
            self.assertEqual(missing, [], f"{name}: tr() strings without translation")

    def test_no_stale_key(self):
        # A key must still exist in the code (as a string, tr() or a table of labels): the core's anywhere, an add-on's
        # in its folder
        for (addon, name), table in self.tables.items():
            consts = self.consts if addon is None else set().union(
                *(c for rel, (c, _) in self.files.items() if addon_of(rel) == addon))
            stale = sorted(k for k in table if k not in consts and k not in USED_ELSEWHERE)
            self.assertEqual(stale, [], f"{addon or 'core'} {name}: keys no longer in the code")

    def test_addon_texts_in_addon(self):
        # A text only one add-on uses is in its locales, not the core's; none in both
        users = {}
        for rel, (consts, _) in self.files.items():
            for s in consts:
                users.setdefault(s, set()).add(addon_of(rel))
        for (addon, name), table in self.tables.items():
            if addon is None:
                own = sorted(k for k in table if len(users.get(k, ())) == 1 and None not in users[k])
                self.assertEqual(own, [], f"core {name}: texts of a single add-on (move them to its locales/)")
            else:
                both = sorted(k for k in table if k in self.tables.get((None, name), {}))
                self.assertEqual(both, [], f"{addon} {name}: also in the core's locales")


if __name__ == "__main__":
    unittest.main()
