"""定时规则：多时段 + 工作日（1.3.0）。

数据来源（都放在 config.json）：

* ``schedule_times``     —— 时段列表，如 ``["08:00", "20:30"]``；
* ``schedule_weekdays``  —— ISO 星期（1=周一 … 7=周日）；空列表 = 每天；
* ``execute_time``       —— **旧字段**，仅用于兼容老配置（没有 schedule_times 时取它）。

这里只放纯函数，方便单测（不 import Qt，不碰真实时间）。
"""

import datetime as _dt
from typing import Iterable, List, Optional, Sequence, Tuple

DEFAULT_TIME = "08:00"


def normalize_times(times: Iterable[str]) -> List[str]:
    """去重、校验、排序（"8:00" → "08:00"；非法值丢弃）。"""
    out = set()
    for raw in times or []:
        text = str(raw or "").strip()
        if not text:
            continue
        parts = text.split(":")
        if len(parts) != 2:
            continue
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        out.add(f"{hour:02d}:{minute:02d}")
    return sorted(out)


def normalize_weekdays(days: Iterable[int]) -> List[int]:
    out = set()
    for raw in days or []:
        try:
            day = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= day <= 7:
            out.add(day)
    return sorted(out)


def effective_times(config: dict) -> List[str]:
    """当前生效的时段：优先新字段，其次旧 ``execute_time``，最后默认 08:00。"""
    times = normalize_times((config or {}).get("schedule_times") or [])
    if times:
        return times
    legacy = normalize_times([(config or {}).get("execute_time") or ""])
    return legacy or [DEFAULT_TIME]


def effective_weekdays(config: dict) -> List[int]:
    """生效的星期；空 = 每天。"""
    return normalize_weekdays((config or {}).get("schedule_weekdays") or [])


def is_active_day(weekdays: Sequence[int], day: _dt.date) -> bool:
    return not weekdays or day.isoweekday() in weekdays


def slot_key(day: _dt.date, hhmm: str) -> str:
    return f"{day.isoformat()} {hhmm}"


def due_slot(times: Sequence[str],
             weekdays: Sequence[int],
             now: _dt.datetime,
             last_key: str) -> Optional[str]:
    """返回「现在该触发的时段 key」，没有则 None。

    语义与旧版一致（**支持补跑**，且在补跑时只跑最近的一次）：

    * 今天不是选中的星期 → 不触发；
    * 只考虑 ``<= now`` 的时段，取其中**最晚**的一个（早于它的都算一起错过）；
    * 该 key 已经触发过（``last_key`` >= 它）→ 不再触发。
    """
    if not is_active_day(weekdays, now.date()):
        return None
    times = normalize_times(times)
    if not times:
        return None
    current = f"{now.hour:02d}:{now.minute:02d}"
    passed = [t for t in times if t <= current]
    if not passed:
        return None
    candidate = slot_key(now.date(), passed[-1])
    if last_key and last_key >= candidate:
        return None
    return candidate


def next_run(times: Sequence[str],
             weekdays: Sequence[int],
             now: _dt.datetime) -> Optional[_dt.datetime]:
    """下一次触发时间（最多向后找 8 天覆盖整周）。"""
    times = normalize_times(times)
    if not times:
        return None
    for offset in range(0, 8):
        day = now.date() + _dt.timedelta(days=offset)
        if not is_active_day(weekdays, day):
            continue
        for hhmm in times:
            hour, minute = (int(x) for x in hhmm.split(":"))
            when = _dt.datetime.combine(day, _dt.time(hour, minute))
            if when > now:
                return when
    return None


def describe_weekdays(weekdays: Sequence[int], order: Sequence[str]) -> str:
    """把星期列表转成人话：空=每天，1~5=工作日，6,7=周末，否则逐个列。

    ``order`` 是 1..7 的本地化短名（由界面传入，函数本身不认识语言）。
    """
    days = normalize_weekdays(weekdays)
    if not days:
        return order[7] if len(order) > 7 else ""
    if days == [1, 2, 3, 4, 5]:
        return order[8] if len(order) > 8 else ""
    if days == [6, 7]:
        return order[9] if len(order) > 9 else ""
    return " ".join(order[d - 1] for d in days)


def parse_hhmm_to_seconds(hhmm: str) -> Optional[int]:
    value = normalize_times([hhmm])
    if not value:
        return None
    hour, minute = (int(x) for x in value[0].split(":"))
    return hour * 3600 + minute * 60


def humanize_next(when: Optional[_dt.datetime], now: _dt.datetime) -> Tuple[int, int, bool]:
    """返回 (小时, 分钟, 是否不是今天)，给首页文案用。"""
    if when is None:
        return 0, 0, False
    diff = int((when - now).total_seconds())
    if diff < 0:
        diff = 0
    return diff // 3600, (diff % 3600) // 60, when.date() != now.date()
