"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

from datetime import datetime

__all__ = ["CronError", "CronSchedule", "parse"]


class CronError(ValueError):
    """cron 式が不正なときに送出する。"""


class CronSchedule:
    """解析済みの cron 式。parse() で生成する。"""

    def matches(self, dt: datetime) -> bool:
        raise NotImplementedError

    def next_after(self, dt: datetime) -> datetime | None:
        raise NotImplementedError

    def prev_before(self, dt: datetime) -> datetime | None:
        raise NotImplementedError

    def iter_after(self, dt: datetime, count: int) -> list[datetime]:
        raise NotImplementedError


def parse(expr: str) -> CronSchedule:
    """cron 式を解析して CronSchedule を返す。不正なら CronError。"""
    raise NotImplementedError
