import csv
import io
from datetime import date


def run(ledger, text):
    results = []
    for cells in csv.reader(io.StringIO(text, newline=""), strict=True):
        if not cells:
            continue
        cells = [cell.strip(" \t") for cell in cells]
        operation = cells[0]
        if operation == "ADD" and len(cells) == 4:
            result = ledger.add(cells[1], cells[2], int(cells[3]))
        elif operation == "RESERVE" and len(cells) == 4:
            result = ledger.reserve(cells[1], cells[2], int(cells[3]))
        elif operation == "CANCEL" and len(cells) == 2:
            result = ledger.cancel(cells[1])
        elif operation == "COMMIT" and len(cells) == 2:
            result = ledger.commit(cells[1])
        elif operation == "ADVANCE" and len(cells) == 2:
            result = ledger.advance(date.fromisoformat(cells[1]))
        else:
            raise ValueError("unknown operation or wrong field count")
        results.append(result)
    return results
