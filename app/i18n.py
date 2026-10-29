"""Stream Box: interface language (TV and companion app).

Texts are written in English in the code; translations live in locales/<lang>.json, a flat map from the English
text to the translated one. Placeholders use {name}: tr("Connected: {login}", login="abc").

The chosen language is stored in ~/.config/stream-box/language ("en" when missing). remote.py serves the locale files
(/locales/<lang>.json) to the companion app and to the TV menu, and tells the TV when the language changes
(script-message streambox-language <lang>). The same files are read by ui.py (QML) and stream-box.lua.
"""
import json, os

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repository (locales/ next to app/)
LANG_FILE = os.path.expanduser("~/.config/stream-box/language")
LANGUAGES = {"en": "English", "fr": "Français"}   # code -> name shown in the language picker (in its own language)
DEFAULT = "en"
_cache = {}


def language():
    try:
        with open(LANG_FILE, encoding="utf-8") as f:
            lang = f.read().strip()
        return lang if lang in LANGUAGES else DEFAULT
    except OSError:
        return DEFAULT


def set_language(lang):
    if lang not in LANGUAGES:
        raise ValueError("unknown language")
    os.makedirs(os.path.dirname(LANG_FILE), exist_ok=True)
    with open(LANG_FILE, "w", encoding="utf-8") as f:
        f.write(lang + "\n")


def catalog(lang):
    """Translations for lang (empty for English), read once per file modification"""
    if lang == "en":
        return {}
    path = os.path.join(DIR, "locales", f"{lang}.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    cached = _cache.get(lang)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    _cache[lang] = (mtime, data)
    return data


def tr(text, **values):
    """text in the current language, {name} placeholders filled from values"""
    out = catalog(language()).get(text) or text
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out
