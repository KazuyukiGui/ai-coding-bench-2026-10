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
=== FILE: given/stock/__init__.py ===
"""在庫取引ファイルから在庫報告を作るパッケージ。"""

=== FILE: given/stock/ledger.py ===
"""SKU ごとの在庫数と在庫金額の管理（移動平均法）。"""


class InsufficientStock(Exception):
    def __init__(self, sku, requested, available):
        super().__init__(
            f"insufficient stock for {sku}: "
            f"requested {requested}, available {available}"
        )
        self.sku = sku
        self.requested = requested
        self.available = available


class Ledger:
    def __init__(self):
        self._qty = {}
        self._avg_cost = {}

    def receive(self, sku, qty, unit_price):
        """入庫。平均単価を更新する。"""
        old_qty = self._qty.get(sku, 0)
        old_avg = self._avg_cost.get(sku, 0.0)
        new_qty = old_qty + qty
        self._avg_cost[sku] = (old_qty * old_avg + qty * unit_price) / new_qty
        self._qty[sku] = new_qty

    def ship(self, sku, qty):
        """出庫。払い出した分の原価を返す。在庫が足りなければ InsufficientStock。"""
        available = self._qty.get(sku, 0)
        if qty > available:
            raise InsufficientStock(sku, qty, available)
        self._qty[sku] = available - qty
        return qty * self._avg_cost[sku]

    def quantity(self, sku):
        return self._qty.get(sku, 0)

    def value(self, sku):
        return self._qty.get(sku, 0) * self._avg_cost.get(sku, 0.0)

    def skus(self):
        """一度でも入庫のあった SKU を昇順で返す。"""
        return sorted(self._qty)

=== FILE: given/stock/parser.py ===
"""在庫取引ファイルの読み取り。

1行が1件の取引で、カンマ区切りの次の形式をとる。

    日付,種別,SKU,数量[,単価]

- 日付は YYYY-MM-DD
- 種別は IN（入庫）か OUT（出庫）。大文字小文字は区別しない
- 数量は1以上の整数
- 単価は IN のときだけ必須で、OUT には書かない

空行と、先頭が # の行は読み飛ばす。
"""

import datetime
from dataclasses import dataclass

KINDS = ("IN", "OUT")


class ParseError(ValueError):
    """取引ファイルの書式の誤り。lineno は1始まりの物理行番号。"""

    def __init__(self, lineno, message):
        super().__init__(f"line {lineno}: {message}")
        self.lineno = lineno
        self.message = message


@dataclass(frozen=True)
class Txn:
    lineno: int
    date: datetime.date
    kind: str
    sku: str
    qty: int
    unit_price: float | None


def _parse_qty(text, lineno):
    if not (text.isascii() and text.isdigit()):
        raise ParseError(lineno, f"bad quantity: {text!r}")
    qty = int(text)
    if qty == 0:
        raise ParseError(lineno, "quantity must be positive")
    return qty


def _parse_price(text, lineno):
    try:
        price = float(text)
    except ValueError:
        raise ParseError(lineno, f"bad price: {text!r}") from None
    if price < 0:
        raise ParseError(lineno, f"negative price: {text!r}")
    return price


def parse_line(line, lineno):
    """1行を読み、Txn を返す。書式が違えば ParseError。"""
    fields = [f.strip() for f in line.split(",")]
    if len(fields) not in (4, 5):
        raise ParseError(lineno, "wrong number of fields")
    date_text, kind, sku, qty_text = fields[:4]
    try:
        date = datetime.date.fromisoformat(date_text)
    except ValueError:
        raise ParseError(lineno, f"bad date: {date_text!r}") from None
    kind = kind.upper()
    if kind not in KINDS:
        raise ParseError(lineno, f"unknown kind: {kind!r}")
    if not sku:
        raise ParseError(lineno, "empty sku")
    qty = _parse_qty(qty_text, lineno)
    price = None
    if kind == "IN":
        if len(fields) != 5:
            raise ParseError(lineno, "IN requires unit price")
        price = _parse_price(fields[4], lineno)
    elif len(fields) == 5:
        raise ParseError(lineno, "OUT must not have unit price")
    return Txn(lineno, date, kind, sku, qty, price)


def parse_lines(lines):
    """行の並びを読み、Txn のリストを返す。日付が前の取引より前なら ParseError。"""
    txns = []
    last_date = None
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        txn = parse_line(line, lineno)
        if last_date is not None and txn.date < last_date:
            raise ParseError(lineno, "date goes backwards")
        last_date = txn.date
        txns.append(txn)
    return txns

=== FILE: given/stock/report.py ===
"""取引ファイルの行から在庫報告（CSV 形式の文字列）を作る。"""

from .ledger import InsufficientStock, Ledger
from .parser import parse_lines

HEADER = "SKU,QTY,VALUE,COGS"


class ReportError(ValueError):
    """取引を台帳に反映できなかった。lineno はその取引の行番号。"""

    def __init__(self, lineno, message):
        super().__init__(f"line {lineno}: {message}")
        self.lineno = lineno
        self.message = message


def apply(txns, ledger=None):
    """取引を順に台帳へ反映し、(台帳, SKU ごとの出庫原価) を返す。"""
    if ledger is None:
        ledger = Ledger()
    cogs = {}
    for txn in txns:
        if txn.kind == "IN":
            ledger.receive(txn.sku, txn.qty, txn.unit_price)
        else:
            try:
                cost = ledger.ship(txn.sku, txn.qty)
            except InsufficientStock as e:
                raise ReportError(txn.lineno, str(e)) from None
            cogs[txn.sku] = cogs.get(txn.sku, 0.0) + cost
    return ledger, cogs


def build_report(lines):
    """取引ファイルの行から報告の文字列を作る。"""
    ledger, cogs = apply(parse_lines(lines))
    rows = [HEADER]
    total_qty = 0
    total_value = 0.0
    total_cogs = 0.0
    for sku in ledger.skus():
        qty = ledger.quantity(sku)
        value = ledger.value(sku)
        sku_cogs = cogs.get(sku, 0.0)
        rows.append(f"{sku},{qty},{value:.2f},{sku_cogs:.2f}")
        total_qty += qty
        total_value += value
        total_cogs += sku_cogs
    rows.append(f"TOTAL,{total_qty},{total_value:.2f},{total_cogs:.2f}")
    return "\n".join(rows) + "\n"

=== FILE: prompt.md ===
# 在庫報告パッケージ：金額の整数化と先入先出法への切り替え

添付の `stock/` パッケージは、在庫取引ファイルの行を読み、SKU ごとの在庫数・在庫金額・出庫原価を CSV 形式の文字列で報告します。

- `stock/parser.py` … 取引ファイルの1行を `Txn` に読み取る
- `stock/ledger.py` … SKU ごとの在庫を管理する `Ledger`
- `stock/report.py` … 取引を台帳に反映し、報告の文字列を作る

今は金額を float で扱い、原価を移動平均法で計算しています。これを次のように変えてください。変更するのは `stock/money.py`（新規）、`stock/parser.py`、`stock/ledger.py`、`stock/report.py` の4ファイルです。`stock/__init__.py` は変えません。

## 1. 新しいモジュール `stock/money.py`

金額は「セント」（最小単位。1単位の 1/100）の整数で表します。

### `parse_cents(text: str) -> int`

- `text` 全体が次のどちらかの形のときだけ受け付けます。
  - ASCII の数字1文字以上（例: `"12"`）
  - ASCII の数字1文字以上・ピリオド1つ・ASCII の数字1〜2文字（例: `"12.5"`, `"12.50"`）
- 先頭の 0 は許します（`"007.10"` は 710）。
- 小数部が1桁なら10セント単位です（`"12.5"` → 1250）。小数部が無ければ単位の整数倍です（`"12"` → 1200）。
- それ以外の文字列（空文字列、符号付き、指数表記、前後に空白や改行がある、桁区切りがある、全角数字、`"5."` や `".5"`、小数部が3桁以上など）は `ValueError` を送出します。
- 桁数に上限はありません。どれほど大きな値でも正確に変換します（float を経由してはいけません）。

### `format_cents(cents: int) -> str`

- 「整数部・ピリオド・小数部2桁」の形にします。整数部に余分な先頭の 0 は付けず、1単位未満なら `"0"` です。桁区切りは付けません。
  - 例: 0 → `"0.00"`, 5 → `"0.05"`, 1250 → `"12.50"`, 123456 → `"1234.56"`
- 負の値は、絶対値を同じ形で書き、先頭に `"-"` を付けます。
  - 例: -5 → `"-0.05"`, -105 → `"-1.05"`

## 2. `stock/parser.py`

- `Txn` のフィールド `unit_price` を `unit_cost` に改めます。型は `int | None` で、IN の取引では単価をセントにした整数、OUT の取引では `None` です。フィールドの並びは `lineno, date, kind, sku, qty, unit_cost` です。
- 単価の書式は `parse_cents` に従います（フィールドは今までどおり前後の空白を除いてから調べます）。`parse_cents` が受け付けない単価は、その行の行番号を持つ `ParseError` にします。単価 0 は許します。
- これ以外の挙動（フィールド数・日付・種別・SKU・数量の検査、空行とコメント行の扱い、行番号の数え方、日付の逆行の検出など）は変えません。

## 3. `stock/ledger.py` — 先入先出法

`Ledger` を、SKU ごとに入庫ロットの列を持つ先入先出法に作り替えます。金額はすべてセントの整数です。

- `receive(sku, qty, unit_cost)`
  - その SKU のロット列の末尾に、数量 `qty`・単価 `unit_cost` のロットを1つ足します。同じ単価の入庫が続いても、ロットは合体させません。
  - `qty` が1未満、または `unit_cost` が負なら `ValueError` を送出し、台帳は何も変えません（その SKU も登録しません）。
- `ship(sku, qty)`
  - 古いロットから順に `qty` 個を払い出し、払い出しの内訳を `(数量, 単価)` のタプルのリストで返します。手を付けたロット1つにつきタプル1つで、払い出した順に並べます。
  - 使い切ったロットは台帳から消えます。一部だけ使ったロットは、残数を減らして先頭に残ります。
  - `qty` が1未満なら `ValueError` を送出します。この検査は在庫数の検査より先に行います。
  - `qty` が現在の在庫数より多ければ `InsufficientStock`（`sku`、`requested=qty`、`available=現在の在庫数`）を送出します。このとき台帳は何も変えません。
- `quantity(sku) -> int` … 残っているロットの数量の合計
- `value(sku) -> int` … 残っているロットの（数量 × 単価）の合計
- `lots(sku) -> list[tuple[int, int]]` … 残っているロットを `(数量, 単価)` のタプルで古い順に並べたリスト。数量 0 のロットは含めません。返したリストを書き換えても台帳には影響しません。
- `skus()` … 今までどおり、`receive` が一度でも成功した SKU を昇順に返します（在庫が 0 になった SKU も含みます）。
- 入庫の無い SKU について、`quantity`・`value` は 0、`lots` は空リストです。
- `InsufficientStock` とその属性 `sku`, `requested`, `available` はそのまま残します。

## 4. `stock/report.py`

- `apply(txns, ledger=None)` は新しい `Ledger` を使います。返す出庫原価の辞書の値は、`ship` が返した内訳の（数量 × 単価）の合計で、セントの整数です。辞書に入るのは今までどおり出庫のあった SKU だけです。
- `build_report(lines)` の出力の形は今までどおりです（見出し行、SKU ごとの行、TOTAL 行。各行の末尾に改行）。金額の列（VALUE, COGS）は `format_cents` で書きます。TOTAL 行の金額もセントの整数のまま足してから書きます。
- 在庫不足を、その OUT 行の行番号を持つ `ReportError` にすることなど、ほかの挙動は変えません。

## 例

入力:

```
# 期首
2024-04-01,IN,A,10,1.00
2024-04-02,IN,A,5,1.20
2024-04-03,out,A,12
2024-04-03,IN,B,3,0.10
2024-04-05,OUT,B,1
```

`build_report` の結果:

```
SKU,QTY,VALUE,COGS
A,3,3.60,12.40
B,2,0.20,0.10
TOTAL,5,3.80,12.50
```

A の出庫 12 個は、1.00 のロットから 10 個、1.20 のロットから 2 個を払い出すので、内訳は `[(10, 100), (2, 120)]`、出庫原価は 1240 セントです。残りは 1.20 のロット 3 個です。

=== FILE: ref/stock/ledger.py ===
"""SKU ごとの在庫ロットの管理（先入先出法）。金額はすべてセントの整数。"""

from collections import deque


class InsufficientStock(Exception):
    def __init__(self, sku, requested, available):
        super().__init__(
            f"insufficient stock for {sku}: "
            f"requested {requested}, available {available}"
        )
        self.sku = sku
        self.requested = requested
        self.available = available


class Ledger:
    def __init__(self):
        self._lots = {}

    def receive(self, sku, qty, unit_cost):
        """入庫。数量 qty・単価 unit_cost のロットを末尾に足す。"""
        if qty < 1:
            raise ValueError(f"quantity must be positive: {qty!r}")
        if unit_cost < 0:
            raise ValueError(f"unit cost must not be negative: {unit_cost!r}")
        self._lots.setdefault(sku, deque()).append([qty, unit_cost])

    def ship(self, sku, qty):
        """出庫。古いロットから払い出し、内訳 [(数量, 単価), ...] を返す。"""
        if qty < 1:
            raise ValueError(f"quantity must be positive: {qty!r}")
        available = self.quantity(sku)
        if qty > available:
            raise InsufficientStock(sku, qty, available)
        lots = self._lots[sku]
        taken = []
        while qty > 0:
            lot = lots[0]
            n = min(qty, lot[0])
            taken.append((n, lot[1]))
            lot[0] -= n
            qty -= n
            if lot[0] == 0:
                lots.popleft()
        return taken

    def quantity(self, sku):
        return sum(qty for qty, _ in self._lots.get(sku, ()))

    def value(self, sku):
        return sum(qty * cost for qty, cost in self._lots.get(sku, ()))

    def lots(self, sku):
        """残っているロットを (数量, 単価) のタプルで古い順に返す。"""
        return [(qty, cost) for qty, cost in self._lots.get(sku, ())]

    def skus(self):
        """一度でも入庫のあった SKU を昇順で返す。"""
        return sorted(self._lots)

=== FILE: ref/stock/money.py ===
"""金額（セント単位の整数）と文字列の相互変換。"""

import re

_AMOUNT_RE = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")


def parse_cents(text):
    """"12.50" のような金額の文字列をセントの整数にする。書式が違えば ValueError。"""
    if not isinstance(text, str) or _AMOUNT_RE.fullmatch(text) is None:
        raise ValueError(f"bad amount: {text!r}")
    whole, _, frac = text.partition(".")
    return int(whole) * 100 + int(frac.ljust(2, "0"))


def format_cents(cents):
    """セントの整数を "1234.56" の形の文字列にする。"""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}{whole}.{frac:02d}"

=== FILE: ref/stock/parser.py ===
"""在庫取引ファイルの読み取り。

1行が1件の取引で、カンマ区切りの次の形式をとる。

    日付,種別,SKU,数量[,単価]

- 日付は YYYY-MM-DD
- 種別は IN（入庫）か OUT（出庫）。大文字小文字は区別しない
- 数量は1以上の整数
- 単価は IN のときだけ必須で、OUT には書かない。"12.50" のような小数2桁までの金額

空行と、先頭が # の行は読み飛ばす。
"""

import datetime
from dataclasses import dataclass

from .money import parse_cents

KINDS = ("IN", "OUT")


class ParseError(ValueError):
    """取引ファイルの書式の誤り。lineno は1始まりの物理行番号。"""

    def __init__(self, lineno, message):
        super().__init__(f"line {lineno}: {message}")
        self.lineno = lineno
        self.message = message


@dataclass(frozen=True)
class Txn:
    lineno: int
    date: datetime.date
    kind: str
    sku: str
    qty: int
    unit_cost: int | None


def _parse_qty(text, lineno):
    if not (text.isascii() and text.isdigit()):
        raise ParseError(lineno, f"bad quantity: {text!r}")
    qty = int(text)
    if qty == 0:
        raise ParseError(lineno, "quantity must be positive")
    return qty


def _parse_unit_cost(text, lineno):
    try:
        return parse_cents(text)
    except ValueError:
        raise ParseError(lineno, f"bad unit cost: {text!r}") from None


def parse_line(line, lineno):
    """1行を読み、Txn を返す。書式が違えば ParseError。"""
    fields = [f.strip() for f in line.split(",")]
    if len(fields) not in (4, 5):
        raise ParseError(lineno, "wrong number of fields")
    date_text, kind, sku, qty_text = fields[:4]
    try:
        date = datetime.date.fromisoformat(date_text)
    except ValueError:
        raise ParseError(lineno, f"bad date: {date_text!r}") from None
    kind = kind.upper()
    if kind not in KINDS:
        raise ParseError(lineno, f"unknown kind: {kind!r}")
    if not sku:
        raise ParseError(lineno, "empty sku")
    qty = _parse_qty(qty_text, lineno)
    unit_cost = None
    if kind == "IN":
        if len(fields) != 5:
            raise ParseError(lineno, "IN requires unit price")
        unit_cost = _parse_unit_cost(fields[4], lineno)
    elif len(fields) == 5:
        raise ParseError(lineno, "OUT must not have unit price")
    return Txn(lineno, date, kind, sku, qty, unit_cost)


def parse_lines(lines):
    """行の並びを読み、Txn のリストを返す。日付が前の取引より前なら ParseError。"""
    txns = []
    last_date = None
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        txn = parse_line(line, lineno)
        if last_date is not None and txn.date < last_date:
            raise ParseError(lineno, "date goes backwards")
        last_date = txn.date
        txns.append(txn)
    return txns

=== FILE: ref/stock/report.py ===
"""取引ファイルの行から在庫報告（CSV 形式の文字列）を作る。"""

from .ledger import InsufficientStock, Ledger
from .money import format_cents
from .parser import parse_lines

HEADER = "SKU,QTY,VALUE,COGS"


class ReportError(ValueError):
    """取引を台帳に反映できなかった。lineno はその取引の行番号。"""

    def __init__(self, lineno, message):
        super().__init__(f"line {lineno}: {message}")
        self.lineno = lineno
        self.message = message


def apply(txns, ledger=None):
    """取引を順に台帳へ反映し、(台帳, SKU ごとの出庫原価) を返す。"""
    if ledger is None:
        ledger = Ledger()
    cogs = {}
    for txn in txns:
        if txn.kind == "IN":
            ledger.receive(txn.sku, txn.qty, txn.unit_cost)
        else:
            try:
                taken = ledger.ship(txn.sku, txn.qty)
            except InsufficientStock as e:
                raise ReportError(txn.lineno, str(e)) from None
            cost = sum(qty * unit_cost for qty, unit_cost in taken)
            cogs[txn.sku] = cogs.get(txn.sku, 0) + cost
    return ledger, cogs


def build_report(lines):
    """取引ファイルの行から報告の文字列を作る。"""
    ledger, cogs = apply(parse_lines(lines))
    rows = [HEADER]
    total_qty = 0
    total_value = 0
    total_cogs = 0
    for sku in ledger.skus():
        qty = ledger.quantity(sku)
        value = ledger.value(sku)
        sku_cogs = cogs.get(sku, 0)
        rows.append(f"{sku},{qty},{format_cents(value)},{format_cents(sku_cogs)}")
        total_qty += qty
        total_value += value
        total_cogs += sku_cogs
    rows.append(
        f"TOTAL,{total_qty},{format_cents(total_value)},{format_cents(total_cogs)}"
    )
    return "\n".join(rows) + "\n"

=== FILE: tests/test_hidden.py ===
import dataclasses
import datetime
import unittest

from stock.ledger import InsufficientStock, Ledger
from stock.money import format_cents, parse_cents
from stock.parser import ParseError, Txn, parse_line, parse_lines
from stock.report import ReportError, apply, build_report


class MoneyTest(unittest.TestCase):
    def test_parse_basic(self):
        cases = {
            "12.50": 1250,
            "12.5": 1250,
            "12": 1200,
            "0.05": 5,
            "0": 0,
            "0.00": 0,
            "007.10": 710,
            "3.07": 307,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                got = parse_cents(text)
                self.assertEqual(got, expected)
                self.assertIsInstance(got, int)

    def test_parse_rejects(self):
        bad = [
            "", "-1", "+1", "-0.50", "1e3", ".5", "5.", "1.234", "1,000",
            " 1.00", "1.00 ", "1.00\n", "１２", "1.0.0", "abc", "1_000",
            "nan", "inf", "1. 5",
        ]
        for text in bad:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_cents(text)

    def test_parse_large_exact(self):
        self.assertEqual(parse_cents("12345678901234567.89"), 1234567890123456789)
        self.assertEqual(parse_cents("30023997515803.31"), 3002399751580331)

    def test_format(self):
        cases = {
            0: "0.00",
            5: "0.05",
            100: "1.00",
            1250: "12.50",
            123456: "1234.56",
            1234567890123456789: "12345678901234567.89",
        }
        for cents, expected in cases.items():
            with self.subTest(cents=cents):
                self.assertEqual(format_cents(cents), expected)

    def test_format_negative(self):
        self.assertEqual(format_cents(-5), "-0.05")
        self.assertEqual(format_cents(-105), "-1.05")
        self.assertEqual(format_cents(-100), "-1.00")
        self.assertEqual(format_cents(-123456), "-1234.56")

    def test_roundtrip(self):
        for text in ["0.01", "10.00", "999.99", "0.10"]:
            with self.subTest(text=text):
                self.assertEqual(format_cents(parse_cents(text)), text)


class ParserTest(unittest.TestCase):
    def test_txn_fields(self):
        names = [f.name for f in dataclasses.fields(Txn)]
        self.assertEqual(names, ["lineno", "date", "kind", "sku", "qty", "unit_cost"])

    def test_unit_cost_in_and_out(self):
        t = parse_line("2024-03-01,IN,A,4, 12.5 ", 7)
        self.assertEqual(t.unit_cost, 1250)
        self.assertIsInstance(t.unit_cost, int)
        self.assertEqual(t.lineno, 7)
        self.assertEqual(t.date, datetime.date(2024, 3, 1))
        self.assertEqual(t.qty, 4)
        o = parse_line("2024-03-01,OUT,A,4", 1)
        self.assertIsNone(o.unit_cost)

    def test_zero_and_large_unit_cost(self):
        self.assertEqual(parse_line("2024-01-01,IN,A,1,0", 1).unit_cost, 0)
        self.assertEqual(
            parse_line("2024-01-01,IN,A,1,30023997515803.31", 1).unit_cost,
            3002399751580331,
        )

    def test_bad_unit_cost_has_lineno(self):
        for price in ["-1", "1e3", "1.234", "abc", "", "5.", "１"]:
            with self.subTest(price=price):
                lines = ["# header", "", f"2024-01-01,IN,A,1,{price}"]
                with self.assertRaises(ParseError) as cm:
                    parse_lines(lines)
                self.assertEqual(cm.exception.lineno, 3)

    def test_existing_checks_kept(self):
        bad = [
            "2024-01-01,OUT,A,1,1.00",
            "2024-01-01,IN,A,1",
            "2024-01-01,IN,A,0,1.00",
            "2024-01-01,IN,A,²,1.00",
            "2024-01-01,IN,A,-1,1.00",
            "2024-01-01,IN,A,1.5,1.00",
            "2024-01-01,MOVE,A,1",
            "2024-01-01,IN, ,1,1.00",
            "2024-13-01,IN,A,1,1.00",
            "2024-01-01,IN,A",
            "2024-01-01,IN,A,1,1.00,x",
        ]
        for line in bad:
            with self.subTest(line=line):
                with self.assertRaises(ParseError) as cm:
                    parse_line(line, 5)
                self.assertEqual(cm.exception.lineno, 5)
        self.assertTrue(issubclass(ParseError, ValueError))

    def test_skips_and_case_kept(self):
        txns = parse_lines(
            ["  # c", "", "2024-01-01,in,A,1,1", "   ", "2024-01-01,Out,A,1"]
        )
        self.assertEqual([t.kind for t in txns], ["IN", "OUT"])
        self.assertEqual([t.lineno for t in txns], [3, 5])
        self.assertEqual([t.unit_cost for t in txns], [100, None])

    def test_date_backwards_kept(self):
        with self.assertRaises(ParseError) as cm:
            parse_lines(["2024-01-02,IN,A,1,1", "", "2024-01-01,IN,A,1,1"])
        self.assertEqual(cm.exception.lineno, 3)


class LedgerTest(unittest.TestCase):
    def test_fifo_breakdown(self):
        led = Ledger()
        led.receive("A", 10, 100)
        led.receive("A", 5, 120)
        self.assertEqual(led.ship("A", 12), [(10, 100), (2, 120)])
        self.assertEqual(led.lots("A"), [(3, 120)])
        self.assertEqual(led.quantity("A"), 3)
        self.assertEqual(led.value("A"), 360)

    def test_lots_not_merged(self):
        led = Ledger()
        led.receive("A", 2, 100)
        led.receive("A", 2, 100)
        self.assertEqual(led.lots("A"), [(2, 100), (2, 100)])
        self.assertEqual(led.ship("A", 3), [(2, 100), (1, 100)])
        self.assertEqual(led.lots("A"), [(1, 100)])

    def test_full_lot_removed(self):
        led = Ledger()
        led.receive("A", 5, 100)
        self.assertEqual(led.ship("A", 5), [(5, 100)])
        self.assertEqual(led.lots("A"), [])
        self.assertEqual(led.quantity("A"), 0)
        self.assertEqual(led.value("A"), 0)
        self.assertEqual(led.skus(), ["A"])

    def test_interleaved(self):
        led = Ledger()
        led.receive("A", 4, 100)
        self.assertEqual(led.ship("A", 3), [(3, 100)])
        led.receive("A", 2, 50)
        self.assertEqual(led.ship("A", 2), [(1, 100), (1, 50)])
        self.assertEqual(led.lots("A"), [(1, 50)])
        self.assertEqual(led.value("A"), 50)

    def test_insufficient_leaves_state(self):
        led = Ledger()
        led.receive("A", 3, 100)
        led.receive("A", 2, 200)
        with self.assertRaises(InsufficientStock) as cm:
            led.ship("A", 6)
        e = cm.exception
        self.assertEqual((e.sku, e.requested, e.available), ("A", 6, 5))
        self.assertEqual(led.lots("A"), [(3, 100), (2, 200)])
        self.assertEqual(led.quantity("A"), 5)
        with self.assertRaises(InsufficientStock) as cm:
            led.ship("Z", 1)
        self.assertEqual(cm.exception.available, 0)
        self.assertEqual(led.skus(), ["A"])

    def test_validation(self):
        led = Ledger()
        for qty, cost in [(0, 100), (-2, 100), (1, -1)]:
            with self.subTest(qty=qty, cost=cost):
                with self.assertRaises(ValueError):
                    led.receive("A", qty, cost)
        self.assertEqual(led.skus(), [])
        led.receive("A", 1, 0)
        with self.assertRaises(ValueError):
            led.ship("A", 0)
        with self.assertRaises(ValueError):
            led.ship("A", -1)
        with self.assertRaises(ValueError):
            led.ship("Z", 0)
        self.assertEqual(led.lots("A"), [(1, 0)])

    def test_lots_returns_copy(self):
        led = Ledger()
        led.receive("A", 3, 100)
        got = led.lots("A")
        got.clear()
        got.append((99, 1))
        self.assertEqual(led.lots("A"), [(3, 100)])
        self.assertEqual(led.quantity("A"), 3)

    def test_unknown_sku_queries(self):
        led = Ledger()
        self.assertEqual(led.quantity("X"), 0)
        self.assertEqual(led.value("X"), 0)
        self.assertEqual(led.lots("X"), [])
        self.assertEqual(led.skus(), [])


class ReportTest(unittest.TestCase):
    def test_example(self):
        lines = [
            "# 期首",
            "2024-04-01,IN,A,10,1.00",
            "2024-04-02,IN,A,5,1.20",
            "2024-04-03,out,A,12",
            "2024-04-03,IN,B,3,0.10",
            "2024-04-05,OUT,B,1",
        ]
        expected = (
            "SKU,QTY,VALUE,COGS\n"
            "A,3,3.60,12.40\n"
            "B,2,0.20,0.10\n"
            "TOTAL,5,3.80,12.50\n"
        )
        self.assertEqual(build_report(lines), expected)

    def test_zero_qty_sku_and_sorting(self):
        lines = [
            "2024-01-01,IN,b,1,2.00",
            "2024-01-01,IN,B,2,3.00",
            "2024-01-01,IN,A,1,0",
            "2024-01-02,OUT,b,1",
        ]
        expected = (
            "SKU,QTY,VALUE,COGS\n"
            "A,1,0.00,0.00\n"
            "B,2,6.00,0.00\n"
            "b,0,0.00,2.00\n"
            "TOTAL,3,6.00,2.00\n"
        )
        self.assertEqual(build_report(lines), expected)

    def test_empty(self):
        expected = "SKU,QTY,VALUE,COGS\nTOTAL,0,0.00,0.00\n"
        self.assertEqual(build_report([]), expected)
        self.assertEqual(build_report(["# only comment", "", "  "]), expected)

    def test_insufficient_lineno(self):
        lines = ["2024-01-01,IN,A,2,1.00", "", "# c", "2024-01-02,OUT,A,3"]
        with self.assertRaises(ReportError) as cm:
            build_report(lines)
        self.assertEqual(cm.exception.lineno, 4)
        self.assertTrue(issubclass(ReportError, ValueError))

    def test_parse_error_propagates(self):
        with self.assertRaises(ParseError) as cm:
            build_report(["2024-01-01,IN,A,1,1.00", "2024-01-01,IN,A,1,1.234"])
        self.assertEqual(cm.exception.lineno, 2)

    def test_large_amounts_exact(self):
        lines = ["2024-01-01,IN,X,3,30023997515803.31", "2024-01-02,OUT,X,1"]
        expected = (
            "SKU,QTY,VALUE,COGS\n"
            "X,2,60047995031606.62,30023997515803.31\n"
            "TOTAL,2,60047995031606.62,30023997515803.31\n"
        )
        self.assertEqual(build_report(lines), expected)

    def test_apply_cogs_int(self):
        txns = parse_lines(
            [
                "2024-01-01,IN,A,10,1.00",
                "2024-01-01,IN,A,5,1.20",
                "2024-01-02,IN,B,1,9.99",
                "2024-01-03,OUT,A,11",
                "2024-01-04,OUT,A,1",
            ]
        )
        ledger, cogs = apply(txns)
        self.assertEqual(cogs, {"A": 1240})
        self.assertIsInstance(cogs["A"], int)
        self.assertEqual(ledger.lots("A"), [(3, 120)])
        self.assertEqual(ledger.lots("B"), [(1, 999)])

    def test_apply_with_existing_ledger(self):
        led = Ledger()
        led.receive("A", 5, 100)
        ledger, cogs = apply(parse_lines(["2024-01-01,OUT,A,2"]), led)
        self.assertIs(ledger, led)
        self.assertEqual(cogs, {"A": 200})
        self.assertEqual(led.quantity("A"), 3)


if __name__ == "__main__":
    unittest.main()

=== END ===
