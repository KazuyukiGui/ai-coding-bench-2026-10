import dataclasses
import datetime
import unittest

from stock.ledger import InsufficientStock, Ledger
from stock.money import format_cents, parse_cents
from stock.parser import ParseError, Txn, parse_line, parse_lines
from stock.report import ReportError, apply, build_report


class MoneyTest(unittest.TestCase):
    def test_parse_basic(self):
        cases = {
            "12.50": 1250,
            "12.5": 1250,
            "12": 1200,
            "0.05": 5,
            "0": 0,
            "0.00": 0,
            "007.10": 710,
            "3.07": 307,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                got = parse_cents(text)
                self.assertEqual(got, expected)
                self.assertIsInstance(got, int)

    def test_parse_rejects(self):
        bad = [
            "", "-1", "+1", "-0.50", "1e3", ".5", "5.", "1.234", "1,000",
            " 1.00", "1.00 ", "1.00\n", "１２", "1.0.0", "abc", "1_000",
            "nan", "inf", "1. 5",
        ]
        for text in bad:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_cents(text)

    def test_parse_large_exact(self):
        self.assertEqual(parse_cents("12345678901234567.89"), 1234567890123456789)
        self.assertEqual(parse_cents("30023997515803.31"), 3002399751580331)

    def test_format(self):
        cases = {
            0: "0.00",
            5: "0.05",
            100: "1.00",
            1250: "12.50",
            123456: "1234.56",
            1234567890123456789: "12345678901234567.89",
        }
        for cents, expected in cases.items():
            with self.subTest(cents=cents):
                self.assertEqual(format_cents(cents), expected)

    def test_format_negative(self):
        self.assertEqual(format_cents(-5), "-0.05")
        self.assertEqual(format_cents(-105), "-1.05")
        self.assertEqual(format_cents(-100), "-1.00")
        self.assertEqual(format_cents(-123456), "-1234.56")

    def test_roundtrip(self):
        for text in ["0.01", "10.00", "999.99", "0.10"]:
            with self.subTest(text=text):
                self.assertEqual(format_cents(parse_cents(text)), text)


class ParserTest(unittest.TestCase):
    def test_txn_fields(self):
        names = [f.name for f in dataclasses.fields(Txn)]
        self.assertEqual(names, ["lineno", "date", "kind", "sku", "qty", "unit_cost"])

    def test_unit_cost_in_and_out(self):
        t = parse_line("2024-03-01,IN,A,4, 12.5 ", 7)
        self.assertEqual(t.unit_cost, 1250)
        self.assertIsInstance(t.unit_cost, int)
        self.assertEqual(t.lineno, 7)
        self.assertEqual(t.date, datetime.date(2024, 3, 1))
        self.assertEqual(t.qty, 4)
        o = parse_line("2024-03-01,OUT,A,4", 1)
        self.assertIsNone(o.unit_cost)

    def test_zero_and_large_unit_cost(self):
        self.assertEqual(parse_line("2024-01-01,IN,A,1,0", 1).unit_cost, 0)
        self.assertEqual(
            parse_line("2024-01-01,IN,A,1,30023997515803.31", 1).unit_cost,
            3002399751580331,
        )

    def test_bad_unit_cost_has_lineno(self):
        for price in ["-1", "1e3", "1.234", "abc", "", "5.", "１"]:
            with self.subTest(price=price):
                lines = ["# header", "", f"2024-01-01,IN,A,1,{price}"]
                with self.assertRaises(ParseError) as cm:
                    parse_lines(lines)
                self.assertEqual(cm.exception.lineno, 3)

    def test_existing_checks_kept(self):
        bad = [
            "2024-01-01,OUT,A,1,1.00",
            "2024-01-01,IN,A,1",
            "2024-01-01,IN,A,0,1.00",
            "2024-01-01,IN,A,²,1.00",
            "2024-01-01,IN,A,-1,1.00",
            "2024-01-01,IN,A,1.5,1.00",
            "2024-01-01,MOVE,A,1",
            "2024-01-01,IN, ,1,1.00",
            "2024-13-01,IN,A,1,1.00",
            "2024-01-01,IN,A",
            "2024-01-01,IN,A,1,1.00,x",
        ]
        for line in bad:
            with self.subTest(line=line):
                with self.assertRaises(ParseError) as cm:
                    parse_line(line, 5)
                self.assertEqual(cm.exception.lineno, 5)
        self.assertTrue(issubclass(ParseError, ValueError))

    def test_skips_and_case_kept(self):
        txns = parse_lines(
            ["  # c", "", "2024-01-01,in,A,1,1", "   ", "2024-01-01,Out,A,1"]
        )
        self.assertEqual([t.kind for t in txns], ["IN", "OUT"])
        self.assertEqual([t.lineno for t in txns], [3, 5])
        self.assertEqual([t.unit_cost for t in txns], [100, None])

    def test_date_backwards_kept(self):
        with self.assertRaises(ParseError) as cm:
            parse_lines(["2024-01-02,IN,A,1,1", "", "2024-01-01,IN,A,1,1"])
        self.assertEqual(cm.exception.lineno, 3)


class LedgerTest(unittest.TestCase):
    def test_fifo_breakdown(self):
        led = Ledger()
        led.receive("A", 10, 100)
        led.receive("A", 5, 120)
        self.assertEqual(led.ship("A", 12), [(10, 100), (2, 120)])
        self.assertEqual(led.lots("A"), [(3, 120)])
        self.assertEqual(led.quantity("A"), 3)
        self.assertEqual(led.value("A"), 360)

    def test_lots_not_merged(self):
        led = Ledger()
        led.receive("A", 2, 100)
        led.receive("A", 2, 100)
        self.assertEqual(led.lots("A"), [(2, 100), (2, 100)])
        self.assertEqual(led.ship("A", 3), [(2, 100), (1, 100)])
        self.assertEqual(led.lots("A"), [(1, 100)])

    def test_full_lot_removed(self):
        led = Ledger()
        led.receive("A", 5, 100)
        self.assertEqual(led.ship("A", 5), [(5, 100)])
        self.assertEqual(led.lots("A"), [])
        self.assertEqual(led.quantity("A"), 0)
        self.assertEqual(led.value("A"), 0)
        self.assertEqual(led.skus(), ["A"])

    def test_interleaved(self):
        led = Ledger()
        led.receive("A", 4, 100)
        self.assertEqual(led.ship("A", 3), [(3, 100)])
        led.receive("A", 2, 50)
        self.assertEqual(led.ship("A", 2), [(1, 100), (1, 50)])
        self.assertEqual(led.lots("A"), [(1, 50)])
        self.assertEqual(led.value("A"), 50)

    def test_insufficient_leaves_state(self):
        led = Ledger()
        led.receive("A", 3, 100)
        led.receive("A", 2, 200)
        with self.assertRaises(InsufficientStock) as cm:
            led.ship("A", 6)
        e = cm.exception
        self.assertEqual((e.sku, e.requested, e.available), ("A", 6, 5))
        self.assertEqual(led.lots("A"), [(3, 100), (2, 200)])
        self.assertEqual(led.quantity("A"), 5)
        with self.assertRaises(InsufficientStock) as cm:
            led.ship("Z", 1)
        self.assertEqual(cm.exception.available, 0)
        self.assertEqual(led.skus(), ["A"])

    def test_validation(self):
        led = Ledger()
        for qty, cost in [(0, 100), (-2, 100), (1, -1)]:
            with self.subTest(qty=qty, cost=cost):
                with self.assertRaises(ValueError):
                    led.receive("A", qty, cost)
        self.assertEqual(led.skus(), [])
        led.receive("A", 1, 0)
        with self.assertRaises(ValueError):
            led.ship("A", 0)
        with self.assertRaises(ValueError):
            led.ship("A", -1)
        with self.assertRaises(ValueError):
            led.ship("Z", 0)
        self.assertEqual(led.lots("A"), [(1, 0)])

    def test_lots_returns_copy(self):
        led = Ledger()
        led.receive("A", 3, 100)
        got = led.lots("A")
        got.clear()
        got.append((99, 1))
        self.assertEqual(led.lots("A"), [(3, 100)])
        self.assertEqual(led.quantity("A"), 3)

    def test_unknown_sku_queries(self):
        led = Ledger()
        self.assertEqual(led.quantity("X"), 0)
        self.assertEqual(led.value("X"), 0)
        self.assertEqual(led.lots("X"), [])
        self.assertEqual(led.skus(), [])


class ReportTest(unittest.TestCase):
    def test_example(self):
        lines = [
            "# 期首",
            "2024-04-01,IN,A,10,1.00",
            "2024-04-02,IN,A,5,1.20",
            "2024-04-03,out,A,12",
            "2024-04-03,IN,B,3,0.10",
            "2024-04-05,OUT,B,1",
        ]
        expected = (
            "SKU,QTY,VALUE,COGS\n"
            "A,3,3.60,12.40\n"
            "B,2,0.20,0.10\n"
            "TOTAL,5,3.80,12.50\n"
        )
        self.assertEqual(build_report(lines), expected)

    def test_zero_qty_sku_and_sorting(self):
        lines = [
            "2024-01-01,IN,b,1,2.00",
            "2024-01-01,IN,B,2,3.00",
            "2024-01-01,IN,A,1,0",
            "2024-01-02,OUT,b,1",
        ]
        expected = (
            "SKU,QTY,VALUE,COGS\n"
            "A,1,0.00,0.00\n"
            "B,2,6.00,0.00\n"
            "b,0,0.00,2.00\n"
            "TOTAL,3,6.00,2.00\n"
        )
        self.assertEqual(build_report(lines), expected)

    def test_empty(self):
        expected = "SKU,QTY,VALUE,COGS\nTOTAL,0,0.00,0.00\n"
        self.assertEqual(build_report([]), expected)
        self.assertEqual(build_report(["# only comment", "", "  "]), expected)

    def test_insufficient_lineno(self):
        lines = ["2024-01-01,IN,A,2,1.00", "", "# c", "2024-01-02,OUT,A,3"]
        with self.assertRaises(ReportError) as cm:
            build_report(lines)
        self.assertEqual(cm.exception.lineno, 4)
        self.assertTrue(issubclass(ReportError, ValueError))

    def test_parse_error_propagates(self):
        with self.assertRaises(ParseError) as cm:
            build_report(["2024-01-01,IN,A,1,1.00", "2024-01-01,IN,A,1,1.234"])
        self.assertEqual(cm.exception.lineno, 2)

    def test_large_amounts_exact(self):
        lines = ["2024-01-01,IN,X,3,30023997515803.31", "2024-01-02,OUT,X,1"]
        expected = (
            "SKU,QTY,VALUE,COGS\n"
            "X,2,60047995031606.62,30023997515803.31\n"
            "TOTAL,2,60047995031606.62,30023997515803.31\n"
        )
        self.assertEqual(build_report(lines), expected)

    def test_apply_cogs_int(self):
        txns = parse_lines(
            [
                "2024-01-01,IN,A,10,1.00",
                "2024-01-01,IN,A,5,1.20",
                "2024-01-02,IN,B,1,9.99",
                "2024-01-03,OUT,A,11",
                "2024-01-04,OUT,A,1",
            ]
        )
        ledger, cogs = apply(txns)
        self.assertEqual(cogs, {"A": 1240})
        self.assertIsInstance(cogs["A"], int)
        self.assertEqual(ledger.lots("A"), [(3, 120)])
        self.assertEqual(ledger.lots("B"), [(1, 999)])

    def test_apply_with_existing_ledger(self):
        led = Ledger()
        led.receive("A", 5, 100)
        ledger, cogs = apply(parse_lines(["2024-01-01,OUT,A,2"]), led)
        self.assertIs(ledger, led)
        self.assertEqual(cogs, {"A": 200})
        self.assertEqual(led.quantity("A"), 3)


if __name__ == "__main__":
    unittest.main()
