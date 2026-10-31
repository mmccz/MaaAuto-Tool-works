"""开机自启：登录计划任务（打包态）与 Run 键（开发态）。

1.4.5 修的是「打开开关、重启电脑、什么也没发生」：MaaAuto.exe 清单要求管理员
权限，而 Windows 不会用 HKCU\\...\\Run 拉起需要提权的程序。这里把两种方式的
命令拼装、注册/清理、失败路径都固定下来，避免以后又退回 Run 键。
"""

import subprocess
import types

import pytest

import autostart


def _proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["schtasks"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------- #
# 命令拼装
# --------------------------------------------------------------------------- #
def test_task_command_frozen_has_no_extra_quotes():
    assert autostart.task_command(r"C:\MaaAuto\MaaAuto.exe") == \
        '"C:\\MaaAuto\\MaaAuto.exe" --autostart'


def test_task_command_script_mode_quotes_both():
    cmd = autostart.task_command(r"C:\Python\python.exe", r"C:\app\main.py")
    assert cmd == '"C:\\Python\\python.exe" "C:\\app\\main.py" --autostart'


# --------------------------------------------------------------------------- #
# schtasks 调用
# --------------------------------------------------------------------------- #
def test_task_exists_reads_returncode(monkeypatch):
    monkeypatch.setattr(autostart, "_schtasks", lambda *a, **k: _proc(0))
    assert autostart.task_exists() is True
    monkeypatch.setattr(autostart, "_schtasks", lambda *a, **k: _proc(1))
    assert autostart.task_exists() is False
    monkeypatch.setattr(autostart, "_schtasks", lambda *a, **k: None)
    assert autostart.task_exists() is False


def test_create_task_uses_highest_privilege_onlogon(monkeypatch):
    calls = []

    def fake(*args, **kwargs):
        calls.append(args)
        return _proc(0)

    monkeypatch.setattr(autostart, "_schtasks", fake)
    assert autostart.create_task('"C:\\MAA\\MaaAuto.exe" --autostart') is True

    args = calls[0]
    assert args[0] == "/Create"
    assert "/RL" in args and args[args.index("/RL") + 1] == "HIGHEST"
    assert "/SC" in args and args[args.index("/SC") + 1] == "ONLOGON"
    assert "/TR" in args and args[args.index("/TR") + 1].endswith("--autostart")
    assert "/F" in args
    assert autostart.TASK_NAME in args


def test_create_task_reports_failure(monkeypatch, caplog):
    monkeypatch.setattr(autostart, "_schtasks",
                        lambda *a, **k: _proc(1, stderr="拒绝访问。"))
    with caplog.at_level("ERROR"):
        assert autostart.create_task("x") is False
    assert any("拒绝访问" in r.message for r in caplog.records)


def test_delete_task_skips_when_absent(monkeypatch):
    calls = []
    monkeypatch.setattr(autostart, "_schtasks",
                        lambda *a, **k: calls.append(a) or _proc(1))
    assert autostart.delete_task() is True
    assert [c[0] for c in calls] == ["/Query"]      # 没有 /Delete


# --------------------------------------------------------------------------- #
# 对外开关
# --------------------------------------------------------------------------- #
def test_frozen_enable_creates_task_and_clears_legacy_run(monkeypatch):
    events = []
    monkeypatch.setattr(autostart, "is_frozen", lambda: True)
    monkeypatch.setattr(autostart, "delete_run_value",
                        lambda *a, **k: events.append("clear_run") or True)
    monkeypatch.setattr(autostart, "create_task",
                        lambda cmd: events.append(("create", cmd)) or True)

    assert autostart.set_enabled(True, executable=r"C:\MaaAuto\MaaAuto.exe") is True
    assert events[0] == "clear_run"
    assert events[1][0] == "create"
    assert events[1][1] == '"C:\\MaaAuto\\MaaAuto.exe" --autostart'


def test_frozen_disable_deletes_task(monkeypatch):
    events = []
    monkeypatch.setattr(autostart, "is_frozen", lambda: True)
    monkeypatch.setattr(autostart, "delete_run_value",
                        lambda *a, **k: events.append("clear_run") or True)
    monkeypatch.setattr(autostart, "delete_task",
                        lambda: events.append("delete_task") or True)

    assert autostart.set_enabled(False) is True
    assert events == ["clear_run", "delete_task"]


def test_dev_mode_uses_run_key(monkeypatch):
    events = []
    monkeypatch.setattr(autostart, "is_frozen", lambda: False)
    monkeypatch.setattr(autostart, "write_run_value",
                        lambda cmd, *a, **k: events.append(("write", cmd)))
    monkeypatch.setattr(autostart, "delete_run_value",
                        lambda *a, **k: events.append(("delete",)))

    assert autostart.set_enabled(True, executable="py.exe", script="main.py") is True
    assert events == [("write", '"py.exe" "main.py" --autostart')]

    events.clear()
    assert autostart.set_enabled(False) is True
    assert events == [("delete",)]


def test_failed_task_creation_falls_back_to_run_key(monkeypatch):
    written = []
    monkeypatch.setattr(autostart, "is_frozen", lambda: True)
    monkeypatch.setattr(autostart, "delete_run_value", lambda *a, **k: True)
    monkeypatch.setattr(autostart, "create_task", lambda cmd: False)
    monkeypatch.setattr(autostart, "write_run_value",
                        lambda cmd, *a, **k: written.append(cmd))

    assert autostart.set_enabled(True, executable="MaaAuto.exe") is False
    assert written == ['"MaaAuto.exe" --autostart']      # 至少留个痕迹


# --------------------------------------------------------------------------- #
# 状态
# --------------------------------------------------------------------------- #
def test_state_prefers_task(monkeypatch):
    monkeypatch.setattr(autostart, "task_exists", lambda: True)
    monkeypatch.setattr(autostart, "run_value_enabled", lambda *a, **k: True)
    assert autostart.state() == "task"


def test_state_falls_back_to_run(monkeypatch):
    monkeypatch.setattr(autostart, "task_exists", lambda: False)
    monkeypatch.setattr(autostart, "run_value_enabled", lambda *a, **k: True)
    assert autostart.state() == "run"
    assert "Run" in autostart.describe()


def test_state_none(monkeypatch):
    monkeypatch.setattr(autostart, "task_exists", lambda: False)
    monkeypatch.setattr(autostart, "run_value_enabled", lambda *a, **k: False)
    assert autostart.state() == "none"
    assert autostart.describe() == "未设置"
