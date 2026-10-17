import os
import sys
import psutil
import logging

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger("MaaAuto")


def resource_path(relative_path):
    """返回资源的绝对路径。

    打包态（PyInstaller）从 ``sys._MEIPASS`` 取；
    开发态从**本文件所在目录**取，而不是 CWD —— 否则从别处启动、
    或走开机自启（Run 键没有工作目录）时会找不到 resources/themes/i18n。
    """
    base_path = getattr(sys, "_MEIPASS", None)
    if not base_path:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def kill_all_related_processes():
    """强制清理所有相关进程"""
    targets = ["maa.exe", "maa-cli.exe", "maaend.exe",
               "mumuplayer.exe", "nemuplayer.exe", "dnplayer.exe"]
    logger.info("正在清理残留进程...")
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'].lower() in targets:
                logger.info(f"强制关闭残留进程: {proc.info['name']}")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


# =========================================================================== #
# 通用异步任务：把同步函数扔到后台线程，避免 UI 冻结
# =========================================================================== #
class AsyncWorker(QThread):
    """
    用法：
        self._worker = AsyncWorker(sc_send, key, title, desp, options)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    注意：
      - 必须把 worker 保存到实例属性（self._worker），否则会被 GC 掉
      - 信号在主线程接收，可以安全更新 UI
    """
    finished = Signal(object)   # 返回值
    error = Signal(str)         # 异常字符串

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