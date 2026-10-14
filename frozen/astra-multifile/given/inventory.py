from copy import deepcopy


class Ledger:
    """Single-lot reservations without expiration."""

    def __init__(self, today):
        self.today = today
        self._lots = {}
        self._reservations = {}

    def add(self, lot_id, sku, quantity):
        if lot_id in self._lots:
            raise ValueError("duplicate lot")
        self._lots[lot_id] = {
            "sku": sku,
            "received": quantity,
            "available": quantity,
            "held": 0,
            "shipped": 0,
            "expired": 0,
        }

    def reserve(self, reservation_id, sku, quantity):
        if reservation_id in self._reservations:
            raise ValueError("duplicate reservation")
        for lot_id, lot in self._lots.items():
            if lot["sku"] == sku and lot["available"] >= quantity:
                lot["available"] -= quantity
                lot["held"] += quantity
                self._reservations[reservation_id] = {
                    "sku": sku,
                    "quantity": quantity,
                    "status": "active",
                    "lot_id": lot_id,
                }
                return lot_id
        raise ValueError("insufficient single lot")

    def _finish(self, reservation_id, status):
        if reservation_id not in self._reservations:
            raise ValueError("unknown reservation")
        reservation = self._reservations[reservation_id]
        if reservation["status"] == status:
            return reservation["lot_id"]
        if reservation["status"] != "active":
            raise ValueError("closed reservation")
        lot = self._lots[reservation["lot_id"]]
        quantity = reservation["quantity"]
        lot["held"] -= quantity
        target = "available" if status == "cancelled" else "shipped"
        lot[target] += quantity
        reservation["status"] = status
        return reservation["lot_id"]

    def cancel(self, reservation_id):
        return self._finish(reservation_id, "cancelled")

    def commit(self, reservation_id):
        return self._finish(reservation_id, "committed")

    def advance(self, day):
        if day < self.today:
            raise ValueError("cannot go backward")
        self.today = day

    def copy(self):
        return deepcopy(self)

    def replace_from(self, other):
        state = deepcopy(other.__dict__)
        self.__dict__.clear()
        self.__dict__.update(state)

    def snapshot(self):
        stock = {}
        for lot in self._lots.values():
            row = stock.setdefault(
                lot["sku"],
                {
                    "sku": lot["sku"],
                    "available": 0,
                    "held": 0,
                    "shipped": 0,
                    "expired": 0,
                },
            )
            for field in ("available", "held", "shipped", "expired"):
                row[field] += lot[field]
        reservations = []
        for reservation_id in sorted(self._reservations):
            row = deepcopy(self._reservations[reservation_id])
            row["reservation_id"] = reservation_id
            reservations.append(row)
        return {
            "today": self.today.isoformat(),
            "stock": [stock[sku] for sku in sorted(stock)],
            "reservations": reservations,
        }
