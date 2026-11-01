"""Config injection: current scheme, whitelist scope, and reversible restore.

Two behaviours are non-negotiable and covered here:
  * the whitelist is the *only* thing touched, and it targets the scheme MAA
    actually runs (``Current``), not a hard-coded ``Default``;
  * restoring reverts those keys only - MAA's own runtime writes (last-run dates,
    bookkeeping) must survive, which is why restore is key level, not a file copy.
"""

import json

import injector


def build_maa_root(tmp_path, *, current="模拟器常用配置", skip_after_update=True, pending=""):
    """A miniature but realistic MAA config directory (two schemes, old + new file)."""

    config = tmp_path / "config"
    config.mkdir(parents=True)
    old = {
        "Current": "Default",
        "Global": {"Timer.Timer1": "False", "VersionUpdate.package": pending},
        "Configurations": {
            "Default": {
                "Start.StartGame": "False",
                "Start.RunDirectly": "False",
                "Start.OpenEmulatorAfterLaunch": "False",
                "Connect.Address": "127.0.0.1:16384",
            }
        },
    }
    new = {
        "ConfigVersion": 1,
        "Current": current,
        "Configurations": {
            "模拟器常用配置": {
                "Gui": {
                    "StartUpSettings": {
                        "RunDirectly": False,
                        "SkipStartupAutoRunAfterUpdate": skip_after_update,
                        "StartEmulator": False,
                    },
                    "RuntimeSettings": {"StartGame": False, "ClientType": "Official"},
                },
                "TaskQueue": [
                    {"TaskType": "StartUp", "Name": "开始唤醒", "IsEnable": True},
                    {"TaskType": "Fight", "Name": "理智作战", "IsEnable": False},
                    {"TaskType": "Infrast", "Name": "基建换班", "IsEnable": True},
                ],
            },
            "Default": {
                "Gui": {
                    "StartUpSettings": {"RunDirectly": True},
                    "RuntimeSettings": {"StartGame": True},
                },
                "TaskQueue": [{"TaskType": "StartUp", "Name": "开始唤醒", "IsEnable": True}],
            },
        },
        "Update": {
            "CheckOnStartup": True,
            "AutoDownloadUpdatePackage": True,
            "AutoInstallUpdatePackage": False,
            "DoNotShowUpdate": False,
            "UpdatePackage": pending,
            "Name": "v6.21.0-beta.3" if pending else "",
        },
        "AnnouncementInfo": {"DoNotShow": False},
        "Timers": {"List": [{"IsEnabled": True}, {"IsEnabled": False}]},
    }
    (config / "gui.json").write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
    (config / "gui.new.json").write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
    return tmp_path


def dig(doc, path):
    node = doc
    for key in path:
        node = node[key]
    return node


# --------------------------------------------------------------------------- #
# Read side
# --------------------------------------------------------------------------- #
def test_current_scheme_comes_from_the_new_file(tmp_path):
    root = build_maa_root(tmp_path)
    assert injector.MaaConfig(root).current_scheme() == "模拟器常用配置"


def test_task_queue_reports_enabled_state(tmp_path):
    cfg = injector.MaaConfig(build_maa_root(tmp_path))
    assert [t["name"] for t in cfg.enabled_tasks()] == ["开始唤醒", "基建换班"]
    assert cfg.last_enabled_task()["name"] == "基建换班"


def test_schedule_skip_and_update_flags_are_visible(tmp_path):
    cfg = injector.MaaConfig(build_maa_root(tmp_path))
    assert cfg.schedule_enabled() is True
    assert cfg.skip_after_update() is True
    assert cfg.run_directly() is False
    assert cfg.check_update_on_startup() is True


def test_pending_update_is_reported(tmp_path):
    cfg = injector.MaaConfig(build_maa_root(tmp_path, pending="E:/pkg.zip"))
    assert cfg.pending_update() == ("v6.21.0-beta.3", "E:/pkg.zip")


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def test_plan_targets_the_active_scheme_only(tmp_path):
    inj = injector.MaaInjector(build_maa_root(tmp_path), tmp_path / "journal.json")
    scheme_changes = [c for c in inj.plan() if c.scope == "scheme" and c.filename == "gui.new.json"]
    assert scheme_changes
    assert all("Configurations" in c.path and c.path[1] == "模拟器常用配置" for c in scheme_changes)
    assert all("Default" not in c.path for c in scheme_changes)


def test_plan_suppresses_update_prompts(tmp_path):
    inj = injector.MaaInjector(build_maa_root(tmp_path), tmp_path / "journal.json")
    targets = {c.path: c.new for c in inj.plan() if c.scope == "global"}
    assert targets[("Update", "CheckOnStartup")] is False
    assert targets[("Update", "AutoDownloadUpdatePackage")] is False
    assert targets[("Update", "DoNotShowUpdate")] is True
    assert targets[("AnnouncementInfo", "DoNotShow")] is True


def test_plan_keeps_old_file_values_as_strings(tmp_path):
    inj = injector.MaaInjector(build_maa_root(tmp_path), tmp_path / "journal.json")
    old_changes = [c for c in inj.plan() if c.filename == "gui.json"]
    assert old_changes
    assert all(isinstance(c.new, str) for c in old_changes)


def test_plan_is_empty_when_already_configured(tmp_path):
    root = build_maa_root(tmp_path, skip_after_update=False)
    inj = injector.MaaInjector(root, tmp_path / "journal.json")
    inj.apply()
    assert inj.plan() == []


def test_missing_scheme_in_the_legacy_file_does_not_fabricate_one(tmp_path):
    root = build_maa_root(tmp_path, current="不存在的方案")
    inj = injector.MaaInjector(root, tmp_path / "journal.json")
    old_changes = [c for c in inj.plan() if c.scope == "scheme" and c.filename == "gui.json"]
    assert all(c.path[1] == "Default" for c in old_changes)


# --------------------------------------------------------------------------- #
# Applying
# --------------------------------------------------------------------------- #
def test_apply_writes_booleans_strings_and_update_flags(tmp_path):
    root = build_maa_root(tmp_path)
    inj = injector.MaaInjector(root, tmp_path / "journal.json")
    assert inj.apply()

    new = json.loads((root / "config" / "gui.new.json").read_text(encoding="utf-8"))
    settings = new["Configurations"]["模拟器常用配置"]["Gui"]["StartUpSettings"]
    assert settings["RunDirectly"] is True
    assert settings["SkipStartupAutoRunAfterUpdate"] is False
    assert new["Update"]["CheckOnStartup"] is False
    assert new["AnnouncementInfo"]["DoNotShow"] is True
    # Untouched scheme stays untouched.
    assert new["Configurations"]["Default"]["Gui"]["StartUpSettings"]["RunDirectly"] is True

    old = json.loads((root / "config" / "gui.json").read_text(encoding="utf-8"))
    assert old["Configurations"]["Default"]["Start.RunDirectly"] == "True"
    assert isinstance(old["Configurations"]["Default"]["Start.RunDirectly"], str)


def test_apply_defers_a_registered_update_package(tmp_path):
    root = build_maa_root(tmp_path, pending="E:/updates/maa.zip")
    inj = injector.MaaInjector(root, tmp_path / "journal.json")
    inj.apply()

    new = json.loads((root / "config" / "gui.new.json").read_text(encoding="utf-8"))
    assert new["Update"]["UpdatePackage"] == "", "MAA 启动时会安装已登记包，必须先摘下"

    journal = json.loads((tmp_path / "journal.json").read_text(encoding="utf-8"))
    assert journal["deferred_update"]["package"] == "E:/updates/maa.zip"


def test_pending_update_is_registered_again_on_restore(tmp_path):
    root = build_maa_root(tmp_path, pending="E:/updates/maa.zip")
    inj = injector.MaaInjector(root, tmp_path / "journal.json")
    inj.apply()
    assert inj.restore() is True

    new = json.loads((root / "config" / "gui.new.json").read_text(encoding="utf-8"))
    assert new["Update"]["UpdatePackage"] == "E:/updates/maa.zip"
    assert new["Update"]["Name"] == "v6.21.0-beta.3"


# --------------------------------------------------------------------------- #
# Restore
# --------------------------------------------------------------------------- #
def test_restore_reverts_the_whitelist_and_keeps_maa_own_writes(tmp_path):
    root = build_maa_root(tmp_path)
    before = json.loads((root / "config" / "gui.new.json").read_text(encoding="utf-8"))
    inj = injector.MaaInjector(root, tmp_path / "journal.json")
    inj.apply()

    # MAA saves its own bookkeeping during the run; restore must not undo it.
    path = root / "config" / "gui.new.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["Configurations"]["模拟器常用配置"]["Gui"]["RuntimeSettings"]["ClientType"] = "Bilibili"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    assert inj.restore() is True
    after = json.loads(path.read_text(encoding="utf-8"))
    settings = after["Configurations"]["模拟器常用配置"]["Gui"]["StartUpSettings"]
    assert settings["RunDirectly"] == before["Configurations"]["模拟器常用配置"]["Gui"]["StartUpSettings"]["RunDirectly"]
    assert after["Update"]["CheckOnStartup"] is True
    assert after["AnnouncementInfo"]["DoNotShow"] is False
    assert after["Configurations"]["模拟器常用配置"]["Gui"]["RuntimeSettings"]["ClientType"] == "Bilibili"
    assert not (root / "config" / "gui.new.json.m2.bak").exists()


def test_journal_survives_and_recover_undoes_a_crashed_apply(tmp_path):
    root = build_maa_root(tmp_path)
    journal = tmp_path / "journal.json"
    injector.MaaInjector(root, journal).apply()

    assert journal.is_file()
    assert injector.MaaInjector.recover(journal) is True

    new = json.loads((root / "config" / "gui.new.json").read_text(encoding="utf-8"))
    assert new["Configurations"]["模拟器常用配置"]["Gui"]["StartUpSettings"]["RunDirectly"] is False
    assert json.loads(journal.read_text(encoding="utf-8"))["done"] is True


def test_recover_on_a_clean_start_does_nothing(tmp_path):
    assert injector.MaaInjector.recover(tmp_path / "missing.json") is False


def test_apply_twice_restores_before_reinjecting(tmp_path):
    root = build_maa_root(tmp_path)
    journal = tmp_path / "journal.json"
    inj = injector.MaaInjector(root, journal)
    inj.apply()
    inj.apply()          # pending journal -> revert, then inject again
    assert inj.restore() is True

    new = json.loads((root / "config" / "gui.new.json").read_text(encoding="utf-8"))
    assert new["Configurations"]["模拟器常用配置"]["Gui"]["StartUpSettings"]["RunDirectly"] is False
