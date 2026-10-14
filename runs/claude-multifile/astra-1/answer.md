=== FILE: stock/money.py ===
"""金額をセントの整数として読み取り、表示する。"""

import re


def parse_cents(text: str) -> int:
    if re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", text) is None:
        raise ValueError(f"bad amount: {text!r}")

    whole, _, fraction = text.partition(".")
    digits = whole + fraction.ljust(2, "0")
    cents = 0
    for start in range(0, len(digits), 9):
        chunk = digits[start:start + 9]
        cents = cents * (10 ** len(chunk)) + int(chunk)
    return cents


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    remaining = abs(cents)
    chunks = []
    while remaining:
        remaining, chunk = divmod(remaining, 1_000_000_000)
        chunks.append(chunk)

    if chunks:
        digits = str(chunks.pop())
        digits += "".join(f"{chunk:09d}" for chunk in reversed(chunks))
    else:
        digits = "0"

    digits = digits.zfill(3)
    return f"{sign}{digits[:-2]}.{digits[-2:]}"
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


def _parse_price(text, lineno):
    try:
        return parse_cents(text)
    except ValueError:
        raise ParseError(lineno, f"bad price: {text!r}") from None


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
        unit_cost = _parse_price(fields[4], lineno)
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
=== FILE: stock/ledger.py ===
"""SKU ごとの在庫ロットと在庫金額の管理（先入先出法）。"""

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
        """入庫。数量とセント単価のロットを末尾に追加する。"""
        if qty < 1:
            raise ValueError("quantity must be positive")
        if unit_cost < 0:
            raise ValueError("unit cost must be nonnegative")
        self._lots.setdefault(sku, deque()).append((qty, unit_cost))

    def ship(self, sku, qty):
        """古いロットから出庫し、払い出した数量とセント単価の内訳を返す。"""
        if qty < 1:
            raise ValueError("quantity must be positive")
        available = self.quantity(sku)
        if qty > available:
            raise InsufficientStock(sku, qty, available)

        lots = self._lots[sku]
        remaining = qty
        shipped = []
        while remaining:
            lot_qty, unit_cost = lots[0]
            taken = min(remaining, lot_qty)
            shipped.append((taken, unit_cost))
            remaining -= taken
            if taken == lot_qty:
                lots.popleft()
            else:
                lots[0] = (lot_qty - taken, unit_cost)
        return shipped

    def quantity(self, sku) -> int:
        return sum(qty for qty, _ in self._lots.get(sku, ()))

    def value(self, sku) -> int:
        return sum(
            qty * unit_cost
            for qty, unit_cost in self._lots.get(sku, ())
        )

    def lots(self, sku) -> list[tuple[int, int]]:
        return list(self._lots.get(sku, ()))

    def skus(self):
        """一度でも入庫のあった SKU を昇順で返す。"""
        return sorted(self._lots)
=== FILE: stock/report.py ===
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
                shipped = ledger.ship(txn.sku, txn.qty)
            except InsufficientStock as e:
                raise ReportError(txn.lineno, str(e)) from None
            cost = sum(qty * unit_cost for qty, unit_cost in shipped)
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
        rows.append(
            f"{sku},{qty},{format_cents(value)},{format_cents(sku_cogs)}"
        )
        total_qty += qty
        total_value += value
        total_cogs += sku_cogs
    rows.append(
        f"TOTAL,{total_qty},{format_cents(total_value)},"
        f"{format_cents(total_cogs)}"
    )
    return "\n".join(rows) + "\n"
=== END ===