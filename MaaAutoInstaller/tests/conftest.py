"""Shared pytest configuration: put MaaAutoInstaller (and its tools/) on the path.

Works in both layouts: the merged repo (``<root>/MaaAutoInstaller/tests``) and the
old standalone installer checkout (``<repo>/tests`` + ``<repo>/MaaAutoInstaller``).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = ROOT if os.path.isdir(os.path.join(ROOT, "installer")) else os.path.join(ROOT, "MaaAutoInstaller")
TOOLS_DIR = os.path.join(PKG_DIR, "tools")
for path in (PKG_DIR, TOOLS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)
