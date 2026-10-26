"""Translations (locales/<lang>.json, keyed by the English text): same placeholders, nothing missing, nothing stale."""
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
    consts, calls = set(), set()
    for path in tracked_files(CODE):
        if path.endswith(".py"):
            c, t = python_strings(path)
            consts |= c
            calls |= t
            continue
        src = read(path)
        if path.endswith(".html"):
            page = StaticTexts()
            page.feed(src)
            consts |= page.texts
        consts |= {unescape(a or b) for a, b in LITERAL.findall(src)}
        calls |= {unescape(a or b) for a, b in TR_CALL.findall(src)}
    return consts, calls


class Locales(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.locales = {}
        for name in os.listdir(os.path.join(REPO, "locales")):
            with open(os.path.join(REPO, "locales", name), encoding="utf-8") as f:
                cls.locales[name] = json.load(f)
        cls.consts, cls.calls = code_strings()

    def test_placeholders(self):
        for name, table in self.locales.items():
            for key, value in table.items():
                with self.subTest(locale=name, key=key):
                    self.assertEqual(sorted(re.findall(r"\{(\w+)\}", key)), sorted(re.findall(r"\{(\w+)\}", value)))

    def test_every_literal_translated(self):
        for name, table in self.locales.items():
            missing = sorted(s for s in self.calls if s not in table)
            self.assertEqual(missing, [], f"{name}: tr() strings without translation")

    def test_no_stale_key(self):
        # A key must still exist somewhere in the code (as a string, tr() or a table of labels)
        for name, table in self.locales.items():
            stale = sorted(k for k in table if k not in self.consts and k not in USED_ELSEWHERE)
            self.assertEqual(stale, [], f"{name}: keys no longer in the code")


if __name__ == "__main__":
    unittest.main()
