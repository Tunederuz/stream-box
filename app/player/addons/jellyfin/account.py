"""Jellyfin add-on: its row (Settings → Accounts and links) and its dialogs, drawn by the TV menu (addons' account
contract): the servers that answer on the network, signed in with Quick Connect (a code to approve in Jellyfin), or
the server forgotten."""
from i18n import tr
from . import service as jf


def row():
    srv = jf.jf_server()
    return {"label": "Jellyfin", "value": tr("Connected") if srv else tr("Not connected"),
            "hint": srv["address"].split("://", 1)[-1] if srv else tr("Your movies and series of a Jellyfin server"),
            "opening": tr("Looking for Jellyfin servers on the network…")}   # (the dialog looks for them: a moment)


def menu(target):
    d = jf.link_state(find=True)
    items = [{"label": "+  " + s["name"] + "  ·  " + s["address"].split("://", 1)[-1], "action": "jellyfin_link",
              "body": {"address": s["address"]}, "then": "code"} for s in d.get("servers") or []]
    found = bool(items)
    if d["configured"]:
        items.append({"label": tr("✕  Disconnect Jellyfin"), "danger": True, "action": "jellyfin_link",
                      "body": {"action": "forget"}, "confirm": tr("Disconnect Jellyfin? Its tab goes away")})
    return {"title": tr("Connect to which Jellyfin server?") if found else
            tr("No Jellyfin server found on the network: give its address in the companion app (Settings → Jellyfin)."),
            "items": items}


def code():
    d = jf.link_state()
    p = d.get("pending")
    if not p and d["configured"]:
        return {"done": True}
    p = p or {}
    return {"title": tr("Connect Jellyfin"),
            "where": tr("In Jellyfin (app or website): your user menu, Quick Connect, then enter:"),
            "code": p.get("code") if not p.get("error") else "",
            "error": tr("Failed: {error}", error=p["error"]) if p.get("error") else "",
            "help": tr("Server: {server}.", server=p["name"]) if p.get("name") else ""}


def cancel():
    p = jf.link_state().get("pending")
    if p and not p.get("error"):   # (waiting for its code: the previous connection comes back)
        jf.link_action({"action": "cancel"})


ACCOUNT = {"row": row, "menu": menu, "code": code, "cancel": cancel}
