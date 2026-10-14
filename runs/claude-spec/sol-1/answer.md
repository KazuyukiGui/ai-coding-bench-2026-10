=== FILE: cronexpr.py ===
"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

from bisect import bisect_left, bisect_right
from calendar import monthrange
from datetime import datetime, date
import re

__all__ = ["CronError", "CronSchedule", "parse"]


class CronError(ValueError):
    """cron 式が不正なときに送出する。"""


_MONTH_NAMES = {
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

_WEEKDAY_NAMES = {
    "SUN": 0,
    "MON": 1,
    "TUE": 2,
    "WED": 3,
    "THU": 4,
    "FRI": 5,
    "SAT": 6,
}

_MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


def _is_ascii_digits(text: str) -> bool:
    return bool(text) and all("0" <= char <= "9" for char in text)


def _parse_bounded_decimal(
    text: str, minimum: int, maximum: int
) -> int:
    if not _is_ascii_digits(text):
        raise CronError("値は ASCII の10進数でなければならない")

    normalized = text.lstrip("0") or "0"
    if len(normalized) > len(str(maximum)):
        raise CronError("値がフィールドの範囲外")

    value = int(normalized)
    if value < minimum or value > maximum:
        raise CronError("値がフィールドの範囲外")
    return value


def _parse_step(text: str) -> int:
    if not _is_ascii_digits(text):
        raise CronError("ステップは ASCII の正の整数でなければならない")

    normalized = text.lstrip("0") or "0"
    if normalized == "0":
        raise CronError("ステップは1以上でなければならない")

    # どのフィールドも幅は最大60未満なので、60以上のステップは
    # すべて同じく開始値だけを生成する。
    if len(normalized) > 2:
        return 60
    return min(int(normalized), 60)


def _parse_value(
    text: str,
    minimum: int,
    maximum: int,
    names: dict[str, int] | None,
) -> int:
    if _is_ascii_digits(text):
        return _parse_bounded_decimal(text, minimum, maximum)

    if (
        names is not None
        and len(text) == 3
        and all(
            ("A" <= char <= "Z") or ("a" <= char <= "z")
            for char in text
        )
    ):
        value = names.get(text.upper())
        if value is not None:
            return value

    raise CronError("不正なフィールド値")


def _parse_field(
    text: str,
    minimum: int,
    maximum: int,
    star_maximum: int,
    names: dict[str, int] | None = None,
    *,
    is_day: bool = False,
    is_weekday: bool = False,
) -> tuple[frozenset[int], bool, frozenset[tuple[int, int]]]:
    values: set[int] = set()
    has_last_day = False
    nth_weekdays: set[tuple[int, int]] = set()

    items = text.split(",")
    if any(item == "" for item in items):
        raise CronError("空の項目は使用できない")

    for item in items:
        if "#" in item:
            if not is_weekday or item.count("#") != 1:
                raise CronError("不正な # 指定")

            weekday_text, ordinal_text = item.split("#")
            weekday = _parse_value(
                weekday_text, minimum, maximum, names
            )
            ordinal = _parse_bounded_decimal(ordinal_text, 1, 5)
            nth_weekdays.add((weekday % 7, ordinal))
            continue

        if item.lower() == "l":
            if not is_day:
                raise CronError("L は日フィールドでのみ使用できる")
            has_last_day = True
            continue

        if "l" in item.lower():
            raise CronError("L は単独の項目でなければならない")

        if item.count("/") > 1:
            raise CronError("不正なステップ指定")

        if "/" in item:
            base, step_text = item.split("/")
            step = _parse_step(step_text)
        else:
            base = item
            step = 1

        if base == "*":
            start = minimum
            end = star_maximum
        elif "-" in base:
            if base.count("-") != 1:
                raise CronError("不正な範囲指定")
            start_text, end_text = base.split("-")
            start = _parse_value(
                start_text, minimum, maximum, names
            )
            end = _parse_value(end_text, minimum, maximum, names)
            if start > end:
                raise CronError("範囲の開始値が終了値より大きい")
        else:
            start = _parse_value(base, minimum, maximum, names)
            if "/" in item:
                if start > star_maximum:
                    raise CronError("ステップ指定の開始値が範囲外")
                end = star_maximum
            else:
                end = start

        for value in range(start, end + 1, step):
            values.add(value % 7 if is_weekday else value)

    return frozenset(values), has_last_day, frozenset(nth_weekdays)


class CronSchedule:
    """解析済みの cron 式。parse() で生成する。"""

    __slots__ = (
        "_minutes",
        "_hours",
        "_days",
        "_months",
        "_weekdays",
        "_last_day",
        "_nth_weekdays",
        "_day_unrestricted",
        "_weekday_unrestricted",
        "_times",
    )

    def __init__(
        self,
        minutes: frozenset[int],
        hours: frozenset[int],
        days: frozenset[int],
        months: frozenset[int],
        weekdays: frozenset[int],
        last_day: bool,
        nth_weekdays: frozenset[tuple[int, int]],
        day_unrestricted: bool,
        weekday_unrestricted: bool,
    ) -> None:
        self._minutes = minutes
        self._hours = hours
        self._days = days
        self._months = months
        self._weekdays = weekdays
        self._last_day = last_day
        self._nth_weekdays = nth_weekdays
        self._day_unrestricted = day_unrestricted
        self._weekday_unrestricted = weekday_unrestricted
        self._times = tuple(
            hour * 60 + minute
            for hour in sorted(hours)
            for minute in sorted(minutes)
        )

    def _date_matches(self, value: date) -> bool:
        if value.month not in self._months:
            return False

        day_matches = value.day in self._days
        if self._last_day:
            day_matches = day_matches or (
                value.day == monthrange(value.year, value.month)[1]
            )

        cron_weekday = (value.weekday() + 1) % 7
        weekday_matches = cron_weekday in self._weekdays
        if not weekday_matches and self._nth_weekdays:
            ordinal = (value.day - 1) // 7 + 1
            weekday_matches = (
                cron_weekday,
                ordinal,
            ) in self._nth_weekdays

        if not self._day_unrestricted and not self._weekday_unrestricted:
            return day_matches or weekday_matches
        return day_matches and weekday_matches

    def matches(self, dt: datetime) -> bool:
        if dt.second != 0 or dt.microsecond != 0:
            return False
        if dt.minute not in self._minutes:
            return False
        if dt.hour not in self._hours:
            return False
        return self._date_matches(dt.date())

    def next_after(self, dt: datetime) -> datetime | None:
        final_year = min(dt.year + 8, 9999)
        final_ordinal = date(final_year, 12, 31).toordinal()
        start_ordinal = dt.date().toordinal()
        current_minute = dt.hour * 60 + dt.minute

        for ordinal in range(start_ordinal, final_ordinal + 1):
            candidate_date = date.fromordinal(ordinal)
            if not self._date_matches(candidate_date):
                continue

            if ordinal == start_ordinal:
                index = bisect_right(self._times, current_minute)
            else:
                index = 0

            if index < len(self._times):
                minute_of_day = self._times[index]
                hour, minute = divmod(minute_of_day, 60)
                return datetime(
                    candidate_date.year,
                    candidate_date.month,
                    candidate_date.day,
                    hour,
                    minute,
                )

        return None

    def prev_before(self, dt: datetime) -> datetime | None:
        first_year = max(dt.year - 8, 1)
        first_ordinal = date(first_year, 1, 1).toordinal()
        start_ordinal = dt.date().toordinal()
        current_minute = dt.hour * 60 + dt.minute

        for ordinal in range(start_ordinal, first_ordinal - 1, -1):
            candidate_date = date.fromordinal(ordinal)
            if not self._date_matches(candidate_date):
                continue

            if ordinal == start_ordinal:
                if dt.second != 0 or dt.microsecond != 0:
                    index = bisect_right(
                        self._times, current_minute
                    ) - 1
                else:
                    index = bisect_left(
                        self._times, current_minute
                    ) - 1
            else:
                index = len(self._times) - 1

            if index >= 0:
                minute_of_day = self._times[index]
                hour, minute = divmod(minute_of_day, 60)
                return datetime(
                    candidate_date.year,
                    candidate_date.month,
                    candidate_date.day,
                    hour,
                    minute,
                )

        return None

    def iter_after(self, dt: datetime, count: int) -> list[datetime]:
        if count < 0:
            raise ValueError("count は0以上でなければならない")

        results: list[datetime] = []
        current = dt
        for _ in range(count):
            following = self.next_after(current)
            if following is None:
                break
            results.append(following)
            current = following
        return results


def parse(expr: str) -> CronSchedule:
    """cron 式を解析して CronSchedule を返す。不正なら CronError。"""
    if not isinstance(expr, str):
        raise CronError("cron 式は文字列でなければならない")

    text = expr.strip(" \t")
    if not text:
        raise CronError("cron 式が空")

    if text.startswith("@"):
        if not all(
            ("A" <= char <= "Z") or ("a" <= char <= "z")
            for char in text[1:]
        ):
            raise CronError("不正なマクロ")
        expanded = _MACROS.get(text.lower())
        if expanded is None:
            raise CronError("不正なマクロ")
        text = expanded

    fields = re.split(r"[ \t]+", text)
    if len(fields) != 5:
        raise CronError("フィールド数は5でなければならない")

    minute_text, hour_text, day_text, month_text, weekday_text = fields

    minutes, _, _ = _parse_field(
        minute_text, 0, 59, 59
    )
    hours, _, _ = _parse_field(
        hour_text, 0, 23, 23
    )
    days, last_day, _ = _parse_field(
        day_text, 1, 31, 31, is_day=True
    )
    months, _, _ = _parse_field(
        month_text, 1, 12, 12, _MONTH_NAMES
    )
    weekdays, _, nth_weekdays = _parse_field(
        weekday_text,
        0,
        7,
        6,
        _WEEKDAY_NAMES,
        is_weekday=True,
    )

    return CronSchedule(
        minutes=minutes,
        hours=hours,
        days=days,
        months=months,
        weekdays=weekdays,
        last_day=last_day,
        nth_weekdays=nth_weekdays,
        day_unrestricted=day_text == "*",
        weekday_unrestricted=weekday_text == "*",
    )
=== END ===