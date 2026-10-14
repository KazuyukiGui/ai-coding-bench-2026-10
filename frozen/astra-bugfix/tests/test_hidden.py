import unittest
from copy import deepcopy

from stockbook import StockBook


def receive(eid, at, lot, quantity, expires=None, sku="S"):
    return {
        "id": eid,
        "kind": "receive",
        "at": at,
        "lot": lot,
        "sku": sku,
        "quantity": quantity,
        "expires": expires,
    }


def reserve(eid, at, reservation, quantity, until, sku="S"):
    return {
        "id": eid,
        "kind": "reserve",
        "at": at,
        "reservation": reservation,
        "sku": sku,
        "quantity": quantity,
        "until": until,
    }


def operation(kind, eid, at, reservation, quantity=None):
    event = {
        "id": eid,
        "kind": kind,
        "at": at,
        "reservation": reservation,
    }
    if kind == "resize":
        event["quantity"] = quantity
    return event


def tick(eid, at):
    return {"id": eid, "kind": "tick", "at": at}


def make_book(*events):
    book = StockBook()
    book.apply(list(events))
    return book


def get_lot(book, lot_id):
    return next(x for x in book.snapshot()["lots"] if x["lot"] == lot_id)


def get_reservation(book, reservation_id):
    return next(
        x for x in book.snapshot()["reservations"]
        if x["reservation"] == reservation_id
    )


def allocations(book, reservation_id):
    return [
        (x["lot"], x["quantity"])
        for x in get_reservation(book, reservation_id)["allocations"]
    ]


class StockBookTests(unittest.TestCase):
    def assert_rejected(self, book, events):
        before = book.snapshot()
        with self.assertRaises(ValueError):
            book.apply(events)
        self.assertEqual(book.snapshot(), before)

    def test_empty_book_and_empty_batch(self):
        book = StockBook()
        expected = {"at": 0, "lots": [], "reservations": []}
        self.assertEqual(book.snapshot(), expected)
        self.assertIsNone(book.apply([]))
        self.assertEqual(book.snapshot(), expected)
        book.apply([tick("t", 7)])
        self.assertIsNone(book.apply([]))
        self.assertEqual(book.snapshot()["at"], 7)

    def test_snapshot_exact_shape(self):
        book = make_book(
            receive("i", 0, "L", 10),
            reserve("r", 1, "R", 3, 12),
        )
        self.assertEqual(book.snapshot(), {
            "at": 1,
            "lots": [{
                "lot": "L",
                "sku": "S",
                "expires": None,
                "remaining": 10,
                "available": 7,
            }],
            "reservations": [{
                "reservation": "R",
                "sku": "S",
                "until": 12,
                "quantity": 3,
                "status": "active",
                "allocations": [{"lot": "L", "quantity": 3}],
            }],
        })

    def test_fefo_split_ties_and_equal_deadline(self):
        book = make_book(
            receive("i1", 0, "z", 5, 10),
            receive("i2", 0, "a", 3, 10),
            receive("i3", 0, "early", 2, 8),
            receive("i4", 0, "none", 9),
            reserve("r", 0, "R", 7, 8),
        )
        self.assertEqual(
            allocations(book, "R"), [("early", 2), ("a", 3), ("z", 2)]
        )
        self.assertEqual(get_lot(book, "none")["available"], 9)
        self.assertEqual(get_lot(book, "z")["available"], 3)

    def test_deadline_eligibility_and_sku_isolation(self):
        book = make_book(
            receive("i1", 0, "short", 50, 5),
            receive("i2", 0, "other", 50, 7, sku="T"),
            receive("i3", 0, "long", 2, 9),
            receive("i4", 0, "none", 5),
            reserve("r", 0, "R", 4, 6),
        )
        self.assertEqual(allocations(book, "R"), [("long", 2), ("none", 2)])
        self.assertEqual(get_lot(book, "short")["available"], 50)
        self.assertEqual(get_lot(book, "other")["available"], 50)
        self.assert_rejected(book, [reserve("x", 1, "X", 1, 8, sku="U")])

    def test_multiple_reservations_share_available_stock(self):
        book = make_book(
            receive("i", 0, "L", 10),
            reserve("r1", 0, "R1", 4, 10),
            reserve("r2", 0, "R2", 5, 10),
        )
        self.assertEqual(get_lot(book, "L")["remaining"], 10)
        self.assertEqual(get_lot(book, "L")["available"], 1)
        self.assert_rejected(book, [reserve("r3", 1, "R3", 2, 10)])
        book.apply([reserve("r3", 1, "R3", 1, 10)])
        self.assertEqual(get_lot(book, "L")["available"], 0)

    def test_reservation_and_lot_expire_at_boundary(self):
        book = make_book(
            receive("i1", 0, "finite", 2, 4),
            receive("i2", 0, "none", 5),
            reserve("r", 0, "R", 3, 4),
        )
        book.apply([tick("t", 4)])
        self.assertEqual(get_lot(book, "finite"), {
            "lot": "finite",
            "sku": "S",
            "expires": 4,
            "remaining": 0,
            "available": 0,
        })
        self.assertEqual(get_lot(book, "none")["available"], 5)
        reservation = get_reservation(book, "R")
        self.assertEqual(reservation["status"], "expired")
        self.assertEqual(reservation["quantity"], 3)
        self.assertEqual(reservation["allocations"], [])

    def test_reservation_expiration_releases_unexpired_stock(self):
        book = make_book(
            receive("i", 0, "L", 6, 10),
            reserve("r", 0, "R", 4, 3),
        )
        book.apply([tick("before", 2)])
        self.assertEqual(get_reservation(book, "R")["status"], "active")
        book.apply([tick("edge", 3)])
        self.assertEqual(get_reservation(book, "R")["status"], "expired")
        self.assertEqual(get_lot(book, "L")["remaining"], 6)
        self.assertEqual(get_lot(book, "L")["available"], 6)
        book.apply([reserve("r2", 3, "R2", 6, 10)])
        self.assertEqual(allocations(book, "R2"), [("L", 6)])

    def test_unreserved_lot_expiration_and_history(self):
        book = make_book(receive("i", 0, "L", 5, 3))
        book.apply([tick("a", 2)])
        self.assertEqual(get_lot(book, "L")["remaining"], 5)
        book.apply([tick("b", 3)])
        self.assertEqual(get_lot(book, "L")["remaining"], 0)
        book.apply([tick("c", 100)])
        self.assertEqual(len(book.snapshot()["lots"]), 1)

    def test_release_preserves_remaining_and_other_reservations(self):
        book = make_book(
            receive("i", 0, "L", 10),
            reserve("r1", 0, "R1", 4, 10),
            reserve("r2", 0, "R2", 3, 10),
        )
        book.apply([operation("release", "rel", 1, "R1")])
        self.assertEqual(get_lot(book, "L")["remaining"], 10)
        self.assertEqual(get_lot(book, "L")["available"], 7)
        self.assertEqual(allocations(book, "R2"), [("L", 3)])
        ended = get_reservation(book, "R1")
        self.assertEqual(ended["status"], "released")
        self.assertEqual(ended["quantity"], 4)
        self.assertEqual(ended["allocations"], [])

    def test_ship_consumes_only_target_allocations(self):
        book = make_book(
            receive("i1", 0, "A", 3, 20),
            receive("i2", 0, "B", 8),
            reserve("r1", 0, "R1", 5, 10),
            reserve("r2", 0, "R2", 2, 10),
        )
        book.apply([operation("ship", "s", 1, "R1")])
        self.assertEqual(get_lot(book, "A")["remaining"], 0)
        self.assertEqual(get_lot(book, "B")["remaining"], 6)
        self.assertEqual(get_lot(book, "B")["available"], 4)
        self.assertEqual(allocations(book, "R2"), [("B", 2)])
        ended = get_reservation(book, "R1")
        self.assertEqual(ended["status"], "shipped")
        self.assertEqual(ended["quantity"], 5)
        self.assertEqual(ended["allocations"], [])

    def test_resize_increase_combines_same_lot(self):
        book = make_book(
            receive("i", 0, "L", 10),
            reserve("r", 0, "R", 2, 10),
        )
        book.apply([operation("resize", "up", 1, "R", 5)])
        self.assertEqual(allocations(book, "R"), [("L", 5)])
        self.assertEqual(get_reservation(book, "R")["quantity"], 5)
        self.assertEqual(get_lot(book, "L")["available"], 5)

    def test_resize_increase_keeps_existing_allocation(self):
        book = make_book(
            receive("i1", 0, "old", 6),
            reserve("r", 0, "R", 3, 10),
            receive("i2", 1, "new", 4, 10),
        )
        book.apply([operation("resize", "up", 2, "R", 5)])
        self.assertEqual(allocations(book, "R"), [("new", 2), ("old", 3)])
        self.assertEqual(get_lot(book, "new")["available"], 2)
        self.assertEqual(get_lot(book, "old")["available"], 3)

    def test_resize_decrease_uses_reverse_fefo(self):
        book = make_book(
            receive("i1", 0, "A", 3, 10),
            receive("i2", 0, "B", 3, 20),
            receive("i3", 0, "N", 3),
            reserve("r", 0, "R", 8, 10),
        )
        book.apply([operation("resize", "down", 1, "R", 4)])
        self.assertEqual(allocations(book, "R"), [("A", 3), ("B", 1)])
        self.assertEqual(get_lot(book, "N")["available"], 3)
        book.apply([operation("resize", "down2", 2, "R", 1)])
        self.assertEqual(allocations(book, "R"), [("A", 1)])

    def test_resize_decrease_tie_breaks_in_reverse(self):
        book = make_book(
            receive("i1", 0, "a", 3, 10),
            receive("i2", 0, "z", 3, 10),
            reserve("r", 0, "R", 5, 9),
        )
        book.apply([operation("resize", "d", 1, "R", 2)])
        self.assertEqual(allocations(book, "R"), [("a", 2)])

    def test_same_quantity_resize_still_advances_time(self):
        book = make_book(
            receive("i", 0, "L", 10),
            reserve("r1", 0, "R1", 3, 10),
            reserve("r2", 0, "R2", 2, 2),
        )
        book.apply([operation("resize", "same", 2, "R1", 3)])
        self.assertEqual(book.snapshot()["at"], 2)
        self.assertEqual(allocations(book, "R1"), [("L", 3)])
        self.assertEqual(get_reservation(book, "R2")["status"], "expired")
        self.assertEqual(get_lot(book, "L")["available"], 7)

    def test_failed_increase_restores_expiration_and_clock(self):
        book = make_book(
            receive("i", 0, "L", 5),
            reserve("r1", 0, "R1", 3, 10),
            reserve("r2", 0, "R2", 2, 2),
        )
        self.assert_rejected(
            book, [operation("resize", "up", 2, "R1", 6)]
        )
        self.assertEqual(get_reservation(book, "R2")["status"], "active")
        book.apply([operation("resize", "up", 2, "R1", 5)])
        self.assertEqual(allocations(book, "R1"), [("L", 5)])
        self.assertEqual(get_reservation(book, "R2")["status"], "expired")

    def test_batch_failure_rolls_back_earlier_events_and_ids(self):
        book = StockBook()
        self.assert_rejected(book, [
            receive("i", 5, "L", 3),
            reserve("r", 5, "R", 4, 9),
        ])
        book.apply([
            receive("i", 0, "L", 7),
            reserve("r", 0, "R", 6, 9),
        ])
        self.assertEqual(allocations(book, "R"), [("L", 6)])
        self.assertEqual(book.snapshot()["at"], 0)

    def test_batch_time_error_undoes_expiration(self):
        book = make_book(
            receive("i", 0, "L", 4, 3),
            reserve("r", 0, "R", 4, 3),
        )
        self.assert_rejected(book, [tick("t1", 3), tick("t2", 2)])
        book.apply([tick("t1", 1)])
        self.assertEqual(book.snapshot()["at"], 1)
        self.assertEqual(get_reservation(book, "R")["status"], "active")

    def test_batch_validation_error_rolls_back_prior_change(self):
        book = make_book(receive("i", 0, "L", 8))
        malformed = tick("bad", 2)
        malformed["extra"] = None
        self.assert_rejected(book, [
            reserve("r", 1, "R", 3, 9),
            malformed,
        ])
        book.apply([reserve("r", 0, "R", 4, 9)])
        self.assertEqual(allocations(book, "R"), [("L", 4)])

    def test_old_replay_does_not_change_clock_or_revive_lot(self):
        original = receive("i", 0, "L", 4, 3)
        book = make_book(original, tick("t", 5))
        before = book.snapshot()
        self.assertIsNone(book.apply([dict(reversed(list(original.items())))]))
        self.assertEqual(book.snapshot(), before)
        book.apply([original, receive("new", 5, "N", 2)])
        self.assertEqual(book.snapshot()["at"], 5)
        self.assertEqual(get_lot(book, "L")["remaining"], 0)

    def test_old_reservation_replay_does_not_revive_reservation(self):
        original = reserve("r", 0, "R", 3, 2)
        book = make_book(
            receive("i", 0, "L", 5),
            original,
            tick("t", 3),
        )
        before = book.snapshot()
        book.apply([original])
        self.assertEqual(book.snapshot(), before)
        self.assertEqual(get_reservation(book, "R")["status"], "expired")

    def test_duplicate_in_batch_and_conflicting_duplicate(self):
        incoming = receive("i", 0, "L", 5)
        booking = reserve("r", 0, "R", 2, 10)
        book = make_book(incoming, deepcopy(incoming), booking, deepcopy(booking))
        self.assertEqual(get_lot(book, "L")["remaining"], 5)
        self.assertEqual(get_lot(book, "L")["available"], 3)
        changed = dict(booking, quantity=3)
        self.assert_rejected(book, [tick("t", 1), changed])
        book.apply([tick("t", 0)])
        self.assertEqual(book.snapshot()["at"], 0)

    def test_caller_mutation_cannot_change_replay_history(self):
        incoming = receive("i", 0, "L", 5)
        original = deepcopy(incoming)
        events = [incoming]
        book = StockBook()
        book.apply(events)
        self.assertEqual(events, [original])
        incoming["quantity"] = 8
        events.append(tick("unused", 100))
        self.assert_rejected(book, [incoming])
        book.apply([original])
        self.assertEqual(get_lot(book, "L")["remaining"], 5)
        self.assertEqual(book.snapshot()["at"], 0)

    def test_validation_precedes_replay_equality(self):
        original = receive("i", 0, "L", 1)
        book = make_book(original)
        self.assert_rejected(book, [dict(original, quantity=True)])
        self.assert_rejected(book, [dict(original, at=False)])
        self.assert_rejected(book, [dict(original, quantity=1.0)])
        self.assert_rejected(book, [dict(original, extra=1)])
        book.apply([original])

    def test_snapshot_is_deeply_independent(self):
        book = make_book(
            receive("i", 0, "L", 8),
            reserve("r", 0, "R", 3, 9),
        )
        before = book.snapshot()
        exposed = book.snapshot()
        exposed["at"] = 99
        exposed["lots"][0]["remaining"] = -1
        exposed["lots"].append({})
        exposed["reservations"][0]["quantity"] = 999
        exposed["reservations"][0]["allocations"][0]["quantity"] = 999
        exposed["reservations"][0]["allocations"].append({})
        exposed["reservations"].append({})
        self.assertEqual(book.snapshot(), before)
        book.apply([operation("ship", "s", 1, "R")])
        self.assertEqual(get_lot(book, "L")["remaining"], 5)

    def test_identifiers_are_permanent_and_namespaces_are_separate(self):
        book = make_book(
            receive("same", 0, "same", 2, 2),
            reserve("r", 0, "same", 1, 2),
            tick("t", 2),
        )
        self.assert_rejected(book, [receive("i2", 2, "same", 3)])
        book.apply([receive("i3", 2, "new", 5)])
        self.assert_rejected(book, [reserve("r2", 2, "same", 1, 8)])

    def test_shipped_lot_and_released_reservation_ids_cannot_be_reused(self):
        book = make_book(
            receive("i", 0, "L", 1),
            reserve("r", 0, "R", 1, 5),
            operation("ship", "s", 1, "R"),
        )
        self.assert_rejected(book, [receive("i2", 1, "L", 2)])
        book.apply([
            receive("i3", 1, "N", 2),
            reserve("r2", 1, "Q", 1, 5),
            operation("release", "rel", 1, "Q"),
        ])
        self.assert_rejected(book, [reserve("r3", 1, "Q", 1, 5)])

    def test_operations_require_active_reservations(self):
        for ended_by in ("release", "ship", "expire"):
            with self.subTest(ended_by=ended_by):
                book = make_book(
                    receive("i", 0, "L", 5),
                    reserve("r", 0, "R", 2, 3),
                )
                if ended_by == "expire":
                    book.apply([tick("end", 3)])
                else:
                    book.apply([operation(ended_by, "end", 1, "R")])
                at = book.snapshot()["at"]
                for kind in ("release", "ship", "resize"):
                    self.assert_rejected(
                        book, [operation(kind, "bad", at, "R", 1)]
                    )
                    self.assert_rejected(
                        book, [operation(kind, "missing", at, "absent", 1)]
                    )

    def test_operations_at_deadline_fail_and_rollback_expiration(self):
        for kind in ("release", "ship", "resize"):
            with self.subTest(kind=kind):
                book = make_book(
                    receive("i", 0, "L", 5, 3),
                    reserve("r", 0, "R", 2, 3),
                )
                self.assert_rejected(
                    book, [operation(kind, "edge", 3, "R", 1)]
                )
                self.assertEqual(get_reservation(book, "R")["status"], "active")
                book.apply([tick("edge", 3)])
                self.assertEqual(get_reservation(book, "R")["status"], "expired")

    def test_time_order_and_equal_timestamps(self):
        book = make_book(receive("i", 4, "L", 5))
        self.assert_rejected(book, [tick("back", 3)])
        book.apply([
            reserve("r", 4, "R", 2, 5),
            operation("resize", "up", 4, "R", 3),
            operation("release", "rel", 4, "R"),
            tick("same", 4),
        ])
        self.assertEqual(book.snapshot()["at"], 4)
        self.assertEqual(get_lot(book, "L")["available"], 5)

    def test_exact_event_schemas_and_container_types(self):
        book = StockBook()
        for invalid in (None, {}, "events", 3, True):
            with self.subTest(container=invalid):
                self.assert_rejected(book, invalid)

        valid_examples = [
            receive("i", 0, "L", 5),
            reserve("r", 0, "R", 2, 10),
            operation("resize", "u", 0, "R", 3),
            operation("release", "d", 0, "R"),
            operation("ship", "s", 0, "R"),
            tick("t", 0),
        ]
        prepared = make_book(
            receive("base_i", 0, "base_L", 20),
            reserve("base_r", 0, "R", 2, 10),
        )
        for valid in valid_examples:
            for field in valid:
                bad = dict(valid)
                del bad[field]
                with self.subTest(kind=valid["kind"], missing=field):
                    self.assert_rejected(prepared, [bad])
            with self.subTest(kind=valid["kind"], extra=True):
                self.assert_rejected(prepared, [dict(valid, extra=None)])

        for invalid in (
            None, [], "event", 1, True, {},
            {"id": "x", "kind": "unknown", "at": 0},
            {"id": "x", "kind": [], "at": 0},
        ):
            with self.subTest(event=invalid):
                self.assert_rejected(prepared, [invalid])

    def test_numeric_validation(self):
        book = make_book(
            receive("base_i", 0, "L", 20),
            reserve("base_r", 0, "R", 2, 10),
        )
        for value in (True, False, 0, -1, 1.0, "1", None):
            for base in (
                receive("i", 0, "N", 1),
                reserve("r", 0, "Q", 1, 10),
                operation("resize", "u", 0, "R", 1),
            ):
                with self.subTest(field="quantity", value=value, kind=base["kind"]):
                    self.assert_rejected(book, [dict(base, quantity=value)])

        for value in (True, False, -1, 0.0, "0", None):
            with self.subTest(field="at", value=value):
                self.assert_rejected(book, [tick("t", value)])

        for value in (True, False, -1, 1.0, "1", None, 0):
            with self.subTest(field="until", value=value):
                self.assert_rejected(book, [reserve("r", 0, "Q", 1, value)])

        for value in (True, False, -1, 1.0, "1", 0):
            with self.subTest(field="expires", value=value):
                self.assert_rejected(book, [receive("i", 0, "N", 1, value)])

        self.assert_rejected(book, [reserve("r", 5, "Q", 1, 5)])
        self.assert_rejected(book, [reserve("r", 5, "Q", 1, 4)])
        self.assert_rejected(book, [receive("i", 5, "N", 1, 5)])
        self.assert_rejected(book, [receive("i", 5, "N", 1, 4)])

    def test_identifier_validation(self):
        book = StockBook()
        examples = [
            receive("i", 0, "L", 1),
            reserve("r", 0, "R", 1, 10),
        ]
        for example in examples:
            for field in ("id", "lot", "sku", "reservation"):
                if field not in example:
                    continue
                for value in ("", None, 0, True, [], {}):
                    with self.subTest(field=field, value=value):
                        self.assert_rejected(book, [dict(example, **{field: value})])

    def test_literal_identifiers_unicode_order_and_case(self):
        names = ["あ", "a", "A", " a", " "]
        events = [
            receive("i" + str(index), 0, name, 1, sku=" ")
            for index, name in enumerate(names)
        ]
        events.append(receive("other", 0, "other", 10, sku=""))
        self.assert_rejected(StockBook(), events)

        book = make_book(*events[:-1])
        book.apply([
            reserve("r", 0, " ", 5, 2, sku=" "),
            receive("case", 0, "case", 5, sku="s"),
        ])
        self.assertEqual(
            allocations(book, " "), [(name, 1) for name in sorted(names)]
        )
        self.assertEqual(
            [x["lot"] for x in book.snapshot()["lots"]],
            sorted(names + ["case"]),
        )
        self.assert_rejected(book, [reserve("bad", 0, "bad", 1, 2, sku="S")])

    def test_reservations_snapshot_sorted_by_identifier(self):
        book = make_book(receive("i", 0, "L", 10))
        book.apply([
            reserve("r1", 0, "z", 1, 5),
            reserve("r2", 0, "あ", 1, 5),
            reserve("r3", 0, "A", 1, 5),
            operation("release", "rel", 1, "z"),
        ])
        self.assertEqual(
            [r["reservation"] for r in book.snapshot()["reservations"]],
            sorted(["z", "あ", "A"]),
        )

    def test_ended_reservation_keeps_resized_quantity(self):
        for kind in ("release", "ship", "expire"):
            with self.subTest(kind=kind):
                book = make_book(
                    receive("i", 0, "L", 10),
                    reserve("r", 0, "R", 2, 5),
                    operation("resize", "u", 1, "R", 6),
                )
                if kind == "expire":
                    book.apply([tick("end", 5)])
                else:
                    book.apply([operation(kind, "end", 2, "R")])
                reservation = get_reservation(book, "R")
                self.assertEqual(reservation["quantity"], 6)
                self.assertEqual(reservation["allocations"], [])
                expected_remaining = 4 if kind == "ship" else 10
                self.assertEqual(
                    get_lot(book, "L")["remaining"], expected_remaining
                )

    def test_ship_replay_cannot_consume_twice(self):
        shipping = operation("ship", "s", 1, "R")
        book = make_book(
            receive("i", 0, "L", 8),
            reserve("r", 0, "R", 3, 10),
            shipping,
            tick("t", 5),
        )
        before = book.snapshot()
        book.apply([shipping, deepcopy(shipping)])
        self.assertEqual(book.snapshot(), before)
        self.assertEqual(get_lot(book, "L")["remaining"], 5)

    def test_batch_conflicting_replay_rolls_back_new_history(self):
        book = make_book(receive("i", 0, "L", 10))
        self.assert_rejected(book, [
            tick("new", 1),
            receive("i", 0, "L", 11),
        ])
        book.apply([tick("new", 0)])
        self.assertEqual(book.snapshot()["at"], 0)

    def test_expiration_runs_before_new_reservation(self):
        book = make_book(
            receive("i", 0, "L", 4),
            reserve("r1", 0, "R1", 4, 3),
        )
        book.apply([reserve("r2", 3, "R2", 4, 8)])
        self.assertEqual(get_reservation(book, "R1")["status"], "expired")
        self.assertEqual(allocations(book, "R2"), [("L", 4)])
        self.assertEqual(get_lot(book, "L")["available"], 0)

    def test_large_integers_and_none_expiration_order(self):
        large = 10 ** 100
        book = make_book(
            receive("i1", large, "finite", large, large + 10),
            receive("i2", large, "none", large),
            reserve("r", large, "R", large + 1, large + 10),
        )
        self.assertEqual(
            allocations(book, "R"), [("finite", large), ("none", 1)]
        )
        book.apply([operation("ship", "s", large + 1, "R")])
        self.assertEqual(get_lot(book, "finite")["remaining"], 0)
        self.assertEqual(get_lot(book, "none")["remaining"], large - 1)

    def test_complete_workflow_preserves_accounting(self):
        book = make_book(
            receive("i1", 0, "A", 5, 20),
            receive("i2", 0, "B", 10),
            reserve("r1", 0, "R1", 7, 10),
            reserve("r2", 0, "R2", 4, 12),
        )
        book.apply([
            operation("resize", "down", 1, "R1", 4),
            operation("resize", "up", 1, "R2", 7),
            operation("ship", "ship", 2, "R2"),
            operation("release", "release", 2, "R1"),
            reserve("r3", 2, "R3", 8, 20),
        ])
        self.assertEqual(get_lot(book, "A")["remaining"], 4)
        self.assertEqual(get_lot(book, "B")["remaining"], 4)
        self.assertEqual(allocations(book, "R3"), [("A", 4), ("B", 4)])
        self.assertEqual(get_lot(book, "A")["available"], 0)
        self.assertEqual(get_lot(book, "B")["available"], 0)
        book.apply([tick("end", 20)])
        self.assertEqual(get_lot(book, "A")["remaining"], 0)
        self.assertEqual(get_lot(book, "B")["available"], 4)
        self.assertEqual(get_reservation(book, "R3")["status"], "expired")


if __name__ == "__main__":
    unittest.main()
