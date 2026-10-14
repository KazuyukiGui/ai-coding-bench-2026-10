import unittest
from models import Allocation, ReservationRequest, Resource
from allocator import ResourceAllocator
from service import BookingService


class TestMultiFileReservation(unittest.TestCase):
    def test_01_models_validation_and_defaults(self) -> None:
        r = ReservationRequest(request_id="req1", category="gpu", start=2, end=5, units=4)
        self.assertEqual(r.units, 4)
        self.assertEqual(r.min_units, 4)
        self.assertIsNone(r.preferred_resource_id)

        r2 = ReservationRequest(
            request_id="req2",
            category="gpu",
            start=0,
            end=1,
            units=4,
            min_units=2,
            preferred_resource_id="resA",
        )
        self.assertEqual(r2.min_units, 2)
        self.assertEqual(r2.preferred_resource_id, "resA")

        with self.assertRaises(ValueError):
            ReservationRequest(request_id="bad1", category="gpu", start=-1, end=3)
        with self.assertRaises(ValueError):
            ReservationRequest(request_id="bad2", category="gpu", start=3, end=3)
        with self.assertRaises(ValueError):
            ReservationRequest(request_id="bad3", category="gpu", start=0, end=3, units=0)
        with self.assertRaises(ValueError):
            ReservationRequest(
                request_id="bad4", category="gpu", start=0, end=3, units=3, min_units=0
            )
        with self.assertRaises(ValueError):
            ReservationRequest(
                request_id="bad5", category="gpu", start=0, end=3, units=3, min_units=4
            )
        with self.assertRaises(ValueError):
            Resource(resource_id="r0", category="gpu", total_units=0)

    def test_02_allocation_unit_hours(self) -> None:
        alloc = Allocation(
            request_id="a1",
            resource_id="res1",
            category="cpu",
            start=3,
            end=8,
            priority=1,
            units=6,
        )
        self.assertEqual(alloc.duration(), 5)
        self.assertEqual(alloc.unit_hours(), 30)
        self.assertTrue(alloc.overlaps(0, 4))
        self.assertFalse(alloc.overlaps(0, 3))
        self.assertFalse(alloc.overlaps(8, 10))

    def test_03_available_units_multi_unit_overlap(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("r1", "gpu", 10))

        alloc.allocate(ReservationRequest("q1", "gpu", 2, 6, units=4))
        alloc.allocate(ReservationRequest("q2", "gpu", 4, 8, units=3))

        self.assertEqual(alloc.available_units("r1", 0, 2), 10)
        self.assertEqual(alloc.available_units("r1", 2, 4), 6)
        self.assertEqual(alloc.available_units("r1", 4, 6), 3)
        self.assertEqual(alloc.available_units("r1", 6, 8), 7)
        self.assertEqual(alloc.available_units("r1", 0, 10), 3)

        with self.assertRaises(KeyError):
            alloc.available_units("unknown", 0, 5)
        with self.assertRaises(ValueError):
            alloc.available_units("r1", 5, 5)
        with self.assertRaises(ValueError):
            alloc.available_units("r1", -1, 5)

    def test_04_allocate_best_fit_and_tie_breaking(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("res_c", "gpu", 8))
        alloc.add_resource(Resource("res_b", "gpu", 6))
        alloc.add_resource(Resource("res_a", "gpu", 6))

        # Request 5 units (min 5):
        # res_c has avail=8 -> alloc=5, leftover=3
        # res_b has avail=6 -> alloc=5, leftover=1
        # res_a has avail=6 -> alloc=5, leftover=1
        # Tie break between res_a and res_b -> res_a
        res1 = alloc.allocate(ReservationRequest("req1", "gpu", 0, 5, units=5))
        self.assertIsNotNone(res1)
        assert res1 is not None
        self.assertEqual(res1.resource_id, "res_a")
        self.assertEqual(res1.units, 5)

        # Next request for 5 units on [0, 5]:
        # res_a has avail=1, res_b has avail=6, res_c has avail=8 -> chooses res_b
        res2 = alloc.allocate(ReservationRequest("req2", "gpu", 0, 5, units=5))
        self.assertIsNotNone(res2)
        assert res2 is not None
        self.assertEqual(res2.resource_id, "res_b")

    def test_05_allocate_partial_units_priority(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("r_small", "gpu", 5))
        alloc.add_resource(Resource("r_med", "gpu", 7))

        # Request wants 8 units, min_units=4
        # r_small can give 5 (leftover 0), r_med can give 7 (leftover 0)
        # Larger alloc_units wins -> r_med with 7 units
        res = alloc.allocate(
            ReservationRequest("req1", "gpu", 0, 4, units=8, min_units=4)
        )
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.resource_id, "r_med")
        self.assertEqual(res.units, 7)

        # Now r_med has 0 avail, r_small has 5 avail.
        # Request wants 8 units, min_units=6 -> neither can satisfy -> None
        res_fail = alloc.allocate(
            ReservationRequest("req2", "gpu", 0, 4, units=8, min_units=6)
        )
        self.assertIsNone(res_fail)

        # Request wants 8 units, min_units=5 -> r_small gives 5
        res_ok = alloc.allocate(
            ReservationRequest("req3", "gpu", 0, 4, units=8, min_units=5)
        )
        self.assertIsNotNone(res_ok)
        assert res_ok is not None
        self.assertEqual(res_ok.resource_id, "r_small")
        self.assertEqual(res_ok.units, 5)

    def test_06_preferred_resource_validation(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("gpu1", "gpu", 4))
        alloc.add_resource(Resource("cpu1", "cpu", 4))

        with self.assertRaises(KeyError):
            alloc.allocate(
                ReservationRequest(
                    "r1", "gpu", 0, 2, preferred_resource_id="nonexistent"
                )
            )

        with self.assertRaises(ValueError):
            alloc.allocate(
                ReservationRequest("r2", "gpu", 0, 2, preferred_resource_id="cpu1")
            )

        res = alloc.allocate(
            ReservationRequest(
                "r3", "gpu", 0, 2, units=4, min_units=2, preferred_resource_id="gpu1"
            )
        )
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.resource_id, "gpu1")
        self.assertEqual(res.units, 4)

        # Duplicate request_id
        with self.assertRaises(ValueError):
            alloc.allocate(ReservationRequest("r3", "gpu", 2, 4))

    def test_07_partial_and_full_release(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("r1", "gpu", 10))
        alloc.allocate(ReservationRequest("req1", "gpu", 0, 5, units=6))

        # Invalid release amounts
        with self.assertRaises(ValueError):
            alloc.release("req1", 0)
        with self.assertRaises(ValueError):
            alloc.release("req1", -2)
        with self.assertRaises(ValueError):
            alloc.release("req1", 7)

        # Ensure state unchanged after failed release
        self.assertEqual(alloc.available_units("r1", 0, 5), 4)

        # Partial release of 2 units -> 4 units remain
        updated = alloc.release("req1", 2)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.units, 4)
        self.assertEqual(alloc.available_units("r1", 0, 5), 6)
        self.assertEqual(len(alloc.get_allocations("r1")), 1)
        self.assertEqual(alloc.get_allocations("r1")[0].units, 4)

        # Release exact remaining units -> full removal
        removed = alloc.release("req1", 4)
        self.assertIsNotNone(removed)
        assert removed is not None
        self.assertEqual(removed.units, 4)
        self.assertEqual(alloc.available_units("r1", 0, 5), 10)
        self.assertEqual(len(alloc.get_allocations("r1")), 0)

        with self.assertRaises(KeyError):
            alloc.release("req1")

    def test_08_release_none_removes_all(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("r1", "gpu", 10))
        alloc.allocate(ReservationRequest("req1", "gpu", 0, 5, units=6))

        removed = alloc.release("req1", None)
        self.assertIsNotNone(removed)
        assert removed is not None
        self.assertEqual(removed.units, 6)
        self.assertEqual(len(alloc.get_allocations()), 0)

    def test_09_submit_batch_ordering_and_validation(self) -> None:
        svc = BookingService()
        svc.register_resource("r1", "gpu", 4)

        # Duplicate in batch
        batch_dup = [
            ReservationRequest("dup", "gpu", 0, 2, units=2),
            ReservationRequest("dup", "gpu", 2, 4, units=2),
        ]
        with self.assertRaises(ValueError):
            svc.submit_batch(batch_dup)
        self.assertEqual(len(svc.allocator.get_allocations()), 0)

        # Sorting test:
        # Same priority=1, same start=0.
        # req_short_many: duration=2, units=4 -> unit_hours = 8
        # req_long_few: duration=5, units=1 -> unit_hours = 5
        # req_short_many should be processed first and take all 4 units on [0, 2],
        # causing req_long_few (needs 1 unit on [0, 5]) to fail!
        reqs = [
            ReservationRequest("req_long_few", "gpu", 0, 5, priority=1, units=1),
            ReservationRequest("req_short_many", "gpu", 0, 2, priority=1, units=4),
        ]
        results = svc.submit_batch(reqs)
        self.assertIsNotNone(results["req_short_many"])
        self.assertIsNone(results["req_long_few"])

        # Existing request_id conflict in subsequent batch
        with self.assertRaises(ValueError):
            svc.submit_batch(
                [
                    ReservationRequest("new_one", "gpu", 5, 6, units=1),
                    ReservationRequest("req_short_many", "gpu", 6, 7, units=1),
                ]
            )
        # Ensure 'new_one' was not allocated due to atomic pre-check
        self.assertEqual(len(svc.allocator.get_allocations()), 1)

    def test_10_cancel_or_reduce(self) -> None:
        svc = BookingService()
        svc.register_resource("r1", "gpu", 5)
        svc.submit_batch([ReservationRequest("b1", "gpu", 0, 4, units=5)])

        self.assertFalse(svc.cancel_or_reduce("unknown_id"))
        with self.assertRaises(ValueError):
            svc.cancel_or_reduce("b1", units=6)

        self.assertTrue(svc.cancel_or_reduce("b1", units=3))
        self.assertEqual(svc.allocator.available_units("r1", 0, 4), 3)

        self.assertTrue(svc.cancel_or_reduce("b1"))
        self.assertEqual(svc.allocator.available_units("r1", 0, 4), 5)
        self.assertFalse(svc.cancel_or_reduce("b1"))

    def test_11_utilization_report_with_units_and_peak(self) -> None:
        svc = BookingService()
        svc.register_resource("g1", "gpu", 4)
        svc.register_resource("g2", "gpu", 6)
        svc.register_resource("c1", "cpu", 10)

        # Total gpu capacity over [2, 8] (duration 6) = (4 + 6) * 6 = 60.0
        svc.submit_batch(
            [
                # Overlaps [2, 8] on [2, 5] -> 3 hours * 3 units = 9
                ReservationRequest("q1", "gpu", 0, 5, units=3, preferred_resource_id="g1"),
                # Overlaps [2, 8] on [4, 7] -> 3 hours * 5 units = 15
                ReservationRequest("q2", "gpu", 4, 7, units=5, preferred_resource_id="g2"),
                # Different category
                ReservationRequest("q3", "cpu", 2, 8, units=10),
            ]
        )
        # Peak concurrent in [2, 8]:
        # t=2,3: q1(3) = 3
        # t=4: q1(3) + q2(5) = 8
        # t=5,6: q2(5) = 5
        # t=7: 0
        report = svc.utilization_report("gpu", 2, 8)
        self.assertAlmostEqual(report["total_capacity_unit_hours"], 60.0)
        self.assertAlmostEqual(report["allocated_unit_hours"], 24.0)
        self.assertAlmostEqual(report["utilization_rate"], 24.0 / 60.0)
        self.assertAlmostEqual(report["peak_concurrent_units"], 8.0)

        # Empty category report
        empty_rep = svc.utilization_report("tpu", 0, 10)
        self.assertEqual(empty_rep["total_capacity_unit_hours"], 0.0)
        self.assertEqual(empty_rep["allocated_unit_hours"], 0.0)
        self.assertEqual(empty_rep["utilization_rate"], 0.0)
        self.assertEqual(empty_rep["peak_concurrent_units"], 0.0)

    def test_12_reschedule_same_resource(self) -> None:
        svc = BookingService()
        svc.register_resource("g1", "gpu", 4)
        svc.register_resource("g2", "gpu", 4)

        svc.submit_batch(
            [
                ReservationRequest(
                    "req1", "gpu", 0, 4, priority=2, units=3, preferred_resource_id="g2"
                )
            ]
        )
        # Reschedule overlapping with its own previous time on g2, and increase units to 4
        new_alloc = svc.reschedule("req1", 2, 6, new_units=4)
        self.assertEqual(new_alloc.resource_id, "g2")
        self.assertEqual(new_alloc.start, 2)
        self.assertEqual(new_alloc.end, 6)
        self.assertEqual(new_alloc.units, 4)
        self.assertEqual(new_alloc.priority, 2)
        self.assertEqual(svc.allocator.available_units("g2", 0, 2), 4)

    def test_13_reschedule_fallback_to_other_resource(self) -> None:
        svc = BookingService()
        svc.register_resource("g1", "gpu", 4)
        svc.register_resource("g2", "gpu", 6)

        svc.submit_batch(
            [
                ReservationRequest(
                    "req1", "gpu", 0, 4, priority=5, units=3, preferred_resource_id="g1"
                ),
                ReservationRequest(
                    "blocker", "gpu", 4, 8, priority=1, units=2, preferred_resource_id="g1"
                ),
            ]
        )
        # Reschedule req1 to [4, 8] keeping 3 units:
        # g1 only has 2 units free in [4, 8], so g1 fails -> falls back to g2
        moved = svc.reschedule("req1", 4, 8)
        self.assertEqual(moved.resource_id, "g2")
        self.assertEqual(moved.units, 3)
        self.assertEqual(moved.start, 4)
        self.assertEqual(moved.end, 8)
        self.assertEqual(moved.priority, 5)
        self.assertEqual(svc.allocator.available_units("g1", 0, 4), 4)

    def test_14_reschedule_rollback_on_failure(self) -> None:
        svc = BookingService()
        svc.register_resource("g1", "gpu", 4)
        svc.register_resource("g2", "gpu", 4)

        # Partially allocated request (requested 4, min 2, got 3 on g1)
        svc.submit_batch(
            [
                ReservationRequest(
                    " occupy_g1", "gpu", 0, 4, priority=5, units=1, preferred_resource_id="g1"
                ),
                ReservationRequest(
                    "target", "gpu", 0, 4, priority=3, units=4, min_units=2, preferred_resource_id="g1"
                ),
                ReservationRequest(
                    "block_g1", "gpu", 5, 9, units=3, preferred_resource_id="g1"
                ),
                ReservationRequest(
                    "block_g2", "gpu", 5, 9, units=3, preferred_resource_id="g2"
                ),
            ]
        )
        orig = [a for a in svc.allocator.get_allocations() if a.request_id == "target"][0]
        self.assertEqual(orig.units, 3)

        # Try to reschedule "target" (3 units) to [5, 9] where both g1 and g2 only have 1 unit free.
        # Must fail with RuntimeError (no partial allocation allowed on reschedule) and restore original!
        with self.assertRaises(RuntimeError):
            svc.reschedule("target", 5, 9)

        restored = [
            a for a in svc.allocator.get_allocations() if a.request_id == "target"
        ][0]
        self.assertEqual(restored, orig)

    def test_15_reschedule_invalid_args_and_unknown_id(self) -> None:
        svc = BookingService()
        svc.register_resource("g1", "gpu", 4)
        svc.submit_batch([ReservationRequest("r1", "gpu", 2, 5, units=2)])

        with self.assertRaises(KeyError):
            svc.reschedule("unknown", 0, 2)

        with self.assertRaises(ValueError):
            svc.reschedule("r1", -1, 3)
        with self.assertRaises(ValueError):
            svc.reschedule("r1", 4, 4)
        with self.assertRaises(ValueError):
            svc.reschedule("r1", 0, 2, new_units=0)

        # Original allocation must still be intact
        allocs = svc.allocator.get_allocations("g1")
        self.assertEqual(len(allocs), 1)
        self.assertEqual(allocs[0].start, 2)
        self.assertEqual(allocs[0].end, 5)
        self.assertEqual(allocs[0].units, 2)


if __name__ == "__main__":
    unittest.main()
