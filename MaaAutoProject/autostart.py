"""Autostart at logon (since 1.4.5: a logon scheduled task; dev mode still uses the
registry Run key).

Why not ``HKCU\\...\\Run``
-------------------------
The ``MaaAuto.exe`` manifest declares ``requireAdministrator``, because it has to
send messages to the MAA window running elevated. Windows will not launch an
elevated program from the Run key: the toggle on Task Manager > Startup still
looks enabled, yet nothing happens at logon and the log stays empty. That is why
"autostart does not work" was reported from 1.0 to 1.4.4.

A scheduled task can run "with highest privileges" (``/RL HIGHEST``): at logon the
Task Scheduler hands out the admin token itself, with no UAC prompt and no Run key.
The cost is that creating / deleting the task needs admin rights - and the app
itself already runs elevated, so the toggle takes effect whenever it is flipped.

Dev mode (``python main.py``) has no elevation needs and keeps the Run key: editing
the registry needs no admin rights, while creating a ``/RL HIGHEST`` task does.
Either way the only job is to start ourselves at logon with ``--autostart``.
"""

import logging
import os
import subprocess
import sys

logger = logging.getLogger("MaaAuto")

TASK_NAME = "MaaAuto"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "MaaAuto"

_CREATE_NO_WINDOW = 0x08000000


# --------------------------------------------------------------------------- #
# Command building
# --------------------------------------------------------------------------- #
def task_command(executable=None, script=None):
    """Command line run at logon (quoted, usable directly as ``schtasks /TR``)."""
    exe = executable or sys.executable
    if script:
        return f'"{exe}" "{script}" --autostart'
    return f'"{exe}" --autostart'


def is_frozen():
    return bool(getattr(sys, "frozen", False))


# --------------------------------------------------------------------------- #
# schtasks wrapper
# --------------------------------------------------------------------------- #
def _schtasks(*args, timeout=20):
    """Run schtasks and return its CompletedProcess; None when the call itself fails.

    Output is decoded with ``errors="replace"``: a Chinese system prints GBK prompts,
    while Python 3.15 decodes as UTF-8 on a non-UTF-8 console, so a plain
    ``text=True`` raises UnicodeDecodeError.
    """
    try:
        return subprocess.run(
            ["schtasks", *args], capture_output=True, text=True,
            timeout=timeout, creationflags=_CREATE_NO_WINDOW, errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"调用 schtasks {' '.join(args)} 失败: {e}")
        return None


def _detail(result):
    if result is None:
        return "无法执行 schtasks"
    return ((result.stderr or "") + (result.stdout or "")).strip() or "无输出"


def task_exists():
    result = _schtasks("/Query", "/TN", TASK_NAME)
    return bool(result is not None and result.returncode == 0)


def create_task(command):
    result = _schtasks("/Create", "/TN", TASK_NAME, "/TR", command,
                       "/SC", "ONLOGON", "/RL", "HIGHEST", "/F")
    if result is None or result.returncode != 0:
        logger.error(f"创建登录自启任务失败: {_detail(result)}")
        return False
    logger.info(f"已创建登录自启任务 {TASK_NAME}: {command}")
    return True


def delete_task():
    if not task_exists():
        return True
    result = _schtasks("/Delete", "/TN", TASK_NAME, "/F")
    if result is None or result.returncode != 0:
        logger.error(f"删除登录自启任务失败: {_detail(result)}")
        return False
    logger.info(f"已删除登录自启任务 {TASK_NAME}")
    return True


# --------------------------------------------------------------------------- #
# Registry Run key (dev mode / cleaning up the old mechanism)
# --------------------------------------------------------------------------- #
def write_run_value(command, name=RUN_VALUE):
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                         winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
    finally:
        winreg.CloseKey(key)


def delete_run_value(name=RUN_VALUE):
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_SET_VALUE)
    except FileNotFoundError:
        return True
    try:
        winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass
    finally:
        winreg.CloseKey(key)
    return True


def run_value_enabled(name=RUN_VALUE):
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return False
    try:
        value, _ = winreg.QueryValueEx(key, name)
        return bool(str(value).strip())
    except FileNotFoundError:
        return False
    finally:
        winreg.CloseKey(key)


# --------------------------------------------------------------------------- #
# Public toggle
# --------------------------------------------------------------------------- #
def set_enabled(enabled, executable=None, script=None):
    """Enable/disable autostart; returns whether it worked (the caller reports failures)."""
    exe = executable or sys.executable
    enabled = bool(enabled)

    if is_frozen():
        # New mechanism: a scheduled task. Drop the Run key left by older versions too, or the app starts twice.
        try:
            delete_run_value()
        except OSError as e:
            logger.debug(f"清理旧的 Run 键失败（可忽略）: {e}")
        if enabled:
            ok = create_task(task_command(exe))
            if not ok:
                # Fall back to the Run key: at least it leaves a trace, and diagnose can see it
                try:
                    write_run_value(task_command(exe))
                except OSError as e:
                    logger.warning(f"回退写 Run 键也失败: {e}")
            return ok
        return delete_task()

    # Dev mode: the Run key is enough and needs no admin rights
    command = task_command(exe, script)
    try:
        if enabled:
            write_run_value(command)
            logger.info(f"开发态开机自启已写入 Run 键: {command}")
        else:
            delete_run_value()
            logger.info("开发态开机自启已从 Run 键移除")
        return True
    except OSError as e:
        logger.error(f"写入开机自启 Run 键失败: {e}")
        return False


def state():
    """Active autostart mode for self-check / diagnose: ``task`` / ``run`` / ``none``."""
    if task_exists():
        return "task"
    if run_value_enabled():
        return "run"
    return "none"


def describe():
    """One human-readable status line."""
    now = state()
    if now == "task":
        return f"登录计划任务 {TASK_NAME}（最高权限）"
    if now == "run":
        return "注册表 Run 键（需要提权的主程序不会被它拉起）"
    return "未设置"
