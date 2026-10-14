=== FILE: inventory.py ===
from copy import deepcopy
from datetime import date


class Ledger:
    """Expiring lots with multi-lot reservations."""

    def __init__(self, today):
        self.today = today
        self._lots = {}
        self._reservations = {}

    def _is_expired(self, lot, today=None):
        if today is None:
            today = self.today
        return lot["expires"] is not None and lot["expires"] < today

    @staticmethod
    def _order_key(item):
        lot_id, lot = item
        if lot["expires"] is None:
            return (1, date.max, lot_id)
        return (0, lot["expires"], lot_id)

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
                if lot["sku"] == sku
                and lot["available"] > 0
                and not self._is_expired(lot)
            ),
            key=self._order_key,
        )
        total = sum(lot["available"] for _, lot in candidates)
        if total < quantity:
            raise ValueError("insufficient stock")
        allocations = []
        remaining = quantity
        for lot_id, lot in candidates:
            if remaining == 0:
                break
            used = min(remaining, lot["available"])
            if used <= 0:
                continue
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

    def _get_reservation(self, reservation_id):
        if reservation_id not in self._reservations:
            raise ValueError("unknown reservation")
        return self._reservations[reservation_id]

    def cancel(self, reservation_id):
        reservation = self._get_reservation(reservation_id)
        if reservation["status"] == "cancelled":
            return reservation["allocations"]
        if reservation["status"] != "active":
            raise ValueError("closed reservation")
        for lot_id, used in reservation["allocations"]:
            lot = self._lots[lot_id]
            lot["held"] -= used
            if self._is_expired(lot):
                lot["expired"] += used
            else:
                lot["available"] += used
        reservation["status"] = "cancelled"
        return reservation["allocations"]

    def commit(self, reservation_id):
        reservation = self._get_reservation(reservation_id)
        if reservation["status"] == "committed":
            return reservation["allocations"]
        if reservation["status"] != "active":
            raise ValueError("closed reservation")
        for lot_id, used in reservation["allocations"]:
            lot = self._lots[lot_id]
            lot["held"] -= used
            lot["shipped"] += used
        reservation["status"] = "committed"
        return reservation["allocations"]

    def advance(self, day):
        if day < self.today:
            raise ValueError("cannot go backward")
        self.today = day
        for lot in self._lots.values():
            if self._is_expired(lot) and lot["available"]:
                lot["expired"] += lot["available"]
                lot["available"] = 0

    def copy(self):
        clone = Ledger(self.today)
        clone.replace_from(self)
        return clone

    def replace_from(self, other):
        today = other.today
        lots = deepcopy(other._lots)
        reservations = deepcopy(other._reservations)
        self.today = today
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
                    {"lot_id": lot_id, "quantity": used}
                    for lot_id, used in reservation["allocations"]
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

_QUANTITY = re.compile(r"[1-9][0-9]*")
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_MAX_QUANTITY = 1_000_000_000

_FIELD_COUNTS = {
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
        raise ValueError("quantity out of range")
    return value


def _parse_date(cell):
    match = _DATE.fullmatch(cell)
    if match is None:
        raise ValueError("invalid date")
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        raise ValueError("invalid date") from None


def _parse(text):
    operations = []
    try:
        for cells in csv.reader(io.StringIO(text, newline=""), strict=True):
            if cells == []:
                continue
            cells = [cell.strip(" \t") for cell in cells]
            operation = cells[0]
            expected = _FIELD_COUNTS.get(operation)
            if expected is None:
                raise ValueError("unknown operation")
            if len(cells) != expected:
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
    except csv.Error as error:
        raise ValueError(f"invalid CSV: {error}") from None
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
    if atomic:
        work = ledger.copy()
        results = _apply(work, operations)
        ledger.replace_from(work)
        return results
    return _apply(ledger, operations)
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