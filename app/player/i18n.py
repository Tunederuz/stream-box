"""Inlet: interface language (TV and companion app).

Texts are written in English in the code; translations live in locales/<lang>.json, a flat map from the English
text to the translated one, and each add-on's own texts in app/player/addons/<id>/locales/<lang>.json (the same map,
merged in: the core's win). Placeholders use {name}: tr("Connected: {login}", login="abc").

The chosen language is stored in ~/.config/stream-box/language ("en" when missing). remote.py serves the locale files
(/locales/<lang>.json, merged) to the companion app and to the TV menu, and tells the TV when the language changes
(script-message streambox-language <lang>). The same files are read by ui.py (QML) and stream-box.lua.
"""
import json, os

DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository (this is app/player/)
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


def files(lang):
    """The locale files of lang: the add-ons', then the core's (the last one wins)"""
    addons = os.path.join(DIR, "app", "player", "addons")
    names = sorted(os.listdir(addons)) if os.path.isdir(addons) else []
    return [os.path.join(addons, n, "locales", f"{lang}.json") for n in names] + [os.path.join(DIR, "locales", f"{lang}.json")]


def catalog(lang):
    """Translations for lang (empty for English), read again when one of its files changes"""
    if lang == "en":
        return {}
    paths = [p for p in files(lang) if os.path.isfile(p)]
    try:
        stamp = tuple((p, os.path.getmtime(p)) for p in paths)
    except OSError:
        return {}
    cached = _cache.get(lang)
    if cached and cached[0] == stamp:
        return cached[1]
    data = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                data.update(json.load(f))
        except (OSError, ValueError):
            pass
    _cache[lang] = (stamp, data)
    return data


def tr(text, **values):
    """text in the current language, {name} placeholders filled from values"""
    out = catalog(language()).get(text) or text
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out
