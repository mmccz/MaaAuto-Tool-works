"""Regression test: the updater UI must never drag PySide6 back in.

Background: upgrade.exe once bundled all of PySide6 (43 MB) just to show one
progress-bar window. Switching to ctypes/Win32 brought it down to 7.5 MB. This
test guards that line:

* no PySide6/PyQt/tkinter in the upgrade_stub / native_ui sources;
* native_ui must import without any GUI framework (ctypes only);
* the window class keeps its key interface (post_stage / post_progress / is_cancelled / run).
"""

import os
import re
import sys

import pytest

from installer.core import native_ui

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = _ROOT if os.path.isdir(os.path.join(_ROOT, "installer")) else os.path.join(_ROOT, "MaaAutoInstaller")
STUB = os.path.join(APP_DIR, "tools", "upgrade_stub.py")
NATIVE = os.path.join(APP_DIR, "installer", "core", "native_ui.py")


@pytest.mark.parametrize("path", [STUB, NATIVE])
@pytest.mark.parametrize("forbidden", ["PySide6", "PyQt5", "PyQt6", "tkinter"])
def test_no_gui_toolkit_imports(path, forbidden):
    """Only real import statements count: a comment saying "no PySide6" is allowed."""
    pattern = re.compile(rf"^\s*(?:import|from)\s+{forbidden}\b", re.MULTILINE)
    source = open(path, encoding="utf-8").read()
    assert not pattern.search(source), \
        f"{os.path.basename(path)} 又 import 了 {forbidden}"


def test_native_ui_has_no_qt_source():
    source = open(NATIVE, encoding="utf-8").read()
    assert "import PySide6" not in source
    assert "from PySide6" not in source


def test_window_api_surface():
    cls = native_ui.NativeProgressWindow
    for method in ("run", "post_stage", "post_progress", "post_message",
                   "is_cancelled", "_handle_message"):
        assert hasattr(cls, method), f"缺少方法 {method}"


def test_message_constants_are_distinct():
    used = [native_ui.WM_APP_STAGE, native_ui.WM_APP_PROGRESS,
            native_ui.WM_APP_MESSAGE, native_ui.WM_APP_DONE]
    assert len(set(used)) == len(used)
    assert all(m > native_ui.WM_APP for m in used)


def test_struct_sizes_match_win64():
    """Struct layout must match 64-bit Windows, otherwise message arguments get truncated."""
    import ctypes

    assert ctypes.sizeof(native_ui.POINT) == 8
    assert ctypes.sizeof(native_ui.RECT) == 16
    if sys.maxsize > 2 ** 32:
        assert ctypes.sizeof(native_ui.MSG) == 48
        assert ctypes.sizeof(native_ui.WPARAM) == 8
