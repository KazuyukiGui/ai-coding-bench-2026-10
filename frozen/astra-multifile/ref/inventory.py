from copy import deepcopy


class Ledger:
    def __init__(self, today):
        self.today = today
        self._lots = {}
        self._reservations = {}

    def add(self, lot_id, sku, quantity, expires=None):
        if lot_id in self._lots:
            raise ValueError("duplicate lot")
        if expires is not None and expires < self.today:
            raise ValueError("already expired")
        self._lots[lot_id] = {
            "lot_id": lot_id,
            "sku": sku,
            "received": quantity,
            "expires": expires,
            "available": quantity,
            "held": 0,
            "shipped": 0,
            "expired": 0,
        }

    def _expired(self, lot):
        expires = lot["expires"]
        return expires is not None and expires < self.today

    def reserve(self, reservation_id, sku, quantity):
        if reservation_id in self._reservations:
            raise ValueError("duplicate reservation")
        candidates = [
            lot for lot in self._lots.values()
            if lot["sku"] == sku
            and lot["available"] > 0
            and not self._expired(lot)
        ]
        candidates.sort(
            key=lambda lot: (
                lot["expires"] is None,
                lot["expires"],
                lot["lot_id"],
            )
        )
        if sum(lot["available"] for lot in candidates) < quantity:
            raise ValueError("insufficient stock")

        remaining = quantity
        allocations = []
        for lot in candidates:
            if remaining == 0:
                break
            taken = min(remaining, lot["available"])
            lot["available"] -= taken
            lot["held"] += taken
            allocations.append((lot["lot_id"], taken))
            remaining -= taken
        allocations = tuple(allocations)
        self._reservations[reservation_id] = {
            "reservation_id": reservation_id,
            "sku": sku,
            "quantity": quantity,
            "status": "active",
            "allocations": allocations,
        }
        return allocations

    def _finish(self, reservation_id, status):
        if reservation_id not in self._reservations:
            raise ValueError("unknown reservation")
        reservation = self._reservations[reservation_id]
        if reservation["status"] == status:
            return reservation["allocations"]
        if reservation["status"] != "active":
            raise ValueError("closed reservation")

        for lot_id, quantity in reservation["allocations"]:
            lot = self._lots[lot_id]
            lot["held"] -= quantity
            if status == "committed":
                destination = "shipped"
            elif self._expired(lot):
                destination = "expired"
            else:
                destination = "available"
            lot[destination] += quantity
        reservation["status"] = status
        return reservation["allocations"]

    def cancel(self, reservation_id):
        return self._finish(reservation_id, "cancelled")

    def commit(self, reservation_id):
        return self._finish(reservation_id, "committed")

    def advance(self, day):
        if day < self.today:
            raise ValueError("cannot go backward")
        self.today = day
        for lot in self._lots.values():
            if self._expired(lot):
                lot["expired"] += lot["available"]
                lot["available"] = 0

    def copy(self):
        return deepcopy(self)

    def replace_from(self, other):
        state = deepcopy(other.__dict__)
        self.__dict__.clear()
        self.__dict__.update(state)

    def snapshot(self):
        lots = []
        for lot_id in sorted(self._lots):
            row = self._lots[lot_id].copy()
            expires = row["expires"]
            row["expires"] = expires.isoformat() if expires is not None else None
            lots.append(row)

        reservations = []
        for reservation_id in sorted(self._reservations):
            reservation = self._reservations[reservation_id]
            row = reservation.copy()
            row["allocations"] = [
                {"lot_id": lot_id, "quantity": quantity}
                for lot_id, quantity in reservation["allocations"]
            ]
            reservations.append(row)
        return {
            "today": self.today.isoformat(),
            "lots": lots,
            "reservations": reservations,
        }
