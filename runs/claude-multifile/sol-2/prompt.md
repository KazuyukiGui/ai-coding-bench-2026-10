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

添付ファイル:
=== FILE: stock/__init__.py ===
"""在庫取引ファイルから在庫報告を作るパッケージ。"""
=== FILE: stock/ledger.py ===
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
=== FILE: stock/parser.py ===
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
=== FILE: stock/report.py ===
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
=== END ===

答え方: 次のファイルの全体（変更しないファイルは不要）を、説明なしで、次の形式だけで返してください。各ファイルは「=== FILE: パス ===」の行で始め、最後に「=== END ===」の行を置きます。ツールは使えません。Python 3.11・標準ライブラリのみ。
返すファイル: stock/money.py、stock/parser.py、stock/ledger.py、stock/report.py
