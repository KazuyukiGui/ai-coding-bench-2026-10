=== FILE: inventory.py ===
from copy import deepcopy
from datetime import date


class Ledger:
    """Expiring lots with reservations spanning multiple lots."""

    def __init__(self, today):
        self.today = today
        self._lots = {}
        self._reservations = {}

    def _is_expired(self, lot):
        return lot["expires"] is not None and lot["expires"] < self.today

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
        candidates = [
            (lot_id, lot)
            for lot_id, lot in self._lots.items()
            if lot["sku"] == sku
            and lot["available"] > 0
            and not self._is_expired(lot)
        ]
        if sum(lot["available"] for _, lot in candidates) < quantity:
            raise ValueError("insufficient stock")
        candidates.sort(
            key=lambda item: (
                item[1]["expires"] is None,
                item[1]["expires"] or date.min,
                item[0],
            )
        )
        allocations = []
        remaining = quantity
        for lot_id, lot in candidates:
            if remaining == 0:
                break
            used = min(remaining, lot["available"])
            allocations.append((lot_id, used))
            remaining -= used
        for lot_id, used in allocations:
            lot = self._lots[lot_id]
            lot["available"] -= used
            lot["held"] += used
        allocations = tuple(allocations)
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
            lot["held"] -= quantity
            if status == "committed":
                lot["shipped"] += quantity
            elif self._is_expired(lot):
                lot["expired"] += quantity
            else:
                lot["available"] += quantity
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
            if self._is_expired(lot):
                lot["expired"] += lot["available"]
                lot["available"] = 0

    def copy(self):
        clone = Ledger(self.today)
        clone._lots = deepcopy(self._lots)
        clone._reservations = deepcopy(self._reservations)
        return clone

    def replace_from(self, other):
        if other is self:
            return
        lots = deepcopy(other._lots)
        reservations = deepcopy(other._reservations)
        self.today = other.today
        self._lots = lots
        self._reservations = reservations

    def snapshot(self):
        lots = []
        for lot_id in sorted(self._lots):
            lot = self._lots[lot_id]
            lots.append({
                "lot_id": lot_id,
                "sku": lot["sku"],
                "received": lot["received"],
                "expires": (
                    None if lot["expires"] is None
                    else lot["expires"].isoformat()
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

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_QUANTITY = re.compile(r"[1-9][0-9]*")
_MAX_QUANTITY = 1_000_000_000

_ARITY = {
    "ADD": 5,
    "RESERVE": 4,
    "CANCEL": 2,
    "COMMIT": 2,
    "ADVANCE": 2,
}


def _parse_name(cell):
    if cell == "":
        raise ValueError("empty identifier")
    return cell


def _parse_quantity(cell):
    if len(cell) > 10 or _QUANTITY.fullmatch(cell) is None:
        raise ValueError("invalid quantity")
    value = int(cell)
    if value > _MAX_QUANTITY:
        raise ValueError("quantity too large")
    return value


def _parse_date(cell):
    if _DATE.fullmatch(cell) is None:
        raise ValueError("invalid date")
    try:
        return date(int(cell[0:4]), int(cell[5:7]), int(cell[8:10]))
    except ValueError:
        raise ValueError("invalid date") from None


def _parse(text):
    operations = []
    try:
        records = list(
            csv.reader(io.StringIO(text, newline=""), strict=True)
        )
    except csv.Error as error:
        raise ValueError("invalid CSV") from error
    for cells in records:
        if cells == []:
            continue
        cells = [cell.strip(" \t") for cell in cells]
        operation = cells[0]
        if operation not in _ARITY:
            raise ValueError("unknown operation")
        if len(cells) != _ARITY[operation]:
            raise ValueError("wrong field count")
        if operation == "ADD":
            expires = None if cells[4] == "" else _parse_date(cells[4])
            args = (
                _parse_name(cells[1]),
                _parse_name(cells[2]),
                _parse_quantity(cells[3]),
                expires,
            )
        elif operation == "RESERVE":
            args = (
                _parse_name(cells[1]),
                _parse_name(cells[2]),
                _parse_quantity(cells[3]),
            )
        elif operation in ("CANCEL", "COMMIT"):
            args = (_parse_name(cells[1]),)
        else:
            args = (_parse_date(cells[1]),)
        operations.append((operation, args))
    return operations


def _apply(ledger, operations):
    results = []
    for operation, args in operations:
        if operation == "ADD":
            result = ledger.add(*args)
        elif operation == "RESERVE":
            result = ledger.reserve(*args)
        elif operation == "CANCEL":
            result = ledger.cancel(*args)
        elif operation == "COMMIT":
            result = ledger.commit(*args)
        else:
            result = ledger.advance(*args)
        results.append(result)
    return results


def run(ledger, text, atomic=True):
    operations = _parse(text)
    if not operations:
        return []
    if not atomic:
        return _apply(ledger, operations)
    work = ledger.copy()
    results = _apply(work, operations)
    ledger.replace_from(work)
    return results
=== FILE: reporting.py ===
import csv
import io

_FIELDS = ("available", "held", "shipped", "expired")


def render(ledger):
    stock = {}
    for lot in ledger.snapshot()["lots"]:
        row = stock.setdefault(lot["sku"], dict.fromkeys(_FIELDS, 0))
        for field in _FIELDS:
            row[field] += lot[field]
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["sku", *_FIELDS])
    for sku in sorted(stock):
        row = stock[sku]
        writer.writerow([sku, *(row[field] for field in _FIELDS)])
    return output.getvalue()
=== END ===