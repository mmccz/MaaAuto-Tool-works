"""Contract shared by the MAA and MaaEnd adapters.

The orchestrator only ever talks to this interface, which keeps every branch
testable without a real screen, a real process or a real log file
(see tests/conftest.py for why that matters).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Protocol, runtime_checkable

import run_state

#: Issue codes that must stop a phase immediately (no retry).
FATAL_CODES = frozenset(
    {
        "NO_EXE",
        "BAD_CONFIG",
        "NO_TASK",
        "NO_EMULATOR",
        "NEED_ADMIN",
        "ALREADY_RUNNING",
        "PERMISSION",
    }
)

#: Issue codes worth retrying with backoff.
RETRYABLE_CODES = frozenset(
    {
        "ADB_FAIL",
        "TASK_ERROR",
        "PARTIAL",
        "LOG_UNKNOWN",
        "TEMPLATE",
        "TIMEOUT",
        "NOT_READY",
    }
)


@dataclass(frozen=True)
class Issue:
    """One preflight problem: machine code + human message + what to do."""

    code: str
    message: str
    hint: str = ""
    fatal: bool = True

    @property
    def retryable(self):
        return (not self.fatal) or self.code in RETRYABLE_CODES


class UpstreamError(RuntimeError):
    """A phase could not even start (launch failed, config unreadable, no admin)."""

    def __init__(self, code, message, hint=""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


@dataclass
class Outcome:
    """Result of one phase attempt."""

    state: str = run_state.STATE_FAILED
    code: str = ""
    message: str = ""
    tasks: List[dict] = field(default_factory=list)
    #: Free-form evidence (last log lines) for the report / task.log.
    evidence: str = ""

    @property
    def ok(self):
        return self.state == run_state.STATE_SUCCESS

    @property
    def retryable(self):
        if self.state in (run_state.STATE_SUCCESS, run_state.STATE_ABORTED):
            return False
        if self.code in FATAL_CODES:
            return False
        return self.code in RETRYABLE_CODES or self.state in (
            run_state.STATE_TIMEOUT,
            run_state.STATE_FAILED,
        )


@runtime_checkable
class Upstream(Protocol):
    """What the orchestrator needs from an upstream (MAA / MaaEnd)."""

    name: str
    control_mode: str

    def probe(self):
        """Locate the executable; None when it cannot be found."""

    def preflight(self):
        """Read-only consistency checks; returns a list of Issue."""

    def prepare(self):
        """Everything that must happen *before* the process starts.

        MAA reads its config once, during startup: writing ``RunDirectly`` after
        the process is up has no effect (this was the 2.0.0 "MAA never starts"
        bug). Adapters that need no pre-work (MaaEnd passes everything on the
        command line) do nothing here.
        """

    def launch(self):
        """Start the process."""

    def wait_ready(self, timeout=None):
        """Block until the upstream finished loading, or fail with UpstreamError."""

    def wait_signal(self, deadline, on_progress=None):
        """Block until the phase finishes or the deadline passes; returns Outcome."""

    def stop(self, graceful=True):
        """Ask the upstream to stop."""

    def cleanup(self):
        """Undo everything arm() changed; safe to call twice."""


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def probe_executable(candidates):
    """First existing file among `candidates` (paths or strings)."""

    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def exe_dir(path):
    """Directory that must be used as the child's cwd (MAA/MaaEnd use relative paths)."""

    return Path(path).parent if path else None


def detect_exe(process_name, extra_candidates=()):
    """Find an executable path: running process first, then known locations."""

    found = running_executable(process_name)
    if found:
        return Path(found)
    return probe_executable(extra_candidates)


def running_executable(process_name):
    """Path of a running process whose name matches `process_name` (fuzzy, case-insensitive)."""

    import psutil

    wanted = str(process_name or "").lower()
    if not wanted:
        return None
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if wanted in name:
                exe = proc.info.get("exe")
                if exe and Path(exe).is_file():
                    return exe
        except Exception:
            continue
    return None


def is_admin():
    """True when the current process runs elevated (needed to launch both upstreams)."""

    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def describe_tasks(tasks):
    """Compact "A -> B -> C" string for logs and reports."""

    names = [str(t.get("name") or "") for t in (tasks or []) if t.get("name")]
    return " -> ".join(names)


__all__ = [
    "FATAL_CODES",
    "RETRYABLE_CODES",
    "Issue",
    "Outcome",
    "Upstream",
    "detect_exe",
    "describe_tasks",
    "exe_dir",
    "is_admin",
    "probe_executable",
    "running_executable",
]
