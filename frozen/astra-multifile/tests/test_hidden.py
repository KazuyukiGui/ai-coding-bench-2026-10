import csv
import io
import unittest
from copy import deepcopy
from datetime import date

from inventory import Ledger
from operations import run
from reporting import render


D = date(2032, 6, 10)
NEXT = date(2032, 6, 11)
LATER = date(2032, 6, 12)
HEADER = "sku,available,held,shipped,expired\n"


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(D)

    def lots(self, ledger=None):
        ledger = self.ledger if ledger is None else ledger
        return {row["lot_id"]: row for row in ledger.snapshot()["lots"]}

    def reservations(self, ledger=None):
        ledger = self.ledger if ledger is None else ledger
        return {
            row["reservation_id"]: row
            for row in ledger.snapshot()["reservations"]
        }

    def assert_counts(self, lot_id, available, held, shipped, expired):
        row = self.lots()[lot_id]
        self.assertEqual(
            tuple(row[key] for key in ("available", "held", "shipped", "expired")),
            (available, held, shipped, expired),
        )
        self.assertEqual(
            row["received"], available + held + shipped + expired
        )

    def assert_rejected_without_change(self, callback):
        before = deepcopy(self.ledger.snapshot())
        with self.assertRaises(ValueError):
            callback()
        self.assertEqual(self.ledger.snapshot(), before)

    def test_empty_contract(self):
        self.assertEqual(
            self.ledger.snapshot(),
            {"today": "2032-06-10", "lots": [], "reservations": []},
        )
        self.assertEqual(render(self.ledger), HEADER)
        self.assertEqual(run(self.ledger, "\n\r\n"), [])

    def test_exact_snapshot_and_return_types(self):
        self.assertIsNone(self.ledger.add("L1", "PART", 7, LATER))
        self.assertEqual(self.ledger.reserve("R1", "PART", 4), (("L1", 4),))
        self.assertEqual(
            self.ledger.snapshot(),
            {
                "today": "2032-06-10",
                "lots": [{
                    "lot_id": "L1",
                    "sku": "PART",
                    "received": 7,
                    "expires": "2032-06-12",
                    "available": 3,
                    "held": 4,
                    "shipped": 0,
                    "expired": 0,
                }],
                "reservations": [{
                    "reservation_id": "R1",
                    "sku": "PART",
                    "quantity": 4,
                    "status": "active",
                    "allocations": [{"lot_id": "L1", "quantity": 4}],
                }],
            },
        )

    def test_plain_single_lot_lifecycle(self):
        self.ledger.add("L", "PART", 9)
        self.assertEqual(self.ledger.reserve("R", "PART", 4), (("L", 4),))
        self.assertEqual(self.ledger.commit("R"), (("L", 4),))
        self.assertEqual(self.lots()["L"]["expires"], None)
        self.assert_counts("L", 5, 0, 4, 0)
        self.assertEqual(render(self.ledger), HEADER + "PART,5,0,4,0\n")

    def test_split_priority_and_id_tie_break(self):
        self.ledger.add("u", "X", 4)
        self.ledger.add("z", "X", 3, NEXT)
        self.ledger.add("b", "X", 2, D)
        self.ledger.add("a", "X", 1, D)
        self.ledger.add("other", "Y", 100, D)
        self.assertEqual(
            self.ledger.reserve("R", "X", 8),
            (("a", 1), ("b", 2), ("z", 3), ("u", 2)),
        )
        self.assert_counts("u", 2, 2, 0, 0)
        self.assert_counts("other", 100, 0, 0, 0)

    def test_none_sorts_after_date_max(self):
        self.ledger.add("a", "X", 2)
        self.ledger.add("z", "X", 2, date.max)
        self.assertEqual(
            self.ledger.reserve("R", "X", 3),
            (("z", 2), ("a", 1)),
        )

    def test_unlimited_lots_use_string_order(self):
        for name in ("あ", "a", "A", "10", "2"):
            self.ledger.add(name, "X", 1)
        self.assertEqual(
            self.ledger.reserve("R", "X", 5),
            tuple((name, 1) for name in sorted(("あ", "a", "A", "10", "2"))),
        )

    def test_exact_fill_has_no_zero_allocations(self):
        self.ledger.add("a", "X", 2, D)
        self.ledger.add("b", "X", 3, NEXT)
        self.assertEqual(self.ledger.reserve("R1", "X", 2), (("a", 2),))
        self.assertEqual(self.ledger.reserve("R2", "X", 1), (("b", 1),))

    def test_insufficient_reservation_is_atomic_and_id_reusable(self):
        self.ledger.add("a", "X", 2, D)
        self.ledger.add("b", "X", 3)
        self.assert_rejected_without_change(
            lambda: self.ledger.reserve("R", "X", 6)
        )
        self.ledger.add("c", "X", 1)
        self.assertEqual(
            self.ledger.reserve("R", "X", 6),
            (("a", 2), ("b", 3), ("c", 1)),
        )

    def test_unknown_sku_does_not_consume_id(self):
        self.assert_rejected_without_change(
            lambda: self.ledger.reserve("R", "missing", 1)
        )
        self.ledger.add("L", "missing", 1)
        self.assertEqual(self.ledger.reserve("R", "missing", 1), (("L", 1),))

    def test_expiry_inclusive_and_forward_only(self):
        self.ledger.add("L", "X", 5, D)
        self.assertIsNone(self.ledger.advance(D))
        self.assert_counts("L", 5, 0, 0, 0)
        self.ledger.reserve("R", "X", 2)
        self.assertIsNone(self.ledger.advance(NEXT))
        self.assert_counts("L", 0, 2, 0, 3)
        self.ledger.advance(NEXT)
        self.assert_counts("L", 0, 2, 0, 3)
        self.assert_rejected_without_change(lambda: self.ledger.advance(D))

    def test_cancel_splits_valid_and_expired_returns(self):
        self.ledger.add("early", "X", 3, D)
        self.ledger.add("late", "X", 4, LATER)
        self.ledger.add("forever", "X", 5)
        expected = (("early", 3), ("late", 4), ("forever", 2))
        self.assertEqual(self.ledger.reserve("R", "X", 9), expected)
        self.ledger.advance(NEXT)
        self.assertEqual(self.ledger.cancel("R"), expected)
        self.assert_counts("early", 0, 0, 0, 3)
        self.assert_counts("late", 4, 0, 0, 0)
        self.assert_counts("forever", 5, 0, 0, 0)
        self.assertEqual(self.reservations()["R"]["status"], "cancelled")

    def test_commit_expired_held_stock(self):
        self.ledger.add("L", "X", 7, D)
        self.ledger.reserve("R", "X", 5)
        self.ledger.advance(LATER)
        self.assertEqual(self.ledger.commit("R"), (("L", 5),))
        self.assert_counts("L", 0, 0, 5, 2)
        self.assertEqual(self.reservations()["R"]["status"], "committed")

    def test_idempotent_terminal_operations_and_opposite_rejection(self):
        for terminal, opposite in (("cancel", "commit"), ("commit", "cancel")):
            with self.subTest(terminal=terminal):
                ledger = Ledger(D)
                ledger.add("L", "X", 4, D)
                expected = ledger.reserve("R", "X", 3)
                self.assertEqual(getattr(ledger, terminal)("R"), expected)
                ledger.advance(NEXT)
                before = deepcopy(ledger.snapshot())
                self.assertEqual(getattr(ledger, terminal)("R"), expected)
                self.assertEqual(ledger.snapshot(), before)
                with self.assertRaises(ValueError):
                    getattr(ledger, opposite)("R")
                self.assertEqual(ledger.snapshot(), before)

    def test_missing_terminal_operations(self):
        self.assert_rejected_without_change(lambda: self.ledger.cancel("R"))
        self.assert_rejected_without_change(lambda: self.ledger.commit("R"))

    def test_duplicate_ids_remain_used_after_closure(self):
        self.ledger.add("L", "X", 5)
        self.ledger.reserve("R", "X", 5)
        self.assert_rejected_without_change(
            lambda: self.ledger.reserve("R", "X", 1)
        )
        self.ledger.cancel("R")
        self.assert_rejected_without_change(
            lambda: self.ledger.reserve("R", "X", 1)
        )
        self.ledger.reserve("S", "X", 5)
        self.ledger.commit("S")
        self.assert_rejected_without_change(
            lambda: self.ledger.reserve("S", "X", 1)
        )
        self.assert_rejected_without_change(
            lambda: self.ledger.add("L", "Y", 8)
        )

    def test_expired_add_rejected_without_consuming_lot_id(self):
        self.assert_rejected_without_change(
            lambda: self.ledger.add("L", "X", 2, date(2032, 6, 9))
        )
        self.ledger.add("L", "X", 2, D)
        self.assert_counts("L", 2, 0, 0, 0)

    def test_exact_names_and_separate_id_namespaces(self):
        self.ledger.add(" same ", " X ", 2)
        self.ledger.add("same", "X", 3)
        self.ledger.add("lower", "x", 4)
        self.assertEqual(
            self.ledger.reserve(" same ", " X ", 2),
            ((" same ", 2),),
        )
        self.assert_counts("same", 3, 0, 0, 0)
        self.assert_counts("lower", 4, 0, 0, 0)

    def test_snapshot_order_and_deep_isolation(self):
        self.ledger.add("z", "X", 3, D)
        self.ledger.add("a", "X", 4)
        self.ledger.reserve("z", "X", 2)
        self.ledger.reserve("a", "X", 2)
        snap = self.ledger.snapshot()
        self.assertEqual([r["lot_id"] for r in snap["lots"]], ["a", "z"])
        self.assertEqual(
            [r["reservation_id"] for r in snap["reservations"]], ["a", "z"]
        )
        self.assertEqual(
            snap["reservations"][0]["allocations"],
            [{"lot_id": "z", "quantity": 1}, {"lot_id": "a", "quantity": 1}],
        )
        original = deepcopy(snap)
        snap["lots"][0]["available"] = -99
        snap["reservations"][0]["allocations"][0]["quantity"] = -99
        snap["lots"].clear()
        self.assertEqual(self.ledger.snapshot(), original)
        self.ledger.commit("a")
        self.assertEqual(original["reservations"][0]["status"], "active")
        self.assertEqual(original["lots"][0]["shipped"], 0)

    def test_copy_is_independent_in_both_directions(self):
        self.ledger.add("L", "X", 10, D)
        self.ledger.reserve("R", "X", 4)
        copied = self.ledger.copy()
        self.assertIsInstance(copied, Ledger)
        self.assertIsNot(copied, self.ledger)
        self.assertEqual(copied.snapshot(), self.ledger.snapshot())
        copied.cancel("R")
        copied.add("M", "X", 2)
        self.assert_counts("L", 6, 4, 0, 0)
        self.ledger.advance(NEXT)
        self.ledger.commit("R")
        self.assertEqual(self.lots(copied)["L"]["available"], 10)
        self.assertEqual(copied.snapshot()["today"], "2032-06-10")
        self.assertNotIn("M", self.lots())

    def test_replace_independence_backward_date_and_self(self):
        source = Ledger(date(2031, 1, 1))
        source.add("L", "X", 5)
        source.reserve("R", "X", 2)
        self.ledger.add("obsolete", "Y", 8)
        self.assertIsNone(self.ledger.replace_from(source))
        self.assertEqual(self.ledger.snapshot(), source.snapshot())
        source.cancel("R")
        self.assert_counts("L", 3, 2, 0, 0)
        self.ledger.commit("R")
        self.assertEqual(self.lots(source)["L"]["shipped"], 0)
        before = deepcopy(self.ledger.snapshot())
        self.assertIsNone(self.ledger.replace_from(self.ledger))
        self.assertEqual(self.ledger.snapshot(), before)

    def test_multiple_reservations_conserve_quantities(self):
        self.ledger.add("A", "X", 8, D)
        self.ledger.add("B", "X", 5)
        self.ledger.reserve("R1", "X", 3)
        self.ledger.reserve("R2", "X", 7)
        self.ledger.advance(NEXT)
        self.ledger.cancel("R1")
        self.ledger.commit("R2")
        self.assert_counts("A", 0, 0, 5, 3)
        self.assert_counts("B", 3, 0, 2, 0)
        self.assertEqual(
            self.ledger.reserve("R3", "X", 3), (("B", 3),)
        )


class OperationTests(unittest.TestCase):
    def test_prompt_example(self):
        ledger = Ledger(D)
        results = run(
            ledger,
            "ADD,L2,PART,4,\n"
            "ADD,L1,PART,3,2032-06-10\n"
            "RESERVE,R1,PART,5\n"
            "ADVANCE,2032-06-11\n"
            "CANCEL,R1\n",
        )
        allocations = (("L1", 3), ("L2", 2))
        self.assertEqual(results, [None, None, allocations, None, allocations])
        self.assertEqual(render(ledger), HEADER + "PART,4,0,0,3\n")

    def test_atomic_failure_restores_all_state(self):
        ledger = Ledger(D)
        ledger.add("L", "X", 5, D)
        ledger.reserve("old", "X", 2)
        before = deepcopy(ledger.snapshot())
        with self.assertRaises(ValueError):
            run(
                ledger,
                "COMMIT,old\n"
                "ADVANCE,2032-06-11\n"
                "ADD,new,X,3,\n"
                "RESERVE,new_r,X,2\n"
                "RESERVE,fail,X,2\n",
            )
        self.assertEqual(ledger.snapshot(), before)
        self.assertEqual(ledger.cancel("old"), (("L", 2),))
        ledger.add("new", "X", 3)
        self.assertEqual(ledger.reserve("new_r", "X", 1), (("L", 1),))

    def test_nonatomic_failure_keeps_prefix_and_stops(self):
        ledger = Ledger(D)
        ledger.add("L", "X", 5, D)
        with self.assertRaises(ValueError):
            run(
                ledger,
                "RESERVE,R,X,2\n"
                "ADVANCE,2032-06-11\n"
                "RESERVE,bad,X,1\n"
                "COMMIT,R\n",
                atomic=False,
            )
        snap = ledger.snapshot()
        self.assertEqual(snap["today"], "2032-06-11")
        self.assertEqual(snap["reservations"][0]["status"], "active")
        self.assertEqual(len(snap["reservations"]), 1)
        self.assertEqual(
            render(ledger), HEADER + "X,0,2,0,3\n"
        )

    def test_syntax_error_anywhere_precedes_business_application(self):
        bad_tails = [
            "UNKNOWN,L\n",
            "ADD,L,X,1\n",
            "ADD,L,X,1,,extra\n",
            "ADD,L,X,01,\n",
            "ADD,L,X,1,2032-02-30\n",
            'ADD,L,"unterminated,1,\n',
            " \t \n",
            '""\n',
        ]
        for atomic in (False, True):
            for tail in bad_tails:
                with self.subTest(atomic=atomic, tail=tail):
                    ledger = Ledger(D)
                    ledger.add("base", "X", 2)
                    before = deepcopy(ledger.snapshot())
                    with self.assertRaises(ValueError):
                        run(
                            ledger,
                            "RESERVE,R,X,1\n" + tail,
                            atomic=atomic,
                        )
                    self.assertEqual(ledger.snapshot(), before)

    def test_numeric_grammar_and_bounds(self):
        invalid = [
            "0", "-1", "+1", "01", "1.0", "1e2",
            "１", "١", "1 0", "", "1000000001",
        ]
        for quantity in invalid:
            for operation in (
                f"ADD,L,X,{quantity},\n",
                f"RESERVE,R,X,{quantity}\n",
            ):
                with self.subTest(operation=operation):
                    ledger = Ledger(D)
                    ledger.add("base", "X", 1_000_000_000)
                    before = ledger.snapshot()
                    with self.assertRaises(ValueError):
                        run(ledger, operation, atomic=False)
                    self.assertEqual(ledger.snapshot(), before)
        ledger = Ledger(D)
        self.assertEqual(
            run(
                ledger,
                "ADD,L,X,1000000000,\n"
                "RESERVE,R,X,1000000000\n"
                "COMMIT,R\n",
            ),
            [None, (("L", 1_000_000_000),), (("L", 1_000_000_000),)],
        )

    def test_date_grammar_and_calendar(self):
        invalid = [
            "", "20320611", "2032-6-11", "2032-06-1",
            "2032-W24-5", "2032-02-30", "2031-02-29",
            "0000-01-01", "２０３２-06-11",
        ]
        for value in invalid:
            with self.subTest(value=value):
                ledger = Ledger(D)
                before = ledger.snapshot()
                with self.assertRaises(ValueError):
                    run(ledger, f"ADVANCE,{value}\n")
                self.assertEqual(ledger.snapshot(), before)
        ledger = Ledger(date(2032, 2, 28))
        self.assertEqual(
            run(ledger, "ADD,L,X,1,2032-02-29\nADVANCE,2032-02-29\n"),
            [None, None],
        )
        self.assertEqual(render(ledger), HEADER + "X,1,0,0,0\n")
        run(ledger, "ADVANCE,2032-03-01\n")
        self.assertEqual(render(ledger), HEADER + "X,0,0,0,1\n")

    def test_date_extremes(self):
        ledger = Ledger(date.min)
        run(
            ledger,
            "ADD,min,X,1,0001-01-01\n"
            "ADD,max,X,1,9999-12-31\n"
            "ADD,none,X,1,\n"
            "ADVANCE,9999-12-31\n",
        )
        self.assertEqual(
            ledger.reserve("R", "X", 2),
            (("max", 1), ("none", 1)),
        )
        self.assertEqual(ledger.snapshot()["lots"][1]["expires"], "0001-01-01")

    def test_csv_quotes_multiline_and_ascii_trimming(self):
        ledger = Ledger(D)
        text = (
            "\n"
            ' ADD , "L,1" , " A,\n""B"" " , 3 , \t\n'
            'RESERVE, R ,"A,\n""B""", 2\n'
        )
        # csv.reader does not treat a quote after an unquoted leading space
        # as an opening quote. Use valid quoted cells for the actual input.
        text = (
            "\n"
            ' ADD ," L,1 "," A,\n""B"" ", 3 , \t\n'
            'RESERVE, R ,"A,\n""B""", 2\n'
        )
        self.assertEqual(
            run(ledger, text),
            [None, (("L,1", 2),)],
        )
        lot = ledger.snapshot()["lots"][0]
        self.assertEqual(lot["sku"], 'A,\n"B"')
        self.assertEqual(lot["lot_id"], "L,1")
        rows = list(csv.reader(io.StringIO(render(ledger), newline="")))
        self.assertEqual(
            rows,
            [
                ["sku", "available", "held", "shipped", "expired"],
                ['A,\n"B"', "1", "2", "0", "0"],
            ],
        )

    def test_only_ascii_space_and_tab_are_trimmed(self):
        ledger = Ledger(D)
        nbsp = "\u00a0"
        self.assertEqual(
            run(
                ledger,
                f"ADD,{nbsp}L{nbsp},{nbsp}X{nbsp},1,\n"
                f"RESERVE,{nbsp}R{nbsp},{nbsp}X{nbsp},1\n",
            ),
            [None, ((f"{nbsp}L{nbsp}", 1),)],
        )
        self.assertEqual(
            ledger.snapshot()["reservations"][0]["reservation_id"],
            f"{nbsp}R{nbsp}",
        )

    def test_empty_names_unknown_ops_and_record_rules(self):
        invalid = [
            "ADD,,X,1,\n",
            "ADD,L, \t,1,\n",
            "RESERVE,,X,1\n",
            "RESERVE,R,,1\n",
            "CANCEL, \t\n",
            "COMMIT,\n",
            "add,L,X,1,\n",
            "\ufeffADD,L,X,1,\n",
            "# comment\n",
            "operation,id\n",
            ",\n",
            "CANCEL,R,extra\n",
            "ADVANCE,2032-06-11,extra\n",
        ]
        for text in invalid:
            with self.subTest(text=text):
                ledger = Ledger(D)
                before = ledger.snapshot()
                with self.assertRaises(ValueError):
                    run(ledger, text)
                self.assertEqual(ledger.snapshot(), before)

    def test_crlf_input_and_terminal_results(self):
        ledger = Ledger(D)
        self.assertEqual(
            run(
                ledger,
                "\r\nADD,L,X,3,\r\n"
                "RESERVE,R,X,2\r\nCOMMIT,R\r\nCOMMIT,R\r\n",
                atomic=False,
            ),
            [None, (("L", 2),), (("L", 2),), (("L", 2),)],
        )
        self.assertEqual(render(ledger), HEADER + "X,1,0,2,0\n")

    def test_atomic_success_updates_original_object(self):
        ledger = Ledger(D)
        alias = ledger
        old_snapshot = ledger.snapshot()
        self.assertEqual(run(ledger, "ADD,L,X,2,\n"), [None])
        self.assertIs(alias, ledger)
        self.assertEqual(render(alias), HEADER + "X,2,0,0,0\n")
        self.assertEqual(old_snapshot["lots"], [])
        before = ledger.snapshot()
        self.assertEqual(run(ledger, ""), [])
        self.assertEqual(ledger.snapshot(), before)

    def test_duplicate_add_is_business_error(self):
        for atomic in (False, True):
            with self.subTest(atomic=atomic):
                ledger = Ledger(D)
                with self.assertRaises(ValueError):
                    run(
                        ledger,
                        "ADD,L,X,1,\nADD,L,Y,2,\nADD,M,X,1,\n",
                        atomic=atomic,
                    )
                expected = HEADER if atomic else HEADER + "X,1,0,0,0\n"
                self.assertEqual(render(ledger), expected)

    def test_backward_day_is_business_error(self):
        ledger = Ledger(D)
        with self.assertRaises(ValueError):
            run(
                ledger,
                "ADD,L,X,1,\nADVANCE,2032-06-09\n",
                atomic=False,
            )
        self.assertEqual(render(ledger), HEADER + "X,1,0,0,0\n")
        self.assertEqual(ledger.snapshot()["today"], "2032-06-10")


class ReportTests(unittest.TestCase):
    def test_aggregation_order_zero_available_and_no_mutation(self):
        ledger = Ledger(D)
        ledger.add("z1", "z", 2)
        ledger.add("a1", "A", 4, D)
        ledger.add("a2", "A", 5)
        ledger.add("b1", "a", 3, D)
        ledger.reserve("r1", "A", 6)
        ledger.commit("r1")
        ledger.reserve("r2", "z", 2)
        ledger.advance(NEXT)
        before = deepcopy(ledger.snapshot())
        self.assertEqual(
            render(ledger),
            HEADER + "A,3,0,6,0\na,0,0,0,3\nz,0,2,0,0\n",
        )
        self.assertEqual(ledger.snapshot(), before)

    def test_csv_escaping_and_unicode_sort(self):
        ledger = Ledger(D)
        ledger.add("L1", '部品,"甲"\n乙', 2)
        ledger.add("L2", " Z ", 1)
        ledger.add("L3", "A,B", 3)
        before = ledger.snapshot()
        self.assertEqual(
            render(ledger),
            HEADER
            + " Z ,1,0,0,0\n"
            + '"A,B",3,0,0,0\n'
            + '"部品,""甲""\n乙",2,0,0,0\n',
        )
        self.assertEqual(ledger.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
