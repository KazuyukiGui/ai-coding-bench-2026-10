=== FILE: cronexpr.py ===
"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

import calendar
import re
from datetime import datetime, timedelta

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


class CronError(ValueError):
    """cron 式が不正なときに送出する。"""


def _parse_value(
    val_str: str,
    min_val: int,
    max_val: int,
    names: dict[str, int] | None = None,
) -> int:
    if not val_str:
        raise CronError("Empty value")
    if names is not None:
        upper = val_str.upper()
        if upper in names:
            return names[upper]
    if val_str.isascii() and val_str.isdigit():
        val = int(val_str)
        if min_val <= val <= max_val:
            return val
        raise CronError(f"Value {val} out of range [{min_val}, {max_val}]")
    raise CronError(f"Invalid value: {val_str!r}")


def _parse_step(step_str: str) -> int:
    if step_str.isascii() and step_str.isdigit():
        step = int(step_str)
        if step >= 1:
            return step
    raise CronError(f"Invalid step: {step_str!r}")


def _parse_item_range(
    item: str,
    min_val: int,
    max_val: int,
    star_min: int,
    star_max: int,
    names: dict[str, int] | None = None,
) -> range:
    if "/" in item:
        parts = item.split("/")
        if len(parts) != 2:
            raise CronError(f"Invalid step syntax: {item!r}")
        base, step_str = parts
        step = _parse_step(step_str)
        if base == "*":
            return range(star_min, star_max + 1, step)
        if "-" in base:
            rparts = base.split("-")
            if len(rparts) != 2:
                raise CronError(f"Invalid range syntax: {item!r}")
            start = _parse_value(rparts[0], min_val, max_val, names)
            end = _parse_value(rparts[1], min_val, max_val, names)
            if start > end:
                raise CronError(f"Range start > end in {item!r}")
            return range(start, end + 1, step)
        start = _parse_value(base, min_val, max_val, names)
        if start > star_max:
            raise CronError(f"Start value {start} exceeds {star_max} in {item!r}")
        return range(start, star_max + 1, step)
    else:
        if item == "*":
            return range(star_min, star_max + 1)
        if "-" in item:
            rparts = item.split("-")
            if len(rparts) != 2:
                raise CronError(f"Invalid range syntax: {item!r}")
            start = _parse_value(rparts[0], min_val, max_val, names)
            end = _parse_value(rparts[1], min_val, max_val, names)
            if start > end:
                raise CronError(f"Range start > end in {item!r}")
            return range(start, end + 1)
        val = _parse_value(item, min_val, max_val, names)
        return range(val, val + 1)


def _parse_standard_field(
    field_str: str,
    min_val: int,
    max_val: int,
    names: dict[str, int] | None = None,
) -> set[int]:
    items = field_str.split(",")
    if any(not item for item in items):
        raise CronError(f"Empty item in field: {field_str!r}")
    values: set[int] = set()
    for item in items:
        r = _parse_item_range(item, min_val, max_val, min_val, max_val, names)
        values.update(r)
    return values


def _parse_dom_field(field_str: str) -> tuple[set[int], bool]:
    items = field_str.split(",")
    if any(not item for item in items):
        raise CronError(f"Empty item in day-of-month field: {field_str!r}")
    values: set[int] = set()
    has_l = False
    for item in items:
        if item.upper() == "L":
            has_l = True
        else:
            r = _parse_item_range(item, 1, 31, 1, 31, None)
            values.update(r)
    return values, has_l


def _parse_dow_field(field_str: str) -> tuple[set[int], set[tuple[int, int]]]:
    items = field_str.split(",")
    if any(not item for item in items):
        raise CronError(f"Empty item in day-of-week field: {field_str!r}")
    values: set[int] = set()
    nth_set: set[tuple[int, int]] = set()
    for item in items:
        if "#" in item:
            parts = item.split("#")
            if len(parts) != 2:
                raise CronError(f"Invalid '#' syntax in day-of-week field: {item!r}")
            w_str, k_str = parts
            w = _parse_value(w_str, 0, 7, _DOW_NAMES)
            if w == 7:
                w = 0
            if not (k_str.isascii() and k_str.isdigit()):
                raise CronError(f"Invalid nth value in day-of-week field: {item!r}")
            k = int(k_str)
            if not (1 <= k <= 5):
                raise CronError(f"nth value {k} out of range [1, 5] in {item!r}")
            nth_set.add((w, k))
        else:
            r = _parse_item_range(item, 0, 7, 0, 6, _DOW_NAMES)
            for v in r:
                values.add(0 if v == 7 else v)
    return values, nth_set


class CronSchedule:
    """解析済みの cron 式。parse() で生成する。"""

    def __init__(
        self,
        minutes: set[int],
        hours: set[int],
        dom_set: set[int],
        dom_has_l: bool,
        months: set[int],
        dow_set: set[int],
        dow_nth: set[tuple[int, int]],
        dom_restricted: bool,
        dow_restricted: bool,
    ) -> None:
        self._minutes_set: frozenset[int] = frozenset(minutes)
        self._minutes: tuple[int, ...] = tuple(sorted(minutes))
        self._hours_set: frozenset[int] = frozenset(hours)
        self._hours: tuple[int, ...] = tuple(sorted(hours))
        self._months_set: frozenset[int] = frozenset(months)
        self._months: tuple[int, ...] = tuple(sorted(months))
        self._dom_set: frozenset[int] = frozenset(dom_set)
        self._dom_has_l: bool = dom_has_l
        self._dow_set: frozenset[int] = frozenset(dow_set)
        self._dow_nth: frozenset[tuple[int, int]] = frozenset(dow_nth)
        self._dom_restricted: bool = dom_restricted
        self._dow_restricted: bool = dow_restricted
        self._days_cache: dict[tuple[int, int], tuple[int, ...]] = {}

    def _valid_days_in_month(self, year: int, month: int) -> tuple[int, ...]:
        first_wd, num_days = calendar.monthrange(year, month)
        first_dow = (first_wd + 1) % 7
        key = (first_dow, num_days)
        cached = self._days_cache.get(key)
        if cached is not None:
            return cached

        dom_set = self._dom_set
        dom_has_l = self._dom_has_l
        dow_set = self._dow_set
        dow_nth = self._dow_nth
        both_restricted = self._dom_restricted and self._dow_restricted

        valid: list[int] = []
        for d in range(1, num_days + 1):
            dom_match = (d in dom_set) or (dom_has_l and d == num_days)
            w = (first_dow + d - 1) % 7
            k = (d - 1) // 7 + 1
            dow_match = (w in dow_set) or ((w, k) in dow_nth)
            if both_restricted:
                matched = dom_match or dow_match
            else:
                matched = dom_match and dow_match
            if matched:
                valid.append(d)

        res = tuple(valid)
        self._days_cache[key] = res
        return res

    def matches(self, dt: datetime) -> bool:
        if dt.second != 0 or dt.microsecond != 0:
            return False
        if dt.minute not in self._minutes_set:
            return False
        if dt.hour not in self._hours_set:
            return False
        if dt.month not in self._months_set:
            return False
        return dt.day in self._valid_days_in_month(dt.year, dt.month)

    def next_after(self, dt: datetime) -> datetime | None:
        try:
            start = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        except OverflowError:
            return None

        max_year = min(dt.year + 8, 9999)
        if start.year > max_year:
            return None

        s_year, s_month, s_day, s_hour, s_minute = (
            start.year,
            start.month,
            start.day,
            start.hour,
            start.minute,
        )
        months = self._months
        hours = self._hours
        minutes = self._minutes
        first_hour = hours[0]
        first_minute = minutes[0]

        for y in range(s_year, max_year + 1):
            for m in months:
                if y == s_year and m < s_month:
                    continue
                valid_days = self._valid_days_in_month(y, m)
                if not valid_days:
                    continue
                for d in valid_days:
                    if y == s_year and m == s_month:
                        if d < s_day:
                            continue
                        if d == s_day:
                            for h in hours:
                                if h < s_hour:
                                    continue
                                if h == s_hour:
                                    for mi in minutes:
                                        if mi >= s_minute:
                                            return datetime(y, m, d, h, mi)
                                else:
                                    return datetime(y, m, d, h, first_minute)
                            continue
                    return datetime(y, m, d, first_hour, first_minute)
        return None

    def prev_before(self, dt: datetime) -> datetime | None:
        if dt.second == 0 and dt.microsecond == 0:
            try:
                start = dt - timedelta(minutes=1)
            except OverflowError:
                return None
        else:
            start = dt.replace(second=0, microsecond=0)

        min_year = max(dt.year - 8, 1)
        if start.year < min_year:
            return None

        s_year, s_month, s_day, s_hour, s_minute = (
            start.year,
            start.month,
            start.day,
            start.hour,
            start.minute,
        )
        months_rev = tuple(reversed(self._months))
        hours_rev = tuple(reversed(self._hours))
        minutes_rev = tuple(reversed(self._minutes))
        last_hour = hours_rev[0]
        last_minute = minutes_rev[0]

        for y in range(s_year, min_year - 1, -1):
            for m in months_rev:
                if y == s_year and m > s_month:
                    continue
                valid_days = self._valid_days_in_month(y, m)
                if not valid_days:
                    continue
                for d in reversed(valid_days):
                    if y == s_year and m == s_month:
                        if d > s_day:
                            continue
                        if d == s_day:
                            for h in hours_rev:
                                if h > s_hour:
                                    continue
                                if h == s_hour:
                                    for mi in minutes_rev:
                                        if mi <= s_minute:
                                            return datetime(y, m, d, h, mi)
                                else:
                                    return datetime(y, m, d, h, last_minute)
                            continue
                    return datetime(y, m, d, last_hour, last_minute)
        return None

    def iter_after(self, dt: datetime, count: int) -> list[datetime]:
        if count < 0:
            raise ValueError("count must be non-negative")
        result: list[datetime] = []
        curr = dt
        for _ in range(count):
            nxt = self.next_after(curr)
            if nxt is None:
                break
            result.append(nxt)
            curr = nxt
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
            raise CronError(f"Invalid macro: {stripped!r}")
        stripped = macro_target

    fields = re.split(r"[ \t]+", stripped)
    if len(fields) != 5:
        raise CronError(f"Expected 5 fields, got {len(fields)}")

    min_field, hour_field, dom_field, month_field, dow_field = fields

    minutes = _parse_standard_field(min_field, 0, 59)
    hours = _parse_standard_field(hour_field, 0, 23)
    dom_set, dom_has_l = _parse_dom_field(dom_field)
    months = _parse_standard_field(month_field, 1, 12, _MONTH_NAMES)
    dow_set, dow_nth = _parse_dow_field(dow_field)

    return CronSchedule(
        minutes=minutes,
        hours=hours,
        dom_set=dom_set,
        dom_has_l=dom_has_l,
        months=months,
        dow_set=dow_set,
        dow_nth=dow_nth,
        dom_restricted=(dom_field != "*"),
        dow_restricted=(dow_field != "*"),
    )
=== END ===
