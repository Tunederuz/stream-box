"""YouTube add-on: its account row (Settings → Accounts and links) and its dialogs, drawn by the TV menu (addons'
account contract): connect with a code on google.com/device (the "YouTube TV app" access), reload the
subscriptions, disconnect."""
from i18n import tr
from . import service as yt


def row():
    a = yt.yt_account_status()
    if a["unavailable"]:   # (youtube_tv.js not running: nothing to offer)
        return None
    return {"label": tr("YouTube account"), "value": tr("Connected") if a["authorized"] else tr("Not connected"),
            "hint": tr("Subscriptions, recommendations, and progress synced with your account")}


def menu(target):
    if not yt.yt_account_status()["authorized"]:
        return {"title": tr("YouTube account"),
                "items": [{"label": tr("+  Connect my YouTube account"), "action": "youtube_login", "then": "code"}]}
    return {"title": tr("YouTube account"), "items": [
        {"label": tr("↻  Reload my subscriptions"), "action": "youtube_sync", "wait": tr("Reloading your subscriptions…"),
         "done": tr("Subscriptions reloaded"), "fail": tr("YouTube unreachable for now")},
        {"label": tr("✕  Disconnect YouTube"), "danger": True, "action": "youtube_logout",
         "confirm": tr("Disconnect your YouTube account? Subscriptions, recommendations and progress sync stop")}]}


def code():
    a = yt.yt_account_status()
    if a["authorized"]:
        return {"done": True}
    p = a.get("pending") or {}
    return {"title": tr("Connect my YouTube account"), "where": tr("On your phone, open google.com/device and enter:"),
            "code": p.get("user_code") if not p.get("error") else "",
            "error": tr("Authorization denied: {error}", error=p["error"]) if p.get("error") else "",
            "help": tr("Google shows \"YouTube on TV\": the box presents itself as the YouTube app for TVs (subscriptions, "
                       "recommendations, progress)."),
            "qr": p.get("verification_uri") if not p.get("error") else None}


ACCOUNT = {"row": row, "menu": menu, "code": code}
