"""Tests of the box's modules: they are in the repository's app/player and app/system and import each other by name"""
import os, sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path[:0] = [os.path.join(APP, "player"), os.path.join(APP, "system")]
