"""Round state machine and its on-disk journal.

One "round" is one automation run: MAA phase, then MaaEnd phase, then finalize.
The state lives here so that an upgrade restart (or a crash) can pick the round
back up instead of starting from scratch.

States are deliberately boring strings: they end up in the log, the UI and the
run_state.json journal, so no enum gymnastics.
"""

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

STATE_IDLE = "idle"
STATE_ARMING = "arming"
STATE_RUNNING = "running"
STATE_RETRY_WAIT = "retry_wait"
STATE_SUCCESS = "success"
STATE_FAILED = "failed"
STATE_TIMEOUT = "timeout"
STATE_ABORTED = "aborted"

ALL_STATES = (
    STATE_IDLE,
    STATE_ARMING,
    STATE_RUNNING,
    STATE_RETRY_WAIT,
    STATE_SUCCESS,
    STATE_FAILED,
    STATE_TIMEOUT,
    STATE_ABORTED,
)

#: States that end a phase for good; a resume must not re-run them.
TERMINAL_STATES = frozenset({STATE_SUCCESS, STATE_FAILED, STATE_TIMEOUT, STATE_ABORTED})

PHASE_MAA = "maa"
PHASE_MAAEND = "maaend"
PHASES = (PHASE_MAA, PHASE_MAAEND)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class RunRecord:
    """Persisted view of one round."""

    run_id: str = ""
    state: str = STATE_IDLE
    phase: str = ""
    attempt: int = 0
    code: str = ""
    message: str = ""
    started_at: str = ""
    updated_at: str = ""
    #: Phases that already reached SUCCESS in this round (resume skips them).
    completed_phases: list = field(default_factory=list)
    #: Task level results collected from the log / stdout, for the report.
    tasks: list = field(default_factory=list)
    #: Last few failure codes, used by the circuit breaker (3 in a row = stop).
    recent_failures: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def touch(self):
        self.updated_at = _now()


class RunStateStore:
    """Atomic JSON persistence for the current round."""

    def __init__(self, config_dir, filename="run_state.json"):
        self.path = Path(config_dir) / filename

    def load(self):
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        return RunRecord.from_dict(data)

    def save(self, record):
        record.touch()
        payload = json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)

    def clear(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def begin(self, run_id=None):
        """Start a fresh round, carrying the circuit-breaker history forward."""

        previous = self.load()
        record = RunRecord(
            run_id=run_id or uuid.uuid4().hex[:12],
            state=STATE_IDLE,
            started_at=_now(),
        )
        if previous is not None:
            record.recent_failures = list(previous.recent_failures)[-3:]
        self.save(record)
        return record

    def resume(self, run_id=None):
        """Load the current round for continuation; begin a new one if unusable."""

        record = self.load()
        if record is None or (run_id and record.run_id != run_id):
            return self.begin(run_id)
        if record.state in TERMINAL_STATES:
            # A finished round cannot be resumed; its history still matters.
            return self.begin(run_id)
        return record

    def record_failure(self, record, code):
        """Track repeated failure codes for the circuit breaker."""

        if not code:
            return
        record.recent_failures = (list(record.recent_failures) + [code])[-3:]
        self.save(record)

    def repeated_failure(self, record, code, threshold=3):
        """True when `code` is the last `threshold` failures in a row."""

        if not code:
            return False
        tail = list(record.recent_failures)[-threshold:]
        return len(tail) >= threshold and all(item == code for item in tail)
