=== FILE: stock/money.py ===
"""金額の表現。金額はセント（1単位の 1/100）の整数で扱う。"""

import re

_AMOUNT_RE = re.compile(r"([0-9]+)(?:\.([0-9]{1,2}))?")

# int と str の相互変換で一度に扱う桁数。int_max_str_digits の最小値 640 より小さくとる。
_CHUNK_DIGITS = 500
_CHUNK_BITS = 1600


def _digits_to_int(digits):
    """ASCII の数字の列を int にする。桁数の上限に掛からないよう分割して変換する。"""
    if len(digits) <= _CHUNK_DIGITS:
        return int(digits)
    k = len(digits) // 2
    return _digits_to_int(digits[:-k]) * 10**k + _digits_to_int(digits[-k:])


def _int_to_digits(n):
    """0 以上の int を10進の数字の列にする。桁数の上限に掛からないよう分割して変換する。"""
    if n.bit_length() <= _CHUNK_BITS:
        return str(n)
    k = n.bit_length() * 3 // 10 // 2
    hi, lo = divmod(n, 10**k)
    return _int_to_digits(hi) + _int_to_digits(lo).zfill(k)


def parse_cents(text):
    """"12", "12.5", "12.50" の形の文字列をセントの整数にする。それ以外は ValueError。"""
    m = _AMOUNT_RE.fullmatch(text)
    if m is None:
        raise ValueError(f"bad amount: {text!r}")
    whole, frac = m.group(1), m.group(2) or ""
    return _digits_to_int(whole) * 100 + int(frac.ljust(2, "0"))


def format_cents(cents):
    """セントの整数を "1234.56" の形の文字列にする。負なら先頭に "-" を付ける。"""
    if cents < 0:
        return "-" + format_cents(-cents)
    whole, frac = divmod(cents, 100)
    return f"{_int_to_digits(whole)}.{frac:02d}"
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
"""SKU ごとの在庫ロットの管理（先入先出法）。金額はセントの整数。"""

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
        # SKU -> [数量, 単価] のロットを古い順に並べた deque
        self._lots = {}

    def receive(self, sku, qty, unit_cost):
        """入庫。ロット列の末尾にロットを1つ足す。"""
        if qty < 1:
            raise ValueError(f"quantity must be positive: {qty!r}")
        if unit_cost < 0:
            raise ValueError(f"unit cost must not be negative: {unit_cost!r}")
        self._lots.setdefault(sku, deque()).append([qty, unit_cost])

    def ship(self, sku, qty):
        """出庫。古いロットから払い出し、(数量, 単価) の内訳のリストを返す。

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
        while remaining > 0:
            lot = lots[0]
            n = min(lot[0], remaining)
            taken.append((n, lot[1]))
            remaining -= n
            lot[0] -= n
            if lot[0] == 0:
                lots.popleft()
        return taken

    def quantity(self, sku):
        return sum(q for q, _ in self._lots.get(sku, ()))

    def value(self, sku):
        return sum(q * c for q, c in self._lots.get(sku, ()))

    def lots(self, sku):
        """残っているロットを (数量, 単価) で古い順に返す。"""
        return [(q, c) for q, c in self._lots.get(sku, ()) if q > 0]

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
            cost = sum(q * c for q, c in taken)
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