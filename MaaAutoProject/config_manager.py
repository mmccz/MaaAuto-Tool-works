import datetime
import json
import os
import shutil
import sys
import logging
from PySide6.QtCore import QObject, Signal


def _get_base_dir():
    """Base directory of the program:
      - frozen (PyInstaller): the directory holding the exe
      - dev mode: the directory holding config_manager.py (the project root)
    Either way config/ and logs/ resolve to the same place, whatever the CWD.
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
    # ---- existing keys ----
    "maa_path": "",
    "maaend_path": "",
    "serverchan_key": "",
    "webhook_url": "",
    "execute_time": "08:00",           # legacy: single slot (kept for compatibility; schedule_times owns it since 1.3.0)
    "schedule_times": [],              # multiple slots, e.g. ["08:00", "20:30"]; empty = use execute_time
    "schedule_weekdays": [],           # 1=Mon ... 7=Sun; empty = every day
    "enable_schedule": False,
    "wait_timeout": 60,
    "game_start_timeout": 120,
    "game_exit_timeout": 7200,
    "retry_times": 3,
    "retry_interval": 30,
    # An emulator that quits right after launch counts as a failure (seconds). MuMu dies at
    # once when ADB cannot connect; older versions called that "done" and reported success. 0 = off.
    "min_emulator_runtime": 60,
    "auto_start": False,
    "minimize_to_tray": True,
    "kill_on_exit": True,
    "foreground_action": "none",
    "blacklist_apps": "",
    "last_trigger_date": "",
    "last_trigger_key": "",            # "YYYY-MM-DD HH:MM": per-slot dedupe (finer than a date)
    "run_count": 0,
    # ---- newer keys ----
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
    # ---- updates ----
    "auto_check_update": True,
    "auto_download_update": False,
    "update_channel": "stable",   # stable / beta (beta includes prereleases)

    # ---- template matching and clicking (multi-resolution / DPI scaling) ----
    # 1.0.x matched fixed sizes full-screen, so buttons missed their templates at 125%/150%.
    # Exposed as tunables: the default range covers 60%..200%, centred on the DPI scale factor.
    "search_scope": "window",        # window = target client area only / screen = whole screen
    "search_padding": 0,             # pixels added around the search area
    "match_threshold": 0.80,         # correlation-coefficient threshold
    "match_scale_min": 0.60,         # lowest template scale searched
    "match_scale_max": 2.00,         # highest
    "match_scale_step": 0.05,        # scale step
    "match_interval": 1.5,           # interval between attempts (seconds)
    "click_mode": "sendinput",       # sendinput = real click / postmessage = background post
    "click_activate": True,          # bring the target window to the foreground before clicking
    "click_restore_cursor": True,    # put the mouse back where it was afterwards
    "click_move_delay_ms": 80,       # pause after moving onto the target, before pressing
    "click_offset_x": 0,             # nudge the hit point (pixels)
    "click_offset_y": 0,
    "template_dir": "",              # custom template dir; empty = config/templates

    # ---- click verification ----
    # "The click was sent" is not "the click landed": if the target is covered or never
    # reached the foreground, the click hits another window - log clean, UI dead. Compare
    # the pixels around the click; if nothing changed, click again and say so in the log.
    "click_verify": True,
    "click_verify_delay_ms": 900,    # wait after clicking before comparing pixels
    "click_retries": 1,              # extra clicks when the first is judged ineffective

    # ---- logging ----
    # logs/<year>/<month>/<day>/run_N_<HHMMSS>/task.log means at least one dir per day;
    # long runs (especially with schedules) pile up thousands, plus failure screenshots.
    # Cleared at startup to "keep the last N days"; 0 = keep everything.
    "log_retention_days": 90,

    # ---- tasks and UI ----
    # Hide the main window in the tray during a task: our own window easily covers MAA's
    # buttons, which breaks finding (we capture ourselves) and clicking (we click ourselves).
    "minimize_on_task": True,

    # ---- UI ----
    "ui_scale": 1.0,                 # UI scale (1.0 / 1.25 / 1.5); applied immediately

    # ---- onboarding / announcements ----
    "tutorial_seen": False,          # Show the tutorial on first start; once seen it never pops up again
    "announcements_seen": [],        # ids of announcements already read (the red dot on the home-page button)
    # updated timestamp at last read: an edited announcement (same id) shows again
    "announcements_seen_updated": "",
}

# Runtime keys "not owned by the settings page": it copies the config at startup and
# sends the whole snapshot back on any auto-save. Without protecting these keys, one
# click on any setting resets tutorial_seen to False (tutorial pops up every start).
RUNTIME_CONFIG_KEYS = (
    "tutorial_seen",
    "announcements_seen",
    "announcements_seen_updated",
    "run_count",
    "last_run_time",
    "last_trigger_date",
    "last_trigger_key",
    "window_geometry",
)


def load_config():
    """Read config.json.
    utf-8-sig tolerates files with a BOM (PowerShell Set-Content -Encoding utf8 adds one).
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
    """Write config.json (UTF-8, no BOM).

    A temp file in the same directory is written first, then os.replace swaps it in
    atomically. The app saves on every change, while an upgrade / exit / Task Manager
    kill can land mid-write; overwriting in place leaves half a JSON file, and the next
    load_config() silently falls back to all defaults - users see "the config is gone".
    """
    tmp_file = CONFIG_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, CONFIG_FILE)


def cleanup_old_logs(retention_days=None, log_dir=None, logger=None):
    """Delete task log directories older than the retention window (called at startup).

    ``logs/`` is laid out as ``<year>/<month>/<day>/run_N_<HHMMSS>/task.log``, so there is
    at least one directory per day; long scheduled runs pile up thousands, plus the
    ``find_fail_*.png`` screenshots from failed matches.

    Only the **date parsed from the directory name** counts, not mtime: today's directory
    is still being written to, so its mtime keeps moving and using it could delete a
    directory in active use. Date directories are removed whole, empty parents too.

    :param retention_days: how many days to keep; ``None`` uses the default, ``<=0`` disables
    :param log_dir:        log root; defaults to ``LOG_DIR`` (tests pass a temp dir)
    :param logger:         optional logger for debug output
    :return: number of date directories removed
    """
    if retention_days is None:
        retention_days = DEFAULT_CONFIG["log_retention_days"]
    try:
        retention_days = int(retention_days)
    except (TypeError, ValueError):
        retention_days = DEFAULT_CONFIG["log_retention_days"]
    if retention_days <= 0:
        return 0

    base = log_dir or LOG_DIR
    cutoff = datetime.date.today() - datetime.timedelta(days=retention_days)

    def _list_dirs(path):
        try:
            return sorted(os.listdir(path))
        except OSError:
            return []

    def _rmdir_if_empty(path):
        try:
            if not os.listdir(path):
                os.rmdir(path)
        except OSError:
            pass

    removed = 0
    for yname in _list_dirs(base):
        ydir = os.path.join(base, yname)
        if not (yname.isdigit() and len(yname) == 4 and os.path.isdir(ydir)):
            continue
        for mname in _list_dirs(ydir):
            mdir = os.path.join(ydir, mname)
            if not (mname.isdigit() and len(mname) == 2 and os.path.isdir(mdir)):
                continue
            for dname in _list_dirs(mdir):
                ddir = os.path.join(mdir, dname)
                if not (dname.isdigit() and len(dname) == 2 and os.path.isdir(ddir)):
                    continue
                try:
                    day = datetime.date(int(yname), int(mname), int(dname))
                except ValueError:
                    continue
                if day >= cutoff:
                    continue          # still within the retention window (today included)
                try:
                    shutil.rmtree(ddir)
                    removed += 1
                except OSError as e:
                    if logger:
                        logger.debug(f"删除旧日志目录失败 {ddir}: {e}")
            _rmdir_if_empty(mdir)
        _rmdir_if_empty(ydir)

    # Top-level failure screenshots: files have a reliable mtime, so clean by mtime
    for name in _list_dirs(base):
        if not (name.startswith("find_fail_") and name.lower().endswith(".png")):
            continue
        path = os.path.join(base, name)
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).date()
        except OSError:
            continue
        if mtime < cutoff:
            try:
                os.unlink(path)
            except OSError:
                pass

    return removed


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