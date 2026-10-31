"""Shared pytest configuration: put MaaAutoProject on the import path.

These tests deliberately avoid the real screen/mouse:
* Template-matching tests replace ``vision.grab_gray`` with synthetic in-memory frames;
* Click tests replace ``input_driver.move_cursor`` / ``_send_mouse`` with recorders.

That lets them run on CI, where there is no interactive desktop.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "MaaAutoProject")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
