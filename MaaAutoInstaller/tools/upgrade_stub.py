"""MaaAuto updater (``upgrade.exe``) -- 3.0.0 payload mode.

No compiling on the user's machine any more: download the CI-built
``MaaAuto_payload_v{ver}.zip``, verify it, unpack, back up and replace, update
the manifest, and roll back on failure.

Command line (unchanged from 2.x, the main app needs no call-site changes) ::

    upgrade.exe --from-main [--restart] [--silent] [--check-only] [--no-ui]
                [--downgrade] [--channel stable|beta]

``--no-ui`` has no window at all and only writes logs, for automation/CI;
``--silent`` still shows a non-interactive progress window (the 2.x semantics).

Exit codes: 0 success/update available; 1 already latest with --check-only; 2 error.
"""

import argparse
import datetime
import shutil
import sys
import tempfile
import time
from typing import Optional
import traceback
from pathlib import Path

# Console encoding is cp1252 in some environments and non-ASCII logs crash; force UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Support both layouts: (1) tools/upgrade_stub.py in the repo, (2) the packaged root dir
_HERE = Path(__file__).resolve().parent
if (_HERE / "installer").is_dir():
    _ROOT = _HERE
else:
    _ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from installer import __version__ as INSTALLER_VERSION
from installer.core import (
    read_manifest, write_manifest,
    check_update, compare_versions, sha256_of_file, download_file,
    is_main_running, request_main_exit,
    clear_upgrading_flag, write_failure_flag,
    apply_payload, apply_delta, apply_delta_chain, restart_main,
    cleanup_old_exe, cleanup_backups,
    DEFAULT_MIN_INSTALLER_VERSION,
)

APP_TITLE = "MaaAuto 升级程序"
APP_TITLE_SILENT = "MaaAuto 后台升级中"
MAIN_EXE = "MaaAuto.exe"


# --------------------------------------------------------------------------- #
# Arguments
# --------------------------------------------------------------------------- #
def parse_args(argv):
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--from-main", action="store_true")
    p.add_argument("--silent", action="store_true")
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--restart", action="store_true")
    p.add_argument("--downgrade", action="store_true")
    p.add_argument("--channel", default="stable", choices=["stable", "beta"])
    p.add_argument("--no-ui", action="store_true",
                   help="完全无界面（自动化/CI）；进度只写日志")
    p.add_argument("--debug", action="store_true")
    args, _unknown = p.parse_known_args(argv)
    return args


def get_install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
class Logger:
    def __init__(self, install_dir: Path):
        self.install_dir = Path(install_dir)
        self.log_path = None
        self._fh = None

    def open(self) -> Path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.log_path = Path(tempfile.gettempdir()) / f"MaaAuto_upgrade_{ts}.log"
        try:
            self._fh = open(self.log_path, "w", encoding="utf-8")
        except Exception:
            self._fh = None
        self.info(f"{APP_TITLE} {INSTALLER_VERSION}")
        self.info(f"argv: {sys.argv}")
        self.info("=" * 48)
        return self.log_path

    def close(self):
        if self._fh:
            try:
                self._fh.flush()
                self._fh.close()
            except Exception:
                pass

    def _write(self, level: str, msg: str):
        line = f"[{datetime.datetime.now():%H:%M:%S}] [{level}] {msg}"
        try:
            print(line, flush=True)
        except Exception:
            pass
        if self._fh:
            try:
                self._fh.write(line + "\n")
                self._fh.flush()
            except Exception:
                pass

    def info(self, msg): self._write("INFO", msg)
    def warn(self, msg): self._write("WARN", msg)
    def error(self, msg): self._write("ERROR", msg)

    def copy_to_install(self) -> None:
        """Copy this run's log to ``<install>/logs/upgrade/``."""
        if not self.log_path or not Path(self.log_path).exists():
            return
        try:
            target_dir = self.install_dir / "logs" / "upgrade"
            target_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(self.log_path, target_dir / f"{stamp}.log")
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Flow
# --------------------------------------------------------------------------- #
class UpgradeFlow:
    def __init__(self, args, log: Logger,
                 on_stage=None, on_progress=None, on_message=None,
                 cancel_check=None):
        self.args = args
        self.log = log
        self.on_stage = on_stage
        self.on_progress = on_progress
        self.on_message = on_message
        self.cancel_check = cancel_check
        self.install_dir = get_install_dir()
        self.manifest = None
        self._fail_reason = ""

    # ---- callbacks ----
    def _stage(self, key):
        if self.on_stage:
            try:
                self.on_stage(key)
            except Exception:
                pass

    def _progress(self, cur, total):
        if self.on_progress:
            try:
                self.on_progress(cur, total)
            except Exception:
                pass

    def _msg(self, text, level="info"):
        self.log.info(text)
        if self.on_message:
            try:
                self.on_message(str(text), level)
            except Exception:
                pass

    def _cancelled(self):
        if self.cancel_check:
            try:
                return bool(self.cancel_check())
            except Exception:
                return False
        return False

    # ---- terminal states ----
    def _restart_if_needed(self, reason: str) -> bool:
        if not getattr(self.args, "restart", False):
            self.log.info(f"未指定 --restart，跳过重启（{reason}）")
            return False
        try:
            if is_main_running():
                self.log.info("主程序仍在运行，跳过重启")
                return False
        except Exception:
            pass
        clear_upgrading_flag(self.install_dir)
        self.log.info(f"重启主程序（{reason}）")
        return restart_main(self.install_dir, log=self.log.info)

    def _write_failure(self, reason: str, info=None) -> None:
        try:
            write_failure_flag(
                install_dir=self.install_dir,
                from_version=(self.manifest.version if self.manifest else "?"),
                to_version=(getattr(info, "latest", "") if info else ""),
                reason=reason,
                log_path=str(self.log.log_path or ""),
            )
            self.log.info(f"已写 upgrade_failed.flag: {reason}")
        except Exception as e:
            self.log.warn(f"写 upgrade_failed.flag 失败: {e}")

    # ---- check ----
    def _settings(self):
        extra = (self.manifest.extra if self.manifest else {}) or {}
        api = extra.get("update_api") or \
            "https://api.github.com/repos/mmccz/MaaAuto-Tool-works/releases/latest"
        prefix = extra.get("payload_asset_prefix") or "MaaAuto_payload_v"
        min_ver = extra.get("min_installer_version") or DEFAULT_MIN_INSTALLER_VERSION
        return api, prefix, min_ver

    def _do_check(self):
        self._stage("locate")
        self.manifest = read_manifest(self.install_dir)
        if self.manifest is None:
            self.log.error(f"找不到 .maaauto.json: {self.install_dir}")
            self._fail_reason = "缺少安装信息 (.maaauto.json)"
            self._msg("未找到安装信息，请用完整安装包重新安装。", "error")
            return None, 2

        api, prefix, min_ver = self._settings()
        self.log.info(f"当前版本 {self.manifest.version}，升级器 {INSTALLER_VERSION}")

        cmp_result = compare_versions(INSTALLER_VERSION, min_ver)
        if cmp_result is None or cmp_result < 0:
            msg = f"升级器版本过低（需要 ≥ {min_ver}），请下载最新完整安装包。"
            self.log.error(msg)
            self._fail_reason = msg
            self._msg(msg, "error")
            return None, 2

        self._stage("check")
        channel = getattr(self.args, "channel", "stable") or "stable"
        self.log.info(f"更新渠道: {channel}")
        info = check_update(self.manifest, api, prefix,
                            allow_downgrade=bool(self.args.downgrade),
                            log=self.log.info,
                            channel=channel)
        if info.error:
            self.log.error(f"检查更新失败: {info.error}")
            self._fail_reason = f"检查更新失败: {info.error}"
            self._msg(f"检查更新失败：{info.error}", "error")
            return None, 2

        if not info.has_update:
            self.log.info(f"已是最新版本 ({info.current})")
            self._msg(f"已是最新版本 v{info.current}", "info")
            return info, 1
        self._msg(f"发现新版本：v{info.current} → v{info.latest}", "info")
        return info, 0

    # ---- check only ----
    def run_check_only(self) -> int:
        try:
            _info, code = self._do_check()
            return code
        except Exception as e:
            self.log.error(f"检查异常: {e}\n{traceback.format_exc()}")
            self._msg(f"检查更新失败：{e}", "error")
            return 2

    # ---- full upgrade ----
    def run_full(self) -> int:
        cleanup_old_exe(self.install_dir)
        cleanup_backups(self.install_dir)

        info, code = self._do_check()
        if code == 2:
            self._write_failure(self._fail_reason or "检查更新失败")
            self._restart_if_needed("检查更新失败")
            return 2
        if code == 1 or info is None or not info.has_update:
            self._restart_if_needed("已是最新")
            return 1 if self.args.check_only else 0

        if self.args.check_only:
            self.log.info("--check-only 模式，不执行升级")
            return 0

        if self._cancelled():
            self.log.info("用户取消")
            self._restart_if_needed("用户取消")
            return 0

        # 0) Prefer delta: download only what changed (measured 61 MB -> 0.6 MB).
        #    Any failure (base mismatch, corrupt patch, dropped network) falls back
        #    to the full package silently.
        if info.delta_url or getattr(info, 'delta_chain', None):
            old_version = self.manifest.version
            try:
                code = self._try_delta(info)
            except Exception as e:
                self.log.warn(f"差分升级失败，回退整包: {e}")
                code = None
            if code is not None:
                return code

        # 1) download payload
        self._stage("download")
        work = Path(tempfile.gettempdir()) / f"MaaAuto_payload_dl_{int(time.time())}"
        work.mkdir(parents=True, exist_ok=True)
        payload = work / info.payload_name
        try:
            self._msg(f"下载 payload（{info.payload_size / 1048576:.1f} MB）...", "info")
            download_file(info.payload_url, payload, log=self.log.info,
                          progress=self._progress)
        except Exception as e:
            self.log.error(f"下载失败: {e}")
            self._write_failure(f"下载 payload 失败: {e}", info)
            shutil.rmtree(work, ignore_errors=True)
            self._restart_if_needed("下载失败")
            return 2

        if self._cancelled():
            shutil.rmtree(work, ignore_errors=True)
            self._restart_if_needed("用户取消")
            return 0

        # 2) verify
        self._stage("verify")
        try:
            actual = sha256_of_file(payload)
        except Exception as e:
            self._write_failure(f"读取 payload 失败: {e}", info)
            shutil.rmtree(work, ignore_errors=True)
            self._restart_if_needed("校验失败")
            return 2

        expected = (info.payload_sha or "").lower()
        if expected and actual != expected:
            msg = f"payload 校验失败：期望 {expected[:12]}…，实际 {actual[:12]}…"
            self.log.error(msg)
            self._write_failure(msg, info)
            shutil.rmtree(work, ignore_errors=True)
            self._restart_if_needed("校验失败")
            return 2
        self.log.info(f"payload sha256: {actual}")

        # 3) stop main app
        self._stage("stop_main")
        if not request_main_exit(self.install_dir, log=self.log.info):
            self.log.error("无法停止主程序")
            self._write_failure("无法停止主程序", info)
            clear_upgrading_flag(self.install_dir)
            shutil.rmtree(work, ignore_errors=True)
            self._restart_if_needed("无法停止主程序")
            return 2

        # 4) replace
        self._stage("apply")
        old_version = self.manifest.version
        result = apply_payload(self.install_dir, payload, log=self.log.info,
                               progress=self._progress,
                               cancel_check=self._cancelled)
        shutil.rmtree(work, ignore_errors=True)

        if not result.success:
            self.log.error(f"替换失败: {result.error}")
            self._write_failure(f"替换失败: {result.error}", info)
            clear_upgrading_flag(self.install_dir)
            self._restart_if_needed("升级失败")
            return 2

        # 5) wrap up
        return self._finish(info, old_version, actual)

    # ---- delta attempt (single patch or serial chain) ----
    def _try_delta(self, info) -> Optional[int]:
        """Try a delta upgrade: one package or a serial chain.

        When versions are skipped (e.g. 1.2.0 -> 1.4.0) there is no direct delta
        package, but the chain 1.2.0 -> 1.3.0 -> 1.4.0 can be patched step by step.
        :return: exit code 0 on success; ``None`` when not applicable (base
                 mismatch etc.), so the caller falls back to the full package.
        """
        chain = list(getattr(info, "delta_chain", None) or [])
        if not chain:
            chain = [{"name": info.delta_name, "browser_download_url": info.delta_url,
                      "size": info.delta_size, "digest": f"sha256:{info.delta_sha}"}]

        work = Path(tempfile.gettempdir()) / f"MaaAuto_delta_dl_{int(time.time())}"
        work.mkdir(parents=True, exist_ok=True)
        try:
            total_mb = sum(int(a.get("size") or 0) for a in chain) / 1048576
            self._stage("download")
            self._msg(f"下载差分更新（{len(chain)} 步，共 {total_mb:.2f} MB）...", "info")

            files = []
            for idx, asset in enumerate(chain, 1):
                name = asset.get("name") or f"delta_{idx}.zip"
                dest = work / name
                download_file(asset.get("browser_download_url", ""), dest,
                              log=self.log.info, progress=self._progress)
                files.append(dest)

            self._stage("verify")
            for asset, path in zip(chain, files):
                digest = (asset.get("digest") or "").lower()
                if digest.startswith("sha256:"):
                    expected = digest.split(":", 1)[1].strip()
                    actual = sha256_of_file(path)
                    if actual != expected:
                        raise RuntimeError(
                            f"差分校验失败 {path.name}：期望 {expected[:12]}…，"
                            f"实际 {actual[:12]}…")

            self._stage("stop_main")
            if not request_main_exit(self.install_dir, log=self.log.info):
                raise RuntimeError("无法停止主程序")

            self._stage("apply")
            old_version = self.manifest.version
            if len(files) == 1:
                result = apply_delta(self.install_dir, files[0], log=self.log.info,
                                     progress=self._progress, cancel_check=self._cancelled)
            else:
                result = apply_delta_chain(self.install_dir, files,
                                           log=self.log.info, progress=self._progress,
                                           cancel_check=self._cancelled)
            if result.base_mismatch:
                self.log.info("本地文件与差分基准不符，改走整包")
                return None
            if not result.success:
                raise RuntimeError(result.error or "差分应用失败")

            self.log.info(f"差分应用成功（{result.replaced} 个文件，"
                          f"{len(files)} 步）")
            return self._finish(info, old_version, sha256_of_file(files[-1]))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ---- wrap up: manifest + restart ----
    def _finish(self, info, old_version: str, source_hash: str) -> int:
        self._stage("manifest")
        try:
            self.manifest.version = info.latest
            self.manifest.installer_version = INSTALLER_VERSION
            self.manifest.last_upgrade_from = old_version
            self.manifest.last_checked_at = datetime.datetime.now().isoformat(timespec="seconds")
            self.manifest.source_hash = source_hash
            write_manifest(self.install_dir, self.manifest)
        except Exception as e:
            self.log.warn(f"更新 .maaauto.json 失败: {e}")

        clear_upgrading_flag(self.install_dir)
        self.log.copy_to_install()
        cleanup_backups(self.install_dir)
        self._msg(f"升级完成：v{old_version} → v{info.latest}", "success")
        time.sleep(1.0)
        self._restart_if_needed("升级成功")
        return 0


# --------------------------------------------------------------------------- #
# no-UI mode
# --------------------------------------------------------------------------- #
def run_headless(args, log: Logger) -> int:
    flow = UpgradeFlow(args, log)
    return flow.run_check_only() if args.check_only else flow.run_full()


# --------------------------------------------------------------------------- #
# progress window
# --------------------------------------------------------------------------- #
STAGE_TEXT = {
    "locate": "读取安装信息…",
    "check": "检查更新…",
    "download": "下载更新包…",
    "verify": "校验文件…",
    "stop_main": "等待主程序退出…",
    "apply": "替换程序文件…",
    "manifest": "更新安装信息…",
    "restart": "重启主程序…",
    "done": "完成",
}


def run_ui(args, log: Logger, mode: str = "upgrade") -> int:
    """Progress window (plain ctypes/Win32).

    The flow runs in a ``threading.Thread``; the window's ``post_stage`` /
    ``post_progress`` / ``post_message`` only stash values into slots and then
    ``PostMessageW`` -- they never ``SetWindowTextW`` from another thread, which
    occasionally crashed with 0xC0000005 (it really happened historically). That
    is the same constraint as "callbacks must go through a Qt Signal".
    """
    from installer.core.native_ui import NativeProgressWindow

    window = NativeProgressWindow(
        title=APP_TITLE_SILENT if args.silent else APP_TITLE,
        silent=bool(args.silent),
        stage_text=STAGE_TEXT,
        check_only=bool(args.check_only),
        close_delay_ms=800 if (args.silent or args.check_only) else 2500,
    )

    flow = UpgradeFlow(
        args, log,
        on_stage=window.post_stage,
        on_progress=window.post_progress,
        on_message=window.post_message,
        cancel_check=window.is_cancelled,
    )

    def task() -> int:
        try:
            return flow.run_check_only() if args.check_only else flow.run_full()
        except Exception:
            log.error(f"升级流程异常:\n{traceback.format_exc()}")
            return 2

    return window.run(task)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main() -> int:
    args = parse_args(sys.argv[1:])
    install_dir = get_install_dir()
    log = Logger(install_dir)
    log.open()

    if not args.from_main:
        log.warn("缺少 --from-main，退出（防止误双击触发升级）")
        log.close()
        return 0

    try:
        if args.no_ui or (args.silent and args.check_only):
            return run_headless(args, log)
        return run_ui(args, log, mode="silent" if args.silent else "upgrade")
    except Exception:
        log.error(f"未捕获异常:\n{traceback.format_exc()}")
        return 2
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(main())
