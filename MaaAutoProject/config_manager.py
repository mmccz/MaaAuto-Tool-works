import json
import os
import logging
from PySide6.QtCore import QObject, Signal

# 自动创建目录
CONFIG_DIR = "config"
LOG_DIR = "logs"
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "maa_path": "",
    "maaend_path": "",
    "serverchan_key": "",
    "execute_time": "08:00",
    "enable_schedule": True,       # 注意这里有逗号
    "wait_timeout": 60,
    "game_start_timeout": 120,
    "game_exit_timeout": 7200,
    "retry_times": 3,
    "retry_interval": 30,
    "auto_start": False,
    "minimize_to_tray": True,
    "kill_on_exit": True,
    "last_trigger_date": "",
    "run_count": 0                 # 最后一行没有逗号，紧跟下面的花括号
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

class LogHandler(logging.Handler, QObject):
    log_signal = Signal(str)
    
    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)
        
    def emit(self, record):
        msg = self.format(record)
        self.log_signal.emit(msg)

def setup_logger():
    logger = logging.getLogger("MaaAuto")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # UI 全局日志（仅用于主界面实时显示）
    ui_handler = LogHandler()
    ui_handler.setFormatter(formatter)
    logger.addHandler(ui_handler)
    
    return logger, ui_handler