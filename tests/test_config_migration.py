"""config.json schema migration (1.x -> 2.0).

The control model changed in 2.0: configuration injection replaces find-and-click
by default. A user who had tuned the click path keeps it, so nothing changes under
their feet.
"""

import config_manager


def test_fresh_config_gets_the_new_defaults():
    assert config_manager.DEFAULT_CONFIG["control"] == "inject"
    assert config_manager.DEFAULT_CONFIG["config_version"] == config_manager.CONFIG_VERSION


def test_old_config_is_upgraded_to_inject():
    migrated = config_manager.migrate_config({"maa_path": "E:/MAA/MAA.exe"})
    assert migrated["control"] == "inject"
    assert migrated["config_version"] == config_manager.CONFIG_VERSION
    assert migrated["maa_path"] == "E:/MAA/MAA.exe"


def test_a_tuned_click_user_stays_on_click():
    old = {"match_threshold": 0.91, "click_retries": 4}
    migrated = config_manager.migrate_config(old)
    assert migrated["control"] == "click"


def test_an_untouched_click_default_does_not_pin_click():
    old = {"match_threshold": config_manager.DEFAULT_CONFIG["match_threshold"]}
    assert config_manager.migrate_config(old)["control"] == "inject"


def test_an_explicit_control_choice_is_never_overwritten():
    assert config_manager.migrate_config({"control": "click"})["control"] == "click"
    assert (
        config_manager.migrate_config(
            {"control": "inject", "config_version": 1, "click_retries": 5}
        )["control"]
        == "inject"
    )


def test_migration_is_idempotent():
    once = config_manager.migrate_config({"maa_path": "x"})
    twice = config_manager.migrate_config(once)
    assert once == twice


def test_garbage_config_version_is_treated_as_old():
    migrated = config_manager.migrate_config({"config_version": "not-a-number"})
    assert migrated["config_version"] == config_manager.CONFIG_VERSION


def test_load_config_merges_defaults_and_migrates(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"maa_path": "E:/MAA/MAA.exe"}', encoding="utf-8")
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(path))

    loaded = config_manager.load_config()

    assert loaded["maa_path"] == "E:/MAA/MAA.exe"
    assert loaded["control"] == "inject"
    assert loaded["retry"] == config_manager.DEFAULT_CONFIG["retry"]


def test_old_launcher_defaults_are_upgraded_to_games_only():
    for old in ("", "Launcher.exe", "Launcher.exe, Games.exe",
                "HypergryphLauncher.exe, Launcher.exe, Games.exe"):
        assert config_manager.migrate_config({"launcher_proc": old})["launcher_proc"] == "Games.exe"


def test_a_custom_launcher_list_is_kept():
    migrated = config_manager.migrate_config({"launcher_proc": "MyLauncher.exe"})
    assert migrated["launcher_proc"] == "MyLauncher.exe"
