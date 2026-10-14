=== FILE: stock/money.py ===
"""金額の表現。金額はセント（1単位の 1/100）の整数で扱う。"""

import re

_AMOUNT = re.compile(r"([0-9]+)(?:\.([0-9]{1,2}))?")

# int() と str() が一度に扱える桁数には上限があるので、これより長いものは分けて変換する。
_CHUNK_DIGITS = 1000


def _digits_to_int(digits):
    """ASCII の数字だけの文字列を整数にする。桁数に上限はない。"""
    if len(digits) <= _CHUNK_DIGITS:
        return int(digits)
    mid = len(digits) // 2
    low_len = len(digits) - mid
    return _digits_to_int(digits[:mid]) * 10**low_len + _digits_to_int(digits[mid:])


def _int_to_digits(n):
    """0 以上の整数を10進の数字の文字列にする。桁数に上限はない。"""
    approx_digits = int(n.bit_length() * 0.30103) + 1
    if approx_digits <= _CHUNK_DIGITS:
        return str(n)
    k = approx_digits // 2
    high, low = divmod(n, 10**k)
    return _int_to_digits(high) + _int_to_digits(low).zfill(k)


def parse_cents(text):
    """"12" や "12.5" や "12.50" の形の金額をセントの整数にする。書式が違えば ValueError。"""
    m = _AMOUNT.fullmatch(text)
    if m is None:
        raise ValueError(f"bad amount: {text!r}")
    units = _digits_to_int(m[1])
    frac = m[2]
    cents = int(frac.ljust(2, "0")) if frac else 0
    return units * 100 + cents


def format_cents(cents):
    """セントの整数を "1234.56" の形の文字列にする。負なら先頭に "-" を付ける。"""
    sign = "-" if cents < 0 else ""
    units, frac = divmod(abs(cents), 100)
    return f"{sign}{_int_to_digits(units)}.{frac:02d}"
=== FILE: stock/parser.py ===
"""在庫取引ファイルの読み取り。

1行が1件の取引で、カンマ区切りの次の形式をとる。

    日付,種別,SKU,数量[,単価]

- 日付は YYYY-MM-DD
- 種別は IN（入庫）か OUT（出庫）。大文字小文字は区別しない
- 数量は1以上の整数
- 単価は IN のときだけ必須で、OUT には書かない。書式は money.parse_cents に従う

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


def _parse_cost(text, lineno):
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
    cost = None
    if kind == "IN":
        if len(fields) != 5:
            raise ParseError(lineno, "IN requires unit price")
        cost = _parse_cost(fields[4], lineno)
    elif len(fields) == 5:
        raise ParseError(lineno, "OUT must not have unit price")
    return Txn(lineno, date, kind, sku, qty, cost)


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
"""SKU ごとの在庫数と在庫金額の管理（先入先出法）。金額はセントの整数。"""

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
        # SKU ごとに、[残数, 単価] のロットを古い順に並べる。
        self._lots = {}

    def receive(self, sku, qty, unit_cost):
        """入庫。ロット列の末尾にロットを1つ足す。"""
        if qty < 1:
            raise ValueError(f"quantity must be positive: {qty!r}")
        if unit_cost < 0:
            raise ValueError(f"unit cost must not be negative: {unit_cost!r}")
        self._lots.setdefault(sku, deque()).append([qty, unit_cost])

    def ship(self, sku, qty):
        """出庫。古いロットから払い出し、(数量, 単価) の内訳を返す。

        在庫が足りなければ InsufficientStock。
        """
        if qty < 1:
            raise ValueError(f"quantity must be positive: {qty!r}")
        available = self.quantity(sku)
        if qty > available:
            raise InsufficientStock(sku, qty, available)
        lots = self._lots[sku]
        taken = []
        remaining = qty
        while remaining:
            lot = lots[0]
            n = min(lot[0], remaining)
            taken.append((n, lot[1]))
            lot[0] -= n
            remaining -= n
            if lot[0] == 0:
                lots.popleft()
        return taken

    def quantity(self, sku):
        return sum(qty for qty, _ in self._lots.get(sku, ()))

    def value(self, sku):
        return sum(qty * cost for qty, cost in self._lots.get(sku, ()))

    def lots(self, sku):
        """残っているロットを (数量, 単価) で古い順に返す。"""
        return [(qty, cost) for qty, cost in self._lots.get(sku, ()) if qty > 0]

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
    """取引を順に台帳へ反映し、(台帳, SKU ごとの出庫原価) を返す。原価はセントの整数。"""
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
=== END ===