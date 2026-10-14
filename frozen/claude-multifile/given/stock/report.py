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
