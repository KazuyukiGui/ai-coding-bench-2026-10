=== FILE: inventory.py ===
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
            raise ValueError("lot is already expired")

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
            if lot["sku"] == sku and lot["available"] > 0
        ]
        candidates.sort(
            key=lambda item: (
                item[1]["expires"] is None,
                item[1]["expires"] if item[1]["expires"] is not None else self.today,
                item[0],
            )
        )

        if sum(lot["available"] for _, lot in candidates) < quantity:
            raise ValueError("insufficient inventory")

        remaining = quantity
        allocations = []
        for lot_id, lot in candidates:
            used = min(lot["available"], remaining)
            if used:
                lot["available"] -= used
                lot["held"] += used
                allocations.append((lot_id, used))
                remaining -= used
            if remaining == 0:
                break

        allocation_tuple = tuple(allocations)
        self._reservations[reservation_id] = {
            "sku": sku,
            "quantity": quantity,
            "status": "active",
            "allocations": allocation_tuple,
        }
        return allocation_tuple

    def cancel(self, reservation_id):
        if reservation_id not in self._reservations:
            raise ValueError("unknown reservation")

        reservation = self._reservations[reservation_id]
        allocations = reservation["allocations"]

        if reservation["status"] == "cancelled":
            return allocations
        if reservation["status"] != "active":
            raise ValueError("reservation is committed")

        for lot_id, quantity in allocations:
            lot = self._lots[lot_id]
            lot["held"] -= quantity
            if lot["expires"] is not None and lot["expires"] < self.today:
                lot["expired"] += quantity
            else:
                lot["available"] += quantity

        reservation["status"] = "cancelled"
        return allocations

    def commit(self, reservation_id):
        if reservation_id not in self._reservations:
            raise ValueError("unknown reservation")

        reservation = self._reservations[reservation_id]
        allocations = reservation["allocations"]

        if reservation["status"] == "committed":
            return allocations
        if reservation["status"] != "active":
            raise ValueError("reservation is cancelled")

        for lot_id, quantity in allocations:
            lot = self._lots[lot_id]
            lot["held"] -= quantity
            lot["shipped"] += quantity

        reservation["status"] = "committed"
        return allocations

    def advance(self, day):
        if day < self.today:
            raise ValueError("cannot go backward")

        for lot in self._lots.values():
            if lot["expires"] is not None and lot["expires"] < day:
                lot["expired"] += lot["available"]
                lot["available"] = 0

        self.today = day
        return None

    def copy(self):
        return deepcopy(self)

    def replace_from(self, other):
        state = deepcopy(other.__dict__)
        self.__dict__.clear()
        self.__dict__.update(state)
        return None

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
            reservation = self._reservations[reservation_id]
            reservations.append(
                {
                    "reservation_id": reservation_id,
                    "sku": reservation["sku"],
                    "quantity": reservation["quantity"],
                    "status": reservation["status"],
                    "allocations": [
                        {"lot_id": lot_id, "quantity": quantity}
                        for lot_id, quantity in reservation["allocations"]
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


_QUANTITY_PATTERN = re.compile(r"[1-9][0-9]*")
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _quantity(value):
    if _QUANTITY_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid quantity")
    quantity = int(value)
    if quantity > 1_000_000_000:
        raise ValueError("invalid quantity")
    return quantity


def _date(value):
    if _DATE_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid date") from exc


def _nonempty(value):
    if value == "":
        raise ValueError("empty identifier or SKU")
    return value


def _parse(text):
    operations = []

    try:
        records = csv.reader(io.StringIO(text, newline=""), strict=True)
        for record in records:
            if record == []:
                continue

            cells = [cell.strip(" \t") for cell in record]
            operation = cells[0]

            if operation == "ADD":
                if len(cells) != 5:
                    raise ValueError("wrong field count")
                expires = None if cells[4] == "" else _date(cells[4])
                operations.append(
                    (
                        "ADD",
                        _nonempty(cells[1]),
                        _nonempty(cells[2]),
                        _quantity(cells[3]),
                        expires,
                    )
                )
            elif operation == "RESERVE":
                if len(cells) != 4:
                    raise ValueError("wrong field count")
                operations.append(
                    (
                        "RESERVE",
                        _nonempty(cells[1]),
                        _nonempty(cells[2]),
                        _quantity(cells[3]),
                    )
                )
            elif operation == "CANCEL":
                if len(cells) != 2:
                    raise ValueError("wrong field count")
                operations.append(("CANCEL", _nonempty(cells[1])))
            elif operation == "COMMIT":
                if len(cells) != 2:
                    raise ValueError("wrong field count")
                operations.append(("COMMIT", _nonempty(cells[1])))
            elif operation == "ADVANCE":
                if len(cells) != 2:
                    raise ValueError("wrong field count")
                operations.append(("ADVANCE", _date(cells[1])))
            else:
                raise ValueError("unknown operation")
    except csv.Error as exc:
        raise ValueError("invalid CSV") from exc

    return operations


def _apply(ledger, operations):
    results = []

    for operation in operations:
        name = operation[0]
        if name == "ADD":
            result = ledger.add(
                operation[1],
                operation[2],
                operation[3],
                operation[4],
            )
        elif name == "RESERVE":
            result = ledger.reserve(operation[1], operation[2], operation[3])
        elif name == "CANCEL":
            result = ledger.cancel(operation[1])
        elif name == "COMMIT":
            result = ledger.commit(operation[1])
        else:
            result = ledger.advance(operation[1])
        results.append(result)

    return results


def run(ledger, text, atomic=True):
    operations = _parse(text)
    if not operations:
        return []

    if not atomic:
        return _apply(ledger, operations)

    working = ledger.copy()
    results = _apply(working, operations)
    ledger.replace_from(working)
    return results
=== FILE: reporting.py ===
import csv
import io


def render(ledger):
    totals = {}

    for lot in ledger.snapshot()["lots"]:
        row = totals.setdefault(
            lot["sku"],
            {
                "available": 0,
                "held": 0,
                "shipped": 0,
                "expired": 0,
            },
        )
        for field in ("available", "held", "shipped", "expired"):
            row[field] += lot[field]

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["sku", "available", "held", "shipped", "expired"])

    for sku in sorted(totals):
        row = totals[sku]
        writer.writerow(
            [
                sku,
                row["available"],
                row["held"],
                row["shipped"],
                row["expired"],
            ]
        )

    return output.getvalue()
=== END ===