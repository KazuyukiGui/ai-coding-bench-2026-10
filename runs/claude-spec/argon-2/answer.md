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
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_DOW_NAMES: dict[str, int] = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}

_FIELD_SPLIT_RE = re.compile(r"[ \t]+")


class CronError(ValueError):
    """cron 式が不正なときに送出する。"""


class CronSchedule:
    """解析済みの cron 式。parse() で生成する。"""

    def __init__(
        self,
        minutes: tuple[int, ...],
        hours: tuple[int, ...],
        doms: frozenset[int],
        dom_last: bool,
        dom_restricted: bool,
        months: tuple[int, ...],
        dows: frozenset[int],
        dow_nths: frozenset[tuple[int, int]],
        dow_restricted: bool,
    ) -> None:
        self._minutes = minutes
        self._minutes_rev = tuple(reversed(minutes))
        self._minutes_set = frozenset(minutes)

        self._hours = hours
        self._hours_rev = tuple(reversed(hours))
        self._hours_set = frozenset(hours)

        self._doms = doms
        self._dom_last = dom_last
        self._dom_restricted = dom_restricted

        self._months = months
        self._months_rev = tuple(reversed(months))
        self._months_set = frozenset(months)

        self._dows = dows
        self._dow_nths = dow_nths
        self._dow_restricted = dow_restricted
        self._both_restricted = dom_restricted and dow_restricted

        self._day_cache: dict[tuple[int, int], tuple[int, ...]] = {}

    def _valid_days(self, year: int, month: int) -> tuple[int, ...]:
        first_weekday, num_days = calendar.monthrange(year, month)
        first_cron_dow = (first_weekday + 1) % 7
        key = (first_cron_dow, num_days)
        cached = self._day_cache.get(key)
        if cached is not None:
            return cached

        doms = self._doms
        dom_last = self._dom_last
        dows = self._dows
        dow_nths = self._dow_nths
        both_restricted = self._both_restricted

        valid: list[int] = []
        for d in range(1, num_days + 1):
            dom_match = (d in doms) or (dom_last and d == num_days)
            cron_dow = (first_cron_dow + d - 1) % 7
            dow_match = (cron_dow in dows) or (
                bool(dow_nths) and (cron_dow, (d - 1) // 7 + 1) in dow_nths
            )
            if both_restricted:
                matched = dom_match or dow_match
            else:
                matched = dom_match and dow_match
            if matched:
                valid.append(d)

        res = tuple(valid)
        self._day_cache[key] = res
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

        _, num_days = calendar.monthrange(dt.year, dt.month)
        d = dt.day
        dom_match = (d in self._doms) or (self._dom_last and d == num_days)
        cron_dow = (dt.weekday() + 1) % 7
        dow_match = (cron_dow in self._dows) or (
            bool(self._dow_nths) and (cron_dow, (d - 1) // 7 + 1) in self._dow_nths
        )
        if self._both_restricted:
            return dom_match or dow_match
        return dom_match and dow_match

    def next_after(self, dt: datetime) -> datetime | None:
        try:
            start = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        except OverflowError:
            return None

        max_year = min(dt.year + 8, 9999)
        y0, m0, d0, h0, min0 = (
            start.year,
            start.month,
            start.day,
            start.hour,
            start.minute,
        )
        if y0 > max_year:
            return None

        months = self._months
        hours = self._hours
        minutes = self._minutes
        first_hour = hours[0]
        first_minute = minutes[0]

        for y in range(y0, max_year + 1):
            for m in months:
                if y == y0 and m < m0:
                    continue
                valid_days = self._valid_days(y, m)
                if not valid_days:
                    continue
                for d in valid_days:
                    if y == y0 and m == m0:
                        if d < d0:
                            continue
                        if d == d0:
                            for h in hours:
                                if h < h0:
                                    continue
                                if h == h0:
                                    for mn in minutes:
                                        if mn >= min0:
                                            return datetime(y, m, d, h, mn)
                                else:
                                    return datetime(y, m, d, h, first_minute)
                            continue
                    return datetime(y, m, d, first_hour, first_minute)
        return None

    def prev_before(self, dt: datetime) -> datetime | None:
        if dt.second > 0 or dt.microsecond > 0:
            start = dt.replace(second=0, microsecond=0)
        else:
            try:
                start = dt - timedelta(minutes=1)
            except OverflowError:
                return None

        min_year = max(dt.year - 8, 1)
        y0, m0, d0, h0, min0 = (
            start.year,
            start.month,
            start.day,
            start.hour,
            start.minute,
        )
        if y0 < min_year:
            return None

        months_rev = self._months_rev
        hours_rev = self._hours_rev
        minutes_rev = self._minutes_rev
        last_hour = hours_rev[0]
        last_minute = minutes_rev[0]

        for y in range(y0, min_year - 1, -1):
            for m in months_rev:
                if y == y0 and m > m0:
                    continue
                valid_days = self._valid_days(y, m)
                if not valid_days:
                    continue
                for d in reversed(valid_days):
                    if y == y0 and m == m0:
                        if d > d0:
                            continue
                        if d == d0:
                            for h in hours_rev:
                                if h > h0:
                                    continue
                                if h == h0:
                                    for mn in minutes_rev:
                                        if mn <= min0:
                                            return datetime(y, m, d, h, mn)
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


def _is_ascii_digits(s: str) -> bool:
    return bool(s) and s.isascii() and s.isdigit()


def _parse_value(
    s: str,
    min_val: int,
    max_val: int,
    names: dict[str, int] | None,
) -> int:
    if not s:
        raise CronError("Empty value")
    if _is_ascii_digits(s):
        val = int(s)
    elif names is not None and s.isascii() and s.lower() in names:
        val = names[s.lower()]
    else:
        raise CronError(f"Invalid value: {s!r}")
    if not (min_val <= val <= max_val):
        raise CronError(f"Value out of range: {val}")
    return val


def _parse_step(s: str) -> int:
    if not _is_ascii_digits(s):
        raise CronError(f"Invalid step: {s!r}")
    step = int(s)
    if step < 1:
        raise CronError(f"Step must be >= 1: {step}")
    return step


def _parse_standard_item(
    item: str,
    min_val: int,
    max_val: int,
    star_min: int,
    star_max: int,
    names: dict[str, int] | None,
) -> set[int]:
    if not item:
        raise CronError("Empty item")
    if item.count("/") > 1:
        raise CronError(f"Too many slashes in item: {item!r}")

    if "/" in item:
        base, step_str = item.split("/")
        step = _parse_step(step_str)
    else:
        base = item
        step = None

    if not base:
        raise CronError(f"Empty base in item: {item!r}")

    if base == "*":
        s = 1 if step is None else step
        return set(range(star_min, star_max + 1, s))

    if "-" in base:
        if base.count("-") > 1:
            raise CronError(f"Too many hyphens in item: {item!r}")
        n_str, m_str = base.split("-")
        n = _parse_value(n_str, min_val, max_val, names)
        m = _parse_value(m_str, min_val, max_val, names)
        if n > m:
            raise CronError(f"Range start > end: {n} > {m}")
        s = 1 if step is None else step
        return set(range(n, m + 1, s))

    n = _parse_value(base, min_val, max_val, names)
    if step is None:
        return {n}
    if n > star_max:
        raise CronError(f"Start value {n} exceeds maximum {star_max} for step")
    return set(range(n, star_max + 1, step))


def _parse_simple_field(
    field: str,
    min_val: int,
    max_val: int,
    names: dict[str, int] | None = None,
) -> tuple[int, ...]:
    if not field:
        raise CronError("Empty field")
    values: set[int] = set()
    for item in field.split(","):
        values |= _parse_standard_item(item, min_val, max_val, min_val, max_val, names)
    return tuple(sorted(values))


def _parse_dom_field(field: str) -> tuple[frozenset[int], bool, bool]:
    if not field:
        raise CronError("Empty DOM field")
    restricted = field != "*"
    values: set[int] = set()
    dom_last = False
    for item in field.split(","):
        if not item:
            raise CronError("Empty item in DOM field")
        if item.isascii() and item.lower() == "l":
            dom_last = True
        else:
            values |= _parse_standard_item(item, 1, 31, 1, 31, None)
    return frozenset(values), dom_last, restricted


def _parse_dow_field(
    field: str,
) -> tuple[frozenset[int], frozenset[tuple[int, int]], bool]:
    if not field:
        raise CronError("Empty DOW field")
    restricted = field != "*"
    values: set[int] = set()
    nths: set[tuple[int, int]] = set()
    for item in field.split(","):
        if not item:
            raise CronError("Empty item in DOW field")
        if "#" in item:
            if item.count("#") > 1 or "/" in item or "-" in item or "*" in item:
                raise CronError(f"Invalid '#' item in DOW field: {item!r}")
            w_str, k_str = item.split("#")
            w = _parse_value(w_str, 0, 7, _DOW_NAMES)
            if w == 7:
                w = 0
            if not _is_ascii_digits(k_str):
                raise CronError(f"Invalid nth value in DOW field: {k_str!r}")
            k = int(k_str)
            if not (1 <= k <= 5):
                raise CronError(f"Nth value out of range (1-5): {k}")
            nths.add((w, k))
        else:
            raw = _parse_standard_item(item, 0, 7, 0, 6, _DOW_NAMES)
            if 7 in raw:
                raw.discard(7)
                raw.add(0)
            values |= raw
    return frozenset(values), frozenset(nths), restricted


def parse(expr: str) -> CronSchedule:
    """cron 式を解析して CronSchedule を返す。不正なら CronError。"""
    if not isinstance(expr, str):
        raise CronError("Expression must be a string")

    stripped = expr.strip(" \t")
    if not stripped:
        raise CronError("Empty cron expression")

    if stripped.startswith("@"):
        macro_key = stripped.lower()
        if macro_key not in _MACROS:
            raise CronError(f"Invalid macro: {stripped!r}")
        stripped = _MACROS[macro_key]

    fields = _FIELD_SPLIT_RE.split(stripped)
    if len(fields) != 5:
        raise CronError(f"Expected 5 fields, got {len(fields)}")

    min_field, hour_field, dom_field, month_field, dow_field = fields

    minutes = _parse_simple_field(min_field, 0, 59, None)
    hours = _parse_simple_field(hour_field, 0, 23, None)
    doms, dom_last, dom_restricted = _parse_dom_field(dom_field)
    months = _parse_simple_field(month_field, 1, 12, _MONTH_NAMES)
    dows, dow_nths, dow_restricted = _parse_dow_field(dow_field)

    return CronSchedule(
        minutes=minutes,
        hours=hours,
        doms=doms,
        dom_last=dom_last,
        dom_restricted=dom_restricted,
        months=months,
        dows=dows,
        dow_nths=dow_nths,
        dow_restricted=dow_restricted,
    )
=== END ===
