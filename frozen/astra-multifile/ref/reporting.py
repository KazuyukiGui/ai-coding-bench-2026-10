import csv
import io


_FIELDS = ("available", "held", "shipped", "expired")


def render(ledger):
    totals = {}
    for lot in ledger.snapshot()["lots"]:
        row = totals.setdefault(lot["sku"], [0, 0, 0, 0])
        for index, field in enumerate(_FIELDS):
            row[index] += lot[field]

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["sku", *_FIELDS])
    for sku in sorted(totals):
        writer.writerow([sku, *totals[sku]])
    return output.getvalue()
