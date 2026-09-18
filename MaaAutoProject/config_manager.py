import json
import os
import logging
from PySide6.QtCore import QObject, Signal

CONFIG_DIR = "config"
LOG_DIR = "logs"
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
    "theme": "system",              # light / dark / system
    "language": "zh_CN",
    "accent_color": "#3b82f6",      # 强调色（十六进制，用于主题强调色自定义）
    "background_image": "",
    "background_opacity": 0.3,
    "background_blur": 0,
    "background_mode": "cover",     # cover / contain / stretch / tile
    "show_animation": True,
    "last_run_time": "",
    "window_geometry": "",   # base64 编码的 Qt 窗口几何
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {**DEFAULT_CONFIG, **data}
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


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