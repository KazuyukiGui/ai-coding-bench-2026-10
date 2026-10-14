"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

import calendar
import re
from datetime import date, datetime, timedelta

__all__ = ["CronError", "CronSchedule", "parse"]

SEARCH_YEARS = 8

MONTH_NAMES = {
    name: i
    for i, name in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
         "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"],
        start=1,
    )
}
DOW_NAMES = {
    name: i
    for i, name in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"])
}

MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


class CronError(ValueError):
    """cron 式が不正なときに送出する。"""


class _FieldSpec:
    def __init__(self, label, lo, hi, star_hi, names=None):
        self.label = label
        self.lo = lo
        self.hi = hi
        self.star_hi = star_hi
        self.names = names or {}


_MINUTE = _FieldSpec("minute", 0, 59, 59)
_HOUR = _FieldSpec("hour", 0, 23, 23)
_DOM = _FieldSpec("day-of-month", 1, 31, 31)
_MONTH = _FieldSpec("month", 1, 12, 12, MONTH_NAMES)
_DOW = _FieldSpec("day-of-week", 0, 7, 6, DOW_NAMES)


def _is_ascii_digits(text):
    return text != "" and all(c in "0123456789" for c in text)


def _parse_value(text, spec):
    if _is_ascii_digits(text):
        value = int(text)
    elif text.isascii() and text.upper() in spec.names:
        value = spec.names[text.upper()]
    else:
        raise CronError(f"invalid {spec.label} value: {text!r}")
    if not spec.lo <= value <= spec.hi:
        raise CronError(f"{spec.label} value out of range: {text!r}")
    return value


def _parse_step(text, spec):
    if not _is_ascii_digits(text):
        raise CronError(f"invalid {spec.label} step: {text!r}")
    step = int(text)
    if step < 1:
        raise CronError(f"{spec.label} step must be positive: {text!r}")
    return step


def _expand_item(item, spec):
    """'*' / 'N' / 'N-M' に任意の '/S' が付いた項目を値の集合に展開する。"""
    step = None
    base = item
    if "/" in item:
        base, step_text = item.split("/", 1)
        step = _parse_step(step_text, spec)
    if base == "*":
        start, end = spec.lo, spec.star_hi
    elif "-" in base:
        a, b = base.split("-", 1)
        start, end = _parse_value(a, spec), _parse_value(b, spec)
        if start > end:
            raise CronError(f"invalid {spec.label} range: {base!r}")
    else:
        start = _parse_value(base, spec)
        if step is None:
            end = start
        else:
            end = spec.star_hi
            if start > end:
                raise CronError(f"invalid {spec.label} start: {base!r}")
    return set(range(start, end + 1, step or 1))


def _split_items(text, spec):
    items = text.split(",")
    if any(item == "" for item in items):
        raise CronError(f"empty item in {spec.label} field: {text!r}")
    return items


def _parse_simple(text, spec):
    values = set()
    for item in _split_items(text, spec):
        values |= _expand_item(item, spec)
    return values


def _parse_dom(text):
    values = set()
    last = False
    for item in _split_items(text, _DOM):
        if item.upper() == "L":
            last = True
        else:
            values |= _expand_item(item, _DOM)
    return values, last


def _parse_dow(text):
    values = set()
    nth = set()
    for item in _split_items(text, _DOW):
        if "#" in item:
            left, right = item.split("#", 1)
            weekday = _parse_value(left, _DOW)
            if not _is_ascii_digits(right) or not 1 <= int(right) <= 5:
                raise CronError(f"invalid nth weekday: {item!r}")
            nth.add((weekday % 7, int(right)))
        else:
            values |= {v % 7 for v in _expand_item(item, _DOW)}
    return values, nth


class CronSchedule:
    """解析済みの cron 式。parse() で生成する。"""

    def __init__(self, fields):
        minute, hour, dom, month, dow = fields
        self._minutes = _parse_simple(minute, _MINUTE)
        self._hours = _parse_simple(hour, _HOUR)
        self._days, self._last_day = _parse_dom(dom)
        self._months = _parse_simple(month, _MONTH)
        self._weekdays, self._nth = _parse_dow(dow)
        self._dom_any = dom == "*"
        self._dow_any = dow == "*"

    def _day_matches(self, d):
        if d.month not in self._months:
            return False
        dom_ok = d.day in self._days or (
            self._last_day and d.day == calendar.monthrange(d.year, d.month)[1]
        )
        weekday = (d.weekday() + 1) % 7
        dow_ok = weekday in self._weekdays or (
            (weekday, (d.day - 1) // 7 + 1) in self._nth
        )
        if self._dom_any or self._dow_any:
            return dom_ok and dow_ok
        return dom_ok or dow_ok

    def matches(self, dt):
        return (
            dt.second == 0
            and dt.microsecond == 0
            and dt.minute in self._minutes
            and dt.hour in self._hours
            and self._day_matches(dt.date())
        )

    def next_after(self, dt):
        base = dt.replace(second=0, microsecond=0)
        try:
            start = base + timedelta(minutes=1)
        except OverflowError:
            return None
        end = date(min(dt.year + SEARCH_YEARS, 9999), 12, 31)
        hours = sorted(self._hours)
        minutes = sorted(self._minutes)
        d = start.date()
        first = True
        while d <= end:
            if self._day_matches(d):
                for h in hours:
                    if first and h < start.hour:
                        continue
                    for m in minutes:
                        if first and h == start.hour and m < start.minute:
                            continue
                        return datetime(d.year, d.month, d.day, h, m)
            if d == end:
                break
            d += timedelta(days=1)
            first = False
        return None

    def prev_before(self, dt):
        base = dt.replace(second=0, microsecond=0)
        if base == dt:
            try:
                start = base - timedelta(minutes=1)
            except OverflowError:
                return None
        else:
            start = base
        end = date(max(dt.year - SEARCH_YEARS, 1), 1, 1)
        hours = sorted(self._hours, reverse=True)
        minutes = sorted(self._minutes, reverse=True)
        d = start.date()
        first = True
        while d >= end:
            if self._day_matches(d):
                for h in hours:
                    if first and h > start.hour:
                        continue
                    for m in minutes:
                        if first and h == start.hour and m > start.minute:
                            continue
                        return datetime(d.year, d.month, d.day, h, m)
            if d == end:
                break
            d -= timedelta(days=1)
            first = False
        return None

    def iter_after(self, dt, count):
        if count < 0:
            raise ValueError("count must not be negative")
        result = []
        current = dt
        while len(result) < count:
            current = self.next_after(current)
            if current is None:
                break
            result.append(current)
        return result


def parse(expr):
    """cron 式を解析して CronSchedule を返す。不正なら CronError。"""
    if not isinstance(expr, str):
        raise CronError("expression must be a string")
    text = expr.strip(" \t")
    if text.startswith("@"):
        macro = MACROS.get(text.lower()) if text.isascii() else None
        if macro is None:
            raise CronError(f"unknown macro: {text!r}")
        text = macro
    fields = re.split(r"[ \t]+", text)
    if len(fields) != 5:
        raise CronError(f"expected 5 fields, got {len(fields)}")
    return CronSchedule(fields)
