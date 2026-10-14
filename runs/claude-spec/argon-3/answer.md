=== FILE: cronexpr.py ===
"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

import calendar
from datetime import datetime, timedelta
import re

__all__ = ["CronError", "CronSchedule", "parse"]

_MACROS: dict[str, str] = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}

_MONTH_NAMES: dict[str, int] = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

_DOW_NAMES: dict[str, int] = {
    "SUN": 0,
    "MON": 1,
    "TUE": 2,
    "WED": 3,
    "THU": 4,
    "FRI": 5,
    "SAT": 6,
}

_SPLIT_RE = re.compile(r"[ \t]+")


class CronError(ValueError):
    """cron 式が不正なときに送出する。"""


def _parse_value(
    s: str,
    min_val: int,
    max_val: int,
    names: dict[str, int] | None,
) -> int:
    if not s:
        raise CronError("Empty value")
    if s.isascii() and s.isdigit():
        val = int(s)
    elif names is not None and s.upper() in names:
        val = names[s.upper()]
    else:
        raise CronError(f"Invalid value: {s!r}")

    if not (min_val <= val <= max_val):
        raise CronError(f"Value {val} out of range [{min_val}, {max_val}]")
    return val


def _parse_field(
    field: str,
    min_val: int,
    max_val: int,
    star_max: int,
    names: dict[str, int] | None = None,
    *,
    allow_l: bool = False,
    allow_hash: bool = False,
) -> tuple[set[int], bool, set[tuple[int, int]]]:
    if not field:
        raise CronError("Empty field")

    values: set[int] = set()
    has_last_day = False
    nth_dow: set[tuple[int, int]] = set()

    for item in field.split(","):
        if not item:
            raise CronError(f"Empty item in field: {field!r}")

        if allow_l and item.upper() == "L":
            has_last_day = True
            continue

        if "#" in item:
            if not allow_hash:
                raise CronError(f"'#' not allowed in this field: {item!r}")
            parts = item.split("#")
            if len(parts) != 2:
                raise CronError(f"Invalid '#' item: {item!r}")
            w_str, k_str = parts
            w = _parse_value(w_str, min_val, max_val, names)
            if not (k_str.isascii() and k_str.isdigit()):
                raise CronError(f"Invalid '#' occurrence: {k_str!r}")
            k = int(k_str)
            if not (1 <= k <= 5):
                raise CronError(f"'#' occurrence out of range [1, 5]: {k}")
            nth_dow.add((w % 7, k))
            continue

        if "/" in item:
            slash_parts = item.split("/")
            if len(slash_parts) != 2:
                raise CronError(f"Invalid step syntax: {item!r}")
            base, step_str = slash_parts
            if not (step_str.isascii() and step_str.isdigit()):
                raise CronError(f"Invalid step value: {step_str!r}")
            step = int(step_str)
            if step < 1:
                raise CronError(f"Step must be >= 1: {step}")
        else:
            base = item
            step = None

        if base == "*":
            s = 1 if step is None else step
            values.update(range(min_val, star_max + 1, s))
        elif "-" in base:
            range_parts = base.split("-")
            if len(range_parts) != 2:
                raise CronError(f"Invalid range syntax: {base!r}")
            n_val = _parse_value(range_parts[0], min_val, max_val, names)
            m_val = _parse_value(range_parts[1], min_val, max_val, names)
            if n_val > m_val:
                raise CronError(f"Range start > end: {base!r}")
            s = 1 if step is None else step
            values.update(range(n_val, m_val + 1, s))
        else:
            n_val = _parse_value(base, min_val, max_val, names)
            if step is None:
                values.add(n_val)
            else:
                if n_val > star_max:
                    raise CronError(f"Start value {n_val} > {star_max} in {item!r}")
                values.update(range(n_val, star_max + 1, step))

    if allow_hash and 7 in values:
        values.remove(7)
        values.add(0)

    return values, has_last_day, nth_dow


class CronSchedule:
    """解析済みの cron 式。parse() で生成する。"""

    def __init__(
        self,
        minutes: set[int],
        hours: set[int],
        dom_values: set[int],
        has_last_day: bool,
        dom_restricted: bool,
        months: set[int],
        dow_values: set[int],
        dow_nth: set[tuple[int, int]],
        dow_restricted: bool,
    ) -> None:
        self._minutes_set = frozenset(minutes)
        self._minutes = sorted(minutes)
        self._hours_set = frozenset(hours)
        self._hours = sorted(hours)
        self._months_set = frozenset(months)
        self._months = sorted(months)

        self._dom_values = frozenset(dom_values)
        self._has_last_day = has_last_day
        self._dom_restricted = dom_restricted

        self._dow_values = frozenset(dow_values)
        self._dow_nth = frozenset(dow_nth)
        self._dow_restricted = dow_restricted

    def _matching_days(self, year: int, month: int) -> list[int]:
        first_weekday, num_days = calendar.monthrange(year, month)

        if not self._dom_restricted and not self._dow_restricted:
            return list(range(1, num_days + 1))

        dom_set: set[int] = set()
        if self._dom_restricted:
            dom_set = {d for d in self._dom_values if d <= num_days}
            if self._has_last_day:
                dom_set.add(num_days)

        dow_set: set[int] = set()
        if self._dow_restricted:
            first_cron_dow = (first_weekday + 1) % 7
            for w in self._dow_values:
                d1 = (w - first_cron_dow) % 7 + 1
                dow_set.update(range(d1, num_days + 1, 7))
            for w, k in self._dow_nth:
                d1 = (w - first_cron_dow) % 7 + 1
                dk = d1 + (k - 1) * 7
                if dk <= num_days:
                    dow_set.add(dk)

        if self._dom_restricted and self._dow_restricted:
            return sorted(dom_set | dow_set)
        if self._dom_restricted:
            return sorted(dom_set)
        return sorted(dow_set)

    def matches(self, dt: datetime) -> bool:
        if dt.second != 0 or dt.microsecond != 0:
            return False
        if dt.minute not in self._minutes_set:
            return False
        if dt.hour not in self._hours_set:
            return False
        if dt.month not in self._months_set:
            return False

        _, num_days = calendar.monthrange(dt.year, dt.month)
        dom_match = (dt.day in self._dom_values) or (
            self._has_last_day and dt.day == num_days
        )
        cron_dow = (dt.weekday() + 1) % 7
        dow_match = (cron_dow in self._dow_values) or (
            (cron_dow, (dt.day - 1) // 7 + 1) in self._dow_nth
        )

        if self._dom_restricted and self._dow_restricted:
            return dom_match or dow_match
        return dom_match and dow_match

    def next_after(self, dt: datetime) -> datetime | None:
        max_year = min(dt.year + 8, 9999)
        try:
            start = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        except OverflowError:
            return None

        if start.year > max_year:
            return None

        s_year, s_month, s_day, s_hour, s_minute = (
            start.year,
            start.month,
            start.day,
            start.hour,
            start.minute,
        )

        for year in range(s_year, max_year + 1):
            for month in self._months:
                if year == s_year and month < s_month:
                    continue

                days = self._matching_days(year, month)
                if not days:
                    continue

                for day in days:
                    if year == s_year and month == s_month and day < s_day:
                        continue

                    if year == s_year and month == s_month and day == s_day:
                        for hour in self._hours:
                            if hour < s_hour:
                                continue
                            if hour == s_hour:
                                for minute in self._minutes:
                                    if minute >= s_minute:
                                        return datetime(year, month, day, hour, minute)
                            else:
                                return datetime(
                                    year, month, day, hour, self._minutes[0]
                                )
                    else:
                        return datetime(
                            year, month, day, self._hours[0], self._minutes[0]
                        )

        return None

    def prev_before(self, dt: datetime) -> datetime | None:
        min_year = max(dt.year - 8, 1)
        if dt.second > 0 or dt.microsecond > 0:
            start = dt.replace(second=0, microsecond=0)
        else:
            try:
                start = dt - timedelta(minutes=1)
            except OverflowError:
                return None

        if start.year < min_year:
            return None

        s_year, s_month, s_day, s_hour, s_minute = (
            start.year,
            start.month,
            start.day,
            start.hour,
            start.minute,
        )

        for year in range(s_year, min_year - 1, -1):
            for month in reversed(self._months):
                if year == s_year and month > s_month:
                    continue

                days = self._matching_days(year, month)
                if not days:
                    continue

                for day in reversed(days):
                    if year == s_year and month == s_month and day > s_day:
                        continue

                    if year == s_year and month == s_month and day == s_day:
                        for hour in reversed(self._hours):
                            if hour > s_hour:
                                continue
                            if hour == s_hour:
                                for minute in reversed(self._minutes):
                                    if minute <= s_minute:
                                        return datetime(year, month, day, hour, minute)
                            else:
                                return datetime(
                                    year, month, day, hour, self._minutes[-1]
                                )
                    else:
                        return datetime(
                            year, month, day, self._hours[-1], self._minutes[-1]
                        )

        return None

    def iter_after(self, dt: datetime, count: int) -> list[datetime]:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("count must be a non-negative integer")
        result: list[datetime] = []
        cur = dt
        for _ in range(count):
            nxt = self.next_after(cur)
            if nxt is None:
                break
            result.append(nxt)
            cur = nxt
        return result


def parse(expr: str) -> CronSchedule:
    """cron 式を解析して CronSchedule を返す。不正なら CronError。"""
    if not isinstance(expr, str):
        raise CronError("Expression must be a string")

    stripped = expr.strip(" \t")
    if not stripped:
        raise CronError("Empty cron expression")

    if stripped.startswith("@"):
        macro_target = _MACROS.get(stripped.lower())
        if macro_target is None:
            raise CronError(f"Unknown macro: {stripped!r}")
        stripped = macro_target

    fields = _SPLIT_RE.split(stripped)
    if len(fields) != 5:
        raise CronError(f"Expected 5 fields, got {len(fields)}")

    min_f, hour_f, dom_f, month_f, dow_f = fields

    minutes, _, _ = _parse_field(min_f, 0, 59, 59)
    hours, _, _ = _parse_field(hour_f, 0, 23, 23)
    dom_values, has_last_day, _ = _parse_field(dom_f, 1, 31, 31, allow_l=True)
    months, _, _ = _parse_field(month_f, 1, 12, 12, _MONTH_NAMES)
    dow_values, _, dow_nth = _parse_field(
        dow_f, 0, 7, 6, _DOW_NAMES, allow_hash=True
    )

    return CronSchedule(
        minutes=minutes,
        hours=hours,
        dom_values=dom_values,
        has_last_day=has_last_day,
        dom_restricted=(dom_f != "*"),
        months=months,
        dow_values=dow_values,
        dow_nth=dow_nth,
        dow_restricted=(dow_f != "*"),
    )
=== END ===
