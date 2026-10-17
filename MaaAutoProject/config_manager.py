import json
import os
import sys
import logging
from PySide6.QtCore import QObject, Signal


def _get_base_dir():
    """
    程序基准目录：
      - 打包后（PyInstaller）：exe 所在目录
      - 开发模式：config_manager.py 所在目录（项目根目录）
    无论从哪个 CWD 启动，config/ 和 logs/ 都在同一个位置。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _get_base_dir()
CONFIG_DIR = os.path.join(BASE_DIR, "config")
LOG_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    # ---- 原有键 ----
    "maa_path": "",
    "maaend_path": "",
    "serverchan_key": "",
    "webhook_url": "",
    "execute_time": "08:00",
    "enable_schedule": False,
    "wait_timeout": 60,
    "game_start_timeout": 120,
    "game_exit_timeout": 7200,
    "retry_times": 3,
    "retry_interval": 30,
    "auto_start": False,
    "minimize_to_tray": True,
    "kill_on_exit": True,
    "foreground_action": "none",
    "blacklist_apps": "",
    "last_trigger_date": "",
    "run_count": 0,
    # ---- 新增键 ----
    "emulator_proc": "MuMuPlayer.exe",
    "pc_game_proc": "Endfield.exe",
    "enable_system_notify": True,
    "theme": "system",
    "language": "zh_CN",
    "accent_color": "#3b82f6",
    "background_image": "",
    "background_opacity": 0.3,
    "background_blur": 0,
    "background_mode": "cover",
    "show_animation": True,
    "last_run_time": "",
    "window_geometry": "",
    # ---- 升级相关 ----
    "auto_check_update": True,
    "auto_download_update": False,
}


def load_config():
    """
    读取 config.json。
    用 utf-8-sig 兼容带 BOM 的文件（PowerShell Set-Content -Encoding utf8 会加 BOM）。
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            return {**DEFAULT_CONFIG, **data}
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(config):
    """写 config.json（UTF-8 无 BOM）。

    先写同目录临时文件、再 os.replace 原子替换。主程序是「改完即存」，
    而升级/退出/任务管理器结束都可能落在写入中间；直接覆盖原文件时
    一旦被打断就是半截 JSON，下次启动 load_config() 会静默回退全默认值，
    用户会感觉「配置全丢了」。
    """
    tmp_file = CONFIG_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, CONFIG_FILE)


class LogHandler(logging.Handler, QObject):
    log_signal = Signal(str)

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)

    def emit(self, record):
        try:
            self.log_signal.emit(self.format(record))
        except Exception:
            pass


def setup_logger():
    logger = logging.getLogger("MaaAuto")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    ui = LogHandler()
    ui.setFormatter(fmt)
    logger.addHandler(ui)
    return logger, ui