=== FILE: cronexpr.py ===
"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

from bisect import bisect_left, bisect_right
from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime
import re

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
    name: number
    for number, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
         "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        start=1,
    )
}

_WEEKDAY_NAMES = {
    name: number
    for number, name in enumerate(
        ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
    )
}

# 下限、値として許される上限、ワイルドカードの上限、名前。
_FIELD_SPECS = (
    (0, 59, 59, {}),
    (0, 23, 23, {}),
    (1, 31, 31, {}),
    (1, 12, 12, _MONTH_NAMES),
    (0, 7, 6, _WEEKDAY_NAMES),
)


@dataclass(frozen=True)
class _Field:
    values: frozenset[int]
    unrestricted: bool
    last_day: bool = False
    nth_weekdays: frozenset[tuple[int, int]] = frozenset()


def _decimal_digits(text: str) -> str:
    """ASCII 数字を検証し、余分な先頭の 0 を除く。"""
    if not text or any(char < "0" or char > "9" for char in text):
        raise CronError(f"不正な整数: {text!r}")
    return text.lstrip("0") or "0"


def _bounded_integer(text: str, lower: int, upper: int) -> int:
    digits = _decimal_digits(text)
    limit = str(upper)
    if len(digits) > len(limit) or (
        len(digits) == len(limit) and digits > limit
    ):
        raise CronError(f"値が範囲外: {text!r}")

    value = int(digits)
    if value < lower:
        raise CronError(f"値が範囲外: {text!r}")
    return value


def _step(text: str) -> int:
    digits = _decimal_digits(text)
    if digits == "0":
        raise CronError("ステップは 1 以上でなければなりません")

    # 全フィールドの区間幅は 60 以下。60 以上のステップは
    # いずれも開始値だけを生成するため、巨大な整数への変換を避ける。
    if len(digits) > 2:
        return 60
    return min(int(digits), 60)


def _value(
    text: str,
    lower: int,
    upper: int,
    names: dict[str, int],
) -> int:
    if text.isascii():
        named = names.get(text.upper())
        if named is not None:
            return named
    return _bounded_integer(text, lower, upper)


def _parse_field(text: str, index: int) -> _Field:
    lower, upper, wildcard_upper, names = _FIELD_SPECS[index]
    values: set[int] = set()
    nth_weekdays: set[tuple[int, int]] = set()
    last_day = False

    for item in text.split(","):
        if not item:
            raise CronError("空の項目は指定できません")

        if index == 2 and item in ("L", "l"):
            last_day = True
            continue

        if "#" in item:
            if index != 4 or item.count("#") != 1:
                raise CronError(f"不正な第 K 曜日の指定: {item!r}")
            weekday_text, occurrence_text = item.split("#")
            weekday = _value(weekday_text, lower, upper, names)
            occurrence = _bounded_integer(occurrence_text, 1, 5)
            nth_weekdays.add((weekday % 7, occurrence))
            continue

        if item.count("/") > 1:
            raise CronError(f"不正なステップ指定: {item!r}")

        has_step = "/" in item
        if has_step:
            base, step_text = item.split("/")
            step = _step(step_text)
        else:
            base = item
            step = 1

        if base == "*":
            start, stop = lower, wildcard_upper
        elif "-" in base:
            endpoints = base.split("-")
            if len(endpoints) != 2:
                raise CronError(f"不正な範囲: {item!r}")
            start = _value(endpoints[0], lower, upper, names)
            stop = _value(endpoints[1], lower, upper, names)
        else:
            start = _value(base, lower, upper, names)
            stop = wildcard_upper if has_step else start

        if start > stop:
            raise CronError(f"範囲の開始値が終了値を超えています: {item!r}")

        values.update(range(start, stop + 1, step))

    if index == 4:
        values = {value % 7 for value in values}

    return _Field(
        values=frozenset(values),
        unrestricted=text == "*",
        last_day=last_day,
        nth_weekdays=frozenset(nth_weekdays),
    )


class CronSchedule:
    """解析済みの cron 式。parse() で生成する。"""

    def __init__(
        self,
        minute: _Field,
        hour: _Field,
        day: _Field,
        month: _Field,
        weekday: _Field,
    ) -> None:
        self._minute = minute
        self._hour = hour
        self._day = day
        self._month = month
        self._weekday = weekday
        self._months = tuple(sorted(month.values))
        self._times = tuple(sorted(
            hour_value * 60 + minute_value
            for hour_value in hour.values
            for minute_value in minute.values
        ))

    def _matches_day(self, day: int, weekday: int, last_day: int) -> bool:
        day_match = (
            day in self._day.values
            or (self._day.last_day and day == last_day)
        )
        weekday_match = (
            weekday in self._weekday.values
            or (weekday, (day - 1) // 7 + 1)
            in self._weekday.nth_weekdays
        )

        if not self._day.unrestricted and not self._weekday.unrestricted:
            return day_match or weekday_match
        return day_match and weekday_match

    def matches(self, dt: datetime) -> bool:
        if dt.second != 0 or dt.microsecond != 0:
            return False
        if (
            dt.minute not in self._minute.values
            or dt.hour not in self._hour.values
            or dt.month not in self._month.values
        ):
            return False

        return self._matches_day(
            dt.day,
            (dt.weekday() + 1) % 7,
            monthrange(dt.year, dt.month)[1],
        )

    def next_after(self, dt: datetime) -> datetime | None:
        final_year = min(dt.year + 8, 9999)
        current_minute = dt.hour * 60 + dt.minute

        for year in range(dt.year, final_year + 1):
            for month in self._months:
                if year == dt.year and month < dt.month:
                    continue

                first_weekday, last_day = monthrange(year, month)
                same_month = year == dt.year and month == dt.month
                first_day = dt.day if same_month else 1

                for day in range(first_day, last_day + 1):
                    weekday = (first_weekday + day) % 7
                    if not self._matches_day(day, weekday, last_day):
                        continue

                    if same_month and day == dt.day:
                        position = bisect_right(self._times, current_minute)
                    else:
                        position = 0

                    if position < len(self._times):
                        hour, minute = divmod(self._times[position], 60)
                        return datetime(year, month, day, hour, minute)

        return None

    def prev_before(self, dt: datetime) -> datetime | None:
        final_year = max(dt.year - 8, 1)
        current_minute = dt.hour * 60 + dt.minute

        for year in range(dt.year, final_year - 1, -1):
            for month in reversed(self._months):
                if year == dt.year and month > dt.month:
                    continue

                first_weekday, last_day = monthrange(year, month)
                same_month = year == dt.year and month == dt.month
                first_day = dt.day if same_month else last_day

                for day in range(first_day, 0, -1):
                    weekday = (first_weekday + day) % 7
                    if not self._matches_day(day, weekday, last_day):
                        continue

                    if same_month and day == dt.day:
                        if dt.second != 0 or dt.microsecond != 0:
                            position = (
                                bisect_right(self._times, current_minute) - 1
                            )
                        else:
                            position = (
                                bisect_left(self._times, current_minute) - 1
                            )
                    else:
                        position = len(self._times) - 1

                    if position >= 0:
                        hour, minute = divmod(self._times[position], 60)
                        return datetime(year, month, day, hour, minute)

        return None

    def iter_after(self, dt: datetime, count: int) -> list[datetime]:
        if count < 0:
            raise ValueError("count は 0 以上でなければなりません")

        result: list[datetime] = []
        current = dt
        for _ in range(count):
            following = self.next_after(current)
            if following is None:
                break
            result.append(following)
            current = following
        return result


def parse(expr: str) -> CronSchedule:
    """cron 式を解析して CronSchedule を返す。不正なら CronError。"""
    if not isinstance(expr, str):
        raise CronError("cron 式は文字列でなければなりません")

    text = expr.strip(" \t")
    if not text:
        raise CronError("cron 式が空です")

    if text.startswith("@"):
        expanded = _MACROS.get(text.lower()) if text.isascii() else None
        if expanded is None:
            raise CronError(f"不正なマクロ: {text!r}")
        text = expanded

    fields = re.split(r"[ \t]+", text)
    if len(fields) != 5:
        raise CronError("cron 式にはちょうど 5 個のフィールドが必要です")

    parsed = [
        _parse_field(field, index)
        for index, field in enumerate(fields)
    ]
    return CronSchedule(*parsed)
=== END ===