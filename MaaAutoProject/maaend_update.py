"""Driving MaaEnd's own updater - AUTO-MAS calls this "update takeover".

MXU has no switch to turn its updater off, and its pending-update state lives in the
WebView localStorage, so the only way to make an update happen *outside* a task round
is to launch MXU by itself and watch its log:

    发现新版本  ->  开始下载更新  ->  已保存待安装更新信息  ->  (restart) ->  已读取更新完成信息

We only drive the last leg: if an update is **already downloaded and pending**, start
MaaEnd without ``--autostart``, let it install and restart itself, then stop it and
let the round begin. Finding a brand-new version (no download yet) is reported, not
clicked - pressing "立即下载" would need UI automation, which is exactly what 2.0
set out to avoid.
"""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import upstream

#: The pending update has been installed and the app is running the new version.
APPLIED_MARKERS = ("已读取更新完成信息", "更新完成")
#: The download finished and the package waits for the next start.
PENDING_MARKERS = ("已保存待安装更新信息", "检测到待安装更新")

DEFAULT_TIMEOUT = 1800          # 30 minutes, same budget AUTO-MAS uses
POLL_INTERVAL = 2.0


@dataclass
class UpdateResult:
    state: str = "none"         # applied | failed | timeout | skipped
    version: str = ""
    message: str = ""
    evidence: str = ""


def newest_log(root):
    try:
        logs = [p for p in (Path(root) / "debug").glob("*.log") if p.is_file()]
    except OSError:
        return None
    if not logs:
        return None
    return max(logs, key=lambda p: p.stat().st_mtime)


def read_log(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _version_near(text, marker):
    import re

    match = re.search(re.escape(marker) + r"[:：]?\s*([^\s,;]+)", text)
    return match.group(1) if match else ""


def run_update_session(root, exe, logger=None, *, timeout=DEFAULT_TIMEOUT, poll=POLL_INTERVAL):
    """Launch MaaEnd on its own and wait until the pending update is applied."""

    root = Path(root)
    exe = str(exe)
    before = newest_log(root)
    started_at = time.time()

    def log(message, level="info"):
        if logger is not None:
            method = getattr(logger, level, None)
            if callable(method):
                method(message)

    try:
        process = subprocess.Popen(
            [exe],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return UpdateResult("failed", "", f"启动 MaaEnd 失败: {exc}")

    log("MaaEnd 更新会话已启动（不带 --autostart），等待它安装待更新")
    deadline = time.monotonic() + float(timeout)
    applied = False
    version = ""
    evidence = ""
    try:
        while time.monotonic() < deadline:
            current = newest_log(root)
            # A restart after the update creates a fresh session log; watch whatever
            # is newest, and also the file we started with.
            candidates = {p for p in (before, current) if p is not None}
            for path in candidates:
                text = read_log(path)
                for marker in APPLIED_MARKERS:
                    if marker in text:
                        applied = True
                        version = _version_near(text, marker)
                        evidence = f"{Path(path).name}: {marker}"
                        break
                if applied:
                    break
            if applied:
                break
            if process.poll() is not None:
                # It exited by itself: either the update is in place or it failed.
                current = newest_log(root)
                text = read_log(current) if current else ""
                for marker in APPLIED_MARKERS:
                    if marker in text:
                        applied = True
                        version = _version_near(text, marker)
                        evidence = f"{Path(current).name}: {marker}"
                        break
                break
            time.sleep(poll)
    finally:
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except Exception:  # noqa: BLE001
                    process.kill()
        except Exception:  # noqa: BLE001
            pass

    if applied:
        log(f"MaaEnd 待安装更新已完成（{version or '版本未知'}）", "success")
        return UpdateResult(
            "applied", version, f"MaaEnd 更新已完成（{version or '版本未知'}）", evidence
        )

    elapsed = time.time() - started_at
    if time.monotonic() >= deadline:
        return UpdateResult("timeout", "", f"MaaEnd 更新在 {elapsed / 60:.0f} 分钟内未完成", evidence)
    # Process exited without the applied marker: the pending update is probably
    # installed on the next start; do not block the round, just say so.
    log("MaaEnd 更新会话结束但未看到完成标志，继续执行任务", "warning")
    return UpdateResult("failed", "", "MaaEnd 更新会话未确认完成", evidence)
