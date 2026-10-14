=== FILE: inventory.py ===
from copy import deepcopy
from datetime import date


class Ledger:
    """Lot-based inventory ledger with expiration dates and multi-lot reservations."""

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

        candidates = [
            (lot_id, lot)
            for lot_id, lot in self._lots.items()
            if lot["sku"] == sku
            and lot["available"] > 0
            and (lot["expires"] is None or lot["expires"] >= self.today)
        ]
        total_available = sum(lot["available"] for _, lot in candidates)
        if total_available < quantity:
            raise ValueError("insufficient available stock")

        candidates.sort(
            key=lambda item: (
                item[1]["expires"] is None,
                item[1]["expires"] or date.max,
                item[0],
            )
        )

        remaining = quantity
        allocations = []
        for lot_id, lot in candidates:
            if remaining == 0:
                break
            take = min(lot["available"], remaining)
            if take > 0:
                lot["available"] -= take
                lot["held"] += take
                allocations.append((lot_id, take))
                remaining -= take

        allocations_tuple = tuple(allocations)
        self._reservations[reservation_id] = {
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
        status = reservation["status"]
        if status == "cancelled":
            return reservation["allocations"]
        if status != "active":
            raise ValueError("cannot cancel committed reservation")

        for lot_id, qty in reservation["allocations"]:
            lot = self._lots[lot_id]
            lot["held"] -= qty
            if lot["expires"] is None or lot["expires"] >= self.today:
                lot["available"] += qty
            else:
                lot["expired"] += qty

        reservation["status"] = "cancelled"
        return reservation["allocations"]

    def commit(self, reservation_id):
        if reservation_id not in self._reservations:
            raise ValueError("unknown reservation")
        reservation = self._reservations[reservation_id]
        status = reservation["status"]
        if status == "committed":
            return reservation["allocations"]
        if status != "active":
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
            if lot["expires"] is not None and lot["expires"] < day:
                if lot["available"] > 0:
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
            lots.append(
                {
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
                }
            )

        reservations = []
        for reservation_id in sorted(self._reservations):
            res = self._reservations[reservation_id]
            reservations.append(
                {
                    "reservation_id": reservation_id,
                    "sku": res["sku"],
                    "quantity": res["quantity"],
                    "status": res["status"],
                    "allocations": [
                        {"lot_id": lot_id, "quantity": qty}
                        for lot_id, qty in res["allocations"]
                    ],
                }
            )

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

_QTY_RE = re.compile(r"[1-9][0-9]*")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _parse_non_empty(value):
    if not value:
        raise ValueError("empty string not allowed")
    return value


def _parse_quantity(value):
    if not _QTY_RE.fullmatch(value):
        raise ValueError("invalid quantity format")
    qty = int(value)
    if not (1 <= qty <= 1_000_000_000):
        raise ValueError("quantity out of range")
    return qty


def _parse_date(value):
    if not _DATE_RE.fullmatch(value):
        raise ValueError("invalid date format")
    return date.fromisoformat(value)


def _parse_operations(text):
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    parsed = []
    try:
        for raw_cells in reader:
            if not raw_cells:
                continue
            cells = [cell.strip(" \t") for cell in raw_cells]
            op = cells[0]
            if op == "ADD":
                if len(cells) != 5:
                    raise ValueError("ADD requires 5 fields")
                lot_id = _parse_non_empty(cells[1])
                sku = _parse_non_empty(cells[2])
                qty = _parse_quantity(cells[3])
                expires = None if cells[4] == "" else _parse_date(cells[4])
                parsed.append((op, (lot_id, sku, qty, expires)))
            elif op == "RESERVE":
                if len(cells) != 4:
                    raise ValueError("RESERVE requires 4 fields")
                reservation_id = _parse_non_empty(cells[1])
                sku = _parse_non_empty(cells[2])
                qty = _parse_quantity(cells[3])
                parsed.append((op, (reservation_id, sku, qty)))
            elif op == "CANCEL":
                if len(cells) != 2:
                    raise ValueError("CANCEL requires 2 fields")
                reservation_id = _parse_non_empty(cells[1])
                parsed.append((op, (reservation_id,)))
            elif op == "COMMIT":
                if len(cells) != 2:
                    raise ValueError("COMMIT requires 2 fields")
                reservation_id = _parse_non_empty(cells[1])
                parsed.append((op, (reservation_id,)))
            elif op == "ADVANCE":
                if len(cells) != 2:
                    raise ValueError("ADVANCE requires 2 fields")
                day = _parse_date(cells[1])
                parsed.append((op, (day,)))
            else:
                raise ValueError("unknown operation")
    except csv.Error as exc:
        raise ValueError("CSV syntax error") from exc
    return parsed


def run(ledger, text, atomic=True):
    parsed = _parse_operations(text)
    if not parsed:
        return []

    target = ledger.copy() if atomic else ledger
    results = []
    for op, args in parsed:
        if op == "ADD":
            result = target.add(*args)
        elif op == "RESERVE":
            result = target.reserve(*args)
        elif op == "CANCEL":
            result = target.cancel(*args)
        elif op == "COMMIT":
            result = target.commit(*args)
        elif op == "ADVANCE":
            result = target.advance(*args)
        results.append(result)

    if atomic:
        ledger.replace_from(target)
    return results
=== FILE: reporting.py ===
import csv
import io


def render(ledger):
    stock = {}
    for lot in ledger.snapshot()["lots"]:
        sku = lot["sku"]
        row = stock.setdefault(
            sku,
            {
                "sku": sku,
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
            row["sku"],
            row["available"],
            row["held"],
            row["shipped"],
            row["expired"],
        ])
    return output.getvalue()
=== END ===
