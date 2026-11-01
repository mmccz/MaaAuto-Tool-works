"""Setup check: the read-only "would this round work?" pass behind the wizard.

Real paths are replaced by a temp tree and a fake environment, so nothing touches
the machine running the tests.
"""

import json

import selfcheck


class FakeEnv:
    def __init__(self, files=(), processes=(), admin=True, detect=None):
        self.files = {str(f) for f in files}
        self.processes = set(processes)
        self.admin = admin
        self.detect = detect or (lambda name, candidates: None)

    def exe_exists(self, path):
        return bool(path) and str(path) in self.files

    def process_running(self, name):
        return name in self.processes

    def is_admin(self):
        return self.admin

    def detect_exe(self, process_name, candidates):
        return self.detect(process_name, candidates)


def make_maa(root, *, tasks=(("StartUp", "开始唤醒", True),), timers=False, skip_after_update=True):
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (root / "MAA.exe").write_text("x", encoding="utf-8")
    (config / "gui.json").write_text(
        json.dumps(
            {
                "Current": "Default",
                "Global": {"Timer.Timer1": "True" if timers else "False"},
                "Configurations": {"Default": {"Start.RunDirectly": "False"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (config / "gui.new.json").write_text(
        json.dumps(
            {
                "Current": "Default",
                "Configurations": {
                    "Default": {
                        "Gui": {
                            "StartUpSettings": {
                                "RunDirectly": False,
                                "SkipStartupAutoRunAfterUpdate": skip_after_update,
                            }
                        },
                        "TaskQueue": [
                            {"TaskType": t, "Name": n, "IsEnable": e} for t, n, e in tasks
                        ],
                    }
                },
                "Timers": {"List": [{"IsEnabled": timers}]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root / "MAA.exe"


def make_maaend(root, *, tasks=(("StartUp", True),), schedule=False):
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (root / "MaaEnd.exe").write_text("x", encoding="utf-8")
    (config / "mxu-MaaEnd.json").write_text(
        json.dumps(
            {
                "lastActiveInstanceId": "abc",
                "instances": [
                    {
                        "id": "abc",
                        "name": "全套日常（电脑）",
                        "tasks": [{"taskName": n, "enabled": e} for n, e in tasks],
                        "schedulePolicies": [{"enabled": schedule}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root / "MaaEnd.exe"


def by_code(checks):
    return {c.code: c for c in checks}


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_fully_configured_machine_has_no_errors(tmp_path):
    maa_exe = make_maa(tmp_path / "maa", skip_after_update=False)
    maaend_exe = make_maaend(tmp_path / "maaend", tasks=(("CloseGamePC", True),))
    env = FakeEnv(
        files=[maa_exe, maaend_exe],
        processes=["MuMuPlayer.exe"],
    )
    checks = selfcheck.run_selfcheck(
        {"maa_path": str(maa_exe), "maaend_path": str(maaend_exe)}, env
    )
    codes = by_code(checks)
    assert selfcheck.summarize(checks)[0] == selfcheck.LEVEL_OK
    assert codes["MAA_QUEUE"].level == selfcheck.LEVEL_OK
    assert codes["MAAEND_CLOSE_TASK"].level == selfcheck.LEVEL_OK
    assert selfcheck.blocking_issues(checks) == []


# --------------------------------------------------------------------------- #
# MAA problems
# --------------------------------------------------------------------------- #
def test_missing_maa_is_a_blocking_error(tmp_path):
    env = FakeEnv(files=[], processes=[])
    checks = selfcheck.run_selfcheck({"maa_path": ""}, env)
    codes = by_code(checks)
    assert codes["MAA_EXE"].level == selfcheck.LEVEL_ERROR
    assert "MAA 路径" in codes["MAA_EXE"].hint


def test_empty_task_queue_is_blocking(tmp_path):
    maa_exe = make_maa(tmp_path / "maa", tasks=(("Fight", "理智作战", False),))
    env = FakeEnv(files=[maa_exe], processes=["MuMuPlayer.exe"])
    checks = selfcheck.run_selfcheck({"maa_path": str(maa_exe)}, env)
    codes = by_code(checks)
    assert codes["MAA_QUEUE"].level == selfcheck.LEVEL_ERROR
    assert "没有勾选任何任务" in codes["MAA_QUEUE"].detail


def test_queue_shows_the_active_scheme_and_enabled_tasks(tmp_path):
    maa_exe = make_maa(
        tmp_path / "maa",
        tasks=(("StartUp", "开始唤醒", True), ("Fight", "理智作战", False), ("Infrast", "基建换班", True)),
    )
    env = FakeEnv(files=[maa_exe], processes=["MuMuPlayer.exe"])
    checks = selfcheck.run_selfcheck({"maa_path": str(maa_exe)}, env)
    detail = by_code(checks)["MAA_QUEUE"].detail
    assert "开始唤醒" in detail and "基建换班" in detail
    assert "理智作战" not in detail


def test_maa_timer_and_skip_switch_are_warnings(tmp_path):
    maa_exe = make_maa(tmp_path / "maa", timers=True, skip_after_update=True)
    env = FakeEnv(files=[maa_exe], processes=["MuMuPlayer.exe"])
    codes = by_code(selfcheck.run_selfcheck({"maa_path": str(maa_exe)}, env))
    assert codes["MAA_SCHEDULE"].level == selfcheck.LEVEL_WARN
    assert codes["MAA_SKIP_AFTER_UPDATE"].level == selfcheck.LEVEL_WARN
    assert codes["MAA_SKIP_AFTER_UPDATE"].hint        # tells the user it is handled


# --------------------------------------------------------------------------- #
# MaaEnd problems
# --------------------------------------------------------------------------- #
def test_last_task_must_close_the_game(tmp_path):
    maaend_exe = make_maaend(tmp_path / "maaend", tasks=(("StartUp", True), ("DailyRewards", True)))
    env = FakeEnv(files=[maaend_exe])
    codes = by_code(selfcheck.run_selfcheck({"maaend_path": str(maaend_exe)}, env))
    assert codes["MAAEND_CLOSE_TASK"].level == selfcheck.LEVEL_WARN
    assert "关闭程序" in codes["MAAEND_CLOSE_TASK"].hint


def test_named_instance_must_exist(tmp_path):
    maaend_exe = make_maaend(tmp_path / "maaend", tasks=(("CloseGamePC", True),))
    env = FakeEnv(files=[maaend_exe])
    checks = selfcheck.run_selfcheck(
        {"maaend_path": str(maaend_exe), "maaend_instance": "不存在的实例"}, env
    )
    assert by_code(checks)["MAAEND_INSTANCE"].level == selfcheck.LEVEL_ERROR


def test_instance_falls_back_to_the_last_active_one(tmp_path):
    maaend_exe = make_maaend(tmp_path / "maaend", tasks=(("CloseGamePC", True),))
    env = FakeEnv(files=[maaend_exe])
    checks = selfcheck.run_selfcheck({"maaend_path": str(maaend_exe)}, env)
    assert by_code(checks)["MAAEND_INSTANCE"].detail == "全套日常（电脑）"


# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #
def test_missing_emulator_and_admin_are_warnings(tmp_path):
    maa_exe = make_maa(tmp_path / "maa")
    env = FakeEnv(files=[maa_exe], processes=[], admin=False)
    checks = selfcheck.run_selfcheck({"maa_path": str(maa_exe)}, env)
    codes = by_code(checks)
    assert codes["EMULATOR"].level == selfcheck.LEVEL_WARN
    assert codes["ADMIN"].level == selfcheck.LEVEL_WARN


def test_environment_can_auto_detect_paths(tmp_path):
    maa_exe = make_maa(tmp_path / "maa")
    env = FakeEnv(files=[maa_exe], detect=lambda name, candidates: maa_exe if name == "maa.exe" else None)
    checks = selfcheck.run_selfcheck({}, env)
    assert by_code(checks)["MAA_EXE"].level == selfcheck.LEVEL_OK
