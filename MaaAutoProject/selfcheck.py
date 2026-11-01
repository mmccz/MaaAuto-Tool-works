"""Read-only setup check ("would this round work?") powers the setup wizard.

Every check answers one question the orchestrator would otherwise only discover
after a run: is the exe there, is a task queue selected, is the last MaaEnd task
a "close" one, is the upstream's own timer going to race with ours.

Nothing here writes, starts or stops anything - it is safe to run on a user's
machine at any time, including before the first round.
"""

import json
from dataclasses import dataclass
from pathlib import Path

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"

LEVEL_ORDER = {LEVEL_OK: 0, LEVEL_WARN: 1, LEVEL_ERROR: 2}

CONTROL_INJECT = "inject"
CONTROL_CLICK = "click"

CLOSE_TASK_PREFIXES = ("CloseGame", "CloseEmulator")


@dataclass
class Check:
    """One line in the wizard: machine code + level + data for the UI text."""

    code: str
    level: str
    detail: str = ""
    hint: str = ""
    #: i18n key for the title, resolved by the UI.
    title_key: str = ""

    @property
    def ok(self):
        return self.level == LEVEL_OK


class Environment:
    """The few side effects self-check needs, isolated so tests can fake them."""

    def exe_exists(self, path):
        return bool(path) and Path(path).is_file()

    def process_running(self, name):
        import process_utils

        return bool(name) and process_utils.is_process_running([str(name)])

    def is_admin(self):
        import upstream

        return upstream.is_admin()

    def detect_exe(self, process_name, candidates):
        """Auto-detection; tests replace this so nothing real is probed."""

        import upstream

        return upstream.detect_exe(process_name, candidates)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _maa_config(config, env):
    """MaaConfig for the configured/auto-detected MAA, or None."""

    import upstream
    from injector import MaaConfig

    candidate = str(config.get("maa_path") or "").strip()
    if candidate and env.exe_exists(candidate):
        return MaaConfig(Path(candidate).parent)
    found = env.detect_exe("maa.exe", [candidate, r"E:\MAA\MAA.exe"])
    if found and env.exe_exists(found):
        return MaaConfig(Path(found).parent)
    return None


def _maaend_root(config, env):
    candidate = str(config.get("maaend_path") or "").strip()
    if candidate and env.exe_exists(candidate):
        return Path(candidate).parent
    found = env.detect_exe("maaend", [candidate, r"E:\MaaEnd\MaaEnd.exe"])
    if found and env.exe_exists(found):
        return Path(found).parent
    return None


def _maaend_instance(config, root):
    """(instance name, instance payload) from MaaEnd's own config file."""

    try:
        data = json.loads((root / "config" / "mxu-MaaEnd.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None, None
    instances = {
        str(item.get("name")): item
        for item in (data.get("instances") or [])
        if isinstance(item, dict) and item.get("name")
    }
    wanted = str(config.get("maaend_instance") or "").strip()
    if wanted:
        return (wanted, instances[wanted]) if wanted in instances else (wanted, None)
    last_id = data.get("lastActiveInstanceId")
    for name, item in instances.items():
        if last_id and item.get("id") == last_id:
            return name, item
    if len(instances) == 1:
        return next(iter(instances.items()))
    return None, None


# --------------------------------------------------------------------------- #
# The check
# --------------------------------------------------------------------------- #
def run_selfcheck(config, env=None):
    """Return the list of checks, worst first (the UI shows them grouped anyway)."""

    config = config or {}
    env = env or Environment()
    checks = []
    control = str(config.get("control") or CONTROL_INJECT).strip().lower()

    checks.append(
        Check(
            "CONTROL",
            LEVEL_OK,
            detail="配置注入" if control == CONTROL_INJECT else "找图点击",
            title_key="setup.check.control",
        )
    )

    # ---- MAA ---------------------------------------------------------- #
    maa = _maa_config(config, env)
    if maa is None:
        checks.append(
            Check(
                "MAA_EXE",
                LEVEL_ERROR,
                detail="未找到 MAA.exe",
                hint="在设置里填写 MAA 路径",
                title_key="setup.check.maa_exe",
            )
        )
    else:
        checks.append(
            Check(
                "MAA_EXE",
                LEVEL_OK,
                detail=str(maa.root),
                title_key="setup.check.maa_exe",
            )
        )
        if not maa.exists():
            checks.append(
                Check(
                    "MAA_CONFIG",
                    LEVEL_ERROR,
                    detail=str(maa.config_dir),
                    hint="先手动启动一次 MAA，让它生成 config 目录",
                    title_key="setup.check.maa_config",
                )
            )
        else:
            tasks = maa.enabled_tasks()
            if tasks:
                checks.append(
                    Check(
                        "MAA_QUEUE",
                        LEVEL_OK,
                        detail=f"{maa.current_scheme()}: " + " -> ".join(t["name"] for t in tasks),
                        title_key="setup.check.maa_queue",
                    )
                )
            else:
                checks.append(
                    Check(
                        "MAA_QUEUE",
                        LEVEL_ERROR,
                        detail=f"方案「{maa.current_scheme()}」没有勾选任何任务",
                        hint="先在 MAA 里勾选要执行的任务",
                        title_key="setup.check.maa_queue",
                    )
                )
            if maa.schedule_enabled():
                checks.append(
                    Check(
                        "MAA_SCHEDULE",
                        LEVEL_WARN,
                        detail="MAA 自带定时已开启",
                        hint="会和本工具的定时重复触发，建议关闭",
                        title_key="setup.check.maa_schedule",
                    )
                )
            if maa.skip_after_update():
                checks.append(
                    Check(
                        "MAA_SKIP_AFTER_UPDATE",
                        LEVEL_WARN,
                        detail="MAA 更新后首启会跳过自动运行",
                        hint="执行任务时会临时关闭该开关，无需手动处理",
                        title_key="setup.check.maa_skip_after_update",
                    )
                )
            if not maa.writable():
                checks.append(
                    Check(
                        "MAA_WRITABLE",
                        LEVEL_ERROR,
                        detail=str(maa.config_dir),
                        hint="以管理员身份运行本程序，或把 MAA 装到可写目录",
                        title_key="setup.check.maa_writable",
                    )
                )

    # ---- MaaEnd -------------------------------------------------------- #
    root = _maaend_root(config, env)
    if root is None:
        checks.append(
            Check(
                "MAAEND_EXE",
                LEVEL_ERROR,
                detail="未找到 MaaEnd.exe",
                hint="在设置里填写 MaaEnd 路径",
                title_key="setup.check.maaend_exe",
            )
        )
    else:
        checks.append(
            Check("MAAEND_EXE", LEVEL_OK, detail=str(root), title_key="setup.check.maaend_exe")
        )
        name, item = _maaend_instance(config, root)
        if item is None:
            checks.append(
                Check(
                    "MAAEND_INSTANCE",
                    LEVEL_ERROR,
                    detail=f"未找到可用实例（{name or '未指定'}）",
                    hint="在设置里选择 MaaEnd 实例",
                    title_key="setup.check.maaend_instance",
                )
            )
        else:
            checks.append(
                Check(
                    "MAAEND_INSTANCE",
                    LEVEL_OK,
                    detail=str(name),
                    title_key="setup.check.maaend_instance",
                )
            )
            enabled = [
                str(t.get("taskName") or "")
                for t in (item.get("tasks") or [])
                if isinstance(t, dict) and t.get("enabled")
            ]
            last = enabled[-1] if enabled else ""
            if last.startswith(CLOSE_TASK_PREFIXES):
                checks.append(
                    Check(
                        "MAAEND_CLOSE_TASK",
                        LEVEL_OK,
                        detail=last,
                        title_key="setup.check.maaend_close_task",
                    )
                )
            else:
                checks.append(
                    Check(
                        "MAAEND_CLOSE_TASK",
                        LEVEL_WARN,
                        detail=last or "实例里没有启用任务",
                        hint="在 MaaEnd 任务列表最后加上「关闭程序」或「关闭模拟器」",
                        title_key="setup.check.maaend_close_task",
                    )
                )
            if any(
                isinstance(p, dict) and p.get("enabled")
                for p in (item.get("schedulePolicies") or [])
            ):
                checks.append(
                    Check(
                        "MAAEND_SCHEDULE",
                        LEVEL_WARN,
                        detail="MaaEnd 自带定时已开启",
                        hint="会和本工具的定时重复触发，建议关闭",
                        title_key="setup.check.maaend_schedule",
                    )
                )

    # ---- environment --------------------------------------------------- #
    emulator = str(config.get("emulator_proc") or "MuMuPlayer.exe").strip()
    if emulator:
        running = env.process_running(emulator)
        checks.append(
            Check(
                "EMULATOR",
                LEVEL_OK if running else LEVEL_WARN,
                detail=emulator if running else f"{emulator} 未在运行",
                hint="" if running else "若 MAA 里没开「启动后自动启动模拟器」，请先手动启动",
                title_key="setup.check.emulator",
            )
        )
    if not env.is_admin():
        checks.append(
            Check(
                "ADMIN",
                LEVEL_WARN,
                detail="当前不是管理员",
                hint="两个上游都被设为以管理员运行；若启动报 740，请以管理员身份运行",
                title_key="setup.check.admin",
            )
        )
    return checks


def summarize(checks):
    """(level, error_count, warn_count) for the dialog header."""

    errors = sum(1 for c in checks if c.level == LEVEL_ERROR)
    warns = sum(1 for c in checks if c.level == LEVEL_WARN)
    if errors:
        return LEVEL_ERROR, errors, warns
    if warns:
        return LEVEL_WARN, errors, warns
    return LEVEL_OK, 0, 0


def blocking_issues(checks):
    """Checks that must be fixed before a run can succeed."""

    return [c for c in checks if c.level == LEVEL_ERROR]
