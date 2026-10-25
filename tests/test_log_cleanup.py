"""任务日志轮转测试（1.1.1 新增）。

背景：``logs/<年>/<月>/<日>/run_N_/task.log`` 每天至少一个目录，配合定时任务
长期运行会堆到几千个；找图失败还会往 logs 根目录丢 ``find_fail_*.png``。
清理按**目录名里的日期**判断（当天目录还在写，不能看 mtime）。
"""

import datetime
import os

import config_manager


def _mk(root, *parts):
    path = os.path.join(root, *parts)
    os.makedirs(path, exist_ok=True)
    return path


def _day(offset_days):
    return datetime.date.today() - datetime.timedelta(days=offset_days)


def _date_paths(root, day):
    return (str(day.year).zfill(4), str(day.month).zfill(2),
            str(day.day).zfill(2))


def test_removes_only_expired_days(tmp_path):
    root = str(tmp_path)
    old = _day(120)
    recent = _day(10)
    today = datetime.date.today()

    for day in (old, recent, today):
        y, m, d = _date_paths(root, day)
        _mk(root, y, m, d)

    removed = config_manager.cleanup_old_logs(90, log_dir=root)

    assert removed == 1
    oy, om, od = _date_paths(root, old)
    ry, rm, rd = _date_paths(root, recent)
    ty, tm, td = _date_paths(root, today)
    assert not os.path.exists(os.path.join(root, oy, om, od))
    assert os.path.isdir(os.path.join(root, ry, rm, rd))
    assert os.path.isdir(os.path.join(root, ty, tm, td))


def test_zero_means_keep_everything(tmp_path):
    root = str(tmp_path)
    y, m, d = _date_paths(root, _day(500))
    _mk(root, y, m, d)

    assert config_manager.cleanup_old_logs(0, log_dir=root) == 0
    assert os.path.isdir(os.path.join(root, y, m, d))


def test_removes_run_dirs_inside_expired_day(tmp_path):
    """删的是整天目录（连同里面的 run_N 子目录）。"""
    root = str(tmp_path)
    y, m, d = _date_paths(root, _day(200))
    run_dir = _mk(root, y, m, d, "run_7_233015")
    with open(os.path.join(run_dir, "task.log"), "w", encoding="utf-8") as f:
        f.write("x")

    config_manager.cleanup_old_logs(90, log_dir=root)
    assert not os.path.exists(os.path.join(root, y, m, d))


def test_cleans_empty_month_and_year(tmp_path):
    """整个月都过期时，空的 月/年 目录也顺手删掉，不留空壳。"""
    root = str(tmp_path)
    y, m, d = _date_paths(root, _day(400))
    _mk(root, y, m, d)

    config_manager.cleanup_old_logs(90, log_dir=root)
    assert os.listdir(root) == []


def test_ignores_non_date_directories(tmp_path):
    """不是「4 位年/2 位月/2 位日」的目录一律不碰。"""
    root = str(tmp_path)
    _mk(root, "config")
    _mk(root, "2026", "backup")
    _mk(root, "tmp")

    config_manager.cleanup_old_logs(1, log_dir=root)
    assert os.path.isdir(os.path.join(root, "config"))
    assert os.path.isdir(os.path.join(root, "2026", "backup"))
    assert os.path.isdir(os.path.join(root, "tmp"))


def test_find_fail_screenshots_by_mtime(tmp_path):
    root = str(tmp_path)
    old_png = os.path.join(root, "find_fail_maa_start_20250101_000000.png")
    new_png = os.path.join(root, "find_fail_maa_start_20990101_000000.png")
    for path in (old_png, new_png):
        with open(path, "wb") as f:
            f.write(b"\x89PNG")
    long_ago = (datetime.datetime.now() - datetime.timedelta(days=120)).timestamp()
    os.utime(old_png, (long_ago, long_ago))

    config_manager.cleanup_old_logs(90, log_dir=root)
    assert not os.path.exists(old_png)
    assert os.path.exists(new_png)


def test_missing_log_dir_is_harmless(tmp_path):
    missing = os.path.join(str(tmp_path), "nope")
    assert config_manager.cleanup_old_logs(90, log_dir=missing) == 0


def test_default_key_exists():
    assert config_manager.DEFAULT_CONFIG["log_retention_days"] == 90
