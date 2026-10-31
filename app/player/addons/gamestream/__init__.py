"""PC link addon (service.py): the games of the PCs running Sunshine on the network, streamed with Moonlight (in the
box's image): finding the PCs, pairing with a code typed in Sunshine, their games and box art, the stream."""
from addons import Addon, Route
from . import service as gs

ADDON = Addon(
    "gamestream", "PC link", order=40,
    description="Games of your PCs, streamed with Moonlight",
    routes={
        "/api/gamestream": Route(lambda q: gs.status()),   # the PCs (Sunshine), pairing, their games, a stream running
        "/api/gamestream_art": Route(lambda q: gs.art(q.get("host", ""), q.get("id", "")),   # box art of a game
                                     content_type="image/png"),
    },
    actions={
        "gamestream_pair": gs.pair,             # pairing with the PC: a code to type in Sunshine
        "gamestream_pair_cancel": gs.pair_cancel,
        "gamestream_search": gs.search,         # look for the PC on the network again
        "gamestream_forget": gs.forget,         # forget the PC (another one can be chosen)
        "gamestream_launch": gs.launch,         # {app}: stream a game
        "gamestream_stop": gs.stop,             # end the stream (the game keeps running on the PC)
        "gamestream_quit": gs.quit_game,        # close the game on the PC
    },
    features=lambda: {"gamestream": gs.available()},   # Moonlight installed (the box's image)
)
