#!/usr/bin/env python3
"""Stream Box: relay. The user unit stream-box-mqtt.service of images 0.5.0 and older starts ~/stream-box/mqtt_bridge.py:
the module is now app/mqtt_bridge.py. To remove once no box runs those images.
"""
import os, runpy, sys

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
sys.path.insert(0, APP)   # (its imports: the modules next to it)
runpy.run_path(os.path.join(APP, "mqtt_bridge.py"), run_name="__main__")
