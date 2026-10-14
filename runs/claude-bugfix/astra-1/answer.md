=== FILE: parking.py ===
"""駐車場の利用料金を計算するモジュール。

昼間帯・夜間帯で単価の異なる時間料金を、入庫から 24 時間ごとのブロックに
分けて計算し、ブロックごとに最大料金を適用する。
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Tuple

DAY = "day"
NIGHT = "night"

TIME_FORMAT = "%Y-%m-%d %H:%M"


@dataclass(frozen=True)
class Rule:
    """料金ルール。時刻は「時」(0〜24) で、時間は分で指定する。"""

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
            not isinstance(self.day_start, int)
            or not isinstance(self.night_start, int)
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
    """YYYY-MM-DD HH:MM 形式の文字列を datetime に変換する。"""
    text = text.strip()
    if re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}", text
    ) is None:
        raise ValueError("invalid datetime format")
    return datetime.strptime(text, TIME_FORMAT)


def format_time(t: datetime) -> str:
    return (
        f"{t.year:04d}-{t.month:02d}-{t.day:02d} "
        f"{t.hour:02d}:{t.minute:02d}"
    )


def band_of(t: datetime, rule: Rule) -> str:
    """時刻 t が属する時間帯 (DAY / NIGHT) を返す。"""
    if rule.day_start <= t.hour < rule.night_start:
        return DAY
    return NIGHT


def split_segments(
    start: datetime, end: datetime, rule: Rule
) -> List[Tuple[datetime, datetime, str]]:
    """[start, end) を時間帯が変わる時刻で区切った区間の一覧を返す。"""
    if end < start:
        raise ValueError("end is before start")
    if start == end:
        return []
    if rule.day_start == 0 and rule.night_start == 24:
        return [(start, end, DAY)]

    segments = []
    cur = start
    while cur < end:
        kind = band_of(cur, rule)
        minute_of_day = cur.hour * 60 + cur.minute
        if kind == DAY:
            until_boundary = rule.night_start * 60 - minute_of_day
        elif cur.hour < rule.day_start:
            until_boundary = rule.day_start * 60 - minute_of_day
        else:
            until_boundary = 24 * 60 - minute_of_day + rule.day_start * 60

        delta = timedelta(minutes=until_boundary)
        nxt = end if end - cur <= delta else cur + delta
        segments.append((cur, nxt, kind))
        cur = nxt
    return segments


def _units(minutes: int, unit: int) -> int:
    return (minutes + unit - 1) // unit


def block_fee(start: datetime, end: datetime, rule: Rule) -> int:
    """1 ブロック分の料金（最大料金適用後）を返す。"""
    total = 0
    for s, e, kind in split_segments(start, end, rule):
        minutes = (e - s) // timedelta(minutes=1)
        if kind == DAY:
            total += _units(minutes, rule.day_unit) * rule.day_price
        else:
            total += _units(minutes, rule.night_unit) * rule.night_price
    if rule.daily_max is None:
        return total
    return min(total, rule.daily_max)


def calc_fee(entry: datetime, exit: datetime, rule: Optional[Rule] = None) -> int:
    """入庫時刻 entry から出庫時刻 exit までの料金を返す。"""
    if rule is None:
        rule = Rule()
    if exit < entry:
        raise ValueError("exit is before entry")
    minutes = (exit - entry) // timedelta(minutes=1)
    if minutes <= rule.free_minutes:
        return 0

    total = 0
    cur = entry
    block_duration = timedelta(hours=24)
    while cur < exit:
        nxt = exit if exit - cur <= block_duration else cur + block_duration
        total += block_fee(cur, nxt, rule)
        cur = nxt
    return total


def format_yen(amount: int) -> str:
    """金額を "¥1,234" の形に整形する。"""
    if amount < 0:
        raise ValueError("amount must be >= 0")
    return f"¥{amount:,}"


def format_duration(delta: timedelta) -> str:
    """経過時間を "X時間Y分" の形に整形する。"""
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
    """利用記録を出庫日ごとに集計し、(日付, 件数, 売上合計) を返す。"""
    totals = {}
    for entry_text, exit_text in records:
        entry = parse_time(entry_text)
        exit_ = parse_time(exit_text)
        fee = calc_fee(entry, exit_, rule)
        key = exit_.date().isoformat()
        count, total = totals.get(key, (0, 0))
        totals[key] = (count + 1, total + fee)
    return [(k, c, t) for k, (c, t) in sorted(totals.items())]
=== END ===