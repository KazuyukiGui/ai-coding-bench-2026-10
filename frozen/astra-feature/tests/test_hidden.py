import copy
import itertools
import unittest

from capacity_calendar import CapacityCalendar


def request(booking_id="new", resource="r", start=0, end=10,
            duration=3, **options):
    result = {
        "id": booking_id,
        "resource": resource,
        "start": start,
        "end": end,
        "duration": duration,
    }
    result.update(options)
    return result


def snapshot(booking_id, resource, units, segments):
    return {
        "id": booking_id,
        "resource": resource,
        "units": units,
        "segments": segments,
    }


def segments_of(ticks):
    result = []
    for tick in ticks:
        if result and result[-1][1] == tick:
            result[-1] = (result[-1][0], tick + 1)
        else:
            result.append((tick, tick + 1))
    return result


def brute_plan(available, duration, min_part, max_parts):
    """Enumerate actual selected time units, independently of the solver."""
    for ticks in itertools.combinations(available, duration):
        segments = segments_of(ticks)
        if len(segments) > max_parts:
            continue
        if all(right - left >= min_part for left, right in segments):
            return segments
    return None


class CalendarTests(unittest.TestCase):
    def make_calendar(self, capacity=1):
        calendar = CapacityCalendar()
        calendar.add_resource("r", capacity)
        return calendar

    def assert_failure_unchanged(self, calendar, operation):
        before = calendar.bookings()
        with self.assertRaises(ValueError):
            operation()
        self.assertEqual(calendar.bookings(), before)

    def test_01_empty_and_resource_registration(self):
        calendar = CapacityCalendar()
        self.assertEqual(calendar.bookings(), [])
        self.assertIsNone(calendar.add_resource("r", 2))
        self.assertEqual(calendar.free_spans("r", 0, 4, 2), [(0, 4)])
        with self.assertRaises(ValueError):
            calendar.add_resource("r", 7)
        self.assertEqual(calendar.free_spans("r", 0, 4, 3), [])

    def test_02_original_book_get_cancel(self):
        calendar = self.make_calendar(3)
        expected = snapshot("a", "r", 2, [(2, 7)])
        self.assertEqual(calendar.book("a", "r", 2, 7, 2), expected)
        self.assertEqual(calendar.get("a"), expected)
        self.assertEqual(calendar.cancel("a"), expected)
        self.assertEqual(calendar.bookings(), [])
        with self.assertRaises(ValueError):
            calendar.get("a")

    def test_03_half_open_intervals(self):
        calendar = self.make_calendar()
        calendar.book("a", "r", 0, 3)
        calendar.book("b", "r", 3, 6)
        self.assertEqual(calendar.free_spans("r", 0, 8), [(6, 8)])
        self.assert_failure_unchanged(
            calendar, lambda: calendar.book("c", "r", 2, 4)
        )

    def test_04_capacity_and_clipped_queries(self):
        calendar = self.make_calendar(4)
        calendar.book("a", "r", 0, 8, 2)
        calendar.book("b", "r", 3, 5, 2)
        self.assertEqual(
            calendar.free_spans("r", 2, 7, 2), [(2, 3), (5, 7)]
        )
        self.assertEqual(calendar.free_spans("r", 3, 5), [])
        self.assertEqual(calendar.free_spans("r", 8, 9, 4), [(8, 9)])

    def test_05_merge_through_usage_changes(self):
        calendar = self.make_calendar(4)
        calendar.book("a", "r", 1, 4, 1)
        calendar.book("b", "r", 3, 7, 1)
        calendar.book("c", "r", 7, 9, 2)
        self.assertEqual(calendar.free_spans("r", 0, 10, 2), [(0, 10)])
        self.assertEqual(
            calendar.free_spans("r", 0, 10, 3),
            [(0, 3), (4, 7), (9, 10)],
        )

    def test_06_order_filter_and_literal_names(self):
        calendar = self.make_calendar(5)
        calendar.add_resource(" ", 1)
        calendar.book("あ", "r", 0, 1)
        calendar.book("a", "r", 0, 1)
        calendar.book("B", "r", 0, 1)
        calendar.book(" ", " ", 0, 1)
        self.assertEqual(
            [item["id"] for item in calendar.bookings()],
            [" ", "B", "a", "あ"],
        )
        self.assertEqual(
            [item["id"] for item in calendar.bookings("r")],
            ["B", "a", "あ"],
        )
        self.assertEqual(calendar.get(" ")["resource"], " ")

    def test_07_original_snapshots_are_independent(self):
        calendar = self.make_calendar()
        first = calendar.book("a", "r", 2, 5)
        second = calendar.get("a")
        first["segments"].append((7, 8))
        first["resource"] = "changed"
        second["segments"].clear()
        listed = calendar.bookings()
        listed[0]["segments"][0] = (0, 100)
        listed.clear()
        self.assertEqual(
            calendar.get("a"), snapshot("a", "r", 1, [(2, 5)])
        )
        free = calendar.free_spans("r", 0, 7)
        free.clear()
        self.assertEqual(calendar.free_spans("r", 0, 7), [(0, 2), (5, 7)])

    def test_08_original_invalid_inputs_are_atomic(self):
        calendar = self.make_calendar()
        calendar.book("old", "r", 0, 2)
        operations = [
            lambda: calendar.book("old", "r", 3, 4),
            lambda: calendar.book("", "r", 3, 4),
            lambda: calendar.book("x", "missing", 3, 4),
            lambda: calendar.book("x", "r", -1, 4),
            lambda: calendar.book("x", "r", 4, 4),
            lambda: calendar.book("x", "r", False, 4),
            lambda: calendar.book("x", "r", 3, 4.0),
            lambda: calendar.book("x", "r", 3, 4, True),
            lambda: calendar.book("x", "r", 3, 4, 0),
            lambda: calendar.cancel("missing"),
            lambda: calendar.get([]),
            lambda: calendar.bookings("missing"),
            lambda: calendar.free_spans("r", 2, 2),
            lambda: calendar.free_spans("r", 0, 5, False),
            lambda: calendar.add_resource("bad", True),
        ]
        for operation in operations:
            with self.subTest(operation=operation):
                self.assert_failure_unchanged(calendar, operation)

    def test_09_default_plan_is_earliest_contiguous(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 2, 4)
        result = calendar.plan([request(duration=3)])
        expected = snapshot("new", "r", 1, [(4, 7)])
        self.assertEqual(result, [expected])
        self.assertEqual(calendar.get("new"), expected)

    def test_10_split_uses_earliest_time_units(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 2, 4)
        result = calendar.plan([request(duration=5, max_parts=2)])
        self.assertEqual(result[0]["segments"], [(0, 2), (4, 7)])

    def test_11_shorten_first_part_for_minimum_tail(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 5, 7)
        result = calendar.plan([
            request(end=11, duration=6, min_part=3, max_parts=2)
        ])
        self.assertEqual(result[0]["segments"], [(0, 3), (7, 10)])

    def test_12_small_spans_are_skipped(self):
        calendar = self.make_calendar()
        calendar.book("b1", "r", 2, 4)
        calendar.book("b2", "r", 8, 9)
        result = calendar.plan([
            request(end=13, duration=6, min_part=3, max_parts=2)
        ])
        self.assertEqual(result[0]["segments"], [(4, 7), (9, 12)])

    def test_13_part_limit_can_force_skipping_earliest_span(self):
        calendar = self.make_calendar()
        calendar.book("b1", "r", 2, 3)
        calendar.book("b2", "r", 5, 6)
        result = calendar.plan([
            request(end=11, duration=7, max_parts=2)
        ])
        self.assertEqual(result[0]["segments"], [(0, 2), (6, 11)])

    def test_14_long_contiguous_span_is_one_part(self):
        calendar = self.make_calendar(3)
        calendar.book("b1", "r", 1, 3)
        calendar.book("b2", "r", 3, 5)
        result = calendar.plan([
            request(end=6, duration=6, units=2, min_part=6, max_parts=6)
        ])
        self.assertEqual(result[0]["segments"], [(0, 6)])

    def test_15_capacity_threshold_drives_split(self):
        calendar = self.make_calendar(3)
        calendar.book("background", "r", 0, 10, 1)
        calendar.book("block", "r", 2, 5, 1)
        result = calendar.plan([
            request(duration=6, units=2, max_parts=2)
        ])
        self.assertEqual(result[0]["segments"], [(0, 2), (5, 9)])
        self.assertEqual(calendar.free_spans("r", 0, 10, 2), [(9, 10)])
        self.assertEqual(calendar.free_spans("r", 0, 10), [(2, 5), (9, 10)])

    def test_16_lexicographic_choice_over_fewer_parts(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 1, 3)
        result = calendar.plan([
            request(end=8, duration=4, max_parts=2)
        ])
        self.assertEqual(result[0]["segments"], [(0, 1), (3, 6)])

    def test_17_batch_order_and_return_order(self):
        calendar = self.make_calendar()
        result = calendar.plan([
            request("z", end=8, duration=3),
            request("a", end=8, duration=2),
        ])
        self.assertEqual(
            result,
            [
                snapshot("z", "r", 1, [(0, 3)]),
                snapshot("a", "r", 1, [(3, 5)]),
            ],
        )
        self.assertEqual(
            [item["id"] for item in calendar.bookings()], ["a", "z"]
        )

    def test_18_no_backtracking_between_requests(self):
        calendar = self.make_calendar()
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan([
                request("a", end=4, duration=2),
                request("b", end=2, duration=2),
            ]),
        )
        self.assertEqual(calendar.free_spans("r", 0, 4), [(0, 4)])

    def test_19_all_replacements_removed_before_planning(self):
        calendar = self.make_calendar()
        calendar.book("old_a", "r", 0, 3)
        calendar.book("old_b", "r", 3, 6)
        result = calendar.plan(
            [request("old_a", end=6, duration=6)],
            replace=["old_b", "old_a"],
        )
        self.assertEqual(
            result, [snapshot("old_a", "r", 1, [(0, 6)])]
        )
        with self.assertRaises(ValueError):
            calendar.get("old_b")

    def test_20_replacement_can_move_resource(self):
        calendar = self.make_calendar()
        calendar.add_resource("s", 2)
        calendar.book("old", "r", 0, 5)
        result = calendar.plan(
            [request("old", resource="s", end=5, duration=4, units=2)],
            replace=("old",),
        )
        self.assertEqual(result, [snapshot("old", "s", 2, [(0, 4)])])
        self.assertEqual(calendar.free_spans("r", 0, 5), [(0, 5)])
        self.assertEqual(calendar.bookings("r"), [])

    def test_21_late_capacity_failure_restores_replacements(self):
        calendar = self.make_calendar()
        calendar.book("old", "r", 0, 5)
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan(
                [
                    request("first", end=5, duration=4),
                    request("second", end=5, duration=2),
                ],
                replace=["old"],
            ),
        )
        self.assertEqual(calendar.free_spans("r", 0, 6), [(5, 6)])

    def test_22_late_validation_failure_restores_everything(self):
        calendar = self.make_calendar()
        calendar.book("old", "r", 0, 5)
        invalid = request("second")
        invalid["extra"] = 1
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan(
                [request("first"), invalid], replace=["old"]
            ),
        )

    def test_23_empty_plan_and_delete_only(self):
        calendar = self.make_calendar()
        calendar.book("a", "r", 0, 3)
        calendar.book("b", "r", 3, 6)
        self.assertEqual(calendar.plan([]), [])
        self.assertEqual(calendar.plan([], replace=["a"]), [])
        self.assertEqual(
            calendar.bookings(), [snapshot("b", "r", 1, [(3, 6)])]
        )

    def test_24_duplicate_ids_in_batch_and_existing(self):
        calendar = self.make_calendar(3)
        calendar.book("old", "r", 0, 2)
        calendar.add_resource("s", 3)
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan([request("old", resource="s")]),
        )
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan(
                [request("old"), request("old", resource="s")],
                replace=["old"],
            ),
        )

    def test_25_invalid_replacement_lists(self):
        calendar = self.make_calendar()
        calendar.book("old", "r", 0, 2)
        for replacement in (
            ["old", "old"],
            ["old", "missing"],
            "old",
            {"old"},
            None,
            [""],
            [[]],
        ):
            with self.subTest(replacement=replacement):
                self.assert_failure_unchanged(
                    calendar,
                    lambda replacement=replacement: calendar.plan(
                        [], replace=replacement
                    ),
                )

    def test_26_invalid_request_containers_and_keys(self):
        calendar = self.make_calendar()
        missing = request()
        del missing["duration"]
        extra = request()
        extra["note"] = "unused"
        for requests in ((), {}, None, [None], [[]], [missing], [extra]):
            with self.subTest(requests=requests):
                self.assert_failure_unchanged(
                    calendar,
                    lambda requests=requests: calendar.plan(requests),
                )

    def test_27_invalid_request_values(self):
        calendar = self.make_calendar()
        invalid_values = {
            "id": ["", 1, []],
            "resource": ["missing", "", None, []],
            "start": [-1, True, 1.0, 10],
            "end": [0, -1, False, 10.0, 121],
            "duration": [0, -1, True, 3.0, 11],
            "units": [0, -1, True, 1.0],
            "min_part": [0, -1, True, 1.0, 4],
            "max_parts": [0, -1, True, 1.0, 7],
        }
        for key, values in invalid_values.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    item = request()
                    item[key] = value
                    self.assert_failure_unchanged(
                        calendar,
                        lambda item=item: calendar.plan([item]),
                    )

    def test_28_infeasible_fragmentation(self):
        calendar = self.make_calendar()
        calendar.book("b1", "r", 2, 3)
        calendar.book("b2", "r", 5, 6)
        calendar.book("b3", "r", 8, 9)
        cases = [
            request(end=11, duration=6, min_part=3, max_parts=3),
            request(end=11, duration=7, max_parts=3),
            request(end=11, duration=3, max_parts=1),
        ]
        for item in cases:
            with self.subTest(item=item):
                self.assert_failure_unchanged(
                    calendar, lambda item=item: calendar.plan([item])
                )

    def test_29_units_exceeding_capacity(self):
        calendar = self.make_calendar(2)
        self.assertEqual(calendar.free_spans("r", 0, 5, 3), [])
        self.assert_failure_unchanged(
            calendar, lambda: calendar.book("a", "r", 0, 5, 3)
        )
        self.assert_failure_unchanged(
            calendar, lambda: calendar.plan([request(units=3)])
        )

    def test_30_split_reservation_interoperates_with_existing_api(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 2, 4)
        result = calendar.plan([
            request("split", end=8, duration=5, max_parts=2)
        ])[0]
        self.assertEqual(result["segments"], [(0, 2), (4, 7)])
        self.assertEqual(calendar.get("split"), result)
        self.assertEqual(calendar.free_spans("r", 0, 9), [(7, 9)])
        calendar.book("tail", "r", 7, 9)
        self.assert_failure_unchanged(
            calendar, lambda: calendar.book("bad", "r", 6, 8)
        )
        self.assertEqual(calendar.cancel("split"), result)
        self.assertEqual(calendar.free_spans("r", 0, 9), [(0, 2), (4, 7)])

    def test_31_split_replacement_releases_every_segment(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 2, 4)
        calendar.plan([
            request("split", end=8, duration=5, max_parts=2)
        ])
        result = calendar.plan(
            [request("whole", end=8, duration=8)],
            replace=["split", "block"],
        )
        self.assertEqual(result, [snapshot("whole", "r", 1, [(0, 8)])])
        self.assertEqual(calendar.bookings(), result)

    def test_32_inputs_and_plan_results_are_independent(self):
        calendar = self.make_calendar(2)
        calendar.book("old", "r", 0, 10)
        requests = [
            request("a", duration=2),
            request("b", duration=2),
        ]
        replacements = ["old"]
        original_requests = copy.deepcopy(requests)
        original_replacements = replacements[:]
        result = calendar.plan(requests, replacements)
        self.assertEqual(requests, original_requests)
        self.assertEqual(replacements, original_replacements)
        requests[0]["duration"] = 9
        requests.clear()
        replacements.clear()
        result[0]["segments"].clear()
        result[0]["units"] = 100
        result[1]["segments"].append((8, 9))
        self.assertEqual(
            calendar.get("a"), snapshot("a", "r", 1, [(0, 2)])
        )
        self.assertEqual(
            calendar.get("b"), snapshot("b", "r", 1, [(0, 2)])
        )

    def test_33_failed_plan_preserves_inputs(self):
        calendar = self.make_calendar()
        calendar.book("old", "r", 0, 5)
        requests = [
            request("a", end=5, duration=4),
            request("b", end=5, duration=4),
        ]
        replacements = ["old"]
        before = copy.deepcopy((requests, replacements))
        self.assert_failure_unchanged(
            calendar, lambda: calendar.plan(requests, replacements)
        )
        self.assertEqual((requests, replacements), before)

    def test_34_window_boundary_and_large_absolute_times(self):
        calendar = self.make_calendar()
        base = 10**15
        calendar.book("earlier", "r", 0, base)
        result = calendar.plan([
            request(
                start=base, end=base + 120,
                duration=120, min_part=120, max_parts=6,
            )
        ])
        self.assertEqual(result[0]["segments"], [(base, base + 120)])
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan([
                request("wide", start=base + 200, end=base + 321)
            ]),
        )
        calendar.book("long", "r", base + 200, base + 1000)
        self.assertEqual(
            calendar.free_spans("r", base + 120, base + 1001),
            [(base + 120, base + 200), (base + 1000, base + 1001)],
        )

    def test_35_six_parts_at_limit(self):
        calendar = self.make_calendar()
        for index in range(5):
            calendar.book(
                "block" + str(index), "r", index * 3 + 2, index * 3 + 3
            )
        result = calendar.plan([
            request(end=17, duration=12, min_part=2, max_parts=6)
        ])
        self.assertEqual(
            result[0]["segments"],
            [(0, 2), (3, 5), (6, 8), (9, 11), (12, 14), (15, 17)],
        )

    def test_36_deterministic_exhaustive_small_windows(self):
        # All availability patterns on six time units, including empty
        # availability, are checked against an independent enumeration.
        horizon = 6
        for mask in range(1 << horizon):
            calendar = self.make_calendar()
            available = []
            for tick in range(horizon):
                if mask & (1 << tick):
                    available.append(tick)
                else:
                    calendar.book(
                        "blocked_" + str(tick), "r", tick, tick + 1
                    )
            original = calendar.bookings()
            for duration in range(1, horizon + 1):
                for min_part in range(1, min(3, duration) + 1):
                    for max_parts in (1, 2, 3):
                        expected = brute_plan(
                            available, duration, min_part, max_parts
                        )
                        with self.subTest(
                            mask=mask,
                            duration=duration,
                            min_part=min_part,
                            max_parts=max_parts,
                        ):
                            item = request(
                                end=horizon,
                                duration=duration,
                                min_part=min_part,
                                max_parts=max_parts,
                            )
                            if expected is None:
                                with self.assertRaises(ValueError):
                                    calendar.plan([item])
                            else:
                                result = calendar.plan([item])
                                self.assertEqual(
                                    result,
                                    [snapshot("new", "r", 1, expected)],
                                )
                                self.assertEqual(
                                    calendar.cancel("new"), result[0]
                                )
                            self.assertEqual(calendar.bookings(), original)


if __name__ == "__main__":
    unittest.main()
