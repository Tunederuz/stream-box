"""Stream Box: the box's system part (app/system: power, updates, box status, display, sound, Wi-Fi, Bluetooth,
installer, backup), optional: the Stream Player (the app, on an OS that runs itself) does not have it. The modules
that serve both take it from here: SYSTEM tells whether it is there, and each of its modules is None without it.

Decided by the folder being there, not by catching ImportError: with the folder, a module that fails to import is a
bug and stops the server as before.
"""
import os

SYSTEM = os.path.isdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "system"))
if SYSTEM:
    import audio, backup, btsetup, display, installer, localupdate, netsetup, system
else:
    audio = backup = btsetup = display = installer = localupdate = netsetup = system = None


def features():
    """What this installation has (GET /api/features): the TV menu and the companion app hide the rest"""
    return {"system": SYSTEM}
