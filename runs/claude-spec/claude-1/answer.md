=== FILE: cronexpr.py ===
"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

import calendar
import re
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta

__all__ = ["CronError", "CronSchedule", "parse"]


class CronError(ValueError):
    """cron 式が不正なときに送出する。"""


_SPACE_RE = re.compile(r"[ \t]+")
_DIGITS_RE = re.compile(r"[0-9]+")

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

# (名前, 下限, 上限, * の下限, * の上限, 英字名)
_MINUTE = ("minute", 0, 59, 0, 59, None)
_HOUR = ("hour", 0, 23, 0, 23, None)
_DOM = ("day of month", 1, 31, 1, 31, None)
_MONTH = ("month", 1, 12, 1, 12, _MONTH_NAMES)
_DOW = ("day of week", 0, 7, 0, 6, _DOW_NAMES)

_MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


def _int(tok: str) -> int | None:
    """ASCII 数字だけからなる文字列なら整数に、そうでなければ None。"""
    if _DIGITS_RE.fullmatch(tok):
        return int(tok)
    return None


def _value(tok: str, spec) -> int:
    name, lo, hi, _, _, names = spec
    v = _int(tok)
    if v is None:
        if names is not None and tok.isascii() and tok.lower() in names:
            v = names[tok.lower()]
        else:
            raise CronError(f"invalid value {tok!r} in {name} field")
    if not lo <= v <= hi:
        raise CronError(f"value {tok!r} out of range in {name} field")
    return v


def _step(tok: str, spec) -> int:
    s = _int(tok)
    if s is None or s < 1:
        raise CronError(f"invalid step {tok!r} in {spec[0]} field")
    return s


def _parse_field(text: str, spec, allow_last: bool, allow_nth: bool):
    """フィールドを解析し (値の集合, L の有無, [(曜日, K), ...]) を返す。"""
    name, _, _, star_lo, star_hi, _ = spec
    values: set[int] = set()
    has_last = False
    nth: list[tuple[int, int]] = []

    for item in text.split(","):
        if item == "":
            raise CronError(f"empty item in {name} field")

        if allow_last and item in ("L", "l"):
            has_last = True
            continue

        if "#" in item:
            if not allow_nth:
                raise CronError(f"'#' is not allowed in {name} field")
            parts = item.split("#")
            if len(parts) != 2:
                raise CronError(f"invalid item {item!r} in {name} field")
            w = _value(parts[0], spec)
            k = _int(parts[1])
            if k is None or not 1 <= k <= 5:
                raise CronError(f"invalid item {item!r} in {name} field")
            nth.append((w % 7, k))
            continue

        if "/" in item:
            parts = item.split("/")
            if len(parts) != 2:
                raise CronError(f"invalid item {item!r} in {name} field")
            base, step_tok = parts
            step = _step(step_tok, spec)
            if base == "*":
                start, end = star_lo, star_hi
            elif "-" in base:
                a, b = base.split("-", 1)
                start, end = _value(a, spec), _value(b, spec)
                if start > end:
                    raise CronError(f"invalid range {base!r} in {name} field")
            else:
                start = _value(base, spec)
                end = star_hi
                if start > end:
                    raise CronError(f"invalid item {item!r} in {name} field")
            values.update(range(start, end + 1, step))
            continue

        if item == "*":
            values.update(range(star_lo, star_hi + 1))
            continue

        if "-" in item:
            a, b = item.split("-", 1)
            start, end = _value(a, spec), _value(b, spec)
            if start > end:
                raise CronError(f"invalid range {item!r} in {name} field")
            values.update(range(start, end + 1))
            continue

        values.add(_value(item, spec))

    return values, has_last, nth


class CronSchedule:
    """解析済みの cron 式。parse() で生成する。"""

    def __init__(self, fields: list[str]):
        minute, hour, dom, month, dow = fields
        minutes, _, _ = _parse_field(minute, _MINUTE, False, False)
        hours, _, _ = _parse_field(hour, _HOUR, False, False)
        doms, has_last, _ = _parse_field(dom, _DOM, True, False)
        months, _, _ = _parse_field(month, _MONTH, False, False)
        dows, _, nth = _parse_field(dow, _DOW, False, True)

        self._minutes = sorted(minutes)
        self._hours = sorted(hours)
        self._minute_set = frozenset(minutes)
        self._hour_set = frozenset(hours)
        self._doms = frozenset(doms)
        self._has_last = has_last
        self._months = sorted(months)
        self._month_set = frozenset(months)
        self._dows = frozenset(v % 7 for v in dows)
        self._nth = tuple(nth)
        self._either = dom != "*" and dow != "*"
        self._expr = " ".join(fields)

    def __repr__(self) -> str:
        return f"CronSchedule({self._expr!r})"

    def _day_ok(self, d: int, first_wd: int, last: int) -> bool:
        dom_match = d in self._doms or (self._has_last and d == last)
        # first_wd は月曜 0 の曜日。cron の曜日は日曜 0。
        cron_dow = (first_wd + d) % 7
        dow_match = cron_dow in self._dows
        if not dow_match and self._nth:
            k = (d - 1) // 7 + 1
            dow_match = (cron_dow, k) in self._nth
        if self._either:
            return dom_match or dow_match
        return dom_match and dow_match

    def _first_time_from(self, h: int, mi: int) -> tuple[int, int] | None:
        hours, minutes = self._hours, self._minutes
        i = bisect_left(hours, h)
        if i < len(hours) and hours[i] == h:
            j = bisect_left(minutes, mi)
            if j < len(minutes):
                return h, minutes[j]
            i += 1
        if i < len(hours):
            return hours[i], minutes[0]
        return None

    def _last_time_until(self, h: int, mi: int) -> tuple[int, int] | None:
        hours, minutes = self._hours, self._minutes
        i = bisect_right(hours, h) - 1
        if i >= 0 and hours[i] == h:
            j = bisect_right(minutes, mi) - 1
            if j >= 0:
                return h, minutes[j]
            i -= 1
        if i >= 0:
            return hours[i], minutes[-1]
        return None

    def matches(self, dt: datetime) -> bool:
        if dt.second != 0 or dt.microsecond != 0:
            return False
        if dt.minute not in self._minute_set or dt.hour not in self._hour_set:
            return False
        if dt.month not in self._month_set:
            return False
        first_wd, last = calendar.monthrange(dt.year, dt.month)
        return self._day_ok(dt.day, first_wd, last)

    def next_after(self, dt: datetime) -> datetime | None:
        start = dt.replace(second=0, microsecond=0)
        try:
            start += timedelta(minutes=1)
        except OverflowError:
            return None
        limit = min(dt.year + 8, 9999)
        for y in range(start.year, limit + 1):
            for m in self._months:
                if (y, m) < (start.year, start.month):
                    continue
                first_wd, last = calendar.monthrange(y, m)
                first_month = (y, m) == (start.year, start.month)
                d0 = start.day if first_month else 1
                for d in range(d0, last + 1):
                    if not self._day_ok(d, first_wd, last):
                        continue
                    if first_month and d == start.day:
                        t = self._first_time_from(start.hour, start.minute)
                    else:
                        t = (self._hours[0], self._minutes[0])
                    if t is not None:
                        return datetime(y, m, d, t[0], t[1])
        return None

    def prev_before(self, dt: datetime) -> datetime | None:
        end = dt.replace(second=0, microsecond=0)
        if end == dt:
            try:
                end -= timedelta(minutes=1)
            except OverflowError:
                return None
        low = max(dt.year - 8, 1)
        for y in range(end.year, low - 1, -1):
            for m in reversed(self._months):
                if (y, m) > (end.year, end.month):
                    continue
                first_wd, last = calendar.monthrange(y, m)
                last_month = (y, m) == (end.year, end.month)
                d0 = end.day if last_month else last
                for d in range(d0, 0, -1):
                    if not self._day_ok(d, first_wd, last):
                        continue
                    if last_month and d == end.day:
                        t = self._last_time_until(end.hour, end.minute)
                    else:
                        t = (self._hours[-1], self._minutes[-1])
                    if t is not None:
                        return datetime(y, m, d, t[0], t[1])
        return None

    def iter_after(self, dt: datetime, count: int) -> list[datetime]:
        if count < 0:
            raise ValueError("count must not be negative")
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
    if s == "":
        raise CronError("empty expression")
    if s.startswith("@"):
        key = s.lower() if s.isascii() else None
        if key not in _MACROS:
            raise CronError(f"unknown macro {s!r}")
        s = _MACROS[key]
    fields = _SPACE_RE.split(s)
    if len(fields) != 5:
        raise CronError(f"expected 5 fields, got {len(fields)}")
    return CronSchedule(fields)
=== END ===