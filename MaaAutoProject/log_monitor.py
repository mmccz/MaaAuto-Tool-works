"""Incremental log / stdout monitoring and the "did the phase finish?" judges.

Two upstream shapes, one idea:

* MAA writes a GUI log with a strict line prefix and *continuation lines* (18% of
  the lines in the 6.21 log have no prefix). Failure task names live in those
  continuation lines, so records are merged before judging.
* MaaEnd prints one line per task event on stdout (``任务开始/任务完成/任务失败: <name>``)
  and exits by itself with ``--quit-after-run``.

Nothing here starts a process or reads a real log path unless it is told to, which
keeps the judges unit-testable with plain strings.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import run_state
import upstream

#: `[2026-11-01 19:01:03.090][INF][AsstProxy]              <12> message`
LINE_RE = re.compile(
    r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+\]\[(\w+)\]\[([^\]]+)\]\s*<\d+>\s?(.*)$"
)

#: Cap for the evidence kept per attempt, so a 20 MB log cannot blow up memory.
EVIDENCE_LIMIT = 12_000

DEFAULT_RULES_NAME = "log_rules.json"


def default_rules_path():
    """Where the built-in rules live, in dev and in a PyInstaller bundle."""

    try:
        from utils import resource_path

        # resource_path takes ONE relative path (it joins _MEIPASS with it).
        candidate = Path(resource_path(str(Path("resources") / DEFAULT_RULES_NAME)))
        if candidate.is_file():
            return candidate
    except Exception:
        pass
    # Fallback: next to this module (same relative layout in the bundle).
    return Path(__file__).resolve().parent / "resources" / DEFAULT_RULES_NAME


def default_cache_path(config_dir):
    return Path(config_dir) / "log_rules_cache.json"


def load_rules(config_dir=None):
    """Rules in effect: built-in, overridden by a compatible cached remote copy.

    The built-in table is always the fallback - a missing/corrupt/unknown-schema
    cache must never leave the program unable to judge a round.
    """

    builtin = LogRules.load()
    if not config_dir:
        return builtin
    try:
        text = default_cache_path(config_dir).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return builtin
    remote = LogRules._read_text(text)
    if remote is None:
        return builtin
    if not (LogRules.MIN_SCHEMA <= remote.schema_version <= LogRules.MAX_SCHEMA):
        return builtin
    remote.source = "cache"
    return remote


def refresh_rules(urls, config_dir, opener=None, timeout=10):
    """Download the remote rule table into the cache; None on any failure.

    Silent by design: rules are an optimisation, not a dependency. Whatever happens
    here, the round still runs on the built-in table.
    """

    import urllib.request

    opener = opener or (lambda url: urllib.request.urlopen(url, timeout=timeout))
    for url in urls or ():
        try:
            with opener(url) as response:
                text = response.read().decode("utf-8")
        except Exception:
            continue
        rules = LogRules._read_text(text)
        if rules is None:
            continue
        if not (LogRules.MIN_SCHEMA <= rules.schema_version <= LogRules.MAX_SCHEMA):
            continue
        try:
            path = default_cache_path(config_dir)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            import os

            os.replace(tmp, path)
        except OSError:
            return rules
        rules.source = "remote"
        return rules
    return None


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
class LogRules:
    """Parsed rule table with a safe fallback to the built-in copy."""

    MIN_SCHEMA = 1
    MAX_SCHEMA = 1

    def __init__(self, data):
        data = data if isinstance(data, dict) else {}
        self.schema_version = int(data.get("schema_version") or 0)
        self.updated = str(data.get("updated") or "")
        self.source = str(data.get("_source") or "builtin")
        maa = data.get("maa") or {}
        maaend = data.get("maaend") or {}
        self.maa_success = [str(x) for x in (maa.get("success") or [])]
        self.maa_failure = [str(x) for x in (maa.get("failure") or [])]
        self.maa_task_done = str(maa.get("task_done") or "")
        self.maa_task_fail = str(maa.get("task_fail") or "")
        self.maa_stop = [str(x) for x in (maa.get("stop") or [])]
        #: Markers proving the queue really started (see resources/log_rules.json).
        self.maa_start = [str(x) for x in (maa.get("start") or [])]
        try:
            self.maa_start_grace = int(maa.get("start_grace_seconds") or 90)
        except (TypeError, ValueError):
            self.maa_start_grace = 90
        self.maa_issues = [dict(x) for x in (maa.get("issues") or []) if isinstance(x, dict)]
        self.maaend_task_start = str(maaend.get("task_start") or "")
        self.maaend_task_done = str(maaend.get("task_done") or "")
        self.maaend_task_fail = str(maaend.get("task_fail") or "")
        self.maaend_issues = [
            dict(x) for x in (maaend.get("issues") or []) if isinstance(x, dict)
        ]

    # ---- loading -------------------------------------------------------- #
    @classmethod
    def load(cls, path=None, remote_text=None):
        """Built-in rules, optionally replaced by a same-schema remote copy."""

        builtin = cls._read_file(path or default_rules_path())
        if remote_text:
            remote = cls._read_text(remote_text)
            if remote is not None and cls.MIN_SCHEMA <= remote.schema_version <= cls.MAX_SCHEMA:
                remote.source = "remote"
                return remote
        builtin.source = "builtin"
        return builtin

    @classmethod
    def _read_file(cls, path):
        try:
            return cls._read_text(Path(path).read_text(encoding="utf-8")) or cls({})
        except (OSError, UnicodeDecodeError):
            return cls({})

    @classmethod
    def _read_text(cls, text):
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        return cls(data)

    # ---- matching ------------------------------------------------------- #
    @staticmethod
    def _match(issue, text):
        needle = str(issue.get("contains") or "")
        return bool(needle) and needle in text

    def maa_issue(self, text):
        """First matching preflight/runtime problem for MAA, as an Issue."""

        for rule in self.maa_issues:
            if self._match(rule, text):
                return upstream.Issue(
                    code=str(rule.get("code") or "MAA_PROBLEM"),
                    message=str(rule.get("contains") or ""),
                    hint=str(rule.get("hint") or ""),
                    fatal=bool(rule.get("fatal", False)),
                )
        return None

    def maaend_issue(self, text):
        for rule in self.maaend_issues:
            if self._match(rule, text):
                return upstream.Issue(
                    code=str(rule.get("code") or "MAAEND_PROBLEM"),
                    message=str(rule.get("contains") or ""),
                    hint=str(rule.get("hint") or ""),
                    fatal=bool(rule.get("fatal", False)),
                )
        return None


# --------------------------------------------------------------------------- #
# Log record + incremental tail
# --------------------------------------------------------------------------- #
@dataclass
class LogLine:
    """One logical log record: the prefixed line plus its continuation lines."""

    timestamp: object = None
    level: str = ""
    module: str = ""
    message: str = ""
    extra: list = field(default_factory=list)

    @property
    def text(self):
        if not self.extra:
            return self.message
        return "\n".join([self.message, *self.extra])


class LogTail:
    """Byte-offset incremental reader with continuation merging and rotation detection."""

    def __init__(self, path, start_offset=0, name="gui.log"):
        self.path = Path(path)
        self.name = name
        self.offset = int(start_offset or 0)
        self._buffer = ""
        self._pending = None

    # ---- sizing --------------------------------------------------------- #
    def size(self):
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    @classmethod
    def at_end(cls, path, name="gui.log"):
        """Start from the current end of file: only this run's lines are judged."""

        tail = cls(path, 0, name)
        tail.offset = tail.size()
        return tail

    @classmethod
    def whole(cls, path, name="gui.log"):
        """Start from byte 0 (used by tests and by post-mortem analysis)."""

        return cls(path, 0, name)

    def rotate_if_needed(self):
        """A shrunk file means the upstream restarted and truncated it."""

        size = self.size()
        if size and size < self.offset:
            self.offset = 0
            self._buffer = ""
            self._pending = None
            return True
        return False

    # ---- reading -------------------------------------------------------- #
    def read(self, records=True):
        """Return the newly completed records (or raw new text when records=False)."""

        self.rotate_if_needed()
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
        except OSError:
            return [] if records else ""
        if not chunk:
            return [] if records else ""
        self.offset += len(chunk)
        text = self._buffer + chunk.decode("utf-8", "replace")
        self._buffer = ""
        # keep the tail after the last newline for the next round
        cut = text.rfind("\n")
        if cut == -1:
            self._buffer = text
            return [] if records else ""
        self._buffer = text[cut + 1 :]
        body = text[: cut + 1]
        if not records:
            return body
        return self._parse(body)

    def _parse(self, body):
        out = []
        for raw in body.splitlines():
            line = raw.rstrip("\r")
            if not line.strip():
                continue
            match = LINE_RE.match(line)
            if match:
                self._flush(out)
                stamp = self._parse_time(match.group(1))
                self._pending = LogLine(
                    timestamp=stamp,
                    level=match.group(2),
                    module=match.group(3),
                    message=match.group(4),
                )
            elif self._pending is not None:
                self._pending.extra.append(line)
            else:
                # Text before any prefixed line (startup banner leftovers).
                self._pending = LogLine(message=line)
        self._flush(out, keep_pending=True)
        return out

    def flush(self):
        """Emit the last pending record (call when the phase ends)."""

        out = []
        self._flush(out)
        return out

    def _flush(self, out, keep_pending=False):
        if self._pending is not None:
            out.append(self._pending)
            if not keep_pending:
                self._pending = None

    @staticmethod
    def _parse_time(text):
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


# --------------------------------------------------------------------------- #
# MAA judge
# --------------------------------------------------------------------------- #
class MaaLogJudge:
    """Turns MAA gui.log records into an Outcome, or None while still running."""

    def __init__(self, rules, *, since=None):
        self.rules = rules
        self.since = since
        self.tasks = {}
        self.issue = None
        self.stopped = False
        #: True once a marker proves the task queue started (MAA began running).
        self.started = False
        self.evidence = []
        self._result = None

    # ---- helpers -------------------------------------------------------- #
    def _remember(self, line):
        self.evidence.append(line.text)
        if len(self.evidence) > 400:
            del self.evidence[:200]
        text = "\n".join(self.evidence)
        if len(text) > EVIDENCE_LIMIT:
            self.evidence = self.evidence[-100:]

    def evidence_text(self, limit=EVIDENCE_LIMIT):
        return "\n".join(self.evidence)[-limit:]

    def _names_in(self, line, prefix):
        body = line.message.split(prefix, 1)[-1].strip()
        if body:
            return [body]
        return [x.strip() for x in line.extra if x.strip()]

    # ---- feeding -------------------------------------------------------- #
    def feed(self, line):
        if self._result is not None:
            return self._result
        if self.since is not None and line.timestamp is not None:
            if line.timestamp < self.since:
                return None
        self._remember(line)
        text = line.text

        if not self.started:
            for marker in self.rules.maa_start:
                if marker and marker in text:
                    self.started = True
                    break

        # Failure wins over success: MAA may print both in one round.
        for phrase in self.rules.maa_failure:
            if phrase and phrase in text:
                failed = []
                for follow in line.extra:
                    if follow.strip():
                        failed.append(follow.strip())
                self.tasks = {**self.tasks, **{name: "fail" for name in failed}}
                self._result = upstream.Outcome(
                    state=run_state.STATE_FAILED,
                    code="PARTIAL",
                    message="MAA 报告有任务失败",
                    tasks=self.task_list(),
                    evidence=self.evidence_text(),
                )
                return self._result

        for phrase in self.rules.maa_success:
            if phrase and phrase in text:
                self._result = upstream.Outcome(
                    state=run_state.STATE_SUCCESS,
                    code="",
                    message="MAA 全部任务完成",
                    tasks=self.task_list(),
                    evidence=self.evidence_text(),
                )
                return self._result

        if self.rules.maa_task_done and self.rules.maa_task_done in text:
            for name in self._names_in(line, self.rules.maa_task_done):
                self.tasks[name] = "done"
        if self.rules.maa_task_fail and self.rules.maa_task_fail in text:
            for name in self._names_in(line, self.rules.maa_task_fail):
                self.tasks[name] = "fail"

        issue = self.rules.maa_issue(text)
        if issue is not None and self.issue is None:
            self.issue = issue

        for phrase in self.rules.maa_stop:
            if phrase and phrase in text:
                self.stopped = True
                break
        return None

    def task_list(self):
        return [
            {"name": name, "state": "done" if state == "done" else "failed"}
            for name, state in self.tasks.items()
        ]

    # ---- finishing ------------------------------------------------------ #
    def finish(self, *, exited=False):
        """Called when the process exited or the deadline hit."""

        if self._result is not None:
            return self._result
        if self.issue is not None:
            state = (
                run_state.STATE_FAILED
                if self.issue.code != "ABORTED"
                else run_state.STATE_ABORTED
            )
            self._result = upstream.Outcome(
                state=state,
                code=self.issue.code,
                message=self.issue.message,
                tasks=self.task_list(),
                evidence=self.evidence_text(),
            )
            return self._result
        if self.stopped:
            self._result = upstream.Outcome(
                state=run_state.STATE_ABORTED,
                code="STOPPED",
                message="MAA 在完成任务前被停止",
                tasks=self.task_list(),
                evidence=self.evidence_text(),
            )
            return self._result
        # Unknown outcome: caller decides (fall back to the process-exit heuristic).
        self._result = upstream.Outcome(
            state=run_state.STATE_FAILED,
            code="LOG_UNKNOWN",
            message="日志里没有出现收尾标志，无法判断任务结果",
            tasks=self.task_list(),
            evidence=self.evidence_text(),
        )
        return self._result


# --------------------------------------------------------------------------- #
# MaaEnd judge (stdout)
# --------------------------------------------------------------------------- #
class MaaEndStdoutJudge:
    """Parses MaaEnd's task lines from stdout; `--quit-after-run` ends the phase."""

    def __init__(self, rules):
        self.rules = rules
        self.tasks = {}
        self.issue = None
        self.evidence = []

    def feed(self, text):
        text = (text or "").strip()
        if not text:
            return
        self.evidence.append(text)
        if len(self.evidence) > 400:
            del self.evidence[:200]

        if self.rules.maaend_task_fail and self.rules.maaend_task_fail in text:
            self.tasks[self._name(text, self.rules.maaend_task_fail)] = "fail"
            return
        if self.rules.maaend_task_done and self.rules.maaend_task_done in text:
            self.tasks[self._name(text, self.rules.maaend_task_done)] = "done"
            return
        if self.rules.maaend_task_start and self.rules.maaend_task_start in text:
            name = self._name(text, self.rules.maaend_task_start)
            self.tasks.setdefault(name, "running")
            return
        issue = self.rules.maaend_issue(text)
        if issue is not None and self.issue is None:
            self.issue = issue

    @staticmethod
    def _name(text, prefix):
        return text.split(prefix, 1)[-1].strip() or "(未命名)"

    def task_list(self):
        return [
            {"name": name, "state": "done" if state == "done" else "failed"}
            for name, state in self.tasks.items()
        ]

    def finish(self, exit_code=None):
        evidence = "\n".join(self.evidence)[-EVIDENCE_LIMIT:]
        failed = [n for n, s in self.tasks.items() if s == "fail"]
        done = [n for n, s in self.tasks.items() if s == "done"]
        if failed:
            return upstream.Outcome(
                state=run_state.STATE_FAILED,
                code="TASK_ERROR",
                message="失败任务: " + "、".join(failed),
                tasks=self.task_list(),
                evidence=evidence,
            )
        if self.issue is not None:
            return upstream.Outcome(
                state=run_state.STATE_FAILED,
                code=self.issue.code,
                message=self.issue.message,
                tasks=self.task_list(),
                evidence=evidence,
            )
        if self.tasks and len(done) == len(self.tasks):
            return upstream.Outcome(
                state=run_state.STATE_SUCCESS,
                code="",
                message="MaaEnd 全部任务完成",
                tasks=self.task_list(),
                evidence=evidence,
            )
        if exit_code is not None and exit_code != 0:
            return upstream.Outcome(
                state=run_state.STATE_FAILED,
                code="TASK_ERROR",
                message=f"MaaEnd 异常退出（退出码 {exit_code}）",
                tasks=self.task_list(),
                evidence=evidence,
            )
        return upstream.Outcome(
            state=run_state.STATE_FAILED,
            code="LOG_UNKNOWN",
            message="MaaEnd 退出，但没有读到任务终态",
            tasks=self.task_list(),
            evidence=evidence,
        )
