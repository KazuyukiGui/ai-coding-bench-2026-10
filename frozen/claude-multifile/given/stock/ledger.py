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
