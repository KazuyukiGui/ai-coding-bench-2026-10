import copy
import unittest

from warehouse import Warehouse


def receive(at, lot, quantity, expires=None, sku="P"):
    return {
        "op": "receive", "at": at, "lot": lot, "sku": sku,
        "quantity": quantity, "expires": expires,
    }


def reserve(at, hold, quantity, until=100, sku="P"):
    return {
        "op": "reserve", "at": at, "hold": hold, "sku": sku,
        "quantity": quantity, "until": until,
    }


def resize(at, hold, quantity, until=100):
    return {
        "op": "resize", "at": at, "hold": hold,
        "quantity": quantity, "until": until,
    }


def ship(at, hold, quantity):
    return {"op": "ship", "at": at, "hold": hold, "quantity": quantity}


def release(at, hold):
    return {"op": "release", "at": at, "hold": hold}


def tick(at):
    return {"op": "tick", "at": at}


def lot_row(lot, quantity, reserved=0, expires=None, sku="P"):
    return {
        "id": lot, "sku": sku, "expires": expires,
        "on_hand": quantity, "reserved": reserved,
        "available": quantity - reserved,
    }


def hold_row(hold, allocations, until=100, sku="P"):
    return {
        "id": hold, "sku": sku, "until": until,
        "quantity": sum(quantity for _, quantity in allocations),
        "allocations": [
            {"lot": lot, "quantity": quantity}
            for lot, quantity in allocations
        ],
    }


def state(now, lots=(), holds=()):
    return {"now": now, "lots": list(lots), "holds": list(holds)}


class WarehouseTests(unittest.TestCase):
    def setUp(self):
        self.w = Warehouse()

    def assert_rejected(self, events):
        before = self.w.snapshot()
        with self.assertRaises(ValueError):
            self.w.apply(events)
        self.assertEqual(self.w.snapshot(), before)

    def test_initial_and_empty_batch(self):
        self.assertEqual(self.w.snapshot(), state(0))
        self.assertEqual(self.w.apply([]), [])
        self.assertEqual(self.w.snapshot(), state(0))
        self.w.apply([tick(7)])
        self.assertEqual(self.w.apply([]), [])
        self.assertEqual(self.w.snapshot(), state(7))

    def test_each_event_has_its_own_snapshot(self):
        results = self.w.apply([
            receive(0, "L", 5),
            reserve(0, "H", 3, until=10),
            ship(1, "H", 2),
            release(2, "H"),
        ])
        self.assertEqual(results, [
            state(0, [lot_row("L", 5)]),
            state(0, [lot_row("L", 5, 3)], [
                hold_row("H", [("L", 3)], until=10),
            ]),
            state(1, [lot_row("L", 3, 1)], [
                hold_row("H", [("L", 1)], until=10),
            ]),
            state(2, [lot_row("L", 3)]),
        ])

    def test_fefo_and_unlimited_expiry(self):
        self.w.apply([
            receive(0, "unlimited", 4),
            receive(0, "late", 3, expires=20),
            receive(0, "early", 2, expires=10),
            reserve(0, "H", 7),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("early", 2), ("late", 3), ("unlimited", 2)]),
        ])

    def test_equal_expiry_uses_receipt_order(self):
        self.w.apply([
            receive(0, "z", 2, expires=8),
            receive(0, "a", 2, expires=8),
            reserve(0, "H", 3),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("z", 2), ("a", 1)]),
        ])
        self.assertEqual(
            [row["id"] for row in self.w.snapshot()["lots"]],
            ["a", "z"],
        )

    def test_unlimited_expiry_also_uses_receipt_order(self):
        self.w.apply([
            receive(0, "z", 2),
            receive(1, "a", 2),
            reserve(1, "H", 3),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("z", 2), ("a", 1)]),
        ])

    def test_other_holds_reduce_available_quantity(self):
        self.w.apply([
            receive(0, "A", 4, expires=20),
            receive(0, "B", 5, expires=30),
            reserve(0, "first", 3),
            reserve(0, "second", 4),
        ])
        self.assertEqual(self.w.snapshot(), state(0, [
            lot_row("A", 4, 4, expires=20),
            lot_row("B", 5, 3, expires=30),
        ], [
            hold_row("first", [("A", 3)]),
            hold_row("second", [("A", 1), ("B", 3)]),
        ]))
        self.assert_rejected([reserve(0, "third", 3)])

    def test_sku_isolation_and_case_sensitivity(self):
        self.w.apply([
            receive(0, "A", 3, sku="P"),
            receive(0, "B", 9, sku="p"),
        ])
        self.assert_rejected([reserve(1, "H", 4, sku="P")])
        self.w.apply([reserve(1, "H", 9, sku="p")])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("B", 9)], sku="p"),
        ])

    def test_missing_sku_is_insufficient_stock(self):
        self.assert_rejected([reserve(0, "H", 1, sku="UNKNOWN")])

    def test_partial_ship_crosses_lot_boundary(self):
        self.w.apply([
            receive(0, "A", 2, expires=10),
            receive(0, "B", 5, expires=20),
            reserve(0, "H", 6, until=40),
            ship(1, "H", 4),
        ])
        self.assertEqual(self.w.snapshot(), state(1, [
            lot_row("A", 0, expires=10),
            lot_row("B", 3, 2, expires=20),
        ], [
            hold_row("H", [("B", 2)], until=40),
        ]))

    def test_ship_all_keeps_empty_lot_and_used_hold_id(self):
        self.w.apply([
            receive(0, "L", 2),
            reserve(0, "H", 2),
            ship(0, "H", 2),
        ])
        self.assertEqual(self.w.snapshot(), state(0, [lot_row("L", 0)]))
        self.w.apply([receive(0, "M", 3)])
        self.assert_rejected([reserve(0, "H", 1)])
        self.assert_rejected([ship(0, "H", 1)])

    def test_overship_rolls_back(self):
        self.w.apply([receive(0, "L", 5), reserve(0, "H", 3)])
        self.assert_rejected([ship(2, "H", 4)])
        self.w.apply([ship(1, "H", 3)])
        self.assertEqual(self.w.snapshot(), state(1, [lot_row("L", 2)]))

    def test_release_restores_availability(self):
        self.w.apply([
            receive(0, "L", 5),
            reserve(0, "H", 5),
            release(1, "H"),
            reserve(1, "J", 5),
        ])
        self.assertEqual(self.w.snapshot(), state(1, [
            lot_row("L", 5, 5),
        ], [
            hold_row("J", [("L", 5)]),
        ]))
        self.assert_rejected([release(2, "H")])
        self.assert_rejected([reserve(2, "H", 1)])

    def test_hold_expires_at_exact_deadline(self):
        self.w.apply([
            receive(0, "L", 4),
            reserve(0, "H", 3, until=5),
            tick(4),
        ])
        self.assertEqual(len(self.w.snapshot()["holds"]), 1)
        self.w.apply([tick(5)])
        self.assertEqual(self.w.snapshot(), state(5, [lot_row("L", 4)]))
        self.assert_rejected([reserve(5, "H", 1, until=9)])

    def test_expired_lot_voids_whole_hold_only(self):
        self.w.apply([
            receive(0, "A", 2, expires=5),
            receive(0, "B", 4, expires=20),
            reserve(0, "H", 3, until=30),
            reserve(0, "J", 2, until=30),
            tick(5),
        ])
        self.assertEqual(self.w.snapshot(), state(5, [
            lot_row("B", 4, 2, expires=20),
        ], [
            hold_row("J", [("B", 2)], until=30),
        ]))
        self.w.apply([tick(20)])
        self.assertEqual(self.w.snapshot(), state(20))

    def test_shipped_allocation_no_longer_causes_expiration(self):
        self.w.apply([
            receive(0, "A", 2, expires=5),
            receive(0, "B", 4, expires=20),
            reserve(0, "H", 4, until=30),
            ship(1, "H", 2),
            tick(5),
        ])
        self.assertEqual(self.w.snapshot(), state(5, [
            lot_row("B", 4, 2, expires=20),
        ], [
            hold_row("H", [("B", 2)], until=30),
        ]))

    def test_expiration_happens_before_reservation(self):
        self.w.apply([
            receive(0, "L", 3),
            reserve(0, "old", 3, until=5),
            reserve(5, "new", 3, until=10),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("new", [("L", 3)], until=10),
        ])

    def test_operation_on_just_expired_hold_rolls_back_time(self):
        self.w.apply([
            receive(0, "L", 4),
            reserve(0, "H", 3, until=5),
        ])
        for event in (ship(5, "H", 1), release(5, "H"),
                      resize(5, "H", 2, until=10)):
            with self.subTest(event=event):
                self.assert_rejected([event])
        self.w.apply([ship(4, "H", 1)])
        self.assertEqual(self.w.snapshot()["now"], 4)

    def test_expired_lot_processing_is_rolled_back_on_error(self):
        self.w.apply([
            receive(0, "A", 2, expires=5),
            receive(0, "B", 4),
            reserve(0, "H", 3, until=20),
        ])
        self.assert_rejected([ship(5, "H", 1)])
        self.w.apply([ship(4, "H", 1)])
        self.assertEqual(self.w.snapshot()["lots"][0]["on_hand"], 1)

    def test_resize_releases_own_stock_before_reallocation(self):
        self.w.apply([
            receive(0, "L", 5),
            reserve(0, "H", 5, until=10),
            resize(1, "H", 5, until=20),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("L", 5)], until=20),
        ])

    def test_resize_same_quantity_reallocates_after_new_receipt(self):
        self.w.apply([
            receive(0, "late", 5, expires=50),
            reserve(0, "H", 3, until=20),
            receive(1, "early", 2, expires=10),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("late", 3)], until=20),
        ])
        self.w.apply([resize(1, "H", 3, until=30)])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("early", 2), ("late", 1)], until=30),
        ])

    def test_resize_preserves_other_holds(self):
        self.w.apply([
            receive(0, "A", 4, expires=10),
            receive(0, "B", 4, expires=20),
            reserve(0, "H", 3),
            reserve(0, "J", 3),
            resize(1, "H", 4, until=50),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("A", 3), ("B", 1)], until=50),
            hold_row("J", [("A", 1), ("B", 2)]),
        ])

    def test_failed_resize_restores_original_hold(self):
        self.w.apply([
            receive(0, "L", 6),
            reserve(0, "H", 3, until=10),
            reserve(0, "J", 3, until=20),
        ])
        self.assert_rejected([resize(1, "H", 4, until=30)])
        self.w.apply([resize(1, "H", 2, until=15)])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("L", 2)], until=15),
            hold_row("J", [("L", 3)], until=20),
        ])

    def test_resize_after_shipping_uses_absolute_quantity(self):
        self.w.apply([
            receive(0, "L", 10),
            reserve(0, "H", 6),
            ship(1, "H", 4),
            resize(2, "H", 3, until=30),
        ])
        self.assertEqual(self.w.snapshot(), state(2, [
            lot_row("L", 6, 3),
        ], [
            hold_row("H", [("L", 3)], until=30),
        ]))

    def test_resize_can_shorten_deadline(self):
        self.w.apply([
            receive(0, "L", 4),
            reserve(0, "H", 3, until=50),
            resize(1, "H", 2, until=4),
            tick(4),
        ])
        self.assertEqual(self.w.snapshot(), state(4, [lot_row("L", 4)]))

    def test_business_deadline_validation(self):
        for expires in (0, 2):
            with self.subTest(expires=expires):
                self.assert_rejected([
                    receive(2, "bad", 1, expires=expires),
                ])
        self.w.apply([receive(2, "L", 4, expires=3)])
        for until in (0, 2):
            with self.subTest(until=until):
                self.assert_rejected([reserve(2, "H", 1, until=until)])
        self.w.apply([reserve(2, "H", 1, until=20)])
        self.assert_rejected([resize(2, "H", 1, until=2)])

    def test_backwards_time_and_same_time(self):
        self.w.apply([receive(5, "L", 3), reserve(5, "H", 2, until=8)])
        self.assert_rejected([tick(4)])
        self.assert_rejected([ship(4, "H", 1)])
        self.w.apply([ship(5, "H", 1), tick(5)])
        self.assertEqual(self.w.snapshot()["now"], 5)

    def test_lot_ids_global_and_permanently_used(self):
        self.w.apply([receive(0, "L", 2, expires=3, sku="P")])
        self.assert_rejected([receive(1, "L", 2, sku="Q")])
        self.w.apply([tick(3)])
        self.assertEqual(self.w.snapshot()["lots"], [])
        self.assert_rejected([receive(3, "L", 2, sku="Q")])

    def test_hold_id_global_but_separate_from_lot_namespace(self):
        self.w.apply([
            receive(0, "same", 3, sku="P"),
            receive(0, "QLOT", 3, sku="Q"),
            reserve(0, "same", 1, sku="P"),
        ])
        self.assert_rejected([reserve(0, "same", 1, sku="Q")])
        self.w.apply([release(0, "same")])
        self.assert_rejected([reserve(0, "same", 1, sku="Q")])

    def test_lot_expiration_keeps_hold_id_used(self):
        self.w.apply([
            receive(0, "A", 1, expires=2),
            receive(0, "B", 3),
            reserve(0, "H", 1),
            tick(2),
        ])
        self.assert_rejected([reserve(2, "H", 1)])
        self.w.apply([reserve(2, "J", 3)])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("J", [("B", 3)]),
        ])

    def test_entire_batch_rolls_back_and_new_ids_are_reusable(self):
        self.w.apply([receive(0, "base", 2)])
        self.assert_rejected([
            receive(1, "fresh", 4, expires=20),
            reserve(1, "newhold", 3, until=10),
            ship(2, "newhold", 1),
            release(3, "absent"),
        ])
        self.w.apply([
            receive(0, "fresh", 4, expires=20),
            reserve(0, "newhold", 4, until=10),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("newhold", [("fresh", 4)], until=10),
        ])

    def test_batch_rollback_restores_preexisting_ship_and_release(self):
        self.w.apply([
            receive(0, "L", 8),
            reserve(0, "H", 3),
            reserve(0, "J", 2),
        ])
        self.assert_rejected([
            ship(1, "H", 2),
            release(2, "J"),
            receive(3, "extra", 2),
            reserve(4, "K", 100),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("L", 3)]),
            hold_row("J", [("L", 2)]),
        ])

    def test_backwards_time_late_in_batch_rolls_everything_back(self):
        self.w.apply([receive(2, "L", 5)])
        self.assert_rejected([
            reserve(3, "H", 2),
            ship(4, "H", 1),
            tick(3),
        ])
        self.w.apply([reserve(2, "H", 5)])

    def test_snapshot_order_is_string_order(self):
        self.w.apply([
            receive(0, "あ", 2),
            receive(0, "a", 2),
            receive(0, "Z", 2),
            reserve(0, "z", 1),
            reserve(0, "A", 1),
            reserve(0, "あ", 1),
        ])
        snapshot = self.w.snapshot()
        self.assertEqual(
            [row["id"] for row in snapshot["lots"]], ["Z", "a", "あ"]
        )
        self.assertEqual(
            [row["id"] for row in snapshot["holds"]], ["A", "z", "あ"]
        )
        self.assertEqual(snapshot["holds"][0]["allocations"], [
            {"lot": "あ", "quantity": 1},
        ])

    def test_inputs_are_unchanged(self):
        events = [
            receive(0, "L", 5),
            reserve(0, "H", 3),
            resize(1, "H", 2, until=10),
            ship(2, "H", 1),
        ]
        original = copy.deepcopy(events)
        self.w.apply(events)
        self.assertEqual(events, original)
        failing = [release(3, "H"), ship(4, "H", 1)]
        original_failing = copy.deepcopy(failing)
        self.assert_rejected(failing)
        self.assertEqual(failing, original_failing)

    def test_outputs_are_detached_at_all_nested_levels(self):
        results = self.w.apply([
            receive(0, "L", 5),
            reserve(0, "H", 3),
            tick(1),
        ])
        expected = copy.deepcopy(results)
        results[1]["lots"][0]["on_hand"] = -1
        results[1]["holds"][0]["allocations"][0]["quantity"] = 99
        results[1]["holds"][0]["allocations"].append(
            {"lot": "fake", "quantity": 1}
        )
        results[1]["lots"].clear()
        results[1]["now"] = 999
        self.assertEqual(results[0], expected[0])
        self.assertEqual(results[2], expected[2])
        self.assertEqual(self.w.snapshot(), expected[2])

        detached = self.w.snapshot()
        detached["holds"][0]["allocations"][0]["lot"] = "changed"
        detached["holds"].clear()
        self.assertEqual(self.w.snapshot(), expected[2])

        self.w.apply([ship(2, "H", 1)])
        self.assertEqual(results[2], expected[2])

    def test_simultaneous_expiry_and_large_time_jump(self):
        self.w.apply([
            receive(0, "A", 2, expires=5),
            receive(0, "B", 5, expires=10),
            receive(0, "C", 4),
            reserve(0, "H", 4, until=5),
            reserve(0, "J", 4, until=10),
            tick(10**12),
        ])
        self.assertEqual(self.w.snapshot(), state(
            10**12, [lot_row("C", 4)]
        ))

    def test_missing_hold_operations(self):
        for event in (
            ship(0, "missing", 1),
            release(0, "missing"),
            resize(0, "missing", 1),
        ):
            with self.subTest(event=event):
                self.assert_rejected([event])

    def test_large_integer_quantities(self):
        quantity = 10**30
        self.w.apply([
            receive(0, "L", quantity),
            reserve(0, "H", quantity - 1),
            ship(1, "H", quantity - 2),
        ])
        self.assertEqual(self.w.snapshot(), state(1, [
            lot_row("L", 2, 1),
        ], [
            hold_row("H", [("L", 1)]),
        ]))

    def test_instances_are_independent(self):
        other = Warehouse()
        self.w.apply([receive(0, "L", 3), reserve(0, "H", 2)])
        self.assertEqual(other.snapshot(), state(0))
        other.apply([receive(1, "L", 8), reserve(1, "H", 7)])
        self.assertEqual(self.w.snapshot()["lots"], [lot_row("L", 3, 2)])
        self.assertEqual(other.snapshot()["lots"], [lot_row("L", 8, 7)])

    def test_shortening_hold_changes_future_expiration(self):
        self.w.apply([
            receive(0, "L", 6),
            reserve(0, "H", 4, until=8),
            resize(1, "H", 2, until=3),
            reserve(3, "J", 6, until=9),
        ])
        self.assertEqual(self.w.snapshot(), state(3, [
            lot_row("L", 6, 6),
        ], [
            hold_row("J", [("L", 6)], until=9),
        ]))

    def test_released_stock_is_reallocated_by_fefo(self):
        self.w.apply([
            receive(0, "A", 3, expires=10),
            receive(0, "B", 3, expires=20),
            reserve(0, "H", 3),
            reserve(0, "J", 2),
            release(1, "H"),
            reserve(1, "K", 4),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("J", [("B", 2)]),
            hold_row("K", [("A", 3), ("B", 1)]),
        ])

    def test_zero_stock_lots_are_skipped_during_allocation(self):
        self.w.apply([
            receive(0, "A", 1, expires=10),
            receive(0, "B", 2, expires=20),
            reserve(0, "H", 1),
            ship(0, "H", 1),
            reserve(0, "J", 2),
        ])
        self.assertEqual(self.w.snapshot(), state(0, [
            lot_row("A", 0, expires=10),
            lot_row("B", 2, 2, expires=20),
        ], [
            hold_row("J", [("B", 2)]),
        ]))


if __name__ == "__main__":
    unittest.main()
