"""Tests of the box's modules: they are in the repository's app/ and import each other by name"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
