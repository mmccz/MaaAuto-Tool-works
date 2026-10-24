"""升级标志 ``config/.upgrading`` 的陈旧判断与清理。

背景
----
升级器（``upgrade.exe``）在停止主程序前写入 ``<install>/config/.upgrading``；
主程序启动时只要看到该文件就 ``sys.exit(0)``（发生在 QApplication 之前，
没有任何窗口、也没有日志）。这是刻意的：升级期间不允许再启动主程序。

风险
----
升级器崩溃、被任务管理器结束，或在 ``request_main_exit()`` 失败后直接返回，
标志就会残留。此后用户每次双击主程序都“毫无反应”，且没有任何提示。

判定规则（保守优先，宁可多退一次，不可误删）
------------------------------------------
==============  ==========================  ====================
条件                                         行为
==============  ==========================  ====================
标志不存在                                    正常启动
写入时间 < STALE_SECONDS                      视为升级中，退出
超时，但升级器/卸载器/安装器进程仍在           视为升级中，退出
超时，且没有上述进程                          判定陈旧：删除标志，继续启动
psutil 不可用 / 判断过程中异常                视为升级中，退出
==============  ==========================  ====================

约定：``config/.upgrading`` 由升级器写入、由升级器删除；主程序只读，
正常情况下看到标志就退出。本模块仅负责「升级器已消失但标志还在」的兜底。
"""

import os
import time
import datetime

# 超过这个秒数且没有升级器进程，才认定为陈旧标志。
# 取值权衡：升级全程 upgrade.exe 都在运行，所以“超时”本身不影响正常升级；
# 而用户被锁死的时间不应太长，5 分钟足够覆盖“升级器刚崩溃、用户立刻重开”。
UPGRADE_FLAG_STALE_SECONDS = 300

# 升级器 / 卸载器：固定进程名。
HELPER_PROCESS_NAMES = ("upgrade.exe", "uninstall.exe")

# 完整安装包（MaaAuto_Online_v*-Windows-x64.exe）与开发态安装器。
HELPER_PROCESS_PREFIXES = ("maaauto_online",)
HELPER_PROCESS_KEYWORDS = ("maaautoinstaller", "maaauto-installer")


def _log(log_path, message):
    """把事件追加到指定日志文件；任何失败都静默忽略。

    该函数运行在日志系统初始化之前，因此不能使用 logging。
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
    """是否有升级器 / 卸载器 / 安装器进程在运行。

    :return: True 表示“可能正在升级”，调用方应按保守策略处理；
             无法判断时同样返回 True。
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
    """返回标志文件的年龄（秒）；读不到 mtime 时返回 None。"""
    try:
        return time.time() - os.path.getmtime(flag_path)
    except OSError:
        return None


def resolve_upgrade_flag(flag_path, log_path=None, helper_probe=None,
                         stale_seconds=UPGRADE_FLAG_STALE_SECONDS):
    """判断主程序是否可以继续启动。

    :param flag_path: ``config/.upgrading`` 的完整路径
    :param log_path:  事件日志路径（通常是 ``logs/upgrading.log``），可为 None
    :param helper_probe: 进程探测函数，默认 :func:`is_helper_running`；
                         仅用于测试注入
    :param stale_seconds: 陈旧阈值，默认 :data:`UPGRADE_FLAG_STALE_SECONDS`
    :return: True  = 继续启动（没有标志，或已清理陈旧标志）
             False = 升级进行中，调用方应直接退出
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
# 自测：python upgrade_guard.py
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
