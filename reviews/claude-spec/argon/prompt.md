あなたは、AI のコーディング性能を比べる試験の「審査員」です。別の AI が作った課題を、試験に使う前に点検します。解く側は課題文と添付ファイル（given）だけを読んでファイル全体を書きます。隠し試験（tests）と模範解答（ref）は解く側には見えません。

次の観点で点検し、問題だけを挙げてください。問題が無ければ空の配列を返します。
1. 課題文に書いていない挙動を、隠し試験が問うていないか（エラー文の文言・例外の型・並び順・空白・丸め方など）
2. 課題文の読み方が2通り以上あり、模範解答と違う読み方でも妥当なのに、試験で落ちる所はないか
3. 試験そのものの誤り（模範解答は通るが、課題文に照らすと期待値が違う）
4. 解く側に渡していない情報（given に無い関数名・ファイル名・定数）に試験が頼っていないか
5. 試験が環境に依存していないか（時刻・乱数・ファイルの並び順・ロケール）

答えは JSON だけで返してください（説明・前置き不要）。
{"issues": [{"severity": "high|medium|low", "where": "tests の関数名か課題文の箇所", "problem": "何が問題か", "fix": "課題文をどう直すか、または試験をどう直すか"}]}
severity の目安: high＝正しく解いても落ちる、medium＝妥当な別解が落ちる恐れ、low＝読みにくいが結果は変わらない。

---
=== FILE: given/cronexpr.py ===
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

=== FILE: prompt.md ===
# cron 式の解析と発火時刻の計算

ジョブ実行基盤で使う、5 フィールドの cron 式を解析して発火時刻を計算するモジュール `cronexpr.py` を実装してください。添付の雛形にある公開 API をすべて実装します。Python 3.11、標準ライブラリのみを使います。

## 公開 API

- `class CronError(ValueError)`
  式が不正なときに送出する例外。式の構文・値に関するエラーはすべてこの例外で送出する。
- `parse(expr: str) -> CronSchedule`
  式を解析して `CronSchedule` を返す。不正なら `CronError`。
- `CronSchedule.matches(dt) -> bool`
- `CronSchedule.next_after(dt) -> datetime | None`
- `CronSchedule.prev_before(dt) -> datetime | None`
- `CronSchedule.iter_after(dt, count) -> list[datetime]`

`dt` は常にタイムゾーン情報なし（naive）の `datetime.datetime` で渡されます。返す `datetime` もタイムゾーン情報なしで、秒とマイクロ秒は必ず 0 です。

## 式の全体

- 式の前後にある半角スペース・タブは無視する。
- 残りが `@` で始まる場合はマクロ（後述）として扱う。
- それ以外は、1 個以上の半角スペースまたはタブの並びで区切った **ちょうど 5 個** のフィールドでなければならない。順に「分」「時」「日」「月」「曜日」。フィールド数が 5 でなければ `CronError`。空文字列や空白だけの式も `CronError`。区切りとして認めるのは半角スペースとタブだけで、それ以外の文字（改行など）はフィールドの一部として扱う（結果として不正な値になる）。

### マクロ

大文字小文字を区別しない。次の 6 つ以外（`@reboot`、`@`、`@daily *`、`@ daily` など）は `CronError`。

| マクロ | 等価な式 |
|---|---|
| `@hourly` | `0 * * * *` |
| `@daily` | `0 0 * * *` |
| `@weekly` | `0 0 * * 0` |
| `@monthly` | `0 0 1 * *` |
| `@yearly` | `0 0 1 1 *` |
| `@annually` | `0 0 1 1 *` |

## フィールド

| フィールド | 値の範囲 | `*` が表す範囲 | 名前 |
|---|---|---|---|
| 分 | 0–59 | 0–59 | なし |
| 時 | 0–23 | 0–23 | なし |
| 日 | 1–31 | 1–31 | なし |
| 月 | 1–12 | 1–12 | `JAN`〜`DEC`（1〜12） |
| 曜日 | 0–7 | 0–6 | `SUN`〜`SAT`（0〜6） |

曜日は 0 が日曜、1 が月曜 … 6 が土曜で、**7 も日曜** を表す。

各フィールドは `,` 区切りの項目の並びで、フィールドが表す値の集合は各項目の値の和集合になる。空の項目（`1,,2`、`1,`、`,1` など）は `CronError`。

### 値

- 値は ASCII の数字 `0`〜`9` だけからなる 10 進数（先頭の 0 は可。`05` は 5）。符号・小数点・全角数字などは不可。
- 月と曜日では、上の表の 3 文字の英字名も値として使える（大文字小文字を区別しない）。`MONDAY` や `JANUARY` のような長い名前は不可。名前の無いフィールドに英字名を書くと `CronError`。
- 値がフィールドの範囲外なら `CronError`。

### 項目

次のいずれか。`N`・`M` は上の「値」、`S` は ASCII 数字だけからなる 1 以上の整数（名前は不可）。

| 項目 | 意味 |
|---|---|
| `*` | そのフィールドの「`*` が表す範囲」の全値 |
| `N` | 値 N |
| `N-M` | N 以上 M 以下の全値。N > M なら `CronError`（折り返さない） |
| `*/S` | 「`*` が表す範囲」の下限から S おきの値 |
| `N-M/S` | N から M まで S おきの値（N, N+S, N+2S, … のうち M 以下のもの） |
| `N/S` | `N-X/S` と同じ。X はそのフィールドの「`*` が表す範囲」の上限。N > X なら `CronError` |

- S が 0、空、数字以外なら `CronError`。`/` を 2 つ以上含む項目、`-` の両側のどちらかが値でない項目も `CronError`。
- 例: 分 `5/20` → 5, 25, 45。曜日 `*/2` → 0, 2, 4, 6。曜日 `MON/2` → 1, 3, 5。曜日 `5-7` → 金・土・日。曜日 `0-7/7` → 日曜。月 `jan/5` → 1, 6, 11。
- 曜日フィールドで得た値 7 は 0（日曜）として扱う。

### 日フィールドの `L`

- 日フィールドでは、項目 `L`（大文字小文字を区別しない）を使える。その月の最終日を表す。他の項目と `,` で並べてよい（例: `15,L`）。
- `L` は単独の項目としてのみ有効。`L/2`、`1-L`、`LW` などは `CronError`。日フィールド以外での `L` も `CronError`。

### 曜日フィールドの `#`

- 曜日フィールドでは、項目 `W#K` を使える。その月の第 K の W 曜日（その月の (K−1)×7+1 日 〜 K×7 日にある W 曜日）を表す。
- W は単独の値（数字 0〜7 または曜日名）でなければならない。範囲・`*`・`/` は不可（`1-2#1`、`*/2#1` は `CronError`）。7 は日曜。
- K は ASCII 数字だけからなる 1〜5 の整数。それ以外（`MON#0`、`MON#6`、`MON#`、`#1`、`MON#1#1` など）は `CronError`。
- その月に第 K の W 曜日が無ければ、その月はこの項目に一致しない。
- 曜日フィールド以外での `#` は `CronError`。
- その他、ここに書かれていない記法（`?` など）はすべて `CronError`。

## 一致の判定

日時 t がスケジュールに一致するのは、次をすべて満たすとき。

1. t の秒とマイクロ秒が 0
2. 分が分フィールドの集合に含まれる
3. 時が時フィールドの集合に含まれる
4. 月が月フィールドの集合に含まれる
5. 「日の条件」を満たす

「日の条件」:

- 日一致 = t の日が日フィールドの集合に含まれる、または `L` が指定されていて t がその月の最終日
- 曜日一致 = t の曜日が曜日フィールドの集合に含まれる、または t が `#` で指定したいずれかの第 K 曜日に当たる
- フィールド文字列が **ちょうど `*` の 1 文字** であるものを「制限なし」、それ以外（`*/1`、`*,1`、`1-31` なども含む）を「制限あり」と呼ぶ。
  - 日・曜日の **両方が制限あり** なら、日一致 **または** 曜日一致 で条件を満たす。
  - それ以外なら、日一致 **かつ** 曜日一致 で条件を満たす（制限なしの側は常に一致する）。

日フィールドの値はどの月でも 1〜31 を受け付ける。その月に存在しない日（4 月 31 日など）には単に一致しないだけで、エラーにはならない。

## 各メソッド

### `matches(dt)`

`dt` が上の判定で一致すれば `True`、そうでなければ `False`。

### `next_after(dt)`

`dt` より **真に後** で、スケジュールに一致する最も早い日時を返す。例: 毎分のスケジュールで `dt` が 10:00:00 なら 10:01、10:00:30 なら 10:01。

探索するのは年が `dt.year + 8` 以下（ただし 9999 以下）の範囲だけ。その範囲に一致する日時が無ければ `None` を返す。`datetime` で表せる最大値を超える場合も `None`。

### `prev_before(dt)`

`dt` より **真に前** で、スケジュールに一致する最も遅い日時を返す。例: 毎分のスケジュールで `dt` が 10:00:00 なら 9:59、10:00:30 なら 10:00。

探索するのは年が `dt.year - 8` 以上（ただし 1 以上）の範囲だけ。その範囲に無ければ `None`。`datetime` で表せる最小値を下回る場合も `None`。

### `iter_after(dt, count)`

`next_after(dt)` の結果を次の `dt` として `next_after` を繰り返し、得た日時を順に最大 `count` 個まで並べたリストを返す。途中で `None` になったらそこで打ち切り、それまでのリストを返す（探索範囲は各呼び出しの `dt` を基準にする）。`count` が 0 なら空リスト。`count` が負なら `ValueError`。

## 性能

一致する日時が見つからない場合（探索範囲 8 年分を調べ尽くす場合）も含め、`next_after` / `prev_before` の 1 回の呼び出しは 0.1 秒程度で終わること。分単位の総当たりでは間に合わない。

=== FILE: ref/cronexpr.py ===
"""5 フィールドの cron 式を解析し、発火時刻を計算する。"""

import calendar
import re
from datetime import date, datetime, timedelta

__all__ = ["CronError", "CronSchedule", "parse"]

SEARCH_YEARS = 8

MONTH_NAMES = {
    name: i
    for i, name in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
         "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"],
        start=1,
    )
}
DOW_NAMES = {
    name: i
    for i, name in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"])
}

MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


class CronError(ValueError):
    """cron 式が不正なときに送出する。"""


class _FieldSpec:
    def __init__(self, label, lo, hi, star_hi, names=None):
        self.label = label
        self.lo = lo
        self.hi = hi
        self.star_hi = star_hi
        self.names = names or {}


_MINUTE = _FieldSpec("minute", 0, 59, 59)
_HOUR = _FieldSpec("hour", 0, 23, 23)
_DOM = _FieldSpec("day-of-month", 1, 31, 31)
_MONTH = _FieldSpec("month", 1, 12, 12, MONTH_NAMES)
_DOW = _FieldSpec("day-of-week", 0, 7, 6, DOW_NAMES)


def _is_ascii_digits(text):
    return text != "" and all(c in "0123456789" for c in text)


def _parse_value(text, spec):
    if _is_ascii_digits(text):
        value = int(text)
    elif text.isascii() and text.upper() in spec.names:
        value = spec.names[text.upper()]
    else:
        raise CronError(f"invalid {spec.label} value: {text!r}")
    if not spec.lo <= value <= spec.hi:
        raise CronError(f"{spec.label} value out of range: {text!r}")
    return value


def _parse_step(text, spec):
    if not _is_ascii_digits(text):
        raise CronError(f"invalid {spec.label} step: {text!r}")
    step = int(text)
    if step < 1:
        raise CronError(f"{spec.label} step must be positive: {text!r}")
    return step


def _expand_item(item, spec):
    """'*' / 'N' / 'N-M' に任意の '/S' が付いた項目を値の集合に展開する。"""
    step = None
    base = item
    if "/" in item:
        base, step_text = item.split("/", 1)
        step = _parse_step(step_text, spec)
    if base == "*":
        start, end = spec.lo, spec.star_hi
    elif "-" in base:
        a, b = base.split("-", 1)
        start, end = _parse_value(a, spec), _parse_value(b, spec)
        if start > end:
            raise CronError(f"invalid {spec.label} range: {base!r}")
    else:
        start = _parse_value(base, spec)
        if step is None:
            end = start
        else:
            end = spec.star_hi
            if start > end:
                raise CronError(f"invalid {spec.label} start: {base!r}")
    return set(range(start, end + 1, step or 1))


def _split_items(text, spec):
    items = text.split(",")
    if any(item == "" for item in items):
        raise CronError(f"empty item in {spec.label} field: {text!r}")
    return items


def _parse_simple(text, spec):
    values = set()
    for item in _split_items(text, spec):
        values |= _expand_item(item, spec)
    return values


def _parse_dom(text):
    values = set()
    last = False
    for item in _split_items(text, _DOM):
        if item.upper() == "L":
            last = True
        else:
            values |= _expand_item(item, _DOM)
    return values, last


def _parse_dow(text):
    values = set()
    nth = set()
    for item in _split_items(text, _DOW):
        if "#" in item:
            left, right = item.split("#", 1)
            weekday = _parse_value(left, _DOW)
            if not _is_ascii_digits(right) or not 1 <= int(right) <= 5:
                raise CronError(f"invalid nth weekday: {item!r}")
            nth.add((weekday % 7, int(right)))
        else:
            values |= {v % 7 for v in _expand_item(item, _DOW)}
    return values, nth


class CronSchedule:
    """解析済みの cron 式。parse() で生成する。"""

    def __init__(self, fields):
        minute, hour, dom, month, dow = fields
        self._minutes = _parse_simple(minute, _MINUTE)
        self._hours = _parse_simple(hour, _HOUR)
        self._days, self._last_day = _parse_dom(dom)
        self._months = _parse_simple(month, _MONTH)
        self._weekdays, self._nth = _parse_dow(dow)
        self._dom_any = dom == "*"
        self._dow_any = dow == "*"

    def _day_matches(self, d):
        if d.month not in self._months:
            return False
        dom_ok = d.day in self._days or (
            self._last_day and d.day == calendar.monthrange(d.year, d.month)[1]
        )
        weekday = (d.weekday() + 1) % 7
        dow_ok = weekday in self._weekdays or (
            (weekday, (d.day - 1) // 7 + 1) in self._nth
        )
        if self._dom_any or self._dow_any:
            return dom_ok and dow_ok
        return dom_ok or dow_ok

    def matches(self, dt):
        return (
            dt.second == 0
            and dt.microsecond == 0
            and dt.minute in self._minutes
            and dt.hour in self._hours
            and self._day_matches(dt.date())
        )

    def next_after(self, dt):
        base = dt.replace(second=0, microsecond=0)
        try:
            start = base + timedelta(minutes=1)
        except OverflowError:
            return None
        end = date(min(dt.year + SEARCH_YEARS, 9999), 12, 31)
        hours = sorted(self._hours)
        minutes = sorted(self._minutes)
        d = start.date()
        first = True
        while d <= end:
            if self._day_matches(d):
                for h in hours:
                    if first and h < start.hour:
                        continue
                    for m in minutes:
                        if first and h == start.hour and m < start.minute:
                            continue
                        return datetime(d.year, d.month, d.day, h, m)
            if d == end:
                break
            d += timedelta(days=1)
            first = False
        return None

    def prev_before(self, dt):
        base = dt.replace(second=0, microsecond=0)
        if base == dt:
            try:
                start = base - timedelta(minutes=1)
            except OverflowError:
                return None
        else:
            start = base
        end = date(max(dt.year - SEARCH_YEARS, 1), 1, 1)
        hours = sorted(self._hours, reverse=True)
        minutes = sorted(self._minutes, reverse=True)
        d = start.date()
        first = True
        while d >= end:
            if self._day_matches(d):
                for h in hours:
                    if first and h > start.hour:
                        continue
                    for m in minutes:
                        if first and h == start.hour and m > start.minute:
                            continue
                        return datetime(d.year, d.month, d.day, h, m)
            if d == end:
                break
            d -= timedelta(days=1)
            first = False
        return None

    def iter_after(self, dt, count):
        if count < 0:
            raise ValueError("count must not be negative")
        result = []
        current = dt
        while len(result) < count:
            current = self.next_after(current)
            if current is None:
                break
            result.append(current)
        return result


def parse(expr):
    """cron 式を解析して CronSchedule を返す。不正なら CronError。"""
    if not isinstance(expr, str):
        raise CronError("expression must be a string")
    text = expr.strip(" \t")
    if text.startswith("@"):
        macro = MACROS.get(text.lower()) if text.isascii() else None
        if macro is None:
            raise CronError(f"unknown macro: {text!r}")
        text = macro
    fields = re.split(r"[ \t]+", text)
    if len(fields) != 5:
        raise CronError(f"expected 5 fields, got {len(fields)}")
    return CronSchedule(fields)

=== FILE: tests/test_hidden.py ===
import time
import unittest
from datetime import datetime as D

from cronexpr import CronError, parse


def fmt(values):
    return [v.strftime("%Y-%m-%d %H:%M") for v in values]


class TestNextAfterBasic(unittest.TestCase):
    def test_every_minute_strictly_after(self):
        s = parse("* * * * *")
        self.assertEqual(s.next_after(D(2024, 5, 1, 10, 0)), D(2024, 5, 1, 10, 1))
        self.assertEqual(s.next_after(D(2024, 5, 1, 10, 0, 30)), D(2024, 5, 1, 10, 1))
        self.assertEqual(
            s.next_after(D(2024, 5, 1, 10, 0, 0, 1)), D(2024, 5, 1, 10, 1)
        )

    def test_daily_time(self):
        s = parse("30 9 * * *")
        self.assertEqual(s.next_after(D(2024, 5, 1, 9, 30)), D(2024, 5, 2, 9, 30))
        self.assertEqual(
            s.next_after(D(2024, 5, 1, 9, 29, 59)), D(2024, 5, 1, 9, 30)
        )
        self.assertEqual(s.next_after(D(2024, 12, 31, 23, 0)), D(2025, 1, 1, 9, 30))

    def test_result_is_second_zero(self):
        r = parse("*/5 * * * *").next_after(D(2024, 5, 1, 10, 2, 45, 123))
        self.assertEqual(r, D(2024, 5, 1, 10, 5))
        self.assertEqual((r.second, r.microsecond), (0, 0))

    def test_year_rollover(self):
        s = parse("0 0 1 1 *")
        self.assertEqual(s.next_after(D(2023, 6, 1)), D(2024, 1, 1))
        self.assertEqual(s.next_after(D(2024, 1, 1)), D(2025, 1, 1))

    def test_ranges_and_steps(self):
        s = parse("*/15 9-17/4 * * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 7)),
            [
                "2024-01-01 09:00", "2024-01-01 09:15", "2024-01-01 09:30",
                "2024-01-01 09:45", "2024-01-01 13:00", "2024-01-01 13:15",
                "2024-01-01 13:30",
            ],
        )
        r = s.iter_after(D(2024, 1, 1, 17, 30), 2)
        self.assertEqual(fmt(r), ["2024-01-01 17:45", "2024-01-02 09:00"])

    def test_single_value_with_step(self):
        s = parse("5/20 * * * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1, 0, 5), 4)),
            ["2024-01-01 00:25", "2024-01-01 00:45",
             "2024-01-01 01:05", "2024-01-01 01:25"],
        )
        s = parse("0 */7 * * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1, 0, 0), 4)),
            ["2024-01-01 07:00", "2024-01-01 14:00",
             "2024-01-01 21:00", "2024-01-02 00:00"],
        )

    def test_step_larger_than_range_and_list(self):
        s = parse("5-10/20,30-31 0 1 1 *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 3)),
            ["2024-01-01 00:05", "2024-01-01 00:30", "2024-01-01 00:31"],
        )

    def test_dom_step_skips_short_months(self):
        s = parse("0 0 */10 * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 4, 21), 3)),
            ["2024-05-01 00:00", "2024-05-11 00:00", "2024-05-21 00:00"],
        )
        self.assertEqual(s.next_after(D(2024, 5, 21)), D(2024, 5, 31))


class TestLastDay(unittest.TestCase):
    def test_last_day_every_month(self):
        s = parse("0 12 L * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 31, 12, 0), 3)),
            ["2024-02-29 12:00", "2024-03-31 12:00", "2024-04-30 12:00"],
        )
        self.assertEqual(s.next_after(D(2023, 2, 1)), D(2023, 2, 28, 12, 0))

    def test_last_day_in_list_lowercase(self):
        s = parse("0 0 15,l 2 *")
        self.assertEqual(
            fmt(s.iter_after(D(2023, 1, 1), 4)),
            ["2023-02-15 00:00", "2023-02-28 00:00",
             "2024-02-15 00:00", "2024-02-29 00:00"],
        )

    def test_last_day_or_nth_weekday(self):
        s = parse("0 0 L * FRI#1")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 6)),
            ["2024-01-05 00:00", "2024-01-31 00:00", "2024-02-02 00:00",
             "2024-02-29 00:00", "2024-03-01 00:00", "2024-03-31 00:00"],
        )


class TestDayOfWeek(unittest.TestCase):
    def test_dom_or_dow_when_both_restricted(self):
        s = parse("0 0 13 * FRI")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 8)),
            ["2024-09-06 00:00", "2024-09-13 00:00", "2024-09-20 00:00",
             "2024-09-27 00:00", "2024-10-04 00:00", "2024-10-11 00:00",
             "2024-10-13 00:00", "2024-10-18 00:00"],
        )

    def test_only_dom_restricted(self):
        s = parse("0 0 13 * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 2)),
            ["2024-09-13 00:00", "2024-10-13 00:00"],
        )

    def test_weekdays_only(self):
        s = parse("0 8 * * MON-FRI")
        # 2024-09-06 は金曜
        self.assertEqual(s.next_after(D(2024, 9, 6, 8, 0)), D(2024, 9, 9, 8, 0))

    def test_seven_is_sunday(self):
        a = parse("0 0 * * 7").iter_after(D(2024, 9, 1), 3)
        b = parse("0 0 * * 0").iter_after(D(2024, 9, 1), 3)
        c = parse("0 0 * * sun").iter_after(D(2024, 9, 1), 3)
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertEqual(fmt(a)[0], "2024-09-08 00:00")
        s = parse("0 0 * * 5-7")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 4)),
            ["2024-09-06 00:00", "2024-09-07 00:00",
             "2024-09-08 00:00", "2024-09-13 00:00"],
        )

    def test_dow_steps(self):
        s = parse("0 0 * * */2")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 4)),
            ["2024-09-03 00:00", "2024-09-05 00:00",
             "2024-09-07 00:00", "2024-09-08 00:00"],
        )
        s = parse("0 0 * * MON/2")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 4)),
            ["2024-09-02 00:00", "2024-09-04 00:00",
             "2024-09-06 00:00", "2024-09-09 00:00"],
        )

    def test_nth_weekday(self):
        s = parse("0 9 * * MON#2")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 3)),
            ["2024-01-08 09:00", "2024-02-12 09:00", "2024-03-11 09:00"],
        )
        s = parse("0 9 * * 5#5")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 5)),
            ["2024-03-29 09:00", "2024-05-31 09:00", "2024-08-30 09:00",
             "2024-11-29 09:00", "2025-01-31 09:00"],
        )
        s = parse("0 0 * * 7#1,SAT#1")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 3)),
            ["2024-09-07 00:00", "2024-10-05 00:00", "2024-10-06 00:00"],
        )

    def test_nth_weekday_or_dom(self):
        s = parse("0 0 1 * MON#1")
        self.assertEqual(
            fmt(s.iter_after(D(2023, 12, 31), 5)),
            ["2024-01-01 00:00", "2024-02-01 00:00", "2024-02-05 00:00",
             "2024-03-01 00:00", "2024-03-04 00:00"],
        )

    def test_restricted_means_not_exactly_star(self):
        # 日フィールドは "*,1" なので制限あり扱い。結果として毎日一致する
        s = parse("0 0 *,1 * MON")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 3)),
            ["2024-09-02 00:00", "2024-09-03 00:00", "2024-09-04 00:00"],
        )
        s = parse("0 0 1 * */1")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 2)),
            ["2024-09-02 00:00", "2024-09-03 00:00"],
        )
        s = parse("0 0 1-31 * MON")
        self.assertEqual(s.next_after(D(2024, 9, 1)), D(2024, 9, 2))


class TestSyntax(unittest.TestCase):
    def test_names_case_insensitive(self):
        s = parse("0 0 1 jan,Jul *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 2, 1), 2)),
            ["2024-07-01 00:00", "2025-01-01 00:00"],
        )
        s = parse("0 0 1 FEB-apr *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 4)),
            ["2024-02-01 00:00", "2024-03-01 00:00",
             "2024-04-01 00:00", "2025-02-01 00:00"],
        )
        s = parse("0 0 1 jan/5 *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 3)),
            ["2024-06-01 00:00", "2024-11-01 00:00", "2025-01-01 00:00"],
        )

    def test_macros(self):
        dt = D(2024, 9, 4, 10, 30)  # 水曜
        self.assertEqual(parse("@hourly").next_after(dt), D(2024, 9, 4, 11, 0))
        self.assertEqual(parse("@daily").next_after(dt), D(2024, 9, 5, 0, 0))
        self.assertEqual(parse("@weekly").next_after(dt), D(2024, 9, 8, 0, 0))
        self.assertEqual(parse("@monthly").next_after(dt), D(2024, 10, 1, 0, 0))
        self.assertEqual(parse("@yearly").next_after(dt), D(2025, 1, 1, 0, 0))
        self.assertEqual(parse("@annually").next_after(dt), D(2025, 1, 1, 0, 0))
        self.assertEqual(parse("@DAILY").next_after(dt), D(2024, 9, 5, 0, 0))
        self.assertEqual(parse("  @Weekly\t").next_after(dt), D(2024, 9, 8, 0, 0))

    def test_whitespace_and_leading_zeros(self):
        s = parse("\t 05   09\t* *  *  ")
        self.assertEqual(s.next_after(D(2024, 1, 1)), D(2024, 1, 1, 9, 5))
        s = parse("00 00 01 01 00")
        # 日・曜日とも制限あり: 1/1 または日曜
        self.assertEqual(
            fmt(s.iter_after(D(2023, 12, 30), 3)),
            ["2023-12-31 00:00", "2024-01-01 00:00", "2024-01-07 00:00"],
        )

    def test_error_is_value_error(self):
        self.assertTrue(issubclass(CronError, ValueError))

    def test_invalid_expressions(self):
        bad = [
            "", "   ", "* * * *", "* * * * * *",
            "60 * * * *", "* 24 * * *", "* * 0 * *", "* * 32 * *",
            "* * * 0 *", "* * * 13 *", "* * * * 8",
            "5-1 * * * *", "* * * FEB-JAN *", "*/0 * * * *",
            "1,,2 * * * *", "1, * * * *", ",1 * * * *",
            "a * * * *", "-1 * * * *", "+1 * * * *", "1.0 * * * *",
            "\uff11 * * * *", "* * * * \uff11",
            "? * * * *", "* * ? * *", "* * * * ?",
            "*/ * * * *", "/5 * * * *", "1-/2 * * * *", "1- * * * *",
            "5/2/1 * * * *", "1-2-3 * * * *", "*/-1 * * * *",
            "L * * * *", "* L * * *", "* * * L *", "* * * * L",
            "* * L/2 * *", "* * 1-L * *", "* * LW * *",
            "* * MON * *", "* * * * JAN", "* * * MON *", "JAN * * * *",
            "* * * * MONDAY", "* * * JANUARY *",
            "* * * * MON#6", "* * * * MON#0", "* * * * 1-2#1",
            "* * * * #1", "* * * * MON#", "* * * * MON#1#1",
            "* * * * */2#1", "* * * * MON#\uff12", "* * * JAN#1 *", "* * 1#1 * *",
            "* * * * 7/2", "* * * * 8-9",
            "@reboot", "@daily *", "@", "@ daily",
            "* * * *\n*",
        ]
        for expr in bad:
            with self.subTest(expr=expr):
                with self.assertRaises(CronError):
                    parse(expr)

    def test_valid_edge_expressions(self):
        for expr in ["0-59 0-23 1-31 1-12 0-7", "59 23 31 12 7",
                     "* * * * 7#5", "* * * * 0-7/7", "* * 31/1 * *",
                     "* * * * 6/1", "* * l * *"]:
            with self.subTest(expr=expr):
                parse(expr)


class TestMatches(unittest.TestCase):
    def test_matches(self):
        s = parse("30 9 13 * FRI")
        self.assertTrue(s.matches(D(2024, 9, 13, 9, 30)))
        self.assertTrue(s.matches(D(2024, 9, 6, 9, 30)))   # 金曜
        self.assertTrue(s.matches(D(2024, 10, 13, 9, 30)))  # 13日（日曜）
        self.assertFalse(s.matches(D(2024, 9, 12, 9, 30)))
        self.assertFalse(s.matches(D(2024, 9, 13, 9, 31)))
        self.assertFalse(s.matches(D(2024, 9, 13, 9, 30, 1)))
        self.assertFalse(s.matches(D(2024, 9, 13, 9, 30, 0, 5)))

    def test_matches_last_and_nth(self):
        s = parse("0 0 L 2 *")
        self.assertTrue(s.matches(D(2024, 2, 29)))
        self.assertFalse(s.matches(D(2024, 2, 28)))
        self.assertTrue(s.matches(D(2023, 2, 28)))
        s = parse("0 0 * * TUE#3")
        self.assertTrue(s.matches(D(2024, 9, 17)))
        self.assertFalse(s.matches(D(2024, 9, 10)))
        self.assertFalse(s.matches(D(2024, 9, 24)))


class TestSearchWindow(unittest.TestCase):
    def test_impossible_returns_none(self):
        for expr in ["0 0 31 4 *", "0 0 30 2 *", "0 0 31 2,4,6,9,11 *"]:
            with self.subTest(expr=expr):
                s = parse(expr)
                self.assertIsNone(s.next_after(D(2024, 1, 1)))
                self.assertIsNone(s.prev_before(D(2024, 1, 1)))
                self.assertEqual(s.iter_after(D(2024, 1, 1), 3), [])

    def test_leap_day_window_inclusive(self):
        s = parse("0 0 29 2 *")
        self.assertEqual(s.next_after(D(2096, 3, 1)), D(2104, 2, 29))
        self.assertEqual(s.next_after(D(2096, 2, 29)), D(2104, 2, 29))
        self.assertEqual(s.prev_before(D(2104, 1, 1)), D(2096, 2, 29))
        self.assertIsNone(s.prev_before(D(2105, 1, 1)))

    def test_fifth_monday_of_february(self):
        s = parse("0 0 * 2 MON#5")
        self.assertEqual(s.next_after(D(2016, 1, 1)), D(2016, 2, 29))
        self.assertIsNone(s.next_after(D(2016, 3, 1)))
        self.assertEqual(s.next_after(D(2036, 3, 1)), D(2044, 2, 29))
        self.assertIsNone(s.next_after(D(2035, 12, 31, 23, 59)))
        self.assertEqual(s.prev_before(D(2052, 12, 31)), D(2044, 2, 29))
        self.assertIsNone(s.prev_before(D(2053, 1, 1)))
        # iter_after は毎回 next_after の探索範囲で打ち切られる
        self.assertEqual(s.iter_after(D(2016, 1, 1), 3), [D(2016, 2, 29)])

    def test_datetime_limits(self):
        s = parse("* * * * *")
        self.assertIsNone(s.next_after(D(9999, 12, 31, 23, 59)))
        self.assertIsNone(s.next_after(D(9999, 12, 31, 23, 59, 30)))
        self.assertEqual(
            s.next_after(D(9999, 12, 31, 23, 58, 59)), D(9999, 12, 31, 23, 59)
        )
        self.assertIsNone(s.prev_before(D(1, 1, 1, 0, 0)))
        self.assertEqual(s.prev_before(D(1, 1, 1, 0, 0, 1)), D(1, 1, 1, 0, 0))
        self.assertEqual(s.prev_before(D(1, 1, 1, 0, 1)), D(1, 1, 1, 0, 0))
        self.assertIsNone(parse("0 0 * 2 MON#5").next_after(D(9990, 1, 1)))
        self.assertEqual(parse("0 0 29 2 *").next_after(D(9995, 1, 1)),
                         D(9996, 2, 29))
        self.assertEqual(parse("0 0 1 1 *").prev_before(D(1, 1, 1, 0, 0, 1)),
                         D(1, 1, 1))
        self.assertEqual(parse("0 0 1 1 *").prev_before(D(5, 3, 1)),
                         D(5, 1, 1))

    def test_performance(self):
        exprs = ["0 0 31 4 *", "0 0 30 2 *", "59 23 * 2 MON#5", "* * 31 11 *"]
        start = time.perf_counter()
        for i in range(5):
            for expr in exprs:
                s = parse(expr)
                s.next_after(D(2016 + i, 3, 1))
                s.prev_before(D(2016 + i, 3, 1))
        self.assertLess(time.perf_counter() - start, 4.0)


class TestPrevBefore(unittest.TestCase):
    def test_every_minute(self):
        s = parse("* * * * *")
        self.assertEqual(s.prev_before(D(2024, 5, 1, 10, 0)), D(2024, 5, 1, 9, 59))
        self.assertEqual(
            s.prev_before(D(2024, 5, 1, 10, 0, 30)), D(2024, 5, 1, 10, 0)
        )
        self.assertEqual(
            s.prev_before(D(2024, 5, 1, 10, 0, 0, 1)), D(2024, 5, 1, 10, 0)
        )

    def test_rollback_across_boundaries(self):
        s = parse("45 17 * * MON-FRI")
        # 2024-09-09 は月曜
        self.assertEqual(s.prev_before(D(2024, 9, 9, 17, 45)), D(2024, 9, 6, 17, 45))
        self.assertEqual(
            s.prev_before(D(2024, 9, 9, 17, 45, 1)), D(2024, 9, 9, 17, 45)
        )
        s = parse("0 12 L * *")
        self.assertEqual(s.prev_before(D(2024, 3, 31, 12, 0)), D(2024, 2, 29, 12, 0))
        self.assertEqual(s.prev_before(D(2024, 1, 1)), D(2023, 12, 31, 12, 0))

    def test_multiple_hours_minutes(self):
        s = parse("10,40 8,20 * * *")
        self.assertEqual(s.prev_before(D(2024, 1, 1, 20, 30)), D(2024, 1, 1, 20, 10))
        self.assertEqual(s.prev_before(D(2024, 1, 1, 20, 10)), D(2024, 1, 1, 8, 40))
        self.assertEqual(s.prev_before(D(2024, 1, 1, 8, 39)), D(2024, 1, 1, 8, 10))
        self.assertEqual(s.prev_before(D(2024, 1, 1, 8, 10)), D(2023, 12, 31, 20, 40))
        self.assertEqual(s.prev_before(D(2024, 1, 1, 23, 59)), D(2024, 1, 1, 20, 40))


class TestIterAfter(unittest.TestCase):
    def test_count_zero_and_negative(self):
        s = parse("* * * * *")
        self.assertEqual(s.iter_after(D(2024, 1, 1), 0), [])
        with self.assertRaises(ValueError):
            s.iter_after(D(2024, 1, 1), -1)

    def test_iter_returns_list_of_consecutive(self):
        s = parse("0 0 * * *")
        r = s.iter_after(D(2024, 2, 27, 12, 0), 3)
        self.assertIsInstance(r, list)
        self.assertEqual(r, [D(2024, 2, 28), D(2024, 2, 29), D(2024, 3, 1)])

    def test_parse_is_independent(self):
        a = parse("0 0 1 * *")
        b = parse("0 0 2 * *")
        self.assertEqual(a.next_after(D(2024, 1, 1)), D(2024, 2, 1))
        self.assertEqual(b.next_after(D(2024, 1, 1)), D(2024, 1, 2))


if __name__ == "__main__":
    unittest.main()

=== END ===
