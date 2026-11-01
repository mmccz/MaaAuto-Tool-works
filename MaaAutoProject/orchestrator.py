"""One automation round, from "start the upstream" to "clean up after it".

This is the single state owner for 2.0: it walks the phases, asks each adapter to
arm itself, judges the outcome from logs, retries only what is worth retrying, and
always leaves the machine the way it found it (injected config restored, processes
stopped when configured).

Everything external is injectable (upstreams, sleep, clock, foreground hook) so the
whole flow can be tested without a screen, a process or a network.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import run_state
import upstream

#: Backoff between attempts of the same phase (seconds), capped by the last value.
BACKOFF = (30, 60, 120)

STATUS_OK = "成功"
STATUS_ERROR = "报错"
STATUS_ABORTED = "中止"


@dataclass
class RunResult:
    status: str = STATUS_OK
    message: str = ""
    tasks: list = field(default_factory=list)
    record: object = None
    #: Codes seen this round, for the report and the log.
    codes: list = field(default_factory=list)


class Orchestrator:
    def __init__(
        self,
        config,
        logger,
        *,
        store=None,
        upstreams=None,
        sleep=None,
        clock=None,
        foreground=None,
        rules=None,
        sleep_chunk=0.5,
    ):
        self.config = config or {}
        self.logger = logger
        self.store = store
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.foreground = foreground
        self.rules = rules
        #: Granularity of the interruptible waits (a stop must not wait out a backoff).
        self.sleep_chunk = max(0.01, float(sleep_chunk))
        self._home = None
        #: Phases actually touched this round; teardown only stops these.
        self._touched = []
        #: phase name -> adapter; built lazily so a disabled phase is never touched.
        self._upstreams = dict(upstreams or {})

    # ---- setup ---------------------------------------------------------- #
    def upstreams(self):
        """Create the adapters for the phases the user actually configured."""

        if self._upstreams:
            return self._upstreams
        import config_manager
        import log_monitor
        from upstream_maa import MaaUpstream
        from upstream_maaend import MaaEndUpstream

        rules = self.rules or log_monitor.load_rules(config_manager.CONFIG_DIR)
        # NOTE: config_manager exposes plain strings (os.path.join), not Path objects.
        journal = str(Path(config_manager.CONFIG_DIR) / "injected_state.json")
        # Both adapters are created unconditionally: each one decides for itself
        # whether it is configured/available (probe() returns None when not).
        self._upstreams[run_state.PHASE_MAA] = MaaUpstream(
            self.config, self.logger, journal_path=journal, rules=rules
        )
        self._upstreams[run_state.PHASE_MAAEND] = MaaEndUpstream(
            self.config, self.logger, rules=rules
        )
        return self._upstreams

    # ---- timing --------------------------------------------------------- #
    def _phase_deadline(self):
        try:
            timeout = float(self.config.get("game_exit_timeout", 7200) or 7200)
        except (TypeError, ValueError):
            timeout = 7200.0
        return self.clock() + max(60.0, timeout)

    def _backoff(self, attempt):
        index = max(0, min(attempt - 1, len(BACKOFF) - 1))
        return BACKOFF[index]

    def _retry_limit(self):
        for key in ("retry", "retry_times"):
            if key in self.config and self.config.get(key) is not None:
                try:
                    return max(0, int(self.config.get(key)))
                except (TypeError, ValueError):
                    continue
        return 2

    # ---- the round ------------------------------------------------------ #
    def run(self, resume=False, run_id=None):
        record = (
            self.store.resume(run_id) if (resume and self.store) else None
        ) or (self.store.begin(run_id) if self.store else run_state.RunRecord())
        result = RunResult(record=record)

        try:
            if self.foreground is not None:
                self.foreground(self.config, self.logger)

            phases = self._phases()
            if not phases:
                result.status = STATUS_ERROR
                result.message = "没有配置 MAA 或 MaaEnd 的路径，无法执行（在设置 → 路径设置里填写）"
                self.logger.error(result.message)
                return result
            for phase, adapter in phases:
                if phase in (record.completed_phases or []):
                    self.logger.info(f"{adapter.name} 阶段在上一轮已完成，跳过（续跑）")
                    continue
                outcome = self._run_phase(phase, adapter, record)
                result.codes.append(outcome.code)
                if outcome.tasks:
                    result.tasks.extend(outcome.tasks)
                if outcome.state == run_state.STATE_SUCCESS:
                    record.completed_phases.append(phase)
                    self._save(record)
                    continue
                if outcome.state == run_state.STATE_ABORTED:
                    result.status = STATUS_ABORTED
                    result.message = outcome.message
                    return result
                # A failed phase does not cancel the next one (legacy behaviour):
                # MAA failing should still let MaaEnd try, and the report keeps both.
                result.status = STATUS_ERROR
                result.message = self._compose_message(outcome)
                self.logger.error(
                    f"{adapter.name} 阶段失败: {outcome.code} {outcome.message}"
                )
                if outcome.code in upstream.FATAL_CODES:
                    break
            return result
        except Exception as exc:  # noqa: BLE001 - reported, never raised at the UI
            from process_utils import TaskInterrupted

            if isinstance(exc, TaskInterrupted):
                record.state = run_state.STATE_ABORTED
                self._save(record)
                result.status = STATUS_ABORTED
                result.message = "任务被用户中止"
                return result
            self.logger.error(f"执行过程中发生未知严重错误: {exc}")
            record.state = run_state.STATE_FAILED
            self._save(record)
            result.status = STATUS_ERROR
            result.message = str(exc)
            return result
        finally:
            self._finalize(result, record)

    def _phases(self):
        """Only the phases that have a configured path; empty means "skip".

        1.x behaved this way ("留空跳过") and it is the predictable rule: an
        auto-detected MaaEnd must not be launched just because it happens to exist.
        The wizard/settings offer detection to *fill* the field.
        """

        adapters = self.upstreams()
        wanted = (
            (run_state.PHASE_MAA, "maa_path"),
            (run_state.PHASE_MAAEND, "maaend_path"),
        )
        return [
            (phase, adapters[phase])
            for phase, key in wanted
            if phase in adapters and str(self.config.get(key) or "").strip()
        ]

    # ---- one phase ------------------------------------------------------ #
    def _run_phase(self, phase, adapter, record):
        """Run one phase; its process is stopped before the next phase begins."""

        try:
            return self._run_phase_inner(phase, adapter, record)
        finally:
            self._stop_phase(adapter)

    def _stop_phase(self, adapter):
        """One phase is done: close its program (and undo its injection) now.

        Leaving MAA running while MaaEnd starts was the reported behaviour: two
        idle GUIs fighting for the foreground, and the injection restored only at
        the very end of the round.
        """

        if bool(self.config.get("keep_upstream", False)):
            self.logger.info(f"{adapter.name} 阶段结束，按设置保留其进程")
            return
        try:
            adapter.stop(graceful=True)
            self.logger.info(f"{adapter.name} 阶段结束，已关闭其进程")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"关闭 {adapter.name} 失败: {exc}")
        try:
            adapter.cleanup()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"清理 {adapter.name} 失败: {exc}")

    def _run_phase_inner(self, phase, adapter, record):
        retry_limit = self._retry_limit()
        if phase not in self._touched:
            self._touched.append(phase)
        attempt = 0
        last = None
        while attempt <= retry_limit:
            attempt += 1
            record.phase = phase
            record.attempt = attempt
            record.state = run_state.STATE_ARMING
            self._save(record)

            issues = list(adapter.preflight())
            for issue in issues:
                self._log_issue(adapter, issue)
            fatal = [i for i in issues if i.fatal]
            if fatal:
                outcome = upstream.Outcome(
                    state=run_state.STATE_FAILED,
                    code=fatal[0].code,
                    message=self._issue_text(fatal[0]),
                )
                self._record_outcome(record, outcome)
                return outcome

            record.state = run_state.STATE_RUNNING
            self._save(record)
            self._maybe_apply_pending_update(phase, adapter)
            try:
                # Order matters: MAA reads its config once at startup, so the
                # injection has to happen before the process exists.
                adapter.prepare()
                adapter.launch()
                adapter.wait_ready()
                outcome = adapter.wait_signal(
                    self._phase_deadline(), self._progress_printer(adapter)
                )
            except upstream.UpstreamError as exc:
                outcome = upstream.Outcome(
                    state=run_state.STATE_FAILED,
                    code=exc.code,
                    message=self._issue_text(
                        upstream.Issue(exc.code, exc.message, exc.hint)
                    ),
                )
            self._record_outcome(record, outcome)
            if outcome.ok:
                return outcome
            last = outcome
            if outcome.state == run_state.STATE_ABORTED:
                return outcome
            if not outcome.retryable:
                return outcome
            if attempt > retry_limit:
                break
            if self.store is not None and self.store.repeated_failure(
                record, outcome.code
            ):
                self.logger.error(
                    f"{adapter.name} 连续多轮都因 {outcome.code} 失败，本次不再重试"
                )
                outcome.message += "（同一错误已连续出现多轮，请先手动排查）"
                return outcome
            wait = self._backoff(attempt)
            self.logger.warning(
                f"{adapter.name} 第 {attempt}/{retry_limit + 1} 次尝试失败"
                f"（{outcome.code}），{wait} 秒后重试"
            )
            record.state = run_state.STATE_RETRY_WAIT
            self._save(record)
            try:
                adapter.stop(graceful=True)
            except Exception:  # noqa: BLE001 - stopping is best effort
                pass
            try:
                adapter.cleanup()
            except Exception:  # noqa: BLE001
                pass
            self._sleep(wait)
        return last or upstream.Outcome()

    def _progress_printer(self, adapter):
        state = {"done": -1}

        def report(tasks):
            if not tasks:
                return
            done = sum(1 for t in tasks if t.get("state") == "done")
            if done == state["done"]:
                return          # nothing changed: a heartbeat here is just noise
            state["done"] = done
            latest = [
                t.get("name") for t in tasks if t.get("state") == "done" and t.get("name")
            ]
            suffix = f"（刚完成: {latest[-1]}）" if latest else ""
            self.logger.info(f"{adapter.name} 进度: {done}/{len(tasks)} 个任务完成{suffix}")

        return report

    def _maybe_apply_pending_update(self, phase, adapter):
        """Between rounds only: let MaaEnd install an already-downloaded update.

        MAA is handled by the injector (packages are deferred, not installed mid-run).
        For MaaEnd the update is installed by MXU itself at startup, so the only safe
        window is right here, before the phase starts. A failure never aborts the
        round - we log it and run anyway.
        """

        if phase != run_state.PHASE_MAAEND:
            return
        policy = str(self.config.get("update_policy") or "between-rounds").lower()
        if policy == "manual":
            return
        state_of = getattr(adapter, "update_state", None)
        driver = getattr(adapter, "apply_pending_update", None)
        if state_of is None or driver is None:
            return
        try:
            state, version, evidence = state_of()
        except Exception as exc:  # noqa: BLE001 - detection must never block a round
            self.logger.warning(f"检查 MaaEnd 更新状态失败: {exc}")
            return
        if state != "pending":
            if state == "available":
                self.logger.warning(
                    f"MaaEnd 有新版本（{version or '版本未知'}）但尚未下载，"
                    "请先打开 MaaEnd 完成更新，否则它可能在运行中弹更新提示"
                )
            return
        self.logger.info(
            f"MaaEnd 有待安装更新（{version or '版本未知'}），先在轮次之间完成它"
        )
        try:
            result = driver()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"MaaEnd 更新会话异常，继续执行任务: {exc}")
            return
        if result is not None and result.state == "applied":
            self.logger.info(f"MaaEnd 更新完成: {result.message}")
        elif result is not None:
            self.logger.warning(f"MaaEnd 更新未完成（{result.state}）: {result.message}")

    # ---- reporting helpers ---------------------------------------------- #
    @staticmethod
    def _issue_text(issue):
        if issue.hint:
            return f"{issue.message}；{issue.hint}"
        return issue.message

    def _log_issue(self, adapter, issue):
        text = self._issue_text(issue)
        if issue.fatal:
            self.logger.error(f"{adapter.name}: {text}")
        else:
            self.logger.warning(f"{adapter.name}: {text}")

    def _compose_message(self, outcome):
        return f"{outcome.code}: {outcome.message}" if outcome.code else outcome.message

    def _record_outcome(self, record, outcome):
        record.state = outcome.state
        record.code = outcome.code
        record.message = outcome.message
        if outcome.tasks:
            record.tasks = outcome.tasks
        if not outcome.ok and self.store is not None:
            self.store.record_failure(record, outcome.code)
        self._save(record)

    def _save(self, record):
        if self.store is not None:
            self.store.save(record)

    def _sleep(self, seconds):
        """Interruptible wait: the stop button must not wait out a 120 s backoff."""

        import process_utils

        remaining = float(seconds)
        while remaining > 0:
            process_utils.check_interrupt()
            step = min(self.sleep_chunk, remaining)
            self.sleep(step)
            remaining -= step

    # ---- teardown ------------------------------------------------------- #
    def _finalize(self, result, record):
        keep = bool(self.config.get("keep_upstream", False))
        # Never build adapters here: if building them is what failed, teardown must not
        # raise a second time (that used to escape run() and hide the real error).
        for phase, adapter in dict(self._upstreams).items():
            touched = phase in self._touched
            try:
                # Only an upstream this round actually started gets stopped; a phase
                # skipped by resume must not have its leftover process killed.
                if not keep and touched:
                    adapter.stop(graceful=True)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"收尾时结束 {adapter.name} 失败: {exc}")
            try:
                # Always: undo the injection and release pipes, even when the
                # phase never started (a half-applied inject must not survive).
                adapter.cleanup()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"收尾时清理 {adapter.name} 失败: {exc}")
        record.state = (
            run_state.STATE_SUCCESS
            if result.status == STATUS_OK
            else run_state.STATE_ABORTED
            if result.status == STATUS_ABORTED
            else run_state.STATE_FAILED
        )
        self._save(record)


def default_store():
    """Run journal next to config.json (that directory is protected by the upgrader)."""

    import config_manager

    return run_state.RunStateStore(config_manager.CONFIG_DIR)
