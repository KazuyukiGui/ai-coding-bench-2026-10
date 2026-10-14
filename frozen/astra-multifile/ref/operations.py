import csv
import io
import re
from datetime import date


_ARITIES = {
    "ADD": 5,
    "RESERVE": 4,
    "CANCEL": 2,
    "COMMIT": 2,
    "ADVANCE": 2,
}


def _name(value):
    if not value:
        raise ValueError("empty name")
    return value


def _quantity(value):
    if re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise ValueError("invalid quantity")
    quantity = int(value)
    if quantity > 1_000_000_000:
        raise ValueError("quantity too large")
    return quantity


def _day(value):
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("invalid date format")
    return date.fromisoformat(value)


def _parse(text):
    commands = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        for cells in reader:
            if not cells:
                continue
            cells = [cell.strip(" \t") for cell in cells]
            operation = cells[0]
            if operation not in _ARITIES or len(cells) != _ARITIES[operation]:
                raise ValueError("unknown operation or wrong field count")

            if operation == "ADD":
                args = (
                    _name(cells[1]),
                    _name(cells[2]),
                    _quantity(cells[3]),
                    _day(cells[4]) if cells[4] else None,
                )
            elif operation == "RESERVE":
                args = (
                    _name(cells[1]),
                    _name(cells[2]),
                    _quantity(cells[3]),
                )
            elif operation in ("CANCEL", "COMMIT"):
                args = (_name(cells[1]),)
            else:
                args = (_day(cells[1]),)
            commands.append((operation.lower(), args))
    except csv.Error as exc:
        raise ValueError("invalid CSV") from exc
    return commands


def run(ledger, text, atomic=True):
    commands = _parse(text)
    target = ledger.copy() if atomic else ledger
    results = []
    for method, args in commands:
        results.append(getattr(target, method)(*args))
    if atomic:
        ledger.replace_from(target)
    return results
