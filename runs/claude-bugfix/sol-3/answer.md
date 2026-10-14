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
    r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}"
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
        if self.free_minutes < 0:
            raise ValueError("free_minutes must be >= 0")
        if (
            type(self.day_start) is not int
            or type(self.night_start) is not int
            or not (0 <= self.day_start < self.night_start <= 24)
        ):
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
    if _TIME_PATTERN.fullmatch(stripped) is None:
        raise ValueError("invalid time format")
    return datetime.strptime(stripped, TIME_FORMAT)


def format_time(t: datetime) -> str:
    return t.strftime(TIME_FORMAT)


def band_of(t: datetime, rule: Rule) -> str:
    """時刻tが属する時間帯(DAY/NIGHT)を返す。"""
    if rule.day_start <= t.hour < rule.night_start:
        return DAY
    return NIGHT


def _transition_hours(rule: Rule) -> Tuple[int, ...]:
    if rule.day_start == 0:
        if rule.night_start == 24:
            return ()
        return 0, rule.night_start
    if rule.night_start == 24:
        return 0, rule.day_start
    return rule.day_start, rule.night_start


def split_segments(
    start: datetime, end: datetime, rule: Rule
) -> List[Tuple[datetime, datetime, str]]:
    """[start, end)を時間帯が変わる時刻で区切った区間の一覧を返す。"""
    if end < start:
        raise ValueError("end is before start")
    if start == end:
        return []

    transition_hours = _transition_hours(rule)
    if not transition_hours:
        return [(start, end, band_of(start, rule))]

    boundaries = []
    current_date = start.date()
    end_date = end.date()

    while True:
        for hour in transition_hours:
            boundary = datetime(
                current_date.year,
                current_date.month,
                current_date.day,
                hour,
            )
            if start < boundary < end:
                boundaries.append(boundary)

        if current_date == end_date:
            break
        current_date += timedelta(days=1)

    segments = []
    current = start
    for boundary in boundaries:
        segments.append((current, boundary, band_of(current, rule)))
        current = boundary
    segments.append((current, end, band_of(current, rule)))
    return segments


def _units(minutes: int, unit: int) -> int:
    return (minutes + unit - 1) // unit


def block_fee(start: datetime, end: datetime, rule: Rule) -> int:
    """1ブロック分の料金（最大料金適用後）を返す。"""
    total = 0
    for segment_start, segment_end, kind in split_segments(start, end, rule):
        minutes = (segment_end - segment_start) // timedelta(minutes=1)
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

    minutes = (exit - entry) // timedelta(minutes=1)
    if minutes <= rule.free_minutes:
        return 0

    total = 0
    current = entry
    block_length = timedelta(hours=24)

    while current < exit:
        if exit - current <= block_length:
            next_boundary = exit
        else:
            next_boundary = current + block_length
        total += block_fee(current, next_boundary, rule)
        current = next_boundary

    return total


def format_yen(amount: int) -> str:
    """金額を"¥1,234"の形に整形する。"""
    if amount < 0:
        raise ValueError("amount must be >= 0")
    return f"¥{amount:,}"


def format_duration(delta: timedelta) -> str:
    """経過時間を"X時間Y分"の形に整形する。"""
    total_minutes = delta // timedelta(minutes=1)
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
        totals[key] = count + 1, total + fee

    return [(key, count, total) for key, (count, total) in sorted(totals.items())]
=== END ===