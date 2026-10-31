import os
import sys
import logging

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger("MaaAuto")


def resource_path(relative_path):
    """Absolute path of a resource.

    Frozen (PyInstaller) builds read it from ``sys._MEIPASS``; a source checkout reads it
    from **the directory of this file**, not the CWD - otherwise starting from elsewhere,
    or via autostart (a Run-key launch has no working directory), fails to find
    resources/themes/i18n.
    """
    base_path = getattr(sys, "_MEIPASS", None)
    if not base_path:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


# =========================================================================== #
# Generic async task: run a sync function on a background thread so the UI never freezes
# =========================================================================== #
class AsyncWorker(QThread):
    """Usage:
        self._worker = AsyncWorker(sc_send, key, title, desp, options)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    Notes:
      - keep the worker on an instance attribute (self._worker) or the GC eats it
      - signals arrive on the main thread, so updating the UI is safe
    """
    finished = Signal(object)   # return value
    error = Signal(str)         # error string

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as e:
            try:
                logger.error(f"AsyncWorker 异常: {e}")
            except Exception:
                pass
            self.error.emit(str(e))