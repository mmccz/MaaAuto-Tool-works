"""MaaEnd adapter: MXU's updater has no config switch, only its log.

A pending update is installed on the next start and can restart the app mid-round,
so the adapter reports it instead of pretending nothing would happen.
"""

import json

import upstream_maaend


def make_maaend(tmp_path, *, version="2.14.0-beta.1", log_text=""):
    root = tmp_path / "MaaEnd"
    config = root / "config"
    debug = root / "debug"
    config.mkdir(parents=True)
    debug.mkdir(parents=True)
    (root / "MaaEnd.exe").write_text("x", encoding="utf-8")
    (root / "interface.json").write_text(
        json.dumps({"version": version}, ensure_ascii=False), encoding="utf-8"
    )
    (config / "mxu-MaaEnd.json").write_text(
        json.dumps(
            {
                "lastActiveInstanceId": "abc",
                "instances": [
                    {
                        "id": "abc",
                        "name": "全套日常（电脑）",
                        "tasks": [{"taskName": "CloseGamePC", "enabled": True}],
                        "schedulePolicies": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if log_text:
        (debug / "2026-11-01-4.log").write_text(log_text, encoding="utf-8")
    return root


def adapter(root):
    return upstream_maaend.MaaEndUpstream(
        {"maaend_path": str(root / "MaaEnd.exe")}, None
    )


def test_no_update_markers_means_none(tmp_path):
    root = make_maaend(tmp_path, log_text="2026-11-01 15:42:44 INFO [App] 加载完成\n")
    assert adapter(root).update_state()[0] == "none"


def test_pending_update_is_detected_with_version(tmp_path):
    root = make_maaend(
        tmp_path,
        log_text=(
            "2026-11-01 20:00:00 INFO [Update] 发现新版本: 2.15.0\n"
            "2026-11-01 20:01:00 INFO [Update] 开始下载更新: 2.15.0\n"
            "2026-11-01 20:02:00 INFO [Update] 已保存待安装更新信息: 2.15.0\n"
        ),
    )
    state, version, evidence = adapter(root).update_state()
    assert state == "pending"
    assert version == "2.15.0"
    assert "已保存待安装更新信息" in evidence


def test_available_update_is_detected(tmp_path):
    root = make_maaend(tmp_path, log_text="发现新版本：2.15.0\n")
    assert adapter(root).update_state()[:2] == ("available", "2.15.0")


def test_downloading_update_is_detected(tmp_path):
    root = make_maaend(tmp_path, log_text="开始下载更新: 2.15.0\n")
    assert adapter(root).update_state()[0] == "downloading"


def test_newest_log_wins(tmp_path):
    root = make_maaend(tmp_path, log_text="发现新版本: 1.0\n")
    newer = root / "debug" / "2026-11-02-1.log"
    newer.write_text("已保存待安装更新信息: 2.0\n", encoding="utf-8")
    import os
    import time

    os.utime(newer, (time.time() + 10, time.time() + 10))
    assert adapter(root).update_state()[:2] == ("pending", "2.0")


def test_preflight_warns_about_a_pending_update(tmp_path):
    root = make_maaend(tmp_path, log_text="已保存待安装更新信息: 2.15.0\n")
    up = adapter(root)
    issues = up.preflight()
    codes = {i.code for i in issues}
    assert "MAAEND_UPDATE_PENDING" in codes
    issue = next(i for i in issues if i.code == "MAAEND_UPDATE_PENDING")
    assert issue.fatal is False
    assert "重启" in issue.hint


# --------------------------------------------------------------------------- #
# Launcher cleanup (2.0.5)
# --------------------------------------------------------------------------- #
def test_launcher_names_are_parsed_from_config(tmp_path):
    up = upstream_maaend.MaaEndUpstream({"launcher_proc": "Launcher.exe; Games.exe，Hypergryph.exe"}, None)
    assert up.launcher_processes() == ["Launcher.exe", "Games.exe", "Hypergryph.exe"]


def test_launcher_names_default_to_games_only(tmp_path):
    """Only Games.exe: Launcher.exe is the bootstrap/updater, killing it is pointless."""

    assert upstream_maaend.MaaEndUpstream({}, None).launcher_processes() == ["Games.exe"]


def test_stop_closes_maaend_and_the_launcher(tmp_path, monkeypatch):
    root = make_maaend(tmp_path)
    killed = []
    monkeypatch.setattr(
        upstream_maaend.process_utils, "kill_process_by_name", lambda names: killed.append(list(names)) or True
    )
    monkeypatch.setattr(
        upstream_maaend.process_utils, "kill_process_tree", lambda names: killed.append(list(names)) or True
    )
    up = upstream_maaend.MaaEndUpstream({"maaend_path": str(root / "MaaEnd.exe")}, None)
    up.stop(graceful=True)
    assert ["maaend.exe"] in killed, "MaaEnd 本身要被关闭"
    assert ["Games.exe"] in killed, "鹰角启动器要一起关闭（含 QtWebEngine 子进程）"


def test_keep_upstream_leaves_the_launcher_alone(tmp_path, monkeypatch):
    root = make_maaend(tmp_path)
    killed = []
    monkeypatch.setattr(
        upstream_maaend.process_utils, "kill_process_by_name", lambda names: killed.append(list(names)) or True
    )
    monkeypatch.setattr(
        upstream_maaend.process_utils, "kill_process_tree", lambda names: killed.append(list(names)) or True
    )
    up = upstream_maaend.MaaEndUpstream(
        {"maaend_path": str(root / "MaaEnd.exe"), "keep_upstream": True}, None
    )
    up.stop(graceful=True)
    assert ["Games.exe"] not in killed
