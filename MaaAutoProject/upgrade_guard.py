"""Staleness test and cleanup for the upgrade flag ``config/.upgrading``.

Background
----------
The upgrader (``upgrade.exe``) writes ``<install>/config/.upgrading`` before stopping the
app; on startup the app calls ``sys.exit(0)`` as soon as it sees that file (before
QApplication, with no window and no log). Deliberate: no starting during an upgrade.

Risk
----
If the upgrader crashes, is killed in Task Manager, or returns right after
``request_main_exit()`` fails, the flag lingers and every double-click "does nothing", with no hint.

Decision rules (exit rather than delete by mistake)
---------------------------------------------------
=================================  ======================================
Condition                          Behaviour
=================================  ======================================
Flag missing                       start normally
Age < STALE_SECONDS                treated as upgrading, exit
Timed out, helper still running    treated as upgrading, exit
Timed out, no helper process       stale: delete the flag, keep starting
psutil unavailable / any error     treated as upgrading, exit
=================================  ======================================

Convention: ``config/.upgrading`` is written and removed by the upgrader; the app only
reads it and normally exits on sight. This module only covers the case where the
upgrader is gone but the flag remains.
"""

import os
import time
import datetime

# a flag older than this, with no upgrader process, counts as stale.
# Trade-off: upgrade.exe runs for the whole upgrade, so a timeout alone never affects
# a real upgrade; 5 minutes still covers "the upgrader just crashed, user retries now".
UPGRADE_FLAG_STALE_SECONDS = 300

# upgrader / uninstaller: fixed process names.
HELPER_PROCESS_NAMES = ("upgrade.exe", "uninstall.exe")

# full installer (MaaAuto_Online_v*-Windows-x64.exe) and the dev-mode installer.
HELPER_PROCESS_PREFIXES = ("maaauto_online",)
HELPER_PROCESS_KEYWORDS = ("maaautoinstaller", "maaauto-installer")


def _log(log_path, message):
    """Append an event to the given log file; any failure is silently ignored.

    This runs before the logging system is set up, so it cannot use logging.
    """
    if not log_path:
        return
    try:
        parent = os.path.dirname(log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{stamp} - INFO - {message}\n")
    except Exception:
        pass


def is_helper_running():
    """Whether an upgrader / uninstaller / installer process is running.

    :return: True means "an upgrade may be in progress" and the caller should play safe;
             True as well when that cannot be determined.
    """
    try:
        import psutil
    except Exception:
        return True

    try:
        iterator = psutil.process_iter(["name"])
    except Exception:
        return True

    for proc in iterator:
        try:
            name = (proc.info.get("name") or "").lower()
        except Exception:
            continue
        if not name:
            continue
        if name in HELPER_PROCESS_NAMES:
            return True
        if name.startswith(HELPER_PROCESS_PREFIXES):
            return True
        if any(key in name for key in HELPER_PROCESS_KEYWORDS):
            return True
    return False


def flag_age_seconds(flag_path):
    """Age of the flag file in seconds; None when its mtime cannot be read."""
    try:
        return time.time() - os.path.getmtime(flag_path)
    except OSError:
        return None


def resolve_upgrade_flag(flag_path, log_path=None, helper_probe=None,
                         stale_seconds=UPGRADE_FLAG_STALE_SECONDS):
    """Decide whether the app may continue starting.

    :param flag_path: full path of ``config/.upgrading``
    :param log_path:  event log path (usually ``logs/upgrading.log``), may be None
    :param helper_probe: process probe, defaults to :func:`is_helper_running`;
                         injected by tests only
    :param stale_seconds: staleness threshold, defaults to :data:`UPGRADE_FLAG_STALE_SECONDS`
    :return: True  = keep starting (no flag, or a stale one was cleared)
             False = an upgrade is in progress, the caller should exit outright
    """
    if not os.path.exists(flag_path):
        return True

    probe = helper_probe or is_helper_running
    age = flag_age_seconds(flag_path)

    if age is None:
        _log(log_path, f"检测到升级标志但无法读取时间戳，按升级中处理: {flag_path}")
        return False

    if age < stale_seconds:
        _log(log_path, f"检测到升级标志（{age:.0f}s），按升级中处理并退出")
        return False

    try:
        if probe():
            _log(log_path,
                 f"升级标志已存在 {age:.0f}s，但升级器仍在运行，继续等待")
            return False
    except Exception as e:
        _log(log_path, f"升级器进程探测失败（{e}），按升级中处理")
        return False

    try:
        os.remove(flag_path)
    except OSError as e:
        _log(log_path, f"检测到陈旧升级标志，但删除失败（{e}），按升级中处理")
        return False

    _log(log_path,
         f"已清理陈旧升级标志（{age:.0f}s 前写入，且无升级器进程），继续启动")
    return True


# --------------------------------------------------------------------------- #
# Self-test: python upgrade_guard.py
# --------------------------------------------------------------------------- #
def _self_test():
    import tempfile

    tmp = tempfile.mkdtemp(prefix="maaauto_guard_")
    flag = os.path.join(tmp, ".upgrading")
    log = os.path.join(tmp, "logs", "upgrading.log")

    assert resolve_upgrade_flag(flag, log_path=log,
                                helper_probe=lambda: False) is True, "无标志"

    with open(flag, "w", encoding="utf-8") as f:
        f.write("upgrading")

    assert resolve_upgrade_flag(flag, log_path=log,
                                helper_probe=lambda: False) is False, "新鲜标志"

    old = time.time() - (UPGRADE_FLAG_STALE_SECONDS + 10)
    os.utime(flag, (old, old))

    assert resolve_upgrade_flag(flag, log_path=log,
                                helper_probe=lambda: True) is False, "超时但升级器在跑"
    assert resolve_upgrade_flag(flag, log_path=log,
                                helper_probe=lambda: False) is True, "超时且无升级器"
    assert not os.path.exists(flag), "陈旧标志应被删除"

    def boom():
        raise RuntimeError("probe failed")

    with open(flag, "w", encoding="utf-8") as f:
        f.write("upgrading")
    os.utime(flag, (old, old))
    assert resolve_upgrade_flag(flag, log_path=log,
                                helper_probe=boom) is False, "探测异常应保守退出"

    assert os.path.exists(log), "应写入事件日志"
    print("[OK] upgrade_guard self-test passed")


if __name__ == "__main__":
    _self_test()
