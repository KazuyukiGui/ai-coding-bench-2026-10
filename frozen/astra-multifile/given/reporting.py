import csv
import io


def render(ledger):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["sku", "available", "held", "shipped", "expired"])
    for row in ledger.snapshot()["stock"]:
        writer.writerow([
            row["sku"],
            row["available"],
            row["held"],
            row["shipped"],
            row["expired"],
        ])
    return output.getvalue()
