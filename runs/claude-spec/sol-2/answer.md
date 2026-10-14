=== FILE: cronexpr.py ===
"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

from bisect import bisect_left, bisect_right
from calendar import monthrange
from datetime import datetime
import re

__all__ = ["CronError", "CronSchedule", "parse"]


class CronError(ValueError):
    """cron 式が不正なときに送出する。"""


_ASCII_INTEGER = re.compile(r"[0-9]+")
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


def _integer(text: str, description: str) -> int:
    if _ASCII_INTEGER.fullmatch(text) is None:
        raise CronError(f"{description}が不正です")
    try:
        return int(text)
    except ValueError:
        raise CronError(f"{description}が不正です") from None


def _value(
    text: str,
    minimum: int,
    maximum: int,
    names: dict[str, int] | None,
) -> int:
    if names is not None:
        named_value = names.get(text.upper())
        if named_value is not None:
            return named_value

    value = _integer(text, "値")
    if not minimum <= value <= maximum:
        raise CronError("値がフィールドの範囲外です")
    return value


def _ordinary_item(
    item: str,
    minimum: int,
    maximum: int,
    star_minimum: int,
    star_maximum: int,
    names: dict[str, int] | None,
) -> set[int]:
    if item.count("/") > 1:
        raise CronError("'/' が多すぎます")

    if "/" in item:
        base, step_text = item.split("/", 1)
        if not base or not step_text:
            raise CronError("ステップ指定が不正です")
        step = _integer(step_text, "ステップ")
        if step < 1:
            raise CronError("ステップは 1 以上でなければなりません")
    else:
        base = item
        step = None

    if base == "*":
        start = star_minimum
        end = star_maximum
    elif "-" in base:
        if base.count("-") != 1:
            raise CronError("範囲指定が不正です")
        start_text, end_text = base.split("-", 1)
        if not start_text or not end_text:
            raise CronError("範囲指定が不正です")
        start = _value(start_text, minimum, maximum, names)
        end = _value(end_text, minimum, maximum, names)
        if start > end:
            raise CronError("範囲の開始値が終了値を超えています")
    else:
        start = _value(base, minimum, maximum, names)
        if step is None:
            return {start}
        end = star_maximum
        if start > end:
            raise CronError("ステップ指定の開始値が範囲外です")

    if step is None:
        step = 1
    return set(range(start, end + 1, step))


def _parse_field(
    text: str,
    *,
    minimum: int,
    maximum: int,
    star_minimum: int,
    star_maximum: int,
    names: dict[str, int] | None = None,
    kind: str,
) -> tuple[set[int], bool, set[tuple[int, int]]]:
    items = text.split(",")
    if any(item == "" for item in items):
        raise CronError("空の項目があります")

    values: set[int] = set()
    has_last_day = False
    nth_weekdays: set[tuple[int, int]] = set()

    for item in items:
        if "#" in item:
            if kind != "weekday" or item.count("#") != 1:
                raise CronError("'#' の指定が不正です")

            weekday_text, occurrence_text = item.split("#", 1)
            if not weekday_text or not occurrence_text:
                raise CronError("'#' の指定が不正です")

            weekday = _value(
                weekday_text,
                minimum,
                maximum,
                names,
            )
            occurrence = _integer(occurrence_text, "曜日の回数")
            if not 1 <= occurrence <= 5:
                raise CronError("曜日の回数は 1 から 5 でなければなりません")

            if weekday == 7:
                weekday = 0
            nth_weekdays.add((weekday, occurrence))
            continue

        if kind == "day" and item.lower() == "l":
            has_last_day = True
            continue

        values.update(
            _ordinary_item(
                item,
                minimum,
                maximum,
                star_minimum,
                star_maximum,
                names,
            )
        )

    if kind == "weekday":
        values = {0 if value == 7 else value for value in values}

    return values, has_last_day, nth_weekdays


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
        "_day_restricted",
        "_weekday_restricted",
        "_times",
        "_ordered_months",
    )

    def __init__(
        self,
        minutes: set[int],
        hours: set[int],
        days: set[int],
        months: set[int],
        weekdays: set[int],
        last_day: bool,
        nth_weekdays: set[tuple[int, int]],
        day_restricted: bool,
        weekday_restricted: bool,
    ) -> None:
        self._minutes = frozenset(minutes)
        self._hours = frozenset(hours)
        self._days = frozenset(days)
        self._months = frozenset(months)
        self._weekdays = frozenset(weekdays)
        self._last_day = last_day
        self._nth_weekdays = frozenset(nth_weekdays)
        self._day_restricted = day_restricted
        self._weekday_restricted = weekday_restricted
        self._ordered_months = tuple(sorted(months))
        self._times = tuple(
            hour * 60 + minute
            for hour in sorted(hours)
            for minute in sorted(minutes)
        )

    def _day_matches(
        self,
        year: int,
        month: int,
        day: int,
        last_day: int | None = None,
    ) -> bool:
        if last_day is None:
            last_day = monthrange(year, month)[1]

        day_matches = day in self._days or (
            self._last_day and day == last_day
        )

        cron_weekday = (datetime(year, month, day).weekday() + 1) % 7
        occurrence = (day - 1) // 7 + 1
        weekday_matches = (
            cron_weekday in self._weekdays
            or (cron_weekday, occurrence) in self._nth_weekdays
        )

        if self._day_restricted and self._weekday_restricted:
            return day_matches or weekday_matches
        return day_matches and weekday_matches

    def matches(self, dt: datetime) -> bool:
        if dt.second != 0 or dt.microsecond != 0:
            return False
        if dt.minute not in self._minutes:
            return False
        if dt.hour not in self._hours:
            return False
        if dt.month not in self._months:
            return False
        return self._day_matches(dt.year, dt.month, dt.day)

    def next_after(self, dt: datetime) -> datetime | None:
        final_year = min(9999, dt.year + 8)

        for year in range(dt.year, final_year + 1):
            for month in self._ordered_months:
                if year == dt.year and month < dt.month:
                    continue

                last_day = monthrange(year, month)[1]
                if year == dt.year and month == dt.month:
                    first_day = dt.day
                else:
                    first_day = 1

                for day in range(first_day, last_day + 1):
                    if not self._day_matches(year, month, day, last_day):
                        continue

                    if (
                        year == dt.year
                        and month == dt.month
                        and day == dt.day
                    ):
                        current_minute = dt.hour * 60 + dt.minute
                        index = bisect_right(self._times, current_minute)
                    else:
                        index = 0

                    if index < len(self._times):
                        minute_of_day = self._times[index]
                        hour, minute = divmod(minute_of_day, 60)
                        return datetime(year, month, day, hour, minute)

        return None

    def prev_before(self, dt: datetime) -> datetime | None:
        first_year = max(1, dt.year - 8)

        for year in range(dt.year, first_year - 1, -1):
            for month in reversed(self._ordered_months):
                if year == dt.year and month > dt.month:
                    continue

                last_day = monthrange(year, month)[1]
                if year == dt.year and month == dt.month:
                    final_day = dt.day
                else:
                    final_day = last_day

                for day in range(final_day, 0, -1):
                    if not self._day_matches(year, month, day, last_day):
                        continue

                    if (
                        year == dt.year
                        and month == dt.month
                        and day == dt.day
                    ):
                        current_minute = dt.hour * 60 + dt.minute
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
        expanded = _MACROS.get(text.lower())
        if expanded is None:
            raise CronError("不正なマクロです")
        text = expanded

    fields = re.split(r"[ \t]+", text)
    if len(fields) != 5:
        raise CronError("cron 式は 5 フィールドでなければなりません")

    minute_text, hour_text, day_text, month_text, weekday_text = fields

    minutes, _, _ = _parse_field(
        minute_text,
        minimum=0,
        maximum=59,
        star_minimum=0,
        star_maximum=59,
        kind="minute",
    )
    hours, _, _ = _parse_field(
        hour_text,
        minimum=0,
        maximum=23,
        star_minimum=0,
        star_maximum=23,
        kind="hour",
    )
    days, last_day, _ = _parse_field(
        day_text,
        minimum=1,
        maximum=31,
        star_minimum=1,
        star_maximum=31,
        kind="day",
    )
    months, _, _ = _parse_field(
        month_text,
        minimum=1,
        maximum=12,
        star_minimum=1,
        star_maximum=12,
        names=_MONTH_NAMES,
        kind="month",
    )
    weekdays, _, nth_weekdays = _parse_field(
        weekday_text,
        minimum=0,
        maximum=7,
        star_minimum=0,
        star_maximum=6,
        names=_WEEKDAY_NAMES,
        kind="weekday",
    )

    return CronSchedule(
        minutes=minutes,
        hours=hours,
        days=days,
        months=months,
        weekdays=weekdays,
        last_day=last_day,
        nth_weekdays=nth_weekdays,
        day_restricted=day_text != "*",
        weekday_restricted=weekday_text != "*",
    )
=== END ===