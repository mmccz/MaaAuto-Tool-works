"""MAA adapter: inject the "start the queue" flags, launch the exe, judge its log.

No clicking at all on this path. The whole point of 2.0 is that the button we
used to find and press (and re-press whenever MAA restyled it) is replaced by two
config keys plus a log watcher.
"""

import subprocess
import time
from datetime import datetime
from pathlib import Path

import log_monitor
import process_utils
import run_state
import upstream
from injector import InjectionError, MaaConfig, MaaInjector

#: How long MAA may take to finish loading before we give up on it.
READY_TIMEOUT = 90
#: How often the log is polled while waiting.
POLL_INTERVAL = 1.0
#: Log lines that mean "MAA finished loading" (any one of them is enough).
READY_MARKERS = (
    "MaaAssistantArknights GUI started",
    "LoadResource Exit",
    "Init: false to true",
)

PROCESS_NAMES = ("maa.exe", "maa-cli.exe")


class MaaUpstream:
    """inject-mode adapter for MaaAssistantArknights."""

    name = "MAA"
    control_mode = "inject"

    def __init__(self, config, logger, *, journal_path=None, rules=None, clock=time):
        self.config = config or {}
        self.logger = logger
        self.clock = clock
        self.journal_path = Path(journal_path) if journal_path else None
        self.rules = rules or log_monitor.LogRules.load()
        self.exe = None
        self.injector = None
        self._started_at = None
        #: gui.log byte offset captured *before* launch: judge only this round.
        self._log_offset = 0
        #: monotonic launch time, used by the "did it even start?" guard.
        self._launched_at = 0.0

    # ---- discovery ------------------------------------------------------ #
    def probe(self):
        self.exe = upstream.detect_exe(
            "maa.exe",
            [
                str(self.config.get("maa_path") or "").strip(),
                r"E:\MAA\MAA.exe",
                str(Path.home() / "MAA" / "MAA.exe"),
            ],
        )
        return self.exe

    @property
    def maa_config(self):
        return MaaConfig(self.exe.parent) if self.exe else None

    # ---- preflight ------------------------------------------------------ #
    def preflight(self):
        issues = []
        exe = self.probe()
        if not exe:
            return [
                upstream.Issue(
                    "NO_EXE",
                    "未找到 MAA.exe",
                    "请在设置里填写 MAA 路径，或确认 MAA 已安装",
                )
            ]
        cfg = self.maa_config
        if not cfg.exists():
            issues.append(
                upstream.Issue(
                    "BAD_CONFIG",
                    f"MAA 配置目录不存在: {cfg.config_dir}",
                    "先手动启动一次 MAA，让它生成 config 目录",
                )
            )
            return issues
        if not cfg.writable():
            issues.append(
                upstream.Issue(
                    "PERMISSION",
                    f"MAA 配置目录不可写: {cfg.config_dir}",
                    "本程序需要以管理员身份运行，或把 MAA 装到可写目录",
                )
            )
        if process_utils.is_process_running(list(PROCESS_NAMES)):
            issues.append(
                upstream.Issue(
                    "ALREADY_RUNNING",
                    "MAA 已经在运行，无法安全注入配置",
                    "请先退出 MAA 再执行，或在设置里把控制方式改成「点击按钮」",
                )
            )
        if not cfg.enabled_tasks():
            issues.append(
                upstream.Issue(
                    "NO_TASK",
                    f"MAA 方案「{cfg.current_scheme()}」里没有勾选任何任务",
                    "请先在 MAA 里勾选要执行的任务",
                )
            )
        if cfg.schedule_enabled():
            issues.append(
                upstream.Issue(
                    "SCHEDULE",
                    "MAA 自带的定时任务处于开启状态",
                    "MAA 的定时和本工具的定时会重复触发，建议在 MAA 里关掉",
                    fatal=False,
                )
            )
        return issues

    # ---- lifecycle ------------------------------------------------------ #
    def prepare(self):
        """Inject the whitelist. MUST run before launch: MAA reads it once at startup."""

        exe = self.exe or self.probe()
        if not exe:
            raise upstream.UpstreamError("NO_EXE", "未找到 MAA.exe")
        if self.journal_path is None:
            raise upstream.UpstreamError("BAD_CONFIG", "缺少注入日志路径")
        self.injector = MaaInjector(exe.parent, self.journal_path, self.logger)
        try:
            changes = self.injector.apply()
        except InjectionError as exc:
            raise upstream.UpstreamError("BAD_CONFIG", str(exc)) from exc
        return changes

    def launch(self):
        """Start MAA with the already-injected config; remember where the log begins."""

        exe = self.exe or self.probe()
        if not exe:
            raise upstream.UpstreamError("NO_EXE", "未找到 MAA.exe")
        log_path = self.maa_config.log_path()
        self._log_offset = log_path.stat().st_size if log_path.is_file() else 0
        self.logger.info(f"启动 MAA: {exe}")
        try:
            subprocess.Popen(
                [str(exe)],
                cwd=str(Path(exe).parent),
                close_fds=True,
            )
        except OSError as exc:
            code = "NEED_ADMIN" if getattr(exc, "winerror", None) == 740 else "LAUNCH_FAIL"
            raise upstream.UpstreamError(
                code,
                f"启动 MAA 失败: {exc}",
                "MAA 被设置为以管理员身份运行，请用管理员权限启动本程序",
            ) from exc
        self._launched_at = time.monotonic()
        self._started_at = datetime.now()

    def wait_ready(self, timeout=None):
        """Wait for MAA's own "loaded" markers instead of guessing with a sleep."""

        limit = float(timeout or READY_TIMEOUT)
        log_path = self.maa_config.log_path()
        tail = log_monitor.LogTail(log_path, self._log_offset)
        deadline = time.monotonic() + limit
        seen = []
        while time.monotonic() < deadline:
            process_utils.check_interrupt()
            for record in tail.read():
                seen.append(record.text)
                if any(marker in record.text for marker in READY_MARKERS):
                    self._log_offset = tail.offset
                    self.logger.info("MAA 已就绪，开始等待任务结束")
                    return True
            if not process_utils.is_process_running(list(PROCESS_NAMES)):
                raise upstream.UpstreamError(
                    "LAUNCH_FAIL",
                    "MAA 进程启动后立即退出",
                    "请手动启动一次 MAA，确认它本身能正常打开",
                )
            time.sleep(0.5)
        # No marker: keep the offset we already consumed so nothing is judged twice.
        self._log_offset = tail.offset
        self.logger.warning(
            f"等待 MAA 加载完成超时（{limit:.0f} 秒），继续按日志判定"
        )
        return False

    # ---- waiting -------------------------------------------------------- #
    def wait_signal(self, deadline, on_progress=None):
        cfg = self.maa_config
        if cfg is None:
            return upstream.Outcome(
                state=run_state.STATE_FAILED, code="NO_EXE", message="未找到 MAA.exe"
            )
        log_path = cfg.log_path()
        tail = log_monitor.LogTail(log_path, self._log_offset)
        judge = log_monitor.MaaLogJudge(self.rules, since=self._started_at)
        last_progress = 0.0
        grace = getattr(self.rules, "maa_start_grace", 90)
        grace = 90.0 if grace is None else float(grace)
        self.logger.debug(f"判定日志: {log_path}")
        while time.monotonic() < deadline:
            process_utils.check_interrupt()
            for record in tail.read():
                outcome = judge.feed(record)
                if outcome is not None:
                    return outcome
            if not judge.started and self._launched_at:
                # Without a start marker the round never began (auto-run not
                # applied / dialog in the way). Fail fast instead of waiting hours.
                if time.monotonic() - self._launched_at > grace:
                    return upstream.Outcome(
                        state=run_state.STATE_FAILED,
                        code="NOT_STARTED",
                        message=(
                            f"MAA 已启动但 {grace:.0f} 秒内没有开始任务"
                            "（日志中没有出现「正在连接模拟器 / Index 0, Type /"
                            " LinkStartWithTasks」）"
                        ),
                        tasks=judge.task_list(),
                        evidence=judge.evidence_text(),
                    )
            if not process_utils.is_process_running(list(PROCESS_NAMES)):
                for record in tail.flush():
                    judge.feed(record)
                outcome = judge.finish(exited=True)
                self.logger.info(f"MAA 进程已退出，判定: {outcome.code or 'success'}")
                return outcome
            now = time.monotonic()
            if on_progress is not None and now - last_progress >= 30:
                last_progress = now
                on_progress(judge.task_list())
            time.sleep(POLL_INTERVAL)
        for record in tail.flush():
            judge.feed(record)
        outcome = judge.finish(exited=False)
        if outcome.code != "LOG_UNKNOWN":
            return outcome
        return upstream.Outcome(
            state=run_state.STATE_TIMEOUT,
            code="TIMEOUT",
            message="等待 MAA 完成超时",
            tasks=judge.task_list(),
            evidence=outcome.evidence,
        )

    # ---- teardown ------------------------------------------------------- #
    def stop(self, graceful=True):
        try:
            process_utils.kill_process_by_name(list(PROCESS_NAMES))
        except Exception as exc:  # noqa: BLE001 - stopping must never mask the result
            self.logger.warning(f"结束 MAA 失败: {exc}")

    def cleanup(self):
        if self.injector is not None:
            try:
                self.injector.restore()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"还原 MAA 配置失败: {exc}")
            self.injector = None
