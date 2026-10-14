# 駐車場料金計算モジュールの不具合修正

時間貸し駐車場の料金を計算するモジュール `parking.py`（添付）があります。現在のコードには、以下の仕様と食い違う動作が含まれています。仕様どおりに動くよう `parking.py` を修正してください。

公開している名前（`DAY`, `NIGHT`, `Rule`, `parse_time`, `split_segments`, `block_fee`, `calc_fee`, `format_yen`, `make_receipt`, `daily_summary`）と、その引数の名前・順序・既定値は変えないでください。仕様に書かれていない補助関数は自由に変えて構いません。

## 前提

- 日時はすべてタイムゾーンを持たない `datetime` で、秒・マイクロ秒は常に 0 とします。
- 「時間帯」は昼間帯と夜間帯の 2 種類で、定数 `DAY = "day"` / `NIGHT = "night"` で表します。
- エラーとして「`ValueError` を送出する」と書いた箇所は、例外の型だけが決まっており、メッセージは自由です。

## `Rule`（料金ルール、frozen な dataclass）

| フィールド | 既定値 | 意味 |
|---|---|---|
| `free_minutes` | 15 | 無料となる駐車時間の上限（分） |
| `day_start` | 8 | 昼間帯の開始時（0〜24 の整数、「時」） |
| `night_start` | 22 | 夜間帯の開始時（0〜24 の整数、「時」） |
| `day_unit` | 30 | 昼間帯の課金単位（分） |
| `day_price` | 200 | 昼間帯の 1 単位あたりの料金（円） |
| `night_unit` | 60 | 夜間帯の課金単位（分） |
| `night_price` | 100 | 夜間帯の 1 単位あたりの料金（円） |
| `daily_max` | 1500 | 1 ブロック（後述）あたりの最大料金（円）。`None` なら上限なし |

各日について、`day_start` 時から `night_start` 時の直前までが昼間帯、それ以外（0 時〜`day_start` 時の直前、および `night_start` 時〜24 時の直前）が夜間帯です。つまり時刻 `t` は `day_start <= t.hour < night_start` のとき昼間帯です。`night_start` が 24 のときは当日の夜間帯は 0 時〜`day_start` 時の直前だけになり、`day_start` が 0 のときは夜間帯は `night_start` 時以降だけになります。

生成時に次をすべて満たさなければ `ValueError` を送出します。

- `free_minutes >= 0`
- `0 <= day_start < night_start <= 24`
- `day_unit > 0` かつ `night_unit > 0`
- `day_price >= 0` かつ `night_price >= 0`
- `daily_max` が `None` であるか、`daily_max > 0`

## `parse_time(text) -> datetime`

`"YYYY-MM-DD HH:MM"` 形式の文字列を `datetime` に変換します。

- 前後の空白文字（`str.strip()` で除かれるもの）は無視します。
- 残りは、半角数字 4 桁の年、`-`、2 桁の月、`-`、2 桁の日、半角スペース 1 個、2 桁の時、`:`、2 桁の分 で構成されていなければなりません（ゼロ埋め必須。秒は付けない）。
- 形式に合わない、または存在しない日時（2 月 30 日、24 時、60 分など）のときは `ValueError` を送出します。

## `split_segments(start, end, rule) -> list[tuple[datetime, datetime, str]]`

半開区間 `[start, end)` を、時間帯が切り替わる時刻で区切り、`(区間の開始, 区間の終了, 時間帯)` のリストを時刻順に返します。

- 区切るのは時間帯が実際に変わる時刻だけです。隣り合う 2 つの区間の時間帯は必ず異なります（例: `day_start=0, night_start=24` なら、何日にまたがっても 1 区間）。
- 時間帯の境界ちょうどの時刻は、その時刻から始まる時間帯に属します（既定ルールで 8:00 は昼間帯、22:00 は夜間帯）。
- 最初の区間の開始は `start`、最後の区間の終了は `end`、各区間の終了は次の区間の開始と一致します。
- `start == end` なら空リスト、`end < start` なら `ValueError` を送出します。

## `block_fee(start, end, rule) -> int`

`[start, end)` を 1 つのブロックとみなした料金を返します。

1. `split_segments(start, end, rule)` で区間に分けます。
2. 各区間の分数を、その時間帯の課金単位（分）で割って **切り上げた** 単位数に、その時間帯の単価を掛けます（例: 既定ルールの昼間帯で 30 分なら 1 単位、31 分なら 2 単位）。
3. それらを合計し、`rule.daily_max` が `None` でなければ `daily_max` と比べて小さい方を返します。

無料時間（`free_minutes`）はここでは考慮しません。

## `calc_fee(entry, exit, rule=None) -> int`

入庫時刻 `entry` から出庫時刻 `exit` までの料金を返します。`rule` が `None` なら `Rule()`（既定値）を使います。

1. `exit < entry` なら `ValueError` を送出します。
2. 駐車時間（分）が `rule.free_minutes` **以下** なら 0 を返します（駐車時間 0 分も 0）。
3. それ以外は、駐車時間を **入庫時刻から 24 時間ごと** のブロックに分けます。最初のブロックは `[entry, entry+24時間)`、次は `[entry+24時間, entry+48時間)` …で、最後のブロックの終了は `exit` です（24 時間ちょうどならブロックは 1 つ）。暦日の 0 時では区切りません。
4. 各ブロックの `block_fee` を合計して返します。無料時間を差し引くことはありません（無料時間を超えたら全時間が課金対象）。

## `format_yen(amount) -> str`

0 以上の整数の金額を、先頭に `¥` を付け、3 桁ごとに `,` で区切った文字列にします（例: `0 → "¥0"`、`1500 → "¥1,500"`、`1234567 → "¥1,234,567"`）。負の数なら `ValueError` を送出します。

## `make_receipt(entry_text, exit_text, rule=None) -> str`

入庫・出庫時刻の文字列から領収書の本文を作ります。`entry_text` / `exit_text` は `parse_time` で解釈し、料金は `calc_fee(入庫, 出庫, rule)` で求めます（どちらかのエラーはそのまま `ValueError` として伝わります）。次の 4 行を `"\n"` でつないだ文字列を返します（末尾に改行は付けません）。

```
入庫 YYYY-MM-DD HH:MM
出庫 YYYY-MM-DD HH:MM
駐車時間 {時間}時間{分}分
料金 {format_yen(料金)}
```

- 入庫・出庫の行は、解釈した日時を `"YYYY-MM-DD HH:MM"` 形式で書きます（入力の前後の空白は残りません）。
- 駐車時間の「時間」は駐車時間全体の時間数（24 以上にもなる）、「分」は 0〜59 で、どちらもゼロ埋めしません（例: `0時間5分`、`50時間0分`）。

## `daily_summary(records, rule=None) -> list[tuple[str, int, int]]`

`records` は `(入庫時刻の文字列, 出庫時刻の文字列)` の組を並べた反復可能オブジェクトです。各組を `parse_time` で解釈して `calc_fee(入庫, 出庫, rule)` で料金を求め、**出庫日** ごとに集計します。

- 戻り値は `(出庫日 "YYYY-MM-DD", 件数, 料金合計)` のリストで、日付の昇順に並べます。
- 件数には料金 0 円の利用も含めます。
- `records` が空なら空リストを返します。
- 解釈できない時刻や `exit < entry` の組があれば `ValueError` を送出します。

添付ファイル:
=== FILE: parking.py ===
"""駐車場の利用料金を計算するモジュール。

昼間帯・夜間帯で単価の異なる時間料金を、入庫から 24 時間ごとのブロックに
分けて計算し、ブロックごとに最大料金を適用する。
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Iterator, List, Optional, Tuple

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
        if not (0 <= self.day_start <= self.night_start <= 24):
            raise ValueError("invalid band hours")
        if self.day_unit <= 0 or self.night_unit <= 0:
            raise ValueError("unit must be positive")
        if self.day_price < 0 or self.night_price < 0:
            raise ValueError("price must be >= 0")
        if self.daily_max is not None and self.daily_max <= 0:
            raise ValueError("daily_max must be positive")


def parse_time(text: str) -> datetime:
    """"YYYY-MM-DD HH:MM" 形式の文字列を datetime に変換する。"""
    return datetime.strptime(text.strip(), TIME_FORMAT)


def format_time(t: datetime) -> str:
    return t.strftime(TIME_FORMAT)


def band_of(t: datetime, rule: Rule) -> str:
    """時刻 t が属する時間帯 (DAY / NIGHT) を返す。"""
    if rule.day_start <= t.hour < rule.night_start:
        return DAY
    return NIGHT


def _boundaries_from(d: date, rule: Rule) -> Iterator[datetime]:
    # 日付 d 以降の帯の境界時刻を昇順に返し続ける
    while True:
        yield datetime(d.year, d.month, d.day, rule.day_start)
        yield datetime(d.year, d.month, d.day, rule.night_start)
        d += timedelta(days=1)


def split_segments(
    start: datetime, end: datetime, rule: Rule
) -> List[Tuple[datetime, datetime, str]]:
    """[start, end) を時間帯が変わる時刻で区切った区間の一覧を返す。"""
    if end < start:
        raise ValueError("end is before start")
    segments = []
    cur = start
    while cur < end:
        kind = band_of(cur, rule)
        nxt = end
        for b in _boundaries_from(cur.date(), rule):
            if b >= end:
                break
            if b > cur and band_of(b, rule) != kind:
                nxt = b
                break
        segments.append((cur, nxt, kind))
        cur = nxt
    return segments


def _units(minutes: int, unit: int) -> int:
    return minutes // unit + 1


def block_fee(start: datetime, end: datetime, rule: Rule) -> int:
    """1 ブロック分の料金（最大料金適用後）を返す。"""
    total = 0
    for s, e, kind in split_segments(start, end, rule):
        minutes = (e - s) // timedelta(minutes=1)
        if kind == DAY:
            total += _units(minutes, rule.day_unit) * rule.day_price
        else:
            total += _units(minutes, rule.night_unit) * rule.night_price
    return min(total, rule.daily_max)


def calc_fee(entry: datetime, exit: datetime, rule: Optional[Rule] = None) -> int:
    """入庫時刻 entry から出庫時刻 exit までの料金を返す。"""
    if rule is None:
        rule = Rule()
    if exit < entry:
        raise ValueError("exit is before entry")
    minutes = (exit - entry) // timedelta(minutes=1)
    if minutes < rule.free_minutes:
        return 0
    total = 0
    cur = entry
    while cur < exit:
        nxt = min(datetime.combine(cur.date() + timedelta(days=1), time()), exit)
        total += block_fee(cur, nxt, rule)
        cur = nxt
    return total


def format_yen(amount: int) -> str:
    """金額を "¥1,234" の形に整形する。"""
    if amount < 0:
        raise ValueError("amount must be >= 0")
    s = str(amount)
    groups = []
    while len(s) >= 3:
        groups.insert(0, s[-3:])
        s = s[:-3]
    groups.insert(0, s)
    return "¥" + ",".join(groups)


def format_duration(delta: timedelta) -> str:
    """経過時間を "X時間Y分" の形に整形する。"""
    hours = delta.seconds // 3600
    minutes = delta.seconds % 3600 // 60
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
    """利用記録を日付ごとに集計し、(日付, 件数, 売上合計) の一覧を返す。"""
    totals = {}
    for entry_text, exit_text in records:
        entry = parse_time(entry_text)
        exit_ = parse_time(exit_text)
        fee = calc_fee(entry, exit_, rule)
        key = entry.date().isoformat()
        count, total = totals.get(key, (0, 0))
        totals[key] = (count + 1, total + fee)
    return [(k, c, t) for k, (c, t) in sorted(totals.items())]
=== END ===

答え方: 次のファイルの全体（変更しないファイルは不要）を、説明なしで、次の形式だけで返してください。各ファイルは「=== FILE: パス ===」の行で始め、最後に「=== END ===」の行を置きます。ツールは使えません。Python 3.11・標準ライブラリのみ。
返すファイル: parking.py
