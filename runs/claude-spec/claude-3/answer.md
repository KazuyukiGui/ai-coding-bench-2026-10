=== FILE: cronexpr.py ===
"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

import bisect
import calendar
import re
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
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}

_DOW_NAMES = {
    name: i
    for i, name in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])
}

_DIGITS = frozenset("0123456789")

# (値の下限, 値の上限, * の下限, * の上限, 名前)
_MINUTE = (0, 59, 0, 59, None)
_HOUR = (0, 23, 0, 23, None)
_DOM = (1, 31, 1, 31, None)
_MONTH = (1, 12, 1, 12, _MONTH_NAMES)
_DOW = (0, 7, 0, 6, _DOW_NAMES)

_SEP = re.compile(r"[ \t]+")


def _is_digits(s: str) -> bool:
    return bool(s) and all(c in _DIGITS for c in s)


def _parse_value(s: str, spec) -> int:
    lo, hi, _, _, names = spec
    if _is_digits(s):
        v = int(s)
    elif names is not None and s.isascii() and s.lower() in names:
        v = names[s.lower()]
    else:
        raise CronError(f"不正な値です: {s!r}")
    if not lo <= v <= hi:
        raise CronError(f"値が範囲外です: {s!r}")
    return v


def _parse_step(s: str) -> int:
    if not _is_digits(s):
        raise CronError(f"不正な間隔です: {s!r}")
    step = int(s)
    if step < 1:
        raise CronError(f"間隔は 1 以上でなければなりません: {s!r}")
    return step


def _parse_field(text: str, spec, allow_last: bool = False, allow_nth: bool = False):
    """フィールドを解析し (値の集合, L の有無, {(第 K, 曜日)}) を返す。"""
    _, _, star_lo, star_hi, _ = spec
    values: set[int] = set()
    last = False
    nth: set[tuple[int, int]] = set()

    for item in text.split(","):
        if not item:
            raise CronError(f"空の項目があります: {text!r}")

        if allow_last and item in ("L", "l"):
            last = True
            continue

        if allow_nth and "#" in item:
            parts = item.split("#")
            if len(parts) != 2:
                raise CronError(f"不正な項目です: {item!r}")
            w = _parse_value(parts[0], spec)
            if not _is_digits(parts[1]):
                raise CronError(f"不正な項目です: {item!r}")
            k = int(parts[1])
            if not 1 <= k <= 5:
                raise CronError(f"不正な項目です: {item!r}")
            nth.add((k, w % 7))
            continue

        step = None
        base = item
        if "/" in item:
            parts = item.split("/")
            if len(parts) != 2:
                raise CronError(f"不正な項目です: {item!r}")
            base, step_text = parts
            step = _parse_step(step_text)

        if base == "*":
            lo, hi = star_lo, star_hi
        elif "-" in base:
            parts = base.split("-")
            if len(parts) != 2:
                raise CronError(f"不正な範囲です: {item!r}")
            lo = _parse_value(parts[0], spec)
            hi = _parse_value(parts[1], spec)
            if lo > hi:
                raise CronError(f"範囲の始点が終点より大きいです: {item!r}")
        else:
            lo = _parse_value(base, spec)
            if step is None:
                hi = lo
            else:
                hi = star_hi
                if lo > hi:
                    raise CronError(f"始点が範囲外です: {item!r}")

        values.update(range(lo, hi + 1, step or 1))

    return values, last, nth


class CronSchedule:
    """解析済みの cron 式。parse() で生成する。"""

    def __init__(self, fields: list[str]):
        minute, hour, dom, month, dow = fields
        minutes, _, _ = _parse_field(minute, _MINUTE)
        hours, _, _ = _parse_field(hour, _HOUR)
        days, last, _ = _parse_field(dom, _DOM, allow_last=True)
        months, _, _ = _parse_field(month, _MONTH)
        dows, _, nth = _parse_field(dow, _DOW, allow_nth=True)

        self._minutes = sorted(minutes)
        self._hours = sorted(hours)
        self._minute_set = frozenset(minutes)
        self._hour_set = frozenset(hours)
        self._days = frozenset(days)
        self._last = last
        self._months = sorted(months)
        self._month_set = frozenset(months)
        self._dows = frozenset(v % 7 for v in dows)
        self._nth = frozenset(nth)
        self._either = dom != "*" and dow != "*"

    def _day_ok(self, y: int, m: int, d: int, last_day: int) -> bool:
        dom_match = d in self._days or (self._last and d == last_day)
        wd = (date(y, m, d).weekday() + 1) % 7
        dow_match = wd in self._dows or ((d - 1) // 7 + 1, wd) in self._nth
        if self._either:
            return dom_match or dow_match
        return dom_match and dow_match

    def _first_time_ge(self, h0: int, m0: int):
        hours, minutes = self._hours, self._minutes
        for h in hours[bisect.bisect_left(hours, h0):]:
            if h == h0:
                j = bisect.bisect_left(minutes, m0)
                if j < len(minutes):
                    return h, minutes[j]
            else:
                return h, minutes[0]
        return None

    def _last_time_le(self, h0: int, m0: int):
        hours, minutes = self._hours, self._minutes
        for h in reversed(hours[:bisect.bisect_right(hours, h0)]):
            if h == h0:
                j = bisect.bisect_right(minutes, m0)
                if j > 0:
                    return h, minutes[j - 1]
            else:
                return h, minutes[-1]
        return None

    def matches(self, dt: datetime) -> bool:
        if dt.second != 0 or dt.microsecond != 0:
            return False
        if dt.minute not in self._minute_set or dt.hour not in self._hour_set:
            return False
        if dt.month not in self._month_set:
            return False
        last_day = calendar.monthrange(dt.year, dt.month)[1]
        return self._day_ok(dt.year, dt.month, dt.day, last_day)

    def next_after(self, dt: datetime) -> datetime | None:
        try:
            start = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        except OverflowError:
            return None
        limit = min(dt.year + 8, 9999)

        for y in range(start.year, limit + 1):
            for mo in self._months:
                if y == start.year and mo < start.month:
                    continue
                last_day = calendar.monthrange(y, mo)[1]
                same_month = y == start.year and mo == start.month
                first = start.day if same_month else 1
                for d in range(first, last_day + 1):
                    if not self._day_ok(y, mo, d, last_day):
                        continue
                    if same_month and d == start.day:
                        t = self._first_time_ge(start.hour, start.minute)
                    else:
                        t = self._first_time_ge(0, 0)
                    if t is not None:
                        return datetime(y, mo, d, t[0], t[1])
        return None

    def prev_before(self, dt: datetime) -> datetime | None:
        upper = dt.replace(second=0, microsecond=0)
        if upper == dt:
            try:
                upper = upper - timedelta(minutes=1)
            except OverflowError:
                return None
        limit = max(dt.year - 8, 1)

        for y in range(upper.year, limit - 1, -1):
            for mo in reversed(self._months):
                if y == upper.year and mo > upper.month:
                    continue
                last_day = calendar.monthrange(y, mo)[1]
                same_month = y == upper.year and mo == upper.month
                first = upper.day if same_month else last_day
                for d in range(first, 0, -1):
                    if not self._day_ok(y, mo, d, last_day):
                        continue
                    if same_month and d == upper.day:
                        t = self._last_time_le(upper.hour, upper.minute)
                    else:
                        t = self._last_time_le(23, 59)
                    if t is not None:
                        return datetime(y, mo, d, t[0], t[1])
        return None

    def iter_after(self, dt: datetime, count: int) -> list[datetime]:
        if count < 0:
            raise ValueError("count は 0 以上でなければなりません")
        result: list[datetime] = []
        current = dt
        while len(result) < count:
            nxt = self.next_after(current)
            if nxt is None:
                break
            result.append(nxt)
            current = nxt
        return result


def parse(expr: str) -> CronSchedule:
    """cron 式を解析して CronSchedule を返す。不正なら CronError。"""
    text = expr.strip(" \t")
    if not text:
        raise CronError("式が空です")

    if text.startswith("@"):
        key = text.lower() if text.isascii() else None
        if key not in _MACROS:
            raise CronError(f"不明なマクロです: {text!r}")
        text = _MACROS[key]

    fields = _SEP.split(text)
    if len(fields) != 5:
        raise CronError(f"フィールド数が 5 ではありません: {expr!r}")
    return CronSchedule(fields)
=== END ===