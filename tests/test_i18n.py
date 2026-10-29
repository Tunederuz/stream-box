"""i18n.py: chosen language, translations and placeholders."""
import importlib, os, sys, unittest

from tests.helpers import REPO, temp_home

sys.path.insert(0, os.path.join(REPO, "app"))


class I18n(unittest.TestCase):
    def setUp(self):
        self.home = os.environ.get("HOME")

    def tearDown(self):
        os.environ["HOME"] = self.home

    def load(self, language=None):
        os.environ["HOME"] = temp_home(language)
        import i18n
        return importlib.reload(i18n)   # LANG_FILE depends on HOME

    def test_default_english(self):
        i18n = self.load()
        self.assertEqual(i18n.language(), "en")
        self.assertEqual(i18n.tr("Connected: {login}", login="abc"), "Connected: abc")

    def test_french(self):
        i18n = self.load("fr")
        self.assertEqual(i18n.language(), "fr")
        self.assertEqual(i18n.tr("Language"), "Langue")
        self.assertNotIn("{", i18n.tr("Connected: {login}", login="abc"))

    def test_unknown_language_falls_back(self):
        i18n = self.load("xx")
        self.assertEqual(i18n.language(), "en")
        with self.assertRaises(ValueError):
            i18n.set_language("xx")

    def test_set_language(self):
        i18n = self.load()
        i18n.set_language("fr")
        self.assertEqual(i18n.language(), "fr")


if __name__ == "__main__":
    unittest.main()
