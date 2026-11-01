"""Adapter construction and teardown in the orchestrator.

Regression guard for the 2.0.0 packaged build: `upstreams()` did
``config_manager.CONFIG_DIR / "injected_state.json"`` while CONFIG_DIR is a plain
string, which raised ``TypeError: unsupported operand type(s) for /: 'str' and 'str'``
on every first run. Teardown then rebuilt the adapters and raised a second time,
so the real error was buried under a duplicate one.
"""

import logging

import orchestrator
import run_state
import upstream


def make_logger():
    logger = logging.getLogger("MaaAuto.test.orchestrator_build")
    logger.setLevel(logging.INFO)
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return logger


def test_upstreams_builds_both_adapters_without_raising(tmp_path):
    runner = orchestrator.Orchestrator(
        {"control": "inject"}, make_logger(), store=orchestrator.default_store()
    )

    adapters = runner.upstreams()

    assert set(adapters) == {run_state.PHASE_MAA, run_state.PHASE_MAAEND}
    assert adapters[run_state.PHASE_MAA].name == "MAA"
    assert adapters[run_state.PHASE_MAAEND].name == "MaaEnd"


def test_upstreams_is_cached(tmp_path):
    runner = orchestrator.Orchestrator({}, make_logger())
    assert runner.upstreams() is runner.upstreams()


def test_finalize_does_not_rebuild_adapters(monkeypatch):
    """Teardown must never call upstreams() again (that is how the TypeError doubled)."""

    calls = []

    class Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("cannot build")

    runner = orchestrator.Orchestrator({}, make_logger())
    monkeypatch.setattr(runner, "upstreams", lambda: calls.append(1) or {})
    result = orchestrator.RunResult(status="报错", message="boom")
    record = run_state.RunRecord(run_id="x")

    runner._finalize(result, record)          # must not raise

    assert calls == []


def test_run_reports_a_failure_when_upstreams_cannot_be_built(tmp_path, monkeypatch):
    runner = orchestrator.Orchestrator(
        {"control": "inject"}, make_logger(), store=run_state.RunStateStore(tmp_path)
    )

    def explode():
        raise TypeError("unsupported operand type(s) for /: 'str' and 'str'")

    monkeypatch.setattr(runner, "upstreams", explode)

    result = runner.run()                     # must not raise

    assert result.status == "报错"
    assert "unsupported operand" in result.message


def test_run_with_an_unconfigured_machine_does_not_crash(tmp_path):
    """No MAA/MaaEnd configured: preflight should fail cleanly, not blow up."""

    runner = orchestrator.Orchestrator(
        {"control": "inject", "maa_path": "", "maaend_path": "", "retry": 0},
        make_logger(),
        store=run_state.RunStateStore(tmp_path),
    )
    monkeypatch_targets = runner.upstreams()
    # Force the "nothing installed" outcome without touching the real machine.
    for adapter in monkeypatch_targets.values():
        adapter.preflight = lambda: [upstream.Issue("NO_EXE", "未找到程序", "请填写路径")]

    result = runner.run()

    assert result.status == "报错"
    assert "没有配置" in result.message
