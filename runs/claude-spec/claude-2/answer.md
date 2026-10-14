=== FILE: cronexpr.py ===
"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

import calendar
import re
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta

__all__ = ["CronError", "CronSchedule", "parse"]


class CronError(ValueError):
    """cron 式が不正なときに送出する。"""


_MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}

_MONTH_NAMES = {
    name: i + 1
    for i, name in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
         "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    )
}
_DOW_NAMES = {
    name: i
    for i, name in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"])
}

_DIGITS = frozenset("0123456789")

# (名前, 値の下限, 値の上限, * の下限, * の上限, 英字名)
_MINUTE = ("minute", 0, 59, 0, 59, None)
_HOUR = ("hour", 0, 23, 0, 23, None)
_DOM = ("day of month", 1, 31, 1, 31, None)
_MONTH = ("month", 1, 12, 1, 12, _MONTH_NAMES)
_DOW = ("day of week", 0, 7, 0, 6, _DOW_NAMES)


def _is_digits(s: str) -> bool:
    return bool(s) and all(c in _DIGITS for c in s)


def _small_int(s: str, cap: int = 10**6) -> int:
    """ASCII 数字列を整数にする。巨大な値は cap に丸める。"""
    t = s.lstrip("0") or "0"
    if len(t) > 7:
        return cap
    return min(int(t), cap)


def _parse_value(text: str, spec) -> int:
    name, vmin, vmax, _, _, names = spec
    if _is_digits(text):
        v = _small_int(text)
    elif names is not None and text.isascii() and len(text) == 3 and text.upper() in names:
        v = names[text.upper()]
    else:
        raise CronError(f"invalid value {text!r} in {name} field")
    if v < vmin or v > vmax:
        raise CronError(f"value {text!r} out of range in {name} field")
    return v


def _parse_step(text: str, spec) -> int:
    if not _is_digits(text):
        raise CronError(f"invalid step {text!r} in {spec[0]} field")
    s = _small_int(text)
    if s < 1:
        raise CronError(f"step must be positive in {spec[0]} field")
    return s


def _parse_range_item(item: str, spec) -> range:
    name, _, _, star_lo, star_hi, _ = spec
    if "/" in item:
        parts = item.split("/")
        if len(parts) != 2:
            raise CronError(f"invalid item {item!r} in {name} field")
        base, step_text = parts
        step = _parse_step(step_text, spec)
    else:
        base, step = item, None

    if base == "*":
        lo, hi = star_lo, star_hi
    elif "-" in base:
        parts = base.split("-")
        if len(parts) != 2:
            raise CronError(f"invalid range {base!r} in {name} field")
        lo = _parse_value(parts[0], spec)
        hi = _parse_value(parts[1], spec)
        if lo > hi:
            raise CronError(f"invalid range {base!r} in {name} field")
    else:
        lo = _parse_value(base, spec)
        if step is None:
            hi = lo
        else:
            hi = star_hi
            if lo > hi:
                raise CronError(f"invalid item {item!r} in {name} field")
    return range(lo, hi + 1, step or 1)


def _parse_field(text: str, spec, allow_last=False, allow_nth=False):
    """(値の集合, L の有無, {(曜日, 第K)}) を返す。"""
    values: set[int] = set()
    last = False
    nth: set[tuple[int, int]] = set()
    for item in text.split(","):
        if not item:
            raise CronError(f"empty item in {spec[0]} field")
        if allow_last and item in ("L", "l"):
            last = True
        elif allow_nth and "#" in item:
            parts = item.split("#")
            if len(parts) != 2:
                raise CronError(f"invalid item {item!r} in {spec[0]} field")
            w = _parse_value(parts[0], spec)
            if not _is_digits(parts[1]):
                raise CronError(f"invalid item {item!r} in {spec[0]} field")
            k = _small_int(parts[1])
            if not 1 <= k <= 5:
                raise CronError(f"invalid item {item!r} in {spec[0]} field")
            nth.add((w % 7, k))
        else:
            values.update(_parse_range_item(item, spec))
    return values, last, nth


class CronSchedule:
    """解析済みの cron 式。parse() で生成する。"""

    def __init__(self, minutes, hours, days, last_day, months, dows, nth,
                 dom_restricted, dow_restricted):
        self._minutes = sorted(minutes)
        self._hours = sorted(hours)
        self._days = frozenset(days)
        self._last_day = last_day
        self._months = frozenset(months)
        self._dows = frozenset(dows)
        self._nth = frozenset(nth)
        self._dom_restricted = dom_restricted
        self._dow_restricted = dow_restricted
        self._minute_set = frozenset(minutes)
        self._hour_set = frozenset(hours)

    def _day_ok(self, d: date) -> bool:
        if d.month not in self._months:
            return False
        dom = d.day in self._days or (
            self._last_day and d.day == calendar.monthrange(d.year, d.month)[1]
        )
        wd = d.isoweekday() % 7
        dow = wd in self._dows or (wd, (d.day - 1) // 7 + 1) in self._nth
        if self._dom_restricted and self._dow_restricted:
            return dom or dow
        return dom and dow

    def _first_time_from(self, hour: int, minute: int):
        hours, minutes = self._hours, self._minutes
        i = bisect_left(hours, hour)
        if i < len(hours) and hours[i] == hour:
            j = bisect_left(minutes, minute)
            if j < len(minutes):
                return hour, minutes[j]
            i += 1
        if i < len(hours):
            return hours[i], minutes[0]
        return None

    def _last_time_until(self, hour: int, minute: int):
        hours, minutes = self._hours, self._minutes
        i = bisect_right(hours, hour) - 1
        if i >= 0 and hours[i] == hour:
            j = bisect_right(minutes, minute) - 1
            if j >= 0:
                return hour, minutes[j]
            i -= 1
        if i >= 0:
            return hours[i], minutes[-1]
        return None

    def matches(self, dt: datetime) -> bool:
        return (
            dt.second == 0
            and dt.microsecond == 0
            and dt.minute in self._minute_set
            and dt.hour in self._hour_set
            and self._day_ok(dt.date())
        )

    def next_after(self, dt: datetime) -> datetime | None:
        base = dt.replace(second=0, microsecond=0)
        try:
            start = base + timedelta(minutes=1)
        except OverflowError:
            return None
        limit = min(dt.year + 8, 9999)
        end_d = date(limit, 12, 31)
        d = start.date()
        first_d = d
        one_day = timedelta(days=1)
        while d <= end_d:
            if self._day_ok(d):
                if d == first_d:
                    t = self._first_time_from(start.hour, start.minute)
                else:
                    t = (self._hours[0], self._minutes[0])
                if t is not None:
                    return datetime(d.year, d.month, d.day, t[0], t[1])
            if d == end_d:
                break
            d += one_day
        return None

    def prev_before(self, dt: datetime) -> datetime | None:
        base = dt.replace(second=0, microsecond=0)
        if base != dt:
            end = base
        else:
            try:
                end = base - timedelta(minutes=1)
            except OverflowError:
                return None
        limit = max(dt.year - 8, 1)
        start_d = date(limit, 1, 1)
        d = end.date()
        first_d = d
        one_day = timedelta(days=1)
        while d >= start_d:
            if self._day_ok(d):
                if d == first_d:
                    t = self._last_time_until(end.hour, end.minute)
                else:
                    t = (self._hours[-1], self._minutes[-1])
                if t is not None:
                    return datetime(d.year, d.month, d.day, t[0], t[1])
            if d == start_d:
                break
            d -= one_day
        return None

    def iter_after(self, dt: datetime, count: int) -> list[datetime]:
        if count < 0:
            raise ValueError("count must be non-negative")
        result: list[datetime] = []
        cur = dt
        while len(result) < count:
            nxt = self.next_after(cur)
            if nxt is None:
                break
            result.append(nxt)
            cur = nxt
        return result


def parse(expr: str) -> CronSchedule:
    """cron 式を解析して CronSchedule を返す。不正なら CronError。"""
    if not isinstance(expr, str):
        raise CronError("expression must be a string")
    s = expr.strip(" \t")
    if not s:
        raise CronError("empty expression")
    if s.startswith("@"):
        key = s.lower() if s.isascii() else None
        if key not in _MACROS:
            raise CronError(f"unknown macro {s!r}")
        s = _MACROS[key]

    fields = re.split(r"[ \t]+", s)
    if len(fields) != 5:
        raise CronError(f"expected 5 fields, got {len(fields)}")
    f_min, f_hour, f_dom, f_month, f_dow = fields

    minutes, _, _ = _parse_field(f_min, _MINUTE)
    hours, _, _ = _parse_field(f_hour, _HOUR)
    days, last_day, _ = _parse_field(f_dom, _DOM, allow_last=True)
    months, _, _ = _parse_field(f_month, _MONTH)
    dows, _, nth = _parse_field(f_dow, _DOW, allow_nth=True)
    dows = {v % 7 for v in dows}

    return CronSchedule(
        minutes=minutes,
        hours=hours,
        days=days,
        last_day=last_day,
        months=months,
        dows=dows,
        nth=nth,
        dom_restricted=f_dom != "*",
        dow_restricted=f_dow != "*",
    )
=== END ===