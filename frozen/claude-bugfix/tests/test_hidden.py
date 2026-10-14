import unittest
from datetime import datetime

import parking
from parking import (
    DAY,
    NIGHT,
    Rule,
    block_fee,
    calc_fee,
    daily_summary,
    format_yen,
    make_receipt,
    parse_time,
    split_segments,
)


def dt(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


class TestParseTime(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse_time("2026-04-01 09:05"), datetime(2026, 4, 1, 9, 5))

    def test_surrounding_whitespace(self):
        self.assertEqual(parse_time("  2026-04-01 09:05\n"), datetime(2026, 4, 1, 9, 5))

    def test_rejects_unpadded(self):
        for text in ["2026-4-01 09:05", "2026-04-1 09:05", "2026-04-01 9:05", "2026-04-01 09:5"]:
            with self.assertRaises(ValueError, msg=text):
                parse_time(text)

    def test_rejects_wrong_separator(self):
        for text in ["2026-04-01  09:05", "2026-04-01T09:05", "2026/04/01 09:05", "2026-04-01 09:05:00"]:
            with self.assertRaises(ValueError, msg=text):
                parse_time(text)

    def test_rejects_nonexistent(self):
        for text in ["2026-02-30 10:00", "2026-04-01 24:00", "2026-04-01 12:60"]:
            with self.assertRaises(ValueError, msg=text):
                parse_time(text)

    def test_rejects_fullwidth_digits(self):
        with self.assertRaises(ValueError):
            parse_time("２０２６-04-01 09:05")


class TestRule(unittest.TestCase):
    def test_valid(self):
        Rule()
        Rule(day_start=0, night_start=24)
        Rule(daily_max=None)
        Rule(free_minutes=0, day_price=0, night_price=0)

    def test_invalid(self):
        bad = [
            dict(day_start=8, night_start=8),
            dict(day_start=10, night_start=9),
            dict(night_start=25),
            dict(day_start=-1),
            dict(day_unit=0),
            dict(night_unit=-30),
            dict(daily_max=0),
            dict(free_minutes=-1),
            dict(night_price=-1),
        ]
        for kwargs in bad:
            with self.assertRaises(ValueError, msg=str(kwargs)):
                Rule(**kwargs)


class TestSplitSegments(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            split_segments(dt("2026-04-01 21:00"), dt("2026-04-01 23:30"), Rule()),
            [
                (dt("2026-04-01 21:00"), dt("2026-04-01 22:00"), DAY),
                (dt("2026-04-01 22:00"), dt("2026-04-01 23:30"), NIGHT),
            ],
        )

    def test_boundary_belongs_to_next_band(self):
        self.assertEqual(
            split_segments(dt("2026-04-01 07:30"), dt("2026-04-01 08:30"), Rule()),
            [
                (dt("2026-04-01 07:30"), dt("2026-04-01 08:00"), NIGHT),
                (dt("2026-04-01 08:00"), dt("2026-04-01 08:30"), DAY),
            ],
        )
        self.assertEqual(
            split_segments(dt("2026-04-01 22:00"), dt("2026-04-01 22:30"), Rule()),
            [(dt("2026-04-01 22:00"), dt("2026-04-01 22:30"), NIGHT)],
        )
        self.assertEqual(
            split_segments(dt("2026-04-01 10:00"), dt("2026-04-01 22:00"), Rule()),
            [(dt("2026-04-01 10:00"), dt("2026-04-01 22:00"), DAY)],
        )

    def test_empty_and_reversed(self):
        self.assertEqual(split_segments(dt("2026-04-01 10:00"), dt("2026-04-01 10:00"), Rule()), [])
        with self.assertRaises(ValueError):
            split_segments(dt("2026-04-01 10:00"), dt("2026-04-01 09:59"), Rule())

    def test_multi_day(self):
        self.assertEqual(
            split_segments(dt("2026-04-01 20:00"), dt("2026-04-03 09:00"), Rule()),
            [
                (dt("2026-04-01 20:00"), dt("2026-04-01 22:00"), DAY),
                (dt("2026-04-01 22:00"), dt("2026-04-02 08:00"), NIGHT),
                (dt("2026-04-02 08:00"), dt("2026-04-02 22:00"), DAY),
                (dt("2026-04-02 22:00"), dt("2026-04-03 08:00"), NIGHT),
                (dt("2026-04-03 08:00"), dt("2026-04-03 09:00"), DAY),
            ],
        )

    def test_whole_day_band(self):
        rule = Rule(day_start=0, night_start=24)
        self.assertEqual(
            split_segments(dt("2026-04-01 23:00"), dt("2026-04-03 01:00"), rule),
            [(dt("2026-04-01 23:00"), dt("2026-04-03 01:00"), DAY)],
        )

    def test_night_start_24(self):
        rule = Rule(day_start=8, night_start=24)
        self.assertEqual(
            split_segments(dt("2026-04-01 23:00"), dt("2026-04-02 09:00"), rule),
            [
                (dt("2026-04-01 23:00"), dt("2026-04-02 00:00"), DAY),
                (dt("2026-04-02 00:00"), dt("2026-04-02 08:00"), NIGHT),
                (dt("2026-04-02 08:00"), dt("2026-04-02 09:00"), DAY),
            ],
        )

    def test_day_start_0(self):
        rule = Rule(day_start=0, night_start=20)
        self.assertEqual(
            split_segments(dt("2026-04-01 19:00"), dt("2026-04-02 01:00"), rule),
            [
                (dt("2026-04-01 19:00"), dt("2026-04-01 20:00"), DAY),
                (dt("2026-04-01 20:00"), dt("2026-04-02 00:00"), NIGHT),
                (dt("2026-04-02 00:00"), dt("2026-04-02 01:00"), DAY),
            ],
        )


class TestBlockFee(unittest.TestCase):
    def test_units_round_up_per_segment(self):
        # 昼 10 分 → 1 単位、夜 10 分 → 1 単位
        self.assertEqual(block_fee(dt("2026-04-01 21:50"), dt("2026-04-01 22:10"), Rule()), 300)

    def test_exact_multiple(self):
        self.assertEqual(block_fee(dt("2026-04-01 10:00"), dt("2026-04-01 11:00"), Rule()), 400)
        self.assertEqual(block_fee(dt("2026-04-01 22:00"), dt("2026-04-02 00:00"), Rule()), 200)

    def test_cap_and_no_cap(self):
        self.assertEqual(block_fee(dt("2026-04-01 08:00"), dt("2026-04-01 22:00"), Rule()), 1500)
        self.assertEqual(
            block_fee(dt("2026-04-01 08:00"), dt("2026-04-01 22:00"), Rule(daily_max=None)), 5600
        )

    def test_no_free_minutes_in_block(self):
        self.assertEqual(block_fee(dt("2026-04-01 10:00"), dt("2026-04-01 10:05"), Rule()), 200)


class TestCalcFee(unittest.TestCase):
    def test_free_boundary(self):
        self.assertEqual(calc_fee(dt("2026-04-01 10:00"), dt("2026-04-01 10:15")), 0)
        self.assertEqual(calc_fee(dt("2026-04-01 10:00"), dt("2026-04-01 10:16")), 200)

    def test_zero_duration_and_reversed(self):
        self.assertEqual(calc_fee(dt("2026-04-01 10:00"), dt("2026-04-01 10:00")), 0)
        self.assertEqual(
            calc_fee(dt("2026-04-01 10:00"), dt("2026-04-01 10:00"), Rule(free_minutes=0)), 0
        )
        with self.assertRaises(ValueError):
            calc_fee(dt("2026-04-01 10:00"), dt("2026-04-01 09:00"))

    def test_free_minutes_zero(self):
        self.assertEqual(
            calc_fee(dt("2026-04-01 10:00"), dt("2026-04-01 10:01"), Rule(free_minutes=0)), 200
        )

    def test_exact_unit(self):
        self.assertEqual(calc_fee(dt("2026-04-01 10:00"), dt("2026-04-01 10:30")), 200)
        self.assertEqual(calc_fee(dt("2026-04-01 10:00"), dt("2026-04-01 10:31")), 400)

    def test_across_band(self):
        self.assertEqual(calc_fee(dt("2026-04-01 21:00"), dt("2026-04-01 23:30")), 600)

    def test_daily_cap(self):
        self.assertEqual(calc_fee(dt("2026-04-01 08:00"), dt("2026-04-01 22:00")), 1500)

    def test_exactly_24_hours_is_one_block(self):
        self.assertEqual(calc_fee(dt("2026-04-01 10:00"), dt("2026-04-02 10:00")), 1500)

    def test_blocks_from_entry(self):
        self.assertEqual(calc_fee(dt("2026-04-01 10:00"), dt("2026-04-03 12:00")), 3800)

    def test_short_last_block_is_charged(self):
        self.assertEqual(calc_fee(dt("2026-04-01 10:00"), dt("2026-04-02 10:10")), 1700)
        self.assertEqual(calc_fee(dt("2026-04-01 20:00"), dt("2026-04-02 20:20")), 1700)

    def test_no_cap(self):
        rule = Rule(daily_max=None)
        self.assertEqual(calc_fee(dt("2026-04-01 08:00"), dt("2026-04-01 22:00"), rule), 5600)
        # 10:00〜翌10:00 (昼 4800 + 夜 1000 + 昼 800) + 10:00〜10:10 (200)
        self.assertEqual(calc_fee(dt("2026-04-01 10:00"), dt("2026-04-02 10:10"), rule), 6800)

    def test_custom_rule(self):
        rule = Rule(
            free_minutes=0,
            day_start=7,
            night_start=19,
            day_unit=15,
            day_price=100,
            night_unit=30,
            night_price=50,
            daily_max=None,
        )
        self.assertEqual(calc_fee(dt("2026-04-01 18:50"), dt("2026-04-01 19:40"), rule), 200)

    def test_night_start_24_rule(self):
        rule = Rule(day_start=8, night_start=24, daily_max=None)
        # 昼 23:00〜24:00 = 400、夜 00:00〜08:00 = 800、昼 08:00〜09:00 = 400
        self.assertEqual(calc_fee(dt("2026-04-01 23:00"), dt("2026-04-02 09:00"), rule), 1600)


class TestFormatYen(unittest.TestCase):
    def test_values(self):
        cases = {
            0: "¥0",
            5: "¥5",
            100: "¥100",
            999: "¥999",
            1000: "¥1,000",
            12345: "¥12,345",
            123456: "¥123,456",
            1234567: "¥1,234,567",
        }
        for amount, expected in cases.items():
            self.assertEqual(format_yen(amount), expected)

    def test_negative(self):
        with self.assertRaises(ValueError):
            format_yen(-1)


class TestReceipt(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            make_receipt("2026-04-01 21:00", "2026-04-01 23:30"),
            "入庫 2026-04-01 21:00\n出庫 2026-04-01 23:30\n駐車時間 2時間30分\n料金 ¥600",
        )

    def test_long_stay(self):
        self.assertEqual(
            make_receipt(" 2026-04-01 10:00 ", "2026-04-03 12:00\n"),
            "入庫 2026-04-01 10:00\n出庫 2026-04-03 12:00\n駐車時間 50時間0分\n料金 ¥3,800",
        )

    def test_free(self):
        self.assertEqual(
            make_receipt("2026-04-01 23:58", "2026-04-02 00:03"),
            "入庫 2026-04-01 23:58\n出庫 2026-04-02 00:03\n駐車時間 0時間5分\n料金 ¥0",
        )

    def test_with_rule_and_errors(self):
        self.assertEqual(
            make_receipt("2026-04-01 08:00", "2026-04-01 22:00", Rule(daily_max=None)),
            "入庫 2026-04-01 08:00\n出庫 2026-04-01 22:00\n駐車時間 14時間0分\n料金 ¥5,600",
        )
        with self.assertRaises(ValueError):
            make_receipt("2026-04-01 10:00", "2026-04-01 09:00")
        with self.assertRaises(ValueError):
            make_receipt("2026-04-01 10:00", "2026-04-01 9:30")


class TestDailySummary(unittest.TestCase):
    RECORDS = [
        ("2026-04-01 23:00", "2026-04-02 00:10"),  # 夜 70 分 → 200
        ("2026-04-01 21:00", "2026-04-01 23:30"),  # 600
        ("2026-04-02 10:00", "2026-04-02 10:10"),  # 無料
        ("2026-03-31 09:00", "2026-04-01 08:00"),  # 上限 1500
    ]

    def test_group_by_exit_date(self):
        self.assertEqual(
            daily_summary(self.RECORDS),
            [("2026-04-01", 2, 2100), ("2026-04-02", 2, 200)],
        )

    def test_with_rule(self):
        self.assertEqual(
            daily_summary(iter(self.RECORDS), Rule(daily_max=None)),
            [("2026-04-01", 2, 6800), ("2026-04-02", 2, 200)],
        )

    def test_empty(self):
        self.assertEqual(daily_summary([]), [])

    def test_invalid_record(self):
        with self.assertRaises(ValueError):
            daily_summary([("2026-04-01 10:00", "2026-04-01 09:00")])
        with self.assertRaises(ValueError):
            daily_summary([("2026-04-01 10:00", "2026-04-01 11:00"), ("bad", "2026-04-01 11:00")])


if __name__ == "__main__":
    unittest.main()
