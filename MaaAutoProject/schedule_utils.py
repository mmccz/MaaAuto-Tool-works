"""Scheduling rules: multiple slots plus weekdays (1.3.0).

Sources (all in config.json):

* ``schedule_times``     - list of slots, e.g. ``["08:00", "20:30"]``;
* ``schedule_weekdays``  - ISO weekdays (1=Mon ... 7=Sun); empty list = every day;
* ``execute_time``       - **legacy**, only for old configs (used when schedule_times is absent).

Pure functions only, so they are easy to unit-test (no Qt, no real clock).
"""

import datetime as _dt
from typing import Iterable, List, Optional, Sequence, Tuple

DEFAULT_TIME = "08:00"


def normalize_times(times: Iterable[str]) -> List[str]:
    """Deduplicate, validate and sort ("8:00" -> "08:00"; invalid values are dropped)."""
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
    """Slots in effect: the new field first, then legacy ``execute_time``, then 08:00."""
    times = normalize_times((config or {}).get("schedule_times") or [])
    if times:
        return times
    legacy = normalize_times([(config or {}).get("execute_time") or ""])
    return legacy or [DEFAULT_TIME]


def effective_weekdays(config: dict) -> List[int]:
    """Weekdays in effect; empty = every day."""
    return normalize_weekdays((config or {}).get("schedule_weekdays") or [])


def is_active_day(weekdays: Sequence[int], day: _dt.date) -> bool:
    return not weekdays or day.isoweekday() in weekdays


def slot_key(day: _dt.date, hhmm: str) -> str:
    return f"{day.isoformat()} {hhmm}"


def due_slot(times: Sequence[str],
             weekdays: Sequence[int],
             now: _dt.datetime,
             last_key: str) -> Optional[str]:
    """The slot key that should fire now, or None.

    Same semantics as before (**catch-up runs** are supported, but only the latest slot):

    * today is not a selected weekday -> nothing fires;
    * consider only slots ``<= now`` and take the **latest** (earlier ones count as
      missed together with it);
    * a key already fired (``last_key`` >= it) -> do not fire again.
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
    """The next fire time (looks up to 8 days ahead to cover a whole week)."""
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
    """Turn a weekday list into words: empty = every day, 1..5 = weekdays, 6-7 = weekend,
    otherwise list them one by one.

    ``order`` holds localised short names for 1..7 (passed in by the UI; this function
    knows nothing about languages).
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
    """Return (hours, minutes, not_today) for the home-page wording."""
    if when is None:
        return 0, 0, False
    diff = int((when - now).total_seconds())
    if diff < 0:
        diff = 0
    return diff // 3600, (diff % 3600) // 60, when.date() != now.date()
