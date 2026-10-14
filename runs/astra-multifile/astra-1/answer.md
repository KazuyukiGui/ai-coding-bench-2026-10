=== FILE: inventory.py ===
from copy import deepcopy
from datetime import date


class Ledger:
    """Inventory ledger with expiring lots and multi-lot reservations."""

    def __init__(self, today):
        self.today = today
        self._lots = {}
        self._reservations = {}

    def add(self, lot_id, sku, quantity, expires=None):
        if lot_id in self._lots:
            raise ValueError("duplicate lot")
        if expires is not None and expires < self.today:
            raise ValueError("lot already expired")
        self._lots[lot_id] = {
            "sku": sku,
            "received": quantity,
            "expires": expires,
            "available": quantity,
            "held": 0,
            "shipped": 0,
            "expired": 0,
        }

    def reserve(self, reservation_id, sku, quantity):
        if reservation_id in self._reservations:
            raise ValueError("duplicate reservation")

        candidates = sorted(
            (
                (lot_id, lot)
                for lot_id, lot in self._lots.items()
                if lot["sku"] == sku and lot["available"] > 0
            ),
            key=lambda item: (
                item[1]["expires"] is None,
                item[1]["expires"] or date.max,
                item[0],
            ),
        )
        remaining = quantity
        allocations = []
        for lot_id, lot in candidates:
            used = min(remaining, lot["available"])
            allocations.append((lot_id, used))
            remaining -= used
            if remaining == 0:
                break

        if remaining:
            raise ValueError("insufficient stock")

        allocations = tuple(allocations)
        for lot_id, used in allocations:
            lot = self._lots[lot_id]
            lot["available"] -= used
            lot["held"] += used
        self._reservations[reservation_id] = {
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
            if status == "committed":
                target = "shipped"
            elif lot["expires"] is not None and lot["expires"] < self.today:
                target = "expired"
            else:
                target = "available"
            lot["held"] -= quantity
            lot[target] += quantity

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
            if lot["expires"] is not None and lot["expires"] < day:
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
            lot = self._lots[lot_id]
            lots.append({
                "lot_id": lot_id,
                "sku": lot["sku"],
                "received": lot["received"],
                "expires": (
                    lot["expires"].isoformat()
                    if lot["expires"] is not None
                    else None
                ),
                "available": lot["available"],
                "held": lot["held"],
                "shipped": lot["shipped"],
                "expired": lot["expired"],
            })

        reservations = []
        for reservation_id in sorted(self._reservations):
            reservation = self._reservations[reservation_id]
            reservations.append({
                "reservation_id": reservation_id,
                "sku": reservation["sku"],
                "quantity": reservation["quantity"],
                "status": reservation["status"],
                "allocations": [
                    {"lot_id": lot_id, "quantity": quantity}
                    for lot_id, quantity in reservation["allocations"]
                ],
            })

        return {
            "today": self.today.isoformat(),
            "lots": lots,
            "reservations": reservations,
        }
=== FILE: operations.py ===
import csv
import io
import re
from datetime import date


def _nonempty(value):
    if not value:
        raise ValueError("empty ID or SKU")
    return value


def _quantity(value):
    if len(value) > 10 or re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise ValueError("invalid quantity")
    quantity = int(value)
    if quantity > 1_000_000_000:
        raise ValueError("quantity out of range")
    return quantity


def _day(value):
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("invalid date format")
    return date.fromisoformat(value)


def _parse(text):
    operations = []
    field_counts = {
        "ADD": 5,
        "RESERVE": 4,
        "CANCEL": 2,
        "COMMIT": 2,
        "ADVANCE": 2,
    }

    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        for cells in reader:
            if cells == []:
                continue
            cells = [cell.strip(" \t") for cell in cells]
            operation = cells[0]
            if operation not in field_counts:
                raise ValueError("unknown operation")
            if len(cells) != field_counts[operation]:
                raise ValueError("wrong field count")

            if operation == "ADD":
                arguments = (
                    _nonempty(cells[1]),
                    _nonempty(cells[2]),
                    _quantity(cells[3]),
                    _day(cells[4]) if cells[4] else None,
                )
            elif operation == "RESERVE":
                arguments = (
                    _nonempty(cells[1]),
                    _nonempty(cells[2]),
                    _quantity(cells[3]),
                )
            elif operation in ("CANCEL", "COMMIT"):
                arguments = (_nonempty(cells[1]),)
            else:
                arguments = (_day(cells[1]),)

            operations.append((operation.lower(), arguments))
    except csv.Error as exc:
        raise ValueError("invalid CSV") from exc

    return operations


def run(ledger, text, atomic=True):
    operations = _parse(text)
    if not operations:
        return []

    target = ledger.copy() if atomic else ledger
    results = []
    for method, arguments in operations:
        results.append(getattr(target, method)(*arguments))

    if atomic:
        ledger.replace_from(target)
    return results
=== FILE: reporting.py ===
import csv
import io


def render(ledger):
    fields = ("available", "held", "shipped", "expired")
    stock = {}
    for lot in ledger.snapshot()["lots"]:
        totals = stock.setdefault(lot["sku"], dict.fromkeys(fields, 0))
        for field in fields:
            totals[field] += lot[field]

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["sku", *fields])
    for sku in sorted(stock):
        writer.writerow([sku, *(stock[sku][field] for field in fields)])
    return output.getvalue()
=== END ===