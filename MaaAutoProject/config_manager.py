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
    # 模拟器「刚启动就退出」视为失败（秒）。MuMu 因为 ADB 连不上会当场退出，
    # 旧版本把它当「任务完成」，误报成功。0 = 关闭该判定。
    "min_emulator_runtime": 60,
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
    "update_channel": "stable",   # stable / beta（beta 会包含 prerelease）

    # ---- 找图与点击（多分辨率 / 缩放适配）----
    # 1.0.x 是「全屏 + 固定尺寸」匹配，125%/150% 缩放下按钮对不上模板。
    # 这里暴露成可调参数：默认范围覆盖 60%~200%，DPI 缩放比作为优先中心。
    "search_scope": "window",        # window=只在目标窗口客户区找 / screen=全屏
    "search_padding": 0,             # 搜索区域外扩像素
    "match_threshold": 0.80,         # 相关系数阈值
    "match_scale_min": 0.60,         # 模板缩放搜索下限
    "match_scale_max": 2.00,         # 上限
    "match_scale_step": 0.05,        # 尺度步长
    "match_interval": 1.5,           # 两次尝试的间隔（秒）
    "click_mode": "sendinput",       # sendinput=真实点击 / postmessage=后台点击
    "click_activate": True,          # 点击前把目标窗口切到前台
    "click_restore_cursor": True,    # 点完把鼠标放回原位
    "click_move_delay_ms": 80,       # 移到目标后停顿，再按下
    "click_offset_x": 0,             # 命中点微调（像素）
    "click_offset_y": 0,
    "template_dir": "",              # 自定义模板目录，留空 = config/templates

    # ---- 点击生效校验 ----
    # 「点击发出去」不等于「点到了」：目标被遮挡或没抢到前台时，注入的点击会落到
    # 别的窗口上，日志毫无异常但界面没反应。这里比对点击点附近的像素变化，
    # 没变化就补点，并在日志里说清楚。
    "click_verify": True,
    "click_verify_delay_ms": 900,    # 点击后等多久再比对像素
    "click_retries": 1,              # 判定无效时补点次数

    # ---- 任务与界面 ----
    # 任务期间把主窗口收进托盘：我们自己的窗口很容易盖住 MAA 的按钮，
    # 那会同时毁掉找图（截到自己的界面）和点击（点到自己窗口上）。
    "minimize_on_task": True,

    # ---- 界面 ----
    "ui_scale": 1.0,                 # 界面缩放（1.0 / 1.25 / 1.5），切换即时生效

    # ---- 新手引导 / 公告 ----
    "tutorial_seen": False,          # 首次启动自动弹「新手教程」，看过就不再弹
    "announcements_seen": [],        # 已读公告 id（首页「公告」按钮上的小红点）
    # 上次读公告时的 updated 时间戳：公告内容更新（id 没变）时也要重新显示
    "announcements_seen_updated": "",
}

# 「设置页不拥有」的运行时键：设置页在启动时复制了一份配置，后续任何一次
# 自动保存都会把整份快照发回来。如果不保护这些键，用户点一下任意设置就会
# 把 tutorial_seen 冲回 False（表现为「新手教程每次启动都弹」）。
RUNTIME_CONFIG_KEYS = (
    "tutorial_seen",
    "announcements_seen",
    "announcements_seen_updated",
    "run_count",
    "last_run_time",
    "last_trigger_date",
    "window_geometry",
)


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