"""PC link add-on: its row (Settings → Accounts and links) and its dialogs, drawn by the TV menu (addons' account
contract): the PCs found or paired, each to pair (a code to type in Sunshine) or forget, and a new search."""
from i18n import tr
from . import service as gs

failed = {"error": ""}   # the pairing's error, shown until the dialog closes (status() gives it once)


def row():
    if not gs.available():
        return None
    st = gs.status()
    paired = [p for p in st["pcs"] if p["paired"]]
    value = (tr("Paired: {name}", name=paired[0]["name"]) if len(paired) == 1
             else tr("{n} PCs paired", n=len(paired)) if paired
             else tr("Not paired") if st["pcs"] else tr("No PC found"))
    return {"label": tr("PC (Sunshine)"), "value": value,
            "hint": tr("Their games in the PC link tab") if paired else tr("Play the games of a PC running Sunshine")}


def menu(target):
    pcs = gs.status()["pcs"]
    if target.startswith("pc:"):   # one PC: pair (again), forget
        pc = next((p for p in pcs if p["host"] == target[3:]), None)
        if not pc:
            raise ValueError(tr("unknown PC"))
        items = []
        if pc["online"]:
            items.append({"label": tr("↻  Pair again") if pc["paired"] else tr("+  Pair with {name}", name=pc["name"]),
                          "action": "gamestream_pair", "body": {"host": pc["host"]}, "then": "code"})
        if pc["paired"]:
            items.append({"label": tr("✕  Forget this PC"), "danger": True, "action": "gamestream_forget",
                          "body": {"host": pc["host"]}, "confirm": tr("Forget {name}? Its games leave the box", name=pc["name"]),
                          "then": "menu"})
        title = (tr("{name} is off or unreachable", name=pc["name"]) if not pc["online"]
                 else tr("Paired with {name}", name=pc["name"]) if pc["paired"]
                 else tr("{name} found on the network", name=pc["name"]))
        return {"title": title, "items": items}
    items = [{"label": p["name"] + "  ·  " + (tr("paired") if p["paired"] else tr("not paired") if p["online"] else tr("off")),
              "open": "pc:" + p["host"]} for p in pcs]
    items.append({"label": tr("↻  Search again"), "action": "gamestream_search", "body": {"wait": True},
                  "wait": tr("Looking for PCs on the network…"), "then": "menu"})
    return {"title": tr("PCs with Sunshine") if pcs else tr("No PC with Sunshine found on the network"), "items": items}


def code():
    p = gs.status().get("pairing")   # (it also keeps the PC once paired)
    if p and p.get("error"):
        failed["error"] = p["error"]
    if failed["error"]:
        return {"title": tr("Pair with the PC"), "error": failed["error"]}
    if not p:
        return {"done": True}
    return {"title": tr("Pair with {name}", name=p.get("name") or ""),
            "where": tr("On the PC, open Sunshine (https://localhost:47990), PIN tab, and enter:"),
            "code": p.get("pin") or "", "help": tr("From a phone: {page}", page=p["page"]) if p.get("page") else ""}


def cancel():
    failed["error"] = ""
    gs.pair_cancel({})


ACCOUNT = {"row": row, "menu": menu, "code": code, "cancel": cancel}
