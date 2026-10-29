#!/usr/bin/env python3
"""Stream Box: companion app for the phone (http://<box>:8080), which drives mpv through its IPC socket.

Streamer and chat changes go through the script-messages of stream-box.lua, so that the on-screen menu, the chat
and the page stay in agreement. Standard library only.

This file starts the background loops and the HTTP server; the code lives in the modules next to it:
  common.py    port, paths, mpv IPC, private JSON files
  api.py       HTTP server: page, PWA and locale files, GET routes, POST /api/<action>
  actions.py   POST actions (one handler per name), TV menu keyboard
  twitch.py    streamer list, who is live, polls and predictions, replays, followed channels, Twitch account
  youtube.py   channels, search, subtitles, storyboard, account subscriptions, "TV app" progress
  jellyfin.py  Jellyfin library, playback and progress reports
  plex.py      Plex library, playback and progress reports
  quickmenu.py quick menu of the simplified version (mpv alone): lists drawn by stream-box.lua
  playback.py  videos started from a link or the history, history loop (positions)
  history.py   history file, media keys, video being played
  ambient.py   ambient screen (weather, schedules), QR code and remote URL, first setup
  images.py    TV menu images, TV preview
  settings.py  player, power button action, background
  system.py    power, wake-up, SSH and developer mode, box status, updates
"""
import os, signal, sys, threading
from http.server import ThreadingHTTPServer

# app/player and app/system on the import path: the modules import each other by name, from either folder (system/
# is not part of the Stream Player)
sys.path[:0] = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), d) for d in ("player", "system")]

import ambient   # ambient.py: weather, schedules, QR code
import history   # history.py: positions kept in memory on a USB drive
import api       # api.py: HTTP request handler
import netsetup  # netsetup.py: setup Wi-Fi access point
import playback  # playback.py: history loop
import quickmenu # quickmenu.py: quick menu of the simplified version
import system    # system.py: box status, wake-up, power key
import twitch    # twitch.py: account, who is live, polls
from common import PORT

twitch.write_cookies(twitch.read_token())   # at startup: cookies aligned with the saved token
threading.Thread(target=twitch.account_loop, daemon=True).start()
threading.Thread(target=twitch.live_loop, daemon=True).start()
threading.Thread(target=ambient.ambient_loop, daemon=True).start()
threading.Thread(target=playback.history_loop, daemon=True).start()
threading.Thread(target=twitch.events_loop, daemon=True).start()
threading.Thread(target=system.health_loop, daemon=True).start()
threading.Thread(target=system.resume_loop, daemon=True).start()
threading.Thread(target=netsetup.setup_loop, daemon=True).start()
threading.Thread(target=quickmenu.listen_loop, daemon=True).start()
system.hold_power_key()
# Stopped (shutdown, session restart): the positions not written yet on a USB drive are written now
signal.signal(signal.SIGTERM, lambda *_: (history.flush(force=True), sys.exit(0)))
ThreadingHTTPServer(("0.0.0.0", PORT), api.Handler).serve_forever()
