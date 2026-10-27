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
  playback.py  videos started from a link or the history, history loop (positions)
  history.py   history file, media keys, video being played
  ambient.py   ambient screen (weather, schedules), QR code and remote URL, first setup
  images.py    TV menu images, TV preview
  settings.py  player, power button action, background
  system.py    power, wake-up, SSH and developer mode, box status, updates
"""
import threading
from http.server import ThreadingHTTPServer

import ambient   # ambient.py: weather, schedules, QR code
import api       # api.py: HTTP request handler
import netsetup  # netsetup.py: setup Wi-Fi access point
import playback  # playback.py: history loop
import system    # system.py: box status, wake-up, power key
import twitch    # twitch.py: account, who is live, polls
import youtube   # youtube.py: subscriptions feed
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
threading.Thread(target=youtube.yt_subfeed_loop, daemon=True).start()
threading.Thread(target=youtube.preview_loop, daemon=True).start()
system.hold_power_key()
ThreadingHTTPServer(("0.0.0.0", PORT), api.Handler).serve_forever()
