"""MAA configuration injection: the "efficient control" path.

MAA has no API, so the way in is its own config files. Everything here is ordered
by what MAA actually does at startup, learned from its source and from a real
6.21 log:

* MAA reads its config **once, during startup** - so injection must happen
  *before* the process is launched (getting this backwards is why the first 2.0
  build launched MAA and then watched it sit idle forever).
* It runs the scheme named by ``Current`` - which is not always ``Default``.
* Old ``gui.json`` stores strings ("True") and flat dotted keys; new
  ``gui.new.json`` stores booleans and nested objects.
* A registered update package (``Update.UpdatePackage``) is applied **at startup
  regardless of the auto-install switch**, which is what pops "restart to
  update?" in the middle of an unattended run - so it is deferred to after the
  round, exactly like AUTO-MAS does.

Restore is key-level: MAA may legitimately rewrite its own config during a run
(last-run dates, task bookkeeping) and that must survive.
"""

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILES = ("gui.json", "gui.new.json")

#: Keys inside the active scheme block of gui.new.json (booleans).
SCHEME_KEYS_NEW = (
    # Let the queue start by itself. This is the whole point of injection.
    (("Gui", "StartUpSettings", "RunDirectly"), True),
    # MAA skips the startup auto-run once after updating itself; clear it.
    (("Gui", "StartUpSettings", "SkipStartupAutoRunAfterUpdate"), False),
)

#: Top-level keys of gui.new.json (booleans). They govern the update/announcement
#: prompts that would otherwise interrupt an unattended round.
GLOBAL_KEYS_NEW = (
    (("Update", "CheckOnStartup"), False),
    (("Update", "AutoDownloadUpdatePackage"), False),
    (("Update", "AutoInstallUpdatePackage"), False),
    (("Update", "DoNotShowUpdate"), True),
    (("AnnouncementInfo", "DoNotShow"), True),
)

#: Same intent in the legacy gui.json, whose scheme block holds flat dotted keys
#: with string values (``"Start.RunDirectly": "True"``).
SCHEME_KEYS_OLD = (("Start.RunDirectly", "True"),)

#: Legacy global keys (flat dotted names with string values).
GLOBAL_KEYS_OLD = (
    ("VersionUpdate.ScheduledUpdateCheck", "False"),
    ("VersionUpdate.AutoDownloadUpdatePackage", "False"),
    ("VersionUpdate.AutoInstallUpdatePackage", "False"),
    ("VersionUpdate.doNotShowUpdate", "True"),
    ("Announcement.DoNotShowAnnouncement", "True"),
)

#: Where a registered-but-deferred update package is remembered.
PENDING_NEW = ("Update", "UpdatePackage")
PENDING_OLD = ("Global", "VersionUpdate.package")

BACKUP_SUFFIX = ".m2.bak"
JOURNAL_VERSION = 2


class InjectionError(RuntimeError):
    """The config could not be injected safely."""


@dataclass
class Change:
    """One key we intend to write (or wrote)."""

    filename: str
    scope: str          # "scheme" | "global"
    path: tuple
    old: object = None
    new: object = None
    had_old: bool = False

    def as_dict(self):
        return {
            "file": self.filename,
            "scope": self.scope,
            "path": list(self.path),
            "old": self.old,
            "new": self.new,
            "had_old": self.had_old,
        }


# --------------------------------------------------------------------------- #
# Small JSON helpers
# --------------------------------------------------------------------------- #
def _dig(doc, path):
    node = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None, False
        node = node[key]
    return node, True


def _set(doc, path, value):
    node = doc
    for key in path[:-1]:
        nxt = node.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            node[key] = nxt
        node = nxt
    node[path[-1]] = value


def _unset(doc, path):
    parent, found = _dig(doc, path[:-1])
    if found and isinstance(parent, dict):
        parent.pop(path[-1], None)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def write_json_atomic(path, data):
    path = Path(path)
    # MAA writes these files itself; keep the same shape (no trailing newline
    # games) and swap atomically so a crash cannot leave half a config.
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Read-only view of an MAA installation
# --------------------------------------------------------------------------- #
class MaaConfig:
    """Read/write view of ``<MAA root>/config`` (read side is used by preflight)."""

    def __init__(self, maa_root):
        self.root = Path(maa_root)
        self.config_dir = self.root / "config"

    # ---- documents ------------------------------------------------------ #
    def document(self, filename):
        return read_json(self.config_dir / filename)

    @property
    def new_doc(self):
        return self.document("gui.new.json")

    @property
    def old_doc(self):
        return self.document("gui.json")

    def exists(self):
        return self.config_dir.is_dir()

    # ---- schemes -------------------------------------------------------- #
    def schemes(self):
        doc = self.new_doc or {}
        groups = doc.get("Configurations")
        return list(groups) if isinstance(groups, dict) else []

    def current_scheme(self):
        """The scheme MAA itself considers active (6.x reads gui.new.json)."""

        doc = self.new_doc or {}
        current = doc.get("Current")
        if isinstance(current, str) and current:
            return current
        old = self.old_doc or {}
        current = old.get("Current")
        if isinstance(current, str) and current:
            return current
        schemes = self.schemes()
        return schemes[0] if schemes else "Default"

    def scheme_block(self, filename, scheme):
        doc = self.document(filename)
        if not isinstance(doc, dict):
            return None
        groups = doc.get("Configurations")
        if not isinstance(groups, dict):
            return None
        block = groups.get(scheme)
        return block if isinstance(block, dict) else None

    # ---- things preflight / the wizard want to know --------------------- #
    def task_queue(self, scheme=None):
        """Enabled tasks of the active scheme: [{"type", "name", "enabled"}]."""

        scheme = scheme or self.current_scheme()
        block = self.scheme_block("gui.new.json", scheme)
        queue = (block or {}).get("TaskQueue")
        if not isinstance(queue, list):
            return []
        out = []
        for task in queue:
            if not isinstance(task, dict):
                continue
            out.append(
                {
                    "type": str(task.get("TaskType") or ""),
                    "name": str(task.get("Name") or task.get("TaskType") or ""),
                    "enabled": bool(task.get("IsEnable", True)),
                }
            )
        return out

    def enabled_tasks(self, scheme=None):
        return [t for t in self.task_queue(scheme) if t["enabled"]]

    def last_enabled_task(self, scheme=None):
        tasks = self.enabled_tasks(scheme)
        return tasks[-1] if tasks else None

    def schedule_enabled(self):
        """True when MAA's own timers are on (they would race with ours)."""

        doc = self.new_doc or {}
        timers = ((doc.get("Timers") or {}).get("List")) or []
        if isinstance(timers, list) and any(
            isinstance(t, dict) and t.get("IsEnabled") for t in timers
        ):
            return True
        old = self.old_doc or {}
        global_block = old.get("Global")
        if isinstance(global_block, dict):
            for index in range(1, 9):
                if str(global_block.get(f"Timer.Timer{index}")) == "True":
                    return True
        return False

    def skip_after_update(self, scheme=None):
        block = self.scheme_block("gui.new.json", scheme or self.current_scheme()) or {}
        settings = ((block.get("Gui") or {}).get("StartUpSettings")) or {}
        return bool(settings.get("SkipStartupAutoRunAfterUpdate", False))

    def run_directly(self, scheme=None):
        block = self.scheme_block("gui.new.json", scheme or self.current_scheme()) or {}
        settings = ((block.get("Gui") or {}).get("StartUpSettings")) or {}
        return bool(settings.get("RunDirectly", False))

    def check_update_on_startup(self):
        update = (self.new_doc or {}).get("Update") or {}
        return bool(update.get("CheckOnStartup", False))

    def pending_update(self):
        """(version, package path) of a registered update MAA would apply at startup."""

        update = (self.new_doc or {}).get("Update") or {}
        package = str(update.get("UpdatePackage") or "")
        if package:
            return str(update.get("Name") or ""), package
        old = self.old_doc or {}
        global_block = old.get("Global")
        if isinstance(global_block, dict):
            package = str(global_block.get("VersionUpdate.package") or "")
            if package:
                return str(global_block.get("VersionUpdate.name") or ""), package
        return "", ""

    def log_path(self):
        return self.root / "debug" / "gui.log"

    def writable(self):
        return os.access(self.config_dir, os.W_OK)


# --------------------------------------------------------------------------- #
# Injector
# --------------------------------------------------------------------------- #
class MaaInjector:
    """Applies the whitelist before launch and restores it afterwards."""

    def __init__(self, maa_root, journal_path, logger=None):
        self.config = MaaConfig(maa_root)
        self.root = Path(maa_root)
        self.journal_path = Path(journal_path)
        self.logger = logger

    # ---- logging -------------------------------------------------------- #
    def _log(self, level, message):
        if self.logger is not None:
            method = getattr(self.logger, level, None)
            if callable(method):
                method(message)

    # ---- planning ------------------------------------------------------- #
    def plan(self):
        """Whitelist keys whose current value differs from what a run needs."""

        scheme = self.config.current_scheme()
        changes = []

        new_doc = self.config.new_doc
        if isinstance(new_doc, dict):
            for path, want in SCHEME_KEYS_NEW:
                full = ("Configurations", scheme) + path
                current, found = _dig(new_doc, full)
                if found and current == want:
                    continue
                changes.append(Change("gui.new.json", "scheme", full, current, want, found))
            for path, want in GLOBAL_KEYS_NEW:
                current, found = _dig(new_doc, path)
                if found and current == want:
                    continue
                changes.append(Change("gui.new.json", "global", path, current, want, found))

        old_doc = self.config.old_doc
        if isinstance(old_doc, dict):
            groups = old_doc.get("Configurations")
            old_scheme = None
            if isinstance(groups, dict) and scheme in groups:
                old_scheme = scheme
            elif isinstance(groups, dict) and "Default" in groups:
                # The legacy file may only know Default; never fabricate a scheme.
                old_scheme = "Default"
            if old_scheme:
                for key, want in SCHEME_KEYS_OLD:
                    full = ("Configurations", old_scheme, key)
                    current, found = _dig(old_doc, full)
                    if found and str(current) == want:
                        continue
                    changes.append(
                        Change("gui.json", "scheme", full, current, want, found)
                    )
            for key, want in GLOBAL_KEYS_OLD:
                full = ("Global", key)
                current, found = _dig(old_doc, full)
                if found and str(current) == want:
                    continue
                changes.append(Change("gui.json", "global", full, current, want, found))
        return changes

    # ---- applying ------------------------------------------------------- #
    def apply(self):
        """Write the plan; returns the applied changes (empty when already set)."""

        pending = self._read_journal()
        if pending and not pending.get("done"):
            self._log("warning", "发现未完成的上一次注入，先还原再重新注入")
            self.restore()
        self.cleanup_journal()

        changes = self.plan()
        deferred_version, deferred_package = self.config.pending_update()
        if not changes and not deferred_package:
            self._log("info", "MAA 配置已满足运行条件，无需注入")
            return []

        if not self.config.exists():
            raise InjectionError(f"MAA 配置目录不存在: {self.config.config_dir}")
        if not self.config.writable():
            raise InjectionError(f"MAA 配置目录不可写: {self.config.config_dir}")

        backups = {}
        for filename in sorted({c.filename for c in changes}):
            source = self.config.config_dir / filename
            if not source.is_file():
                raise InjectionError(f"缺少配置文件: {source}")
            backup = source.with_name(source.name + BACKUP_SUFFIX)
            shutil.copy2(source, backup)
            backups[filename] = str(backup)

        journal = {
            "version": JOURNAL_VERSION,
            "maa_root": str(self.root),
            "scheme": self.config.current_scheme(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "done": False,
            "backups": backups,
            "changes": [c.as_dict() for c in changes],
            # A registered package would be applied by MAA at startup, popping the
            # "restart to update?" dialog in the middle of the round. Park it.
            "deferred_update": {
                "version": deferred_version,
                "package": deferred_package,
            }
            if deferred_package
            else None,
        }
        self._write_journal(journal)

        try:
            for filename in {c.filename for c in changes}:
                doc = self.config.document(filename)
                if not isinstance(doc, dict):
                    raise InjectionError(f"配置文件无法解析: {filename}")
                for change in (c for c in changes if c.filename == filename):
                    _set(doc, change.path, change.new)
                write_json_atomic(self.config.config_dir / filename, doc)
            if deferred_package:
                self._clear_pending_package()
        except Exception:
            self.restore()
            raise

        self._log(
            "info",
            f"MAA 配置已注入 {len(changes)} 项（方案 {journal['scheme']}）",
        )
        # The per-key list is only interesting when debugging, and as one line it
        # used to be a screen-wide wall of text in the UI log.
        self._log(
            "debug",
            "注入明细: " + ", ".join(f"{c.path[-1]}={c.new!r}" for c in changes),
        )
        if deferred_package:
            self._log(
                "info",
                f"已把 MAA 待安装更新 {deferred_version or '(未知版本)'} 延后到本轮之后，"
                "避免启动时弹窗/重启",
            )
        return changes

    def _clear_pending_package(self):
        for filename, path in (
            ("gui.new.json", PENDING_NEW),
            ("gui.json", PENDING_OLD),
        ):
            doc = self.config.document(filename)
            if not isinstance(doc, dict):
                continue
            current, found = _dig(doc, path)
            if not found or current in ("", None):
                continue
            _set(doc, path, "")
            write_json_atomic(self.config.config_dir / filename, doc)

    # ---- restoring ------------------------------------------------------ #
    def restore(self):
        """Revert exactly the keys we changed, keeping MAA's own runtime writes.

        A byte-exact copy-back would also undo whatever MAA saved during the run
        (last-run dates, task bookkeeping), so restore is key level; the backup
        stays as a disaster-recovery file and is deleted once the revert worked.
        """

        journal = self._read_journal()
        if not journal:
            return False
        try:
            self._revert_keys(journal)
        except Exception as exc:  # noqa: BLE001 - fall back to the full copy
            self._log("warning", f"按键还原失败（{exc}），改用整文件备份还原")
            self._restore_backups(journal)
        self._restore_pending_package(journal)
        self._mark_done(journal)
        self._log("info", "MAA 配置已还原")
        return True

    def _revert_keys(self, journal):
        by_file = {}
        for change in journal.get("changes") or []:
            filename = change.get("file")
            path = tuple(change.get("path") or ())
            if not filename or not path:
                continue
            by_file.setdefault(filename, []).append((path, change))
        for filename, entries in by_file.items():
            doc = self.config.document(filename)
            if not isinstance(doc, dict):
                continue
            for path, change in entries:
                if change.get("had_old"):
                    _set(doc, path, change.get("old"))
                else:
                    _unset(doc, path)
            write_json_atomic(self.config.config_dir / filename, doc)

    def _restore_backups(self, journal):
        for filename, backup in (journal.get("backups") or {}).items():
            target = self.config.config_dir / filename
            backup_path = Path(backup)
            try:
                if backup_path.is_file():
                    shutil.copy2(backup_path, target)
            except OSError as exc:
                self._log("warning", f"还原 {filename} 失败: {exc}")

    def _restore_pending_package(self, journal):
        deferred = journal.get("deferred_update") or {}
        package = str(deferred.get("package") or "")
        if not package:
            return
        if self.config.pending_update()[1]:
            return          # MAA registered something itself; do not overwrite it
        doc = self.config.document("gui.new.json")
        if not isinstance(doc, dict):
            return
        try:
            _set(doc, PENDING_NEW, package)
            _set(doc, ("Update", "Name"), str(deferred.get("version") or ""))
            write_json_atomic(self.config.config_dir / "gui.new.json", doc)
            self._log("info", "MAA 待安装更新已重新登记，下一轮启动时由 MAA 自行安装")
        except OSError as exc:
            self._log("warning", f"重新登记 MAA 更新包失败: {exc}")

    def _cleanup_backups(self, journal):
        for backup in (journal.get("backups") or {}).values():
            try:
                Path(backup).unlink()
            except OSError:
                pass

    @classmethod
    def recover(cls, journal_path, logger=None):
        """Startup compensation for a crashed round (idempotent)."""

        injector = cls.__new__(cls)
        injector.journal_path = Path(journal_path)
        injector.logger = logger
        journal = injector._read_journal()
        if not journal or journal.get("done"):
            injector.cleanup_journal()
            return False
        injector.root = Path(journal.get("maa_root") or "")
        injector.config = MaaConfig(injector.root)
        injector.restore()
        return True

    # ---- journal -------------------------------------------------------- #
    def _read_journal(self):
        try:
            data = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _write_journal(self, journal):
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.journal_path.with_name(self.journal_path.name + ".tmp")
        tmp.write_text(
            json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.journal_path)

    def _mark_done(self, journal):
        journal["done"] = True
        self._write_journal(journal)
        self._cleanup_backups(journal)

    def cleanup_journal(self):
        try:
            self.journal_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
