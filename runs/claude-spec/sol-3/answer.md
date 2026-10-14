=== FILE: cronexpr.py ===
"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

from bisect import bisect_left, bisect_right
from calendar import monthrange
from datetime import date, datetime, timedelta

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


def _bounded_integer(text: str, minimum: int, maximum: int) -> int:
    if not _is_ascii_digits(text):
        raise CronError(f"不正な数値です: {text!r}")

    normalized = text.lstrip("0") or "0"
    maximum_text = str(maximum)
    if (
        len(normalized) > len(maximum_text)
        or (
            len(normalized) == len(maximum_text)
            and normalized > maximum_text
        )
    ):
        raise CronError(f"値が範囲外です: {text!r}")

    value = int(normalized)
    if value < minimum:
        raise CronError(f"値が範囲外です: {text!r}")
    return value


def _parse_step(text: str, maximum_useful: int) -> int:
    if not _is_ascii_digits(text):
        raise CronError(f"不正なステップです: {text!r}")

    normalized = text.lstrip("0")
    if not normalized:
        raise CronError("ステップには 1 以上を指定してください")

    limit_text = str(maximum_useful)
    if (
        len(normalized) > len(limit_text)
        or (
            len(normalized) == len(limit_text)
            and normalized > limit_text
        )
    ):
        return maximum_useful + 1
    return int(normalized)


def _parse_value(
    text: str,
    minimum: int,
    maximum: int,
    names: dict[str, int] | None,
) -> int:
    if _is_ascii_digits(text):
        return _bounded_integer(text, minimum, maximum)

    if names is not None:
        value = names.get(text.upper())
        if value is not None:
            return value

    raise CronError(f"不正な値です: {text!r}")


def _parse_field(
    text: str,
    minimum: int,
    maximum: int,
    star_maximum: int,
    names: dict[str, int] | None = None,
    *,
    allow_last: bool = False,
    allow_nth: bool = False,
) -> tuple[frozenset[int], bool, frozenset[tuple[int, int]]]:
    items = text.split(",")
    if any(item == "" for item in items):
        raise CronError("空の項目があります")

    values: set[int] = set()
    has_last = False
    nth_weekdays: set[tuple[int, int]] = set()

    for item in items:
        if allow_last and item.upper() == "L":
            has_last = True
            continue

        if allow_nth and "#" in item:
            if item.count("#") != 1:
                raise CronError(f"不正な # 指定です: {item!r}")

            weekday_text, occurrence_text = item.split("#")
            weekday = _parse_value(
                weekday_text, minimum, maximum, names
            )
            occurrence = _bounded_integer(occurrence_text, 1, 5)
            nth_weekdays.add((weekday % 7, occurrence))
            continue

        if item.count("/") > 1:
            raise CronError(f"不正なステップ指定です: {item!r}")

        if "/" in item:
            base, step_text = item.split("/")
            step = _parse_step(step_text, maximum + 1)
        else:
            base = item
            step = 1

        if base == "*":
            start = minimum
            end = star_maximum
        elif "-" in base:
            if base.count("-") != 1:
                raise CronError(f"不正な範囲です: {item!r}")
            start_text, end_text = base.split("-")
            start = _parse_value(start_text, minimum, maximum, names)
            end = _parse_value(end_text, minimum, maximum, names)
            if start > end:
                raise CronError(f"範囲の開始値が終了値を超えています: {item!r}")
        else:
            start = _parse_value(base, minimum, maximum, names)
            if "/" in item:
                end = star_maximum
                if start > end:
                    raise CronError(f"ステップ指定の開始値が範囲外です: {item!r}")
            else:
                end = start

        for value in range(start, end + 1, step):
            values.add(value % 7 if allow_nth else value)

    return frozenset(values), has_last, frozenset(nth_weekdays)


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
        "_time_minutes",
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
        self._time_minutes = tuple(
            hour * 60 + minute
            for hour in sorted(hours)
            for minute in sorted(minutes)
        )

    @staticmethod
    def _cron_weekday(value: date | datetime) -> int:
        return (value.weekday() + 1) % 7

    def _day_matches(self, value: date | datetime) -> bool:
        last_day = monthrange(value.year, value.month)[1]
        day_match = value.day in self._days or (
            self._last_day and value.day == last_day
        )

        weekday = self._cron_weekday(value)
        occurrence = (value.day - 1) // 7 + 1
        weekday_match = weekday in self._weekdays or (
            weekday, occurrence
        ) in self._nth_weekdays

        if not self._day_unrestricted and not self._weekday_unrestricted:
            return day_match or weekday_match
        return day_match and weekday_match

    def matches(self, dt: datetime) -> bool:
        if dt.second != 0 or dt.microsecond != 0:
            return False
        if dt.minute not in self._minutes:
            return False
        if dt.hour not in self._hours:
            return False
        if dt.month not in self._months:
            return False
        return self._day_matches(dt)

    def next_after(self, dt: datetime) -> datetime | None:
        limit_year = min(dt.year + 8, 9999)

        try:
            start = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        except OverflowError:
            return None

        current_ordinal = start.date().toordinal()
        final_ordinal = date(limit_year, 12, 31).toordinal()

        while current_ordinal <= final_ordinal:
            current_date = date.fromordinal(current_ordinal)

            if (
                current_date.month in self._months
                and self._day_matches(current_date)
            ):
                if current_ordinal == start.date().toordinal():
                    threshold = start.hour * 60 + start.minute
                    index = bisect_left(self._time_minutes, threshold)
                else:
                    index = 0

                if index < len(self._time_minutes):
                    time_value = self._time_minutes[index]
                    return datetime(
                        current_date.year,
                        current_date.month,
                        current_date.day,
                        time_value // 60,
                        time_value % 60,
                    )

            current_ordinal += 1

        return None

    def prev_before(self, dt: datetime) -> datetime | None:
        limit_year = max(dt.year - 8, 1)
        base = dt.replace(second=0, microsecond=0)

        if dt.second != 0 or dt.microsecond != 0:
            start = base
        else:
            try:
                start = base - timedelta(minutes=1)
            except OverflowError:
                return None

        current_ordinal = start.date().toordinal()
        first_ordinal = date(limit_year, 1, 1).toordinal()

        while current_ordinal >= first_ordinal:
            current_date = date.fromordinal(current_ordinal)

            if (
                current_date.month in self._months
                and self._day_matches(current_date)
            ):
                if current_ordinal == start.date().toordinal():
                    threshold = start.hour * 60 + start.minute
                    index = bisect_right(self._time_minutes, threshold) - 1
                else:
                    index = len(self._time_minutes) - 1

                if index >= 0:
                    time_value = self._time_minutes[index]
                    return datetime(
                        current_date.year,
                        current_date.month,
                        current_date.day,
                        time_value // 60,
                        time_value % 60,
                    )

            current_ordinal -= 1

        return None

    def iter_after(self, dt: datetime, count: int) -> list[datetime]:
        if count < 0:
            raise ValueError("count は 0 以上でなければなりません")

        results: list[datetime] = []
        current = dt

        for _ in range(count):
            next_value = self.next_after(current)
            if next_value is None:
                break
            results.append(next_value)
            current = next_value

        return results


def parse(expr: str) -> CronSchedule:
    """cron 式を解析して CronSchedule を返す。不正なら CronError。"""
    if not isinstance(expr, str):
        raise CronError("cron 式は文字列でなければなりません")

    expression = expr.strip(" \t")
    if not expression:
        raise CronError("cron 式が空です")

    if expression.startswith("@"):
        expanded = _MACROS.get(expression.lower())
        if expanded is None:
            raise CronError(f"不正なマクロです: {expression!r}")
        expression = expanded

    fields = []
    start = 0
    for index, char in enumerate(expression):
        if char in " \t":
            if start != index:
                fields.append(expression[start:index])
            start = index + 1
        elif start < index and expression[start:index].strip(" \t") == "":
            start = index
    if start < len(expression):
        fields.append(expression[start:])

    if len(fields) != 5:
        raise CronError("cron 式にはちょうど 5 個のフィールドが必要です")

    minute_text, hour_text, day_text, month_text, weekday_text = fields

    minutes, _, _ = _parse_field(minute_text, 0, 59, 59)
    hours, _, _ = _parse_field(hour_text, 0, 23, 23)
    days, last_day, _ = _parse_field(
        day_text, 1, 31, 31, allow_last=True
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
        allow_nth=True,
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