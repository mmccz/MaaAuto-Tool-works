"""开机自启（1.4.5 起：登录计划任务；开发态仍用注册表 Run 键）。

为什么不用 ``HKCU\\...\\Run``
----------------------------
``MaaAuto.exe`` 的清单里写着 ``requireAdministrator``——它要往以管理员身份运行
的 MAA 窗口发消息。Windows 不会用 Run 键去拉起需要提权的程序：任务管理器的
「启动」页里开关还亮着，登录时却什么都不发生，日志也一片空白。1.0~1.4.4 的
「开机自启无效」就是这个原因。

计划任务可以指定「使用最高权限运行」（``/RL HIGHEST``）：登录时由任务计划
程序直接给出管理员令牌，既不弹 UAC，也不需要 Run 键。代价是创建/删除任务
需要管理员权限——而主程序本身就是提权运行的，所以开关随时能生效。

开发态（``python main.py``）没有提权需求，继续用 Run 键：改注册表不需要管理员，
而 ``/RL HIGHEST`` 的任务创建需要。两种方式都只是「登录时带 ``--autostart``
拉起自己」。
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
# 命令拼装
# --------------------------------------------------------------------------- #
def task_command(executable=None, script=None):
    """登录时执行的命令行（含引号，可直接作为 ``schtasks /TR`` 的值）。"""
    exe = executable or sys.executable
    if script:
        return f'"{exe}" "{script}" --autostart'
    return f'"{exe}" --autostart'


def is_frozen():
    return bool(getattr(sys, "frozen", False))


# --------------------------------------------------------------------------- #
# schtasks 封装
# --------------------------------------------------------------------------- #
def _schtasks(*args, timeout=20):
    """调用 schtasks，返回 CompletedProcess；调用失败返回 None。

    输出解码用 ``errors="replace"``：中文系统的提示是 GBK，而 Python 3.15
    在非 UTF-8 控制台下按 UTF-8 解，直接 ``text=True`` 会抛 UnicodeDecodeError。
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
# 注册表 Run 键（开发态 / 清理旧机制）
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
# 对外开关
# --------------------------------------------------------------------------- #
def set_enabled(enabled, executable=None, script=None):
    """打开/关闭开机自启，返回是否成功（失败时调用方负责提示用户）。"""
    exe = executable or sys.executable
    enabled = bool(enabled)

    if is_frozen():
        # 新机制：任务计划。顺手清掉旧版本留下的 Run 键，免得起两次。
        try:
            delete_run_value()
        except OSError as e:
            logger.debug(f"清理旧的 Run 键失败（可忽略）: {e}")
        if enabled:
            ok = create_task(task_command(exe))
            if not ok:
                # 退回 Run 键：至少留个痕迹，也方便用 diagnose 看到
                try:
                    write_run_value(task_command(exe))
                except OSError as e:
                    logger.warning(f"回退写 Run 键也失败: {e}")
            return ok
        return delete_task()

    # 开发态：Run 键足够，而且不需要管理员
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
    """当前生效的自启方式，给自检 / 诊断用：``task`` / ``run`` / ``none``。"""
    if task_exists():
        return "task"
    if run_value_enabled():
        return "run"
    return "none"


def describe():
    """一行人类可读的状态说明。"""
    now = state()
    if now == "task":
        return f"登录计划任务 {TASK_NAME}（最高权限）"
    if now == "run":
        return "注册表 Run 键（需要提权的主程序不会被它拉起）"
    return "未设置"
