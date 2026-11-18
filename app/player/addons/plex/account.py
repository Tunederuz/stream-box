"""Plex add-on: its row (Settings → Accounts and links) and its dialogs, drawn by the TV menu (addons' account
contract): sign in with a code on plex.tv/link, or the server forgotten."""
from i18n import tr
from . import service as px


def row():
    c = px.px_config()
    return {"label": "Plex", "value": tr("Connected") if c else tr("Not connected"),
            "hint": c["address"].split("://", 1)[-1] if c else tr("Your movies and series of a Plex server")}


def menu(target):
    c = px.px_config()
    items = [{"label": tr("+  Sign in with another Plex account") if c else tr("+  Sign in with a Plex account"),
              "action": "plex_link", "then": "code"}]
    if c:
        items.append({"label": tr("✕  Disconnect Plex"), "danger": True, "action": "plex", "body": {"address": ""},
                      "confirm": tr("Disconnect Plex? Its tab goes away")})
    return {"title": tr("Plex: {server}", server=c["address"]) if c else "Plex", "items": items}


def code():
    d = px.link_state()
    p = d.get("pending")
    if not p and d["configured"]:
        return {"done": True}
    p = p or {}
    return {"title": tr("Sign in with a Plex account"), "where": tr("On your phone, open plex.tv/link and enter:"),
            "code": p.get("code") if not p.get("error") else "",
            "error": tr("Failed: {error}", error=p["error"]) if p.get("error") else "",
            "help": tr("The box then takes the first server of the account it reaches, local ones first."),
            "qr": "https://plex.tv/link"}


def cancel():
    px.link_cancel()


ACCOUNT = {"row": row, "menu": menu, "code": code, "cancel": cancel}
