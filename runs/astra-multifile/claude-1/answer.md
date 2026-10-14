=== FILE: inventory.py ===
from datetime import date


def _lot_order(item):
    lot_id, lot = item
    expires = lot["expires"]
    if expires is None:
        return (1, date.max, lot_id)
    return (0, expires, lot_id)


class Ledger:
    """Lot inventory with expiration and multi-lot reservations."""

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
        return None

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
        candidates.sort(key=_lot_order)
        total = sum(lot["available"] for _, lot in candidates)
        if total < quantity:
            raise ValueError("insufficient stock")
        allocations = []
        remaining = quantity
        for lot_id, lot in candidates:
            if remaining == 0:
                break
            used = min(lot["available"], remaining)
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

    def _reservation(self, reservation_id):
        if reservation_id not in self._reservations:
            raise ValueError("unknown reservation")
        return self._reservations[reservation_id]

    def cancel(self, reservation_id):
        reservation = self._reservation(reservation_id)
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
        reservation = self._reservation(reservation_id)
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
        return None

    def _state(self):
        lots = {lot_id: dict(lot) for lot_id, lot in self._lots.items()}
        reservations = {
            reservation_id: dict(reservation)
            for reservation_id, reservation in self._reservations.items()
        }
        return self.today, lots, reservations

    def copy(self):
        clone = Ledger.__new__(type(self))
        clone.today, clone._lots, clone._reservations = self._state()
        return clone

    def replace_from(self, other):
        today, lots, reservations = other._state()
        self.today = today
        self._lots = lots
        self._reservations = reservations
        return None

    def snapshot(self):
        lots = []
        for lot_id in sorted(self._lots):
            lot = self._lots[lot_id]
            expires = lot["expires"]
            lots.append({
                "lot_id": lot_id,
                "sku": lot["sku"],
                "received": lot["received"],
                "expires": None if expires is None else expires.isoformat(),
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

_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_QUANTITY = re.compile(r"[1-9][0-9]*")
_MAX_QUANTITY = 1_000_000_000

_ARITY = {
    "ADD": 5,
    "RESERVE": 4,
    "CANCEL": 2,
    "COMMIT": 2,
    "ADVANCE": 2,
}


def _parse_date(cell):
    match = _DATE.fullmatch(cell)
    if match is None:
        raise ValueError("invalid date")
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        raise ValueError("invalid date") from None


def _parse_quantity(cell):
    if len(cell) > 10 or _QUANTITY.fullmatch(cell) is None:
        raise ValueError("invalid quantity")
    quantity = int(cell)
    if quantity > _MAX_QUANTITY:
        raise ValueError("quantity out of range")
    return quantity


def _parse_name(cell):
    if cell == "":
        raise ValueError("empty identifier")
    return cell


def _parse_record(cells):
    operation = cells[0]
    if operation not in _ARITY or len(cells) != _ARITY[operation]:
        raise ValueError("unknown operation or wrong field count")
    if operation == "ADD":
        expires = None if cells[4] == "" else _parse_date(cells[4])
        return (
            "add",
            (
                _parse_name(cells[1]),
                _parse_name(cells[2]),
                _parse_quantity(cells[3]),
                expires,
            ),
        )
    if operation == "RESERVE":
        return (
            "reserve",
            (
                _parse_name(cells[1]),
                _parse_name(cells[2]),
                _parse_quantity(cells[3]),
            ),
        )
    if operation == "CANCEL":
        return ("cancel", (_parse_name(cells[1]),))
    if operation == "COMMIT":
        return ("commit", (_parse_name(cells[1]),))
    return ("advance", (_parse_date(cells[1]),))


def _parse(text):
    commands = []
    try:
        for cells in csv.reader(io.StringIO(text, newline=""), strict=True):
            if cells == []:
                continue
            cells = [cell.strip(" \t") for cell in cells]
            commands.append(_parse_record(cells))
    except csv.Error as error:
        raise ValueError(f"invalid CSV: {error}") from None
    return commands


def _apply(ledger, commands):
    results = []
    for name, args in commands:
        results.append(getattr(ledger, name)(*args))
    return results


def run(ledger, text, atomic=True):
    commands = _parse(text)
    if not commands:
        return []
    if not atomic:
        return _apply(ledger, commands)
    backup = ledger.copy()
    try:
        return _apply(ledger, commands)
    except BaseException:
        ledger.replace_from(backup)
        raise
=== FILE: reporting.py ===
import csv
import io

_FIELDS = ("available", "held", "shipped", "expired")


def render(ledger):
    totals = {}
    for lot in ledger.snapshot()["lots"]:
        row = totals.setdefault(lot["sku"], dict.fromkeys(_FIELDS, 0))
        for field in _FIELDS:
            row[field] += lot[field]
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["sku", *_FIELDS])
    for sku in sorted(totals):
        row = totals[sku]
        writer.writerow([sku, *(row[field] for field in _FIELDS)])
    return output.getvalue()
=== END ===