#!/usr/bin/env python3
"""Owlink: relay. The user unit stream-box-mqtt.service of images 0.5.0 and older starts ~/stream-box/mqtt_bridge.py:
the module is now app/system/mqtt_bridge.py. To remove once no box runs those images.
"""
import os, runpy, sys

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
sys.path[:0] = [os.path.join(APP, "player"), os.path.join(APP, "system")]   # (its imports: the modules of both)
runpy.run_path(os.path.join(APP, "system", "mqtt_bridge.py"), run_name="__main__")
