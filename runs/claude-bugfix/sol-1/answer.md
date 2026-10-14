=== FILE: parking.py ===
"""駐車場の利用料金を計算するモジュール。

昼間帯・夜間帯で単価の異なる時間料金を、入庫から24時間ごとのブロックに
分けて計算し、ブロックごとに最大料金を適用する。
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Tuple

DAY = "day"
NIGHT = "night"

TIME_FORMAT = "%Y-%m-%d %H:%M"
_TIME_PATTERN = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2}) "
    r"([0-9]{2}):([0-9]{2})"
)


@dataclass(frozen=True)
class Rule:
    """料金ルール。時刻は「時」(0〜24)で、時間は分で指定する。"""

    free_minutes: int = 15
    day_start: int = 8
    night_start: int = 22
    day_unit: int = 30
    day_price: int = 200
    night_unit: int = 60
    night_price: int = 100
    daily_max: Optional[int] = 1500

    def __post_init__(self) -> None:
        integer_fields = (
            self.free_minutes,
            self.day_start,
            self.night_start,
            self.day_unit,
            self.day_price,
            self.night_unit,
            self.night_price,
        )
        if any(type(value) is not int for value in integer_fields):
            raise ValueError("rule values must be integers")
        if self.daily_max is not None and type(self.daily_max) is not int:
            raise ValueError("daily_max must be an integer or None")
        if self.free_minutes < 0:
            raise ValueError("free_minutes must be >= 0")
        if not (0 <= self.day_start < self.night_start <= 24):
            raise ValueError("invalid band hours")
        if self.day_unit <= 0 or self.night_unit <= 0:
            raise ValueError("unit must be positive")
        if self.day_price < 0 or self.night_price < 0:
            raise ValueError("price must be >= 0")
        if self.daily_max is not None and self.daily_max <= 0:
            raise ValueError("daily_max must be positive")


def parse_time(text: str) -> datetime:
    """"YYYY-MM-DD HH:MM"形式の文字列をdatetimeに変換する。"""
    stripped = text.strip()
    match = _TIME_PATTERN.fullmatch(stripped)
    if match is None:
        raise ValueError("invalid time format")
    try:
        return datetime(*(int(value) for value in match.groups()))
    except ValueError:
        raise ValueError("invalid date or time") from None


def format_time(t: datetime) -> str:
    return t.strftime(TIME_FORMAT)


def band_of(t: datetime, rule: Rule) -> str:
    """時刻tが属する時間帯(DAY/NIGHT)を返す。"""
    if rule.day_start <= t.hour < rule.night_start:
        return DAY
    return NIGHT


def _next_boundary(t: datetime, kind: str, rule: Rule) -> datetime:
    if kind == DAY:
        if rule.night_start == 24:
            return datetime.combine(t.date(), datetime.min.time()) + timedelta(days=1)
        boundary = t.replace(
            hour=rule.night_start, minute=0, second=0, microsecond=0
        )
    else:
        if rule.day_start == 0:
            return datetime.combine(t.date(), datetime.min.time()) + timedelta(days=1)
        boundary = t.replace(
            hour=rule.day_start, minute=0, second=0, microsecond=0
        )

    if boundary <= t:
        boundary += timedelta(days=1)
    return boundary


def split_segments(
    start: datetime, end: datetime, rule: Rule
) -> List[Tuple[datetime, datetime, str]]:
    """[start, end)を時間帯が変わる時刻で区切った区間の一覧を返す。"""
    if end < start:
        raise ValueError("end is before start")
    if start == end:
        return []

    if rule.day_start == 0 and rule.night_start == 24:
        return [(start, end, DAY)]

    segments = []
    current = start
    while current < end:
        kind = band_of(current, rule)
        next_boundary = _next_boundary(current, kind, rule)
        segment_end = min(next_boundary, end)
        segments.append((current, segment_end, kind))
        current = segment_end
    return segments


def _units(minutes: int, unit: int) -> int:
    return (minutes + unit - 1) // unit


def block_fee(start: datetime, end: datetime, rule: Rule) -> int:
    """1ブロック分の料金（最大料金適用後）を返す。"""
    total = 0
    for segment_start, segment_end, kind in split_segments(start, end, rule):
        minutes = int(
            (segment_end - segment_start).total_seconds()
            // timedelta(minutes=1).total_seconds()
        )
        if kind == DAY:
            total += _units(minutes, rule.day_unit) * rule.day_price
        else:
            total += _units(minutes, rule.night_unit) * rule.night_price

    if rule.daily_max is None:
        return total
    return min(total, rule.daily_max)


def calc_fee(entry: datetime, exit: datetime, rule: Optional[Rule] = None) -> int:
    """入庫時刻entryから出庫時刻exitまでの料金を返す。"""
    if rule is None:
        rule = Rule()
    if exit < entry:
        raise ValueError("exit is before entry")

    minutes = int(
        (exit - entry).total_seconds()
        // timedelta(minutes=1).total_seconds()
    )
    if minutes <= rule.free_minutes:
        return 0

    total = 0
    current = entry
    while current < exit:
        block_end = min(current + timedelta(hours=24), exit)
        total += block_fee(current, block_end, rule)
        current = block_end
    return total


def format_yen(amount: int) -> str:
    """金額を"¥1,234"の形に整形する。"""
    if amount < 0:
        raise ValueError("amount must be >= 0")
    return f"¥{amount:,}"


def format_duration(delta: timedelta) -> str:
    """経過時間を"X時間Y分"の形に整形する。"""
    total_minutes = int(
        delta.total_seconds() // timedelta(minutes=1).total_seconds()
    )
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}時間{minutes}分"


def make_receipt(entry_text: str, exit_text: str, rule: Optional[Rule] = None) -> str:
    """領収書の本文を作る。"""
    entry = parse_time(entry_text)
    exit_ = parse_time(exit_text)
    fee = calc_fee(entry, exit_, rule)
    lines = [
        f"入庫 {format_time(entry)}",
        f"出庫 {format_time(exit_)}",
        f"駐車時間 {format_duration(exit_ - entry)}",
        f"料金 {format_yen(fee)}",
    ]
    return "\n".join(lines)


def daily_summary(
    records: Iterable[Tuple[str, str]], rule: Optional[Rule] = None
) -> List[Tuple[str, int, int]]:
    """利用記録を出庫日ごとに集計し、(日付, 件数, 売上合計)を返す。"""
    totals = {}
    for entry_text, exit_text in records:
        entry = parse_time(entry_text)
        exit_ = parse_time(exit_text)
        fee = calc_fee(entry, exit_, rule)
        key = exit_.date().isoformat()
        count, total = totals.get(key, (0, 0))
        totals[key] = (count + 1, total + fee)

    return [(key, count, total) for key, (count, total) in sorted(totals.items())]
=== END ===