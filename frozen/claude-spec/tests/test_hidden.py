import time
import unittest
from datetime import datetime as D

from cronexpr import CronError, parse


def fmt(values):
    return [v.strftime("%Y-%m-%d %H:%M") for v in values]


class TestNextAfterBasic(unittest.TestCase):
    def test_every_minute_strictly_after(self):
        s = parse("* * * * *")
        self.assertEqual(s.next_after(D(2024, 5, 1, 10, 0)), D(2024, 5, 1, 10, 1))
        self.assertEqual(s.next_after(D(2024, 5, 1, 10, 0, 30)), D(2024, 5, 1, 10, 1))
        self.assertEqual(
            s.next_after(D(2024, 5, 1, 10, 0, 0, 1)), D(2024, 5, 1, 10, 1)
        )

    def test_daily_time(self):
        s = parse("30 9 * * *")
        self.assertEqual(s.next_after(D(2024, 5, 1, 9, 30)), D(2024, 5, 2, 9, 30))
        self.assertEqual(
            s.next_after(D(2024, 5, 1, 9, 29, 59)), D(2024, 5, 1, 9, 30)
        )
        self.assertEqual(s.next_after(D(2024, 12, 31, 23, 0)), D(2025, 1, 1, 9, 30))

    def test_result_is_second_zero(self):
        r = parse("*/5 * * * *").next_after(D(2024, 5, 1, 10, 2, 45, 123))
        self.assertEqual(r, D(2024, 5, 1, 10, 5))
        self.assertEqual((r.second, r.microsecond), (0, 0))

    def test_year_rollover(self):
        s = parse("0 0 1 1 *")
        self.assertEqual(s.next_after(D(2023, 6, 1)), D(2024, 1, 1))
        self.assertEqual(s.next_after(D(2024, 1, 1)), D(2025, 1, 1))

    def test_ranges_and_steps(self):
        s = parse("*/15 9-17/4 * * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 7)),
            [
                "2024-01-01 09:00", "2024-01-01 09:15", "2024-01-01 09:30",
                "2024-01-01 09:45", "2024-01-01 13:00", "2024-01-01 13:15",
                "2024-01-01 13:30",
            ],
        )
        r = s.iter_after(D(2024, 1, 1, 17, 30), 2)
        self.assertEqual(fmt(r), ["2024-01-01 17:45", "2024-01-02 09:00"])

    def test_single_value_with_step(self):
        s = parse("5/20 * * * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1, 0, 5), 4)),
            ["2024-01-01 00:25", "2024-01-01 00:45",
             "2024-01-01 01:05", "2024-01-01 01:25"],
        )
        s = parse("0 */7 * * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1, 0, 0), 4)),
            ["2024-01-01 07:00", "2024-01-01 14:00",
             "2024-01-01 21:00", "2024-01-02 00:00"],
        )

    def test_step_larger_than_range_and_list(self):
        s = parse("5-10/20,30-31 0 1 1 *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 3)),
            ["2024-01-01 00:05", "2024-01-01 00:30", "2024-01-01 00:31"],
        )

    def test_dom_step_skips_short_months(self):
        s = parse("0 0 */10 * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 4, 21), 3)),
            ["2024-05-01 00:00", "2024-05-11 00:00", "2024-05-21 00:00"],
        )
        self.assertEqual(s.next_after(D(2024, 5, 21)), D(2024, 5, 31))


class TestLastDay(unittest.TestCase):
    def test_last_day_every_month(self):
        s = parse("0 12 L * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 31, 12, 0), 3)),
            ["2024-02-29 12:00", "2024-03-31 12:00", "2024-04-30 12:00"],
        )
        self.assertEqual(s.next_after(D(2023, 2, 1)), D(2023, 2, 28, 12, 0))

    def test_last_day_in_list_lowercase(self):
        s = parse("0 0 15,l 2 *")
        self.assertEqual(
            fmt(s.iter_after(D(2023, 1, 1), 4)),
            ["2023-02-15 00:00", "2023-02-28 00:00",
             "2024-02-15 00:00", "2024-02-29 00:00"],
        )

    def test_last_day_or_nth_weekday(self):
        s = parse("0 0 L * FRI#1")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 6)),
            ["2024-01-05 00:00", "2024-01-31 00:00", "2024-02-02 00:00",
             "2024-02-29 00:00", "2024-03-01 00:00", "2024-03-31 00:00"],
        )


class TestDayOfWeek(unittest.TestCase):
    def test_dom_or_dow_when_both_restricted(self):
        s = parse("0 0 13 * FRI")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 8)),
            ["2024-09-06 00:00", "2024-09-13 00:00", "2024-09-20 00:00",
             "2024-09-27 00:00", "2024-10-04 00:00", "2024-10-11 00:00",
             "2024-10-13 00:00", "2024-10-18 00:00"],
        )

    def test_only_dom_restricted(self):
        s = parse("0 0 13 * *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 2)),
            ["2024-09-13 00:00", "2024-10-13 00:00"],
        )

    def test_weekdays_only(self):
        s = parse("0 8 * * MON-FRI")
        # 2024-09-06 は金曜
        self.assertEqual(s.next_after(D(2024, 9, 6, 8, 0)), D(2024, 9, 9, 8, 0))

    def test_seven_is_sunday(self):
        a = parse("0 0 * * 7").iter_after(D(2024, 9, 1), 3)
        b = parse("0 0 * * 0").iter_after(D(2024, 9, 1), 3)
        c = parse("0 0 * * sun").iter_after(D(2024, 9, 1), 3)
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertEqual(fmt(a)[0], "2024-09-08 00:00")
        s = parse("0 0 * * 5-7")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 4)),
            ["2024-09-06 00:00", "2024-09-07 00:00",
             "2024-09-08 00:00", "2024-09-13 00:00"],
        )

    def test_dow_steps(self):
        s = parse("0 0 * * */2")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 4)),
            ["2024-09-03 00:00", "2024-09-05 00:00",
             "2024-09-07 00:00", "2024-09-08 00:00"],
        )
        s = parse("0 0 * * MON/2")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 4)),
            ["2024-09-02 00:00", "2024-09-04 00:00",
             "2024-09-06 00:00", "2024-09-09 00:00"],
        )

    def test_nth_weekday(self):
        s = parse("0 9 * * MON#2")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 3)),
            ["2024-01-08 09:00", "2024-02-12 09:00", "2024-03-11 09:00"],
        )
        s = parse("0 9 * * 5#5")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 5)),
            ["2024-03-29 09:00", "2024-05-31 09:00", "2024-08-30 09:00",
             "2024-11-29 09:00", "2025-01-31 09:00"],
        )
        s = parse("0 0 * * 7#1,SAT#1")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 3)),
            ["2024-09-07 00:00", "2024-10-05 00:00", "2024-10-06 00:00"],
        )

    def test_nth_weekday_or_dom(self):
        s = parse("0 0 1 * MON#1")
        self.assertEqual(
            fmt(s.iter_after(D(2023, 12, 31), 5)),
            ["2024-01-01 00:00", "2024-02-01 00:00", "2024-02-05 00:00",
             "2024-03-01 00:00", "2024-03-04 00:00"],
        )

    def test_restricted_means_not_exactly_star(self):
        # 日フィールドは "*,1" なので制限あり扱い。結果として毎日一致する
        s = parse("0 0 *,1 * MON")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 3)),
            ["2024-09-02 00:00", "2024-09-03 00:00", "2024-09-04 00:00"],
        )
        s = parse("0 0 1 * */1")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 9, 1), 2)),
            ["2024-09-02 00:00", "2024-09-03 00:00"],
        )
        s = parse("0 0 1-31 * MON")
        self.assertEqual(s.next_after(D(2024, 9, 1)), D(2024, 9, 2))


class TestSyntax(unittest.TestCase):
    def test_names_case_insensitive(self):
        s = parse("0 0 1 jan,Jul *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 2, 1), 2)),
            ["2024-07-01 00:00", "2025-01-01 00:00"],
        )
        s = parse("0 0 1 FEB-apr *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 4)),
            ["2024-02-01 00:00", "2024-03-01 00:00",
             "2024-04-01 00:00", "2025-02-01 00:00"],
        )
        s = parse("0 0 1 jan/5 *")
        self.assertEqual(
            fmt(s.iter_after(D(2024, 1, 1), 3)),
            ["2024-06-01 00:00", "2024-11-01 00:00", "2025-01-01 00:00"],
        )

    def test_macros(self):
        dt = D(2024, 9, 4, 10, 30)  # 水曜
        self.assertEqual(parse("@hourly").next_after(dt), D(2024, 9, 4, 11, 0))
        self.assertEqual(parse("@daily").next_after(dt), D(2024, 9, 5, 0, 0))
        self.assertEqual(parse("@weekly").next_after(dt), D(2024, 9, 8, 0, 0))
        self.assertEqual(parse("@monthly").next_after(dt), D(2024, 10, 1, 0, 0))
        self.assertEqual(parse("@yearly").next_after(dt), D(2025, 1, 1, 0, 0))
        self.assertEqual(parse("@annually").next_after(dt), D(2025, 1, 1, 0, 0))
        self.assertEqual(parse("@DAILY").next_after(dt), D(2024, 9, 5, 0, 0))
        self.assertEqual(parse("  @Weekly\t").next_after(dt), D(2024, 9, 8, 0, 0))

    def test_whitespace_and_leading_zeros(self):
        s = parse("\t 05   09\t* *  *  ")
        self.assertEqual(s.next_after(D(2024, 1, 1)), D(2024, 1, 1, 9, 5))
        s = parse("00 00 01 01 00")
        # 日・曜日とも制限あり: 1月のうち 1日 または日曜
        self.assertEqual(
            fmt(s.iter_after(D(2023, 12, 30), 3)),
            ["2024-01-01 00:00", "2024-01-07 00:00", "2024-01-14 00:00"],
        )

    def test_error_is_value_error(self):
        self.assertTrue(issubclass(CronError, ValueError))

    def test_invalid_expressions(self):
        bad = [
            "", "   ", "* * * *", "* * * * * *",
            "60 * * * *", "* 24 * * *", "* * 0 * *", "* * 32 * *",
            "* * * 0 *", "* * * 13 *", "* * * * 8",
            "5-1 * * * *", "* * * FEB-JAN *", "*/0 * * * *",
            "1,,2 * * * *", "1, * * * *", ",1 * * * *",
            "a * * * *", "-1 * * * *", "+1 * * * *", "1.0 * * * *",
            "\uff11 * * * *", "* * * * \uff11",
            "? * * * *", "* * ? * *", "* * * * ?",
            "*/ * * * *", "/5 * * * *", "1-/2 * * * *", "1- * * * *",
            "5/2/1 * * * *", "1-2-3 * * * *", "*/-1 * * * *",
            "L * * * *", "* L * * *", "* * * L *", "* * * * L",
            "* * L/2 * *", "* * 1-L * *", "* * LW * *",
            "* * MON * *", "* * * * JAN", "* * * MON *", "JAN * * * *",
            "* * * * MONDAY", "* * * JANUARY *",
            "* * * * MON#6", "* * * * MON#0", "* * * * 1-2#1",
            "* * * * #1", "* * * * MON#", "* * * * MON#1#1",
            "* * * * */2#1", "* * * * MON#\uff12", "* * * JAN#1 *", "* * 1#1 * *",
            "* * * * 7/2", "* * * * 8-9",
            "@reboot", "@daily *", "@", "@ daily",
            "* * * *\n*",
        ]
        for expr in bad:
            with self.subTest(expr=expr):
                with self.assertRaises(CronError):
                    parse(expr)

    def test_valid_edge_expressions(self):
        for expr in ["0-59 0-23 1-31 1-12 0-7", "59 23 31 12 7",
                     "* * * * 7#5", "* * * * 0-7/7", "* * 31/1 * *",
                     "* * * * 6/1", "* * l * *"]:
            with self.subTest(expr=expr):
                parse(expr)


class TestMatches(unittest.TestCase):
    def test_matches(self):
        s = parse("30 9 13 * FRI")
        self.assertTrue(s.matches(D(2024, 9, 13, 9, 30)))
        self.assertTrue(s.matches(D(2024, 9, 6, 9, 30)))   # 金曜
        self.assertTrue(s.matches(D(2024, 10, 13, 9, 30)))  # 13日（日曜）
        self.assertFalse(s.matches(D(2024, 9, 12, 9, 30)))
        self.assertFalse(s.matches(D(2024, 9, 13, 9, 31)))
        self.assertFalse(s.matches(D(2024, 9, 13, 9, 30, 1)))
        self.assertFalse(s.matches(D(2024, 9, 13, 9, 30, 0, 5)))

    def test_matches_last_and_nth(self):
        s = parse("0 0 L 2 *")
        self.assertTrue(s.matches(D(2024, 2, 29)))
        self.assertFalse(s.matches(D(2024, 2, 28)))
        self.assertTrue(s.matches(D(2023, 2, 28)))
        s = parse("0 0 * * TUE#3")
        self.assertTrue(s.matches(D(2024, 9, 17)))
        self.assertFalse(s.matches(D(2024, 9, 10)))
        self.assertFalse(s.matches(D(2024, 9, 24)))


class TestSearchWindow(unittest.TestCase):
    def test_impossible_returns_none(self):
        for expr in ["0 0 31 4 *", "0 0 30 2 *", "0 0 31 2,4,6,9,11 *"]:
            with self.subTest(expr=expr):
                s = parse(expr)
                self.assertIsNone(s.next_after(D(2024, 1, 1)))
                self.assertIsNone(s.prev_before(D(2024, 1, 1)))
                self.assertEqual(s.iter_after(D(2024, 1, 1), 3), [])

    def test_leap_day_window_inclusive(self):
        s = parse("0 0 29 2 *")
        self.assertEqual(s.next_after(D(2096, 3, 1)), D(2104, 2, 29))
        self.assertEqual(s.next_after(D(2096, 2, 29)), D(2104, 2, 29))
        self.assertEqual(s.prev_before(D(2104, 1, 1)), D(2096, 2, 29))
        self.assertEqual(s.prev_before(D(2105, 1, 1)), D(2104, 2, 29))

    def test_fifth_monday_of_february(self):
        s = parse("0 0 * 2 MON#5")
        self.assertEqual(s.next_after(D(2016, 1, 1)), D(2016, 2, 29))
        self.assertIsNone(s.next_after(D(2016, 3, 1)))
        self.assertEqual(s.next_after(D(2036, 3, 1)), D(2044, 2, 29))
        self.assertIsNone(s.next_after(D(2035, 12, 31, 23, 59)))
        self.assertEqual(s.prev_before(D(2052, 12, 31)), D(2044, 2, 29))
        self.assertIsNone(s.prev_before(D(2053, 1, 1)))
        # iter_after は毎回 next_after の探索範囲で打ち切られる
        self.assertEqual(s.iter_after(D(2016, 1, 1), 3), [D(2016, 2, 29)])

    def test_datetime_limits(self):
        s = parse("* * * * *")
        self.assertIsNone(s.next_after(D(9999, 12, 31, 23, 59)))
        self.assertIsNone(s.next_after(D(9999, 12, 31, 23, 59, 30)))
        self.assertEqual(
            s.next_after(D(9999, 12, 31, 23, 58, 59)), D(9999, 12, 31, 23, 59)
        )
        self.assertIsNone(s.prev_before(D(1, 1, 1, 0, 0)))
        self.assertEqual(s.prev_before(D(1, 1, 1, 0, 0, 1)), D(1, 1, 1, 0, 0))
        self.assertEqual(s.prev_before(D(1, 1, 1, 0, 1)), D(1, 1, 1, 0, 0))
        self.assertIsNone(parse("0 0 * 2 MON#5").next_after(D(9990, 1, 1)))
        self.assertEqual(parse("0 0 29 2 *").next_after(D(9995, 1, 1)),
                         D(9996, 2, 29))
        self.assertEqual(parse("0 0 1 1 *").prev_before(D(1, 1, 1, 0, 0, 1)),
                         D(1, 1, 1))
        self.assertEqual(parse("0 0 1 1 *").prev_before(D(5, 3, 1)),
                         D(5, 1, 1))

    def test_performance(self):
        exprs = ["0 0 31 4 *", "0 0 30 2 *", "59 23 * 2 MON#5", "* * 31 11 *"]
        start = time.perf_counter()
        for i in range(5):
            for expr in exprs:
                s = parse(expr)
                s.next_after(D(2016 + i, 3, 1))
                s.prev_before(D(2016 + i, 3, 1))
        self.assertLess(time.perf_counter() - start, 20.0)  # 模範解答 0.04 秒・分単位の総当たりは約 70 秒（mini 実測）


class TestPrevBefore(unittest.TestCase):
    def test_every_minute(self):
        s = parse("* * * * *")
        self.assertEqual(s.prev_before(D(2024, 5, 1, 10, 0)), D(2024, 5, 1, 9, 59))
        self.assertEqual(
            s.prev_before(D(2024, 5, 1, 10, 0, 30)), D(2024, 5, 1, 10, 0)
        )
        self.assertEqual(
            s.prev_before(D(2024, 5, 1, 10, 0, 0, 1)), D(2024, 5, 1, 10, 0)
        )

    def test_rollback_across_boundaries(self):
        s = parse("45 17 * * MON-FRI")
        # 2024-09-09 は月曜
        self.assertEqual(s.prev_before(D(2024, 9, 9, 17, 45)), D(2024, 9, 6, 17, 45))
        self.assertEqual(
            s.prev_before(D(2024, 9, 9, 17, 45, 1)), D(2024, 9, 9, 17, 45)
        )
        s = parse("0 12 L * *")
        self.assertEqual(s.prev_before(D(2024, 3, 31, 12, 0)), D(2024, 2, 29, 12, 0))
        self.assertEqual(s.prev_before(D(2024, 1, 1)), D(2023, 12, 31, 12, 0))

    def test_multiple_hours_minutes(self):
        s = parse("10,40 8,20 * * *")
        self.assertEqual(s.prev_before(D(2024, 1, 1, 20, 30)), D(2024, 1, 1, 20, 10))
        self.assertEqual(s.prev_before(D(2024, 1, 1, 20, 10)), D(2024, 1, 1, 8, 40))
        self.assertEqual(s.prev_before(D(2024, 1, 1, 8, 39)), D(2024, 1, 1, 8, 10))
        self.assertEqual(s.prev_before(D(2024, 1, 1, 8, 10)), D(2023, 12, 31, 20, 40))
        self.assertEqual(s.prev_before(D(2024, 1, 1, 23, 59)), D(2024, 1, 1, 20, 40))


class TestIterAfter(unittest.TestCase):
    def test_count_zero_and_negative(self):
        s = parse("* * * * *")
        self.assertEqual(s.iter_after(D(2024, 1, 1), 0), [])
        with self.assertRaises(ValueError):
            s.iter_after(D(2024, 1, 1), -1)

    def test_iter_returns_list_of_consecutive(self):
        s = parse("0 0 * * *")
        r = s.iter_after(D(2024, 2, 27, 12, 0), 3)
        self.assertIsInstance(r, list)
        self.assertEqual(r, [D(2024, 2, 28), D(2024, 2, 29), D(2024, 3, 1)])

    def test_parse_is_independent(self):
        a = parse("0 0 1 * *")
        b = parse("0 0 2 * *")
        self.assertEqual(a.next_after(D(2024, 1, 1)), D(2024, 2, 1))
        self.assertEqual(b.next_after(D(2024, 1, 1)), D(2024, 1, 2))


if __name__ == "__main__":
    unittest.main()
