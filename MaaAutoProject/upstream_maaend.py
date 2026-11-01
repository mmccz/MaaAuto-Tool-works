"""MaaEnd adapter: MXU command line + stdout judgement.

MaaEnd is the MaaFramework "MXU" shell. Its help text (extracted from the 2.14
binary) is::

    --autostart              run in autostart mode and trigger auto execution
    -i, --instance <name>    which instance (scheme) to run, autostart only
    -q, --quit-after-run     exit when the auto execution finishes

So the whole phase is: pick the instance, launch with those three flags, read the
task lines off stdout, and let the process exit tell us the round is over. No
window, no template, no foreground requirement.
"""

import json
import subprocess
import threading
import time
from pathlib import Path
from queue import Empty, Queue

import log_monitor
import process_utils
import run_state
import upstream

PROCESS_NAMES = ("maaend.exe",)
CONFIG_RELATIVE = Path("config") / "mxu-MaaEnd.json"
#: Tasks that end the run by closing the game / emulator (hard requirement #2).
CLOSE_TASK_PREFIXES = ("CloseGame", "CloseEmulator")

#: MXU writes its update state machine to the per-session front-end log. These are
#: the same markers AUTO-MAS keys on (发现新版本 / 开始下载更新 / 已保存待安装更新信息).
UPDATE_PENDING_MARKERS = ("已保存待安装更新信息", "检测到待安装更新")
UPDATE_AVAILABLE_MARKERS = ("发现新版本",)
UPDATE_DOWNLOADING_MARKERS = ("开始下载更新", "更新下载完成")
POLL_INTERVAL = 0.2


class MaaEndUpstream:
    """MXU command-line adapter for MaaEnd."""

    name = "MaaEnd"
    control_mode = "inject"

    def __init__(self, config, logger, *, rules=None, clock=time, popen=None):
        self.config = config or {}
        self.logger = logger
        self.clock = clock
        self.rules = rules or log_monitor.LogRules.load()
        self.popen = popen or subprocess.Popen
        self.exe = None
        self.instance = ""
        self._process = None
        self._queue = Queue()
        self._reader = None
        self._eof = False

    # ---- discovery ------------------------------------------------------ #
    def probe(self):
        self.exe = upstream.detect_exe(
            "maaend",
            [
                str(self.config.get("maaend_path") or "").strip(),
                r"E:\MaaEnd\MaaEnd.exe",
                str(Path.home() / "MaaEnd" / "MaaEnd.exe"),
            ],
        )
        return self.exe

    @property
    def root(self):
        return Path(self.exe).parent if self.exe else None

    def config_data(self):
        if self.root is None:
            return None
        try:
            return json.loads((self.root / CONFIG_RELATIVE).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return None

    def instances(self):
        data = self.config_data() or {}
        found = {}
        for item in data.get("instances") or []:
            if isinstance(item, dict) and item.get("name"):
                found[str(item["name"])] = item
        return found

    def resolve_instance(self):
        """Configured name, else the instance MaaEnd itself used last."""

        wanted = str(self.config.get("maaend_instance") or "").strip()
        instances = self.instances()
        if wanted:
            if wanted in instances:
                self.instance = wanted
                return wanted
            raise upstream.UpstreamError(
                "BAD_CONFIG",
                f"MaaEnd 里没有名为「{wanted}」的实例",
                "请在设置里选择 MaaEnd 实例，或在该实例存在后重试",
            )
        data = self.config_data() or {}
        last_id = data.get("lastActiveInstanceId")
        for name, item in instances.items():
            if last_id and item.get("id") == last_id:
                self.instance = name
                return name
        if len(instances) == 1:
            self.instance = next(iter(instances))
            return self.instance
        raise upstream.UpstreamError(
            "BAD_CONFIG",
            "无法确定 MaaEnd 实例",
            "MaaEnd 里有多个实例，请在设置里指定要用哪一个",
        )

    # ---- update state --------------------------------------------------- #
    def newest_log(self):
        """Latest ``debug/<date>-<n>.log``: MXU writes its update flow there."""

        if self.exe is None:
            self.probe()
        if self.root is None:
            return None
        try:
            candidates = sorted(
                (p for p in (self.root / "debug").glob("*.log") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return None
        return candidates[0] if candidates else None

    def update_state(self):
        """(state, version, evidence) with state in none/available/downloading/pending.

        MXU has no config switch for its updater; the only observable is its log.
        A pending update is installed at the **next** start, which can restart the
        app in the middle of a round - worth telling the user about.
        """

        log = self.newest_log()
        if log is None:
            return "none", "", ""
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "none", "", ""
        version = ""
        for marker in UPDATE_PENDING_MARKERS:
            if marker in text:
                version = self._version_after(text, marker)
                return "pending", version, f"{log.name}: {marker}"
        for marker in UPDATE_DOWNLOADING_MARKERS:
            if marker in text:
                return "downloading", self._version_after(text, marker), f"{log.name}: {marker}"
        for marker in UPDATE_AVAILABLE_MARKERS:
            if marker in text:
                return "available", self._version_after(text, marker), f"{log.name}: {marker}"
        return "none", "", ""

    @staticmethod
    def _version_after(text, marker):
        import re

        match = re.search(re.escape(marker) + r"[:：]?\s*([^\s,;]+)", text)
        return match.group(1) if match else ""

    def apply_pending_update(self, timeout=None):
        """Drive MXU's own installer when an update is already downloaded.

        Only the "pending" state is driven; a fresh "available" version needs the
        user to press download in MXU, so it stays a warning.
        """

        import maaend_update

        if self.exe is None:
            self.probe()
        if self.root is None:
            return None
        arguments = {}
        if timeout:
            arguments["timeout"] = timeout
        return maaend_update.run_update_session(
            self.root, self.exe, self.logger, **arguments
        )

    # ---- preflight ------------------------------------------------------ #
    def preflight(self):
        issues = []
        exe = self.probe()
        if not exe:
            return [
                upstream.Issue(
                    "NO_EXE",
                    "未找到 MaaEnd.exe",
                    "请在设置里填写 MaaEnd 路径，或确认 MaaEnd 已安装",
                )
            ]
        if self.config_data() is None:
            issues.append(
                upstream.Issue(
                    "BAD_CONFIG",
                    f"无法读取 {self.root / CONFIG_RELATIVE}",
                    "先手动启动一次 MaaEnd 完成首次配置",
                )
            )
            return issues
        try:
            self.resolve_instance()
        except upstream.UpstreamError as exc:
            issues.append(upstream.Issue(exc.code, exc.message, exc.hint))
            return issues

        item = self.instances().get(self.instance) or {}
        tasks = [t for t in (item.get("tasks") or []) if isinstance(t, dict)]
        enabled = [t for t in tasks if t.get("enabled")]
        if not enabled:
            issues.append(
                upstream.Issue(
                    "NO_TASK",
                    f"MaaEnd 实例「{self.instance}」里没有启用任务",
                    "请先在 MaaEnd 里勾选任务",
                )
            )
        else:
            last = str(enabled[-1].get("taskName") or "")
            if not last.startswith(CLOSE_TASK_PREFIXES):
                issues.append(
                    upstream.Issue(
                        "NO_CLOSE_TASK",
                        f"实例「{self.instance}」最后一个任务是「{last}」，不是关闭类任务",
                        "请在 MaaEnd 任务列表最后加上「关闭程序」或「关闭模拟器」",
                        fatal=False,
                    )
                )
        if any(
            isinstance(p, dict) and p.get("enabled")
            for p in (item.get("schedulePolicies") or [])
        ):
            issues.append(
                upstream.Issue(
                    "SCHEDULE",
                    "MaaEnd 自带的定时处于开启状态",
                    "MaaEnd 的定时会与本工具的定时重复触发，建议关闭",
                    fatal=False,
                )
            )
        state, version, evidence = self.update_state()
        if state in ("pending", "downloading"):
            issues.append(
                upstream.Issue(
                    "MAAEND_UPDATE_PENDING",
                    f"MaaEnd 有正在/待安装的更新（{version or '版本未知'}）",
                    "MaaEnd 会在下次启动时安装它并可能重启；若本轮被打断，请先手动打开一次 MaaEnd 完成更新",
                    fatal=False,
                )
            )
        elif state == "available":
            issues.append(
                upstream.Issue(
                    "MAAEND_UPDATE_AVAILABLE",
                    f"MaaEnd 检测到新版本（{version or '版本未知'}）",
                    "建议在 MaaEnd 里完成更新再挂机，避免它在运行中弹更新提示",
                    fatal=False,
                )
            )
        if not upstream.is_admin():
            issues.append(
                upstream.Issue(
                    "NEED_ADMIN",
                    "当前进程不是管理员，可能无法启动 MaaEnd",
                    "若启动失败并提示 WinError 740，请以管理员身份运行本程序",
                    fatal=False,
                )
            )
        return issues

    # ---- lifecycle ------------------------------------------------------ #
    def command(self):
        return [
            str(self.exe),
            "--autostart",
            "--instance",
            self.instance,
            "--quit-after-run",
        ]

    def prepare(self):
        """Nothing to pre-write: the command line already asks for the run."""

        return []

    def wait_ready(self, timeout=None):
        """MXU reports readiness on stdout; the first line doubles as the start signal."""

        return True

    def launch(self):
        exe = self.exe or self.probe()
        if not exe:
            raise upstream.UpstreamError("NO_EXE", "未找到 MaaEnd.exe")
        if not self.instance:
            self.resolve_instance()
        self._queue = Queue()
        self._eof = False
        self.logger.info(f"启动 MaaEnd（实例: {self.instance}）")
        self.logger.debug(f"命令行: {' '.join(self.command())}")
        try:
            self._process = self.popen(
                self.command(),
                cwd=str(self.root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            code = "NEED_ADMIN" if getattr(exc, "winerror", None) == 740 else "LAUNCH_FAIL"
            raise upstream.UpstreamError(
                code,
                f"启动 MaaEnd 失败: {exc}",
                "MaaEnd 被设置为以管理员身份运行，请用管理员权限启动本程序",
            ) from exc
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self):
        """Read stdout lines into a queue; the judge consumes them later."""

        stream = getattr(self._process, "stdout", None)
        if stream is None:
            self._eof = True
            return
        try:
            for line in stream:
                self._queue.put(line)
        except Exception:  # noqa: BLE001 - a broken pipe just ends the stream
            pass
        finally:
            self._eof = True
            self._queue.put(None)

    # ---- waiting -------------------------------------------------------- #
    def _drain(self, judge):
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                return
            if item is None:
                self._eof = True
                continue
            judge.feed(item)

    def wait_signal(self, deadline, on_progress=None):
        if self._process is None:
            return upstream.Outcome(
                state=run_state.STATE_FAILED,
                code="LAUNCH_FAIL",
                message="MaaEnd 未启动",
            )
        judge = log_monitor.MaaEndStdoutJudge(self.rules)
        last_progress = 0.0
        while time.monotonic() < deadline:
            process_utils.check_interrupt()
            self._drain(judge)
            exit_code = self._process.poll()
            if exit_code is not None and self._eof:
                self._drain(judge)
                outcome = judge.finish(exit_code=exit_code)
                self.logger.info(
                    f"MaaEnd 已退出（退出码 {exit_code}），判定: {outcome.code or 'success'}"
                )
                return outcome
            now = time.monotonic()
            if on_progress is not None and now - last_progress >= 30:
                last_progress = now
                on_progress(judge.task_list())
            time.sleep(POLL_INTERVAL)
        self._drain(judge)
        outcome = judge.finish(exit_code=None)
        if outcome.state == run_state.STATE_SUCCESS:
            return outcome
        return upstream.Outcome(
            state=run_state.STATE_TIMEOUT,
            code="TIMEOUT",
            message="等待 MaaEnd 完成超时",
            tasks=judge.task_list(),
            evidence=outcome.evidence,
        )

    # ---- teardown ------------------------------------------------------- #
    def launcher_processes(self):
        """Names of the game launcher processes to close with MaaEnd."""

        raw = str(self.config.get("launcher_proc") or "Games.exe")
        # Accept ascii/全角 separators, semicolons and newlines alike.
        raw = raw.translate({0xFF0C: 44, 0x3B: 44, 0x0A: 44, 0x09: 44})
        return [chunk.strip() for chunk in raw.split(",") if chunk.strip()]

    def stop_launcher(self):
        """Close the launcher MaaEnd leaves behind (it stays in the tray otherwise)."""

        names = self.launcher_processes()
        if not names:
            return False
        try:
            killed = process_utils.kill_process_tree(names)
        except Exception as exc:  # noqa: BLE001 - never mask the task result
            self.logger.warning(f"关闭游戏启动器失败: {exc}")
            return False
        if killed and self.logger is not None:
            self.logger.info(f"已关闭游戏启动器（{', '.join(names)}）")
        return killed

    def stop(self, graceful=True):
        proc = self._process
        if proc is not None and proc.poll() is None:
            try:
                if graceful:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except Exception:  # noqa: BLE001
                        proc.kill()
                else:
                    proc.kill()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"结束 MaaEnd 失败: {exc}")
        try:
            process_utils.kill_process_by_name(list(PROCESS_NAMES))
        except Exception:  # noqa: BLE001
            pass
        # The launcher is part of what MaaEnd's PC pretask started: close it too,
        # unless the user asked to keep the upstream environment alive.
        if not bool(self.config.get("keep_upstream", False)):
            self.stop_launcher()

    def cleanup(self):
        proc = self._process
        if proc is not None and getattr(proc, "stdout", None) is not None:
            try:
                proc.stdout.close()
            except Exception:  # noqa: BLE001
                pass
        if self._reader is not None and self._reader.is_alive():
            self._reader.join(timeout=2)
        self._process = None
