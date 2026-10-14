=== FILE: inventory.py ===
from copy import deepcopy
from datetime import date


class Ledger:
    """Lot-tracked inventory ledger with expiration dates and multi-lot reservations."""

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
            "lot_id": lot_id,
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
            lot
            for lot in self._lots.values()
            if lot["sku"] == sku and lot["available"] > 0
        ]
        total_available = sum(lot["available"] for lot in candidates)
        if total_available < quantity:
            raise ValueError("insufficient available stock")

        candidates.sort(
            key=lambda lot: (
                lot["expires"] is None,
                lot["expires"] or date.max,
                lot["lot_id"],
            )
        )

        remaining = quantity
        allocations = []
        for lot in candidates:
            if remaining == 0:
                break
            take = min(lot["available"], remaining)
            lot["available"] -= take
            lot["held"] += take
            remaining -= take
            allocations.append((lot["lot_id"], take))

        allocations_tuple = tuple(allocations)
        self._reservations[reservation_id] = {
            "reservation_id": reservation_id,
            "sku": sku,
            "quantity": quantity,
            "status": "active",
            "allocations": allocations_tuple,
        }
        return allocations_tuple

    def cancel(self, reservation_id):
        if reservation_id not in self._reservations:
            raise ValueError("unknown reservation")
        reservation = self._reservations[reservation_id]
        if reservation["status"] == "cancelled":
            return reservation["allocations"]
        if reservation["status"] != "active":
            raise ValueError("cannot cancel committed reservation")

        for lot_id, qty in reservation["allocations"]:
            lot = self._lots[lot_id]
            lot["held"] -= qty
            if lot["expires"] is not None and lot["expires"] < self.today:
                lot["expired"] += qty
            else:
                lot["available"] += qty

        reservation["status"] = "cancelled"
        return reservation["allocations"]

    def commit(self, reservation_id):
        if reservation_id not in self._reservations:
            raise ValueError("unknown reservation")
        reservation = self._reservations[reservation_id]
        if reservation["status"] == "committed":
            return reservation["allocations"]
        if reservation["status"] != "active":
            raise ValueError("cannot commit cancelled reservation")

        for lot_id, qty in reservation["allocations"]:
            lot = self._lots[lot_id]
            lot["held"] -= qty
            lot["shipped"] += qty

        reservation["status"] = "committed"
        return reservation["allocations"]

    def advance(self, day):
        if day < self.today:
            raise ValueError("cannot go backward")
        self.today = day
        for lot in self._lots.values():
            if lot["expires"] is not None and lot["expires"] < day and lot["available"] > 0:
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
                "expires": lot["expires"].isoformat() if lot["expires"] is not None else None,
                "available": lot["available"],
                "held": lot["held"],
                "shipped": lot["shipped"],
                "expired": lot["expired"],
            })

        reservations = []
        for reservation_id in sorted(self._reservations):
            res = self._reservations[reservation_id]
            reservations.append({
                "reservation_id": reservation_id,
                "sku": res["sku"],
                "quantity": res["quantity"],
                "status": res["status"],
                "allocations": [
                    {"lot_id": lot_id, "quantity": qty}
                    for lot_id, qty in res["allocations"]
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

_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_QUANTITY_PATTERN = re.compile(r"[1-9][0-9]*")
_MAX_QUANTITY = 1_000_000_000


def _parse_non_empty(value):
    if not value:
        raise ValueError("empty string is not allowed")
    return value


def _parse_quantity(value):
    if not _QUANTITY_PATTERN.fullmatch(value):
        raise ValueError("invalid quantity format")
    quantity = int(value)
    if quantity > _MAX_QUANTITY:
        raise ValueError("quantity exceeds maximum")
    return quantity


def _parse_date(value):
    if not _DATE_PATTERN.fullmatch(value):
        raise ValueError("invalid date format")
    return date.fromisoformat(value)


def run(ledger, text, atomic=True):
    parsed_operations = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        for raw_cells in reader:
            if not raw_cells:
                continue
            cells = [cell.strip(" \t") for cell in raw_cells]
            operation = cells[0]
            if operation == "ADD":
                if len(cells) != 5:
                    raise ValueError("ADD requires 5 fields")
                lot_id = _parse_non_empty(cells[1])
                sku = _parse_non_empty(cells[2])
                quantity = _parse_quantity(cells[3])
                expires = None if cells[4] == "" else _parse_date(cells[4])
                parsed_operations.append(("ADD", (lot_id, sku, quantity, expires)))
            elif operation == "RESERVE":
                if len(cells) != 4:
                    raise ValueError("RESERVE requires 4 fields")
                reservation_id = _parse_non_empty(cells[1])
                sku = _parse_non_empty(cells[2])
                quantity = _parse_quantity(cells[3])
                parsed_operations.append(("RESERVE", (reservation_id, sku, quantity)))
            elif operation == "CANCEL":
                if len(cells) != 2:
                    raise ValueError("CANCEL requires 2 fields")
                reservation_id = _parse_non_empty(cells[1])
                parsed_operations.append(("CANCEL", (reservation_id,)))
            elif operation == "COMMIT":
                if len(cells) != 2:
                    raise ValueError("COMMIT requires 2 fields")
                reservation_id = _parse_non_empty(cells[1])
                parsed_operations.append(("COMMIT", (reservation_id,)))
            elif operation == "ADVANCE":
                if len(cells) != 2:
                    raise ValueError("ADVANCE requires 2 fields")
                day = _parse_date(cells[1])
                parsed_operations.append(("ADVANCE", (day,)))
            else:
                raise ValueError("unknown operation")
    except csv.Error as exc:
        raise ValueError("invalid CSV syntax") from exc

    if not parsed_operations:
        return []

    backup = ledger.copy() if atomic else None
    results = []
    try:
        for operation, args in parsed_operations:
            if operation == "ADD":
                result = ledger.add(*args)
            elif operation == "RESERVE":
                result = ledger.reserve(*args)
            elif operation == "CANCEL":
                result = ledger.cancel(*args)
            elif operation == "COMMIT":
                result = ledger.commit(*args)
            elif operation == "ADVANCE":
                result = ledger.advance(*args)
            results.append(result)
    except Exception:
        if atomic:
            ledger.replace_from(backup)
        raise

    return results
=== FILE: reporting.py ===
import csv
import io


def render(ledger):
    snapshot = ledger.snapshot()
    stock = {}
    for lot in snapshot["lots"]:
        row = stock.setdefault(
            lot["sku"],
            {
                "available": 0,
                "held": 0,
                "shipped": 0,
                "expired": 0,
            },
        )
        row["available"] += lot["available"]
        row["held"] += lot["held"]
        row["shipped"] += lot["shipped"]
        row["expired"] += lot["expired"]

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["sku", "available", "held", "shipped", "expired"])
    for sku in sorted(stock):
        row = stock[sku]
        writer.writerow([
            sku,
            row["available"],
            row["held"],
            row["shipped"],
            row["expired"],
        ])
    return output.getvalue()
=== END ===
