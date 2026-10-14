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
