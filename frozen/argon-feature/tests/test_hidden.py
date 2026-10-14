import unittest
from datetime import datetime, date, time
from reservation_system import (
    ReservationSystem,
    ReservationError,
    Room,
    Reservation,
    MaintenanceWindow,
)


class TestReservationSystemFeature(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = ReservationSystem()
        self.sys.add_room("R1", "Room A", 10, time(9, 0), time(18, 0))
        self.sys.add_room("R2", "Room B", 20, time(8, 0), time(0, 0))
        self.base_date = date(2025, 5, 1)

    def dt(self, hour: int, minute: int = 0, day_offset: int = 0) -> datetime:
        d = date(2025, 5, 1 + day_offset)
        return datetime.combine(d, time(hour, minute))

    # --- 1. 既存挙動の維持 ---
    def test_01_existing_basic_booking_and_cancel(self) -> None:
        r1 = self.sys.book("R1", "alice", self.dt(10, 0), self.dt(11, 0))
        self.assertEqual(r1.reservation_id, 1)
        self.assertEqual(r1.duration_minutes, 60)
        self.assertEqual(r1.setup_minutes, 0)
        self.assertEqual(r1.teardown_minutes, 0)
        self.assertEqual(r1.total_duration_minutes, 60)

        with self.assertRaises(ReservationError):
            self.sys.book("R1", "bob", self.dt(10, 30), self.dt(11, 30))

        self.sys.cancel(r1.reservation_id)
        r2 = self.sys.book("R1", "bob", self.dt(10, 30), self.dt(11, 30))
        self.assertEqual(r2.reservation_id, 2)

    # --- 2. バッファ時間とプロパティ ---
    def test_02_buffer_properties_and_boundaries(self) -> None:
        res = self.sys.book(
            "R1", "alice", self.dt(9, 15), self.dt(10, 15), setup_minutes=15, teardown_minutes=30
        )
        self.assertEqual(res.effective_start, self.dt(9, 0))
        self.assertEqual(res.effective_end, self.dt(10, 45))
        self.assertEqual(res.duration_minutes, 60)
        self.assertEqual(res.total_duration_minutes, 105)

        # バッファの後にぴったり接する予約は可能
        res2 = self.sys.book(
            "R1", "bob", self.dt(11, 0), self.dt(12, 0), setup_minutes=15, teardown_minutes=0
        )
        self.assertEqual(res2.effective_start, self.dt(10, 45))

    def test_03_buffer_overlap_and_operating_hours_violation(self) -> None:
        self.sys.book(
            "R1", "alice", self.dt(10, 0), self.dt(11, 0), setup_minutes=15, teardown_minutes=15
        )
        # 他方のバッファと重なる予約はエラー
        with self.assertRaises(ReservationError):
            self.sys.book("R1", "bob", self.dt(11, 0), self.dt(12, 0))
        with self.assertRaises(ReservationError):
            self.sys.book("R1", "bob", self.dt(11, 15), self.dt(12, 0), setup_minutes=15)

        # バッファが営業時間(9:00-18:00)をはみ出す場合はエラー
        with self.assertRaises(ReservationError):
            self.sys.book("R1", "bob", self.dt(9, 0), self.dt(10, 0), setup_minutes=15)
        with self.assertRaises(ReservationError):
            self.sys.book("R1", "bob", self.dt(17, 0), self.dt(18, 0), teardown_minutes=15)

    def test_04_buffer_invalid_values(self) -> None:
        for setup, teardown in [(-15, 0), (0, -15), (10, 0), (0, 20), (5, 5)]:
            with self.assertRaises(ReservationError):
                self.sys.book("R1", "alice", self.dt(12, 0), self.dt(13, 0), setup, teardown)

    # --- 3. メンテナンス枠 ---
    def test_05_maintenance_without_force(self) -> None:
        self.sys.book("R1", "alice", self.dt(10, 0), self.dt(11, 0), teardown_minutes=15)

        # 予約のバッファ(11:00-11:15)と重なるメンテナンス(force=False)はエラー
        with self.assertRaises(ReservationError):
            self.sys.add_maintenance("R1", self.dt(11, 0), self.dt(12, 0), "AC check", force=False)

        # 接しているだけ(11:15-12:00)なら成功
        mw, cancelled = self.sys.add_maintenance(
            "R1", self.dt(11, 15), self.dt(12, 0), "AC check", force=False
        )
        self.assertEqual(mw.window_id, 1)
        self.assertEqual(cancelled, [])

        # メンテナンス枠と重なる新規予約は不可（バッファが重なる場合も不可）
        with self.assertRaises(ReservationError):
            self.sys.book("R1", "bob", self.dt(12, 0), self.dt(13, 0), setup_minutes=15)

    def test_06_maintenance_with_force_cancels_reservations(self) -> None:
        r1 = self.sys.book("R1", "alice", self.dt(10, 0), self.dt(11, 0))
        r2 = self.sys.book("R1", "bob", self.dt(11, 0), self.dt(12, 0), teardown_minutes=15)
        r3 = self.sys.book("R1", "charlie", self.dt(13, 0), self.dt(14, 0), setup_minutes=30)
        r4 = self.sys.book("R1", "dave", self.dt(15, 0), self.dt(16, 0))

        # 10:30 - 13:00 のメンテナンス（r1は本体、r2は全体、r3はsetupバッファが重なる）
        mw, cancelled = self.sys.add_maintenance(
            "R1", self.dt(10, 30), self.dt(13, 0), "Emergency repair", force=True
        )
        self.assertEqual([r.reservation_id for r in cancelled], [r1.reservation_id, r2.reservation_id, r3.reservation_id])
        self.assertEqual(self.sys.get_reservation(r1.reservation_id).status, "CANCELLED")
        self.assertEqual(self.sys.get_reservation(r2.reservation_id).status, "CANCELLED")
        self.assertEqual(self.sys.get_reservation(r3.reservation_id).status, "CANCELLED")
        self.assertEqual(self.sys.get_reservation(r4.reservation_id).status, "ACTIVE")

    def test_07_maintenance_overlap_and_outside_operating_hours(self) -> None:
        # 営業時間外(7:00-9:30)にまたがるメンテナンス枠も登録可能
        mw1, _ = self.sys.add_maintenance("R1", self.dt(7, 0), self.dt(9, 30), "Morning clean")
        self.assertEqual(mw1.window_id, 1)

        # 既存のメンテナンス枠と重なる場合は force=True でもエラー
        with self.assertRaises(ReservationError):
            self.sys.add_maintenance("R1", self.dt(9, 0), self.dt(10, 0), "Overlap MW", force=True)

        # メンテナンス枠のバリデーション違反（15分刻みでない、日跨ぎ、逆転）
        with self.assertRaises(ReservationError):
            self.sys.add_maintenance("R1", self.dt(10, 5), self.dt(11, 0), "Bad align")
        with self.assertRaises(ReservationError):
            self.sys.add_maintenance("R1", self.dt(23, 0), self.dt(1, 0, day_offset=1), "Cross day")

    # --- 4. 定期予約 ---
    def test_08_recurring_booking_success(self) -> None:
        res_list = self.sys.book_recurring(
            "R1",
            "alice",
            self.dt(10, 0),
            self.dt(11, 0),
            interval_days=7,
            occurrences=3,
            setup_minutes=15,
            teardown_minutes=15,
        )
        self.assertEqual(len(res_list), 3)
        self.assertEqual([r.reservation_id for r in res_list], [1, 2, 3])
        self.assertEqual(res_list[0].start, self.dt(10, 0, day_offset=0))
        self.assertEqual(res_list[1].start, self.dt(10, 0, day_offset=7))
        self.assertEqual(res_list[2].start, self.dt(10, 0, day_offset=14))
        self.assertEqual(res_list[2].effective_start, self.dt(9, 45, day_offset=14))

    def test_09_recurring_booking_all_or_nothing_on_conflict(self) -> None:
        # 2週目に既存の予約を置く
        existing = self.sys.book("R1", "bob", self.dt(10, 30, day_offset=7), self.dt(11, 30, day_offset=7))
        self.assertEqual(existing.reservation_id, 1)

        # skip_conflicts=False なら全体が失敗し、1週目も登録されずIDも進まない
        with self.assertRaises(ReservationError):
            self.sys.book_recurring(
                "R1", "alice", self.dt(10, 0), self.dt(11, 0), interval_days=7, occurrences=3, skip_conflicts=False
            )

        self.assertEqual(len(self.sys.get_reservations("R1", target_date=self.base_date)), 0)
        next_res = self.sys.book("R1", "charlie", self.dt(14, 0), self.dt(15, 0))
        self.assertEqual(next_res.reservation_id, 2)

    def test_10_recurring_booking_skip_conflicts(self) -> None:
        # 2週目に予約、3週目にメンテナンス枠を置く
        self.sys.book("R1", "bob", self.dt(10, 30, day_offset=7), self.dt(11, 30, day_offset=7))
        self.sys.add_maintenance("R1", self.dt(9, 0, day_offset=14), self.dt(10, 15, day_offset=14), "Inspect")

        # 15分setupがあるため3週目もメンテナンス枠(〜10:15)と競合しスキップされる -> 1週目と4週目だけ通る
        res_list = self.sys.book_recurring(
            "R1",
            "alice",
            self.dt(10, 0),
            self.dt(11, 0),
            interval_days=7,
            occurrences=4,
            setup_minutes=15,
            skip_conflicts=True,
        )
        self.assertEqual(len(res_list), 2)
        self.assertEqual(res_list[0].start, self.dt(10, 0, day_offset=0))
        self.assertEqual(res_list[1].start, self.dt(10, 0, day_offset=21))
        self.assertEqual([r.reservation_id for r in res_list], [2, 3])

    def test_11_recurring_booking_invalid_params_even_with_skip_conflicts(self) -> None:
        # 基本ルール違反（営業時間外など）は skip_conflicts=True でも例外を送出する
        with self.assertRaises(ReservationError):
            self.sys.book_recurring(
                "R1", "alice", self.dt(8, 30), self.dt(9, 30), interval_days=7, occurrences=2, skip_conflicts=True
            )
        with self.assertRaises(ReservationError):
            self.sys.book_recurring(
                "R1", "alice", self.dt(10, 0), self.dt(11, 0), interval_days=0, occurrences=2, skip_conflicts=True
            )
        with self.assertRaises(ReservationError):
            self.sys.book_recurring(
                "R1", "alice", self.dt(10, 0), self.dt(11, 0), interval_days=7, occurrences=0, skip_conflicts=True
            )

    # --- 5. 空き枠検索 ---
    def test_12_find_available_slots_with_buffers_and_maintenance(self) -> None:
        # 9:00-18:00 の部屋で、9:00-10:00 メンテ、11:30-17:30 予約(setup 15, teardown 30 -> 11:15〜18:00占有)
        self.sys.add_maintenance("R1", self.dt(8, 0), self.dt(10, 0), "Morning setup")
        self.sys.book(
            "R1", "alice", self.dt(11, 30), self.dt(17, 30), setup_minutes=15, teardown_minutes=30
        )
        # 空いているのは実質 10:00 〜 11:15 (75分間)
        # 本体30分 + setup 15分 + teardown 15分 = 計60分必要
        # 可能な effective_start は 10:00 (本体10:15-10:45) と 10:15 (本体10:30-11:00) の2枠
        slots = self.sys.find_available_slots(
            "R1", self.base_date, duration_minutes=30, setup_minutes=15, teardown_minutes=15
        )
        self.assertEqual(
            slots,
            [
                (self.dt(10, 15), self.dt(10, 45)),
                (self.dt(10, 30), self.dt(11, 0)),
            ],
        )

    def test_13_find_available_slots_validation(self) -> None:
        with self.assertRaises(ReservationError):
            self.sys.find_available_slots("UNKNOWN", self.base_date, 30)
        with self.assertRaises(ReservationError):
            self.sys.find_available_slots("R1", self.base_date, 0)
        with self.assertRaises(ReservationError):
            self.sys.find_available_slots("R1", self.base_date, 20)
        with self.assertRaises(ReservationError):
            self.sys.find_available_slots("R1", self.base_date, 30, setup_minutes=-15)
        with self.assertRaises(ReservationError):
            self.sys.find_available_slots("R1", self.base_date, 30, teardown_minutes=10)

    def test_14_midnight_closing_room_slots_and_booking(self) -> None:
        # R2 は 8:00 - 0:00 (翌日00:00まで営業)
        self.sys.book("R2", "alice", self.dt(8, 0), self.dt(22, 30), teardown_minutes=30)
        # 23:00 から 24:00 (翌日0:00) まで60分空いている
        slots = self.sys.find_available_slots(
            "R2", self.base_date, duration_minutes=30, setup_minutes=15, teardown_minutes=15
        )
        self.assertEqual(slots, [(self.dt(23, 15), self.dt(23, 45))])

        # 23:15-23:45 (teardown 15分で 24:00 終了) が実際に予約可能であること
        res = self.sys.book(
            "R2", "bob", self.dt(23, 15), self.dt(23, 45), setup_minutes=15, teardown_minutes=15
        )
        self.assertEqual(res.effective_end, self.dt(0, 0, day_offset=1))

    # --- 6. 日次レポート ---
    def test_15_daily_report_with_buffers_and_maintenance(self) -> None:
        # R1: 9:00 - 18:00 (operating_minutes = 540)
        # メンテ: 8:00 - 10:00 -> 営業時間内は 9:00 - 10:00 の 60分のみカウント
        self.sys.add_maintenance("R1", self.dt(8, 0), self.dt(10, 0), "Clean")
        # 予約1: 10:15 - 11:15 (60分), setup 15, teardown 15 (buffer 30分)
        self.sys.book("R1", "alice", self.dt(10, 15), self.dt(11, 15), setup_minutes=15, teardown_minutes=15)
        # 予約2: 13:00 - 15:00 (120分), setup 0, teardown 30 (buffer 30分)
        self.sys.book("R1", "bob", self.dt(13, 0), self.dt(15, 0), setup_minutes=0, teardown_minutes=30)
        # 予約3 (キャンセル済み): 16:00 - 17:00 -> カウントされない
        r3 = self.sys.book("R1", "charlie", self.dt(16, 0), self.dt(17, 0), setup_minutes=15)
        self.sys.cancel(r3.reservation_id)

        report = self.sys.get_daily_report("R1", self.base_date)
        self.assertEqual(report["reservation_count"], 2)
        self.assertEqual(report["booked_minutes"], 180)
        self.assertEqual(report["buffer_minutes"], 60)
        self.assertEqual(report["maintenance_minutes"], 60)
        self.assertEqual(report["operating_minutes"], 540)
        # (180 + 60) / (540 - 60) = 240 / 480 = 0.5
        self.assertEqual(report["utilization_rate"], 0.5)

    def test_16_daily_report_full_day_maintenance_zero_division(self) -> None:
        # 営業時間全体を覆うメンテナンス枠があるとき、分母が0になり utilization_rate は 0.0 になる
        self.sys.add_maintenance("R1", self.dt(8, 0), self.dt(19, 0), "Full day renovation")
        report = self.sys.get_daily_report("R1", self.base_date)
        self.assertEqual(report["operating_minutes"], 540)
        self.assertEqual(report["maintenance_minutes"], 540)
        self.assertEqual(report["booked_minutes"], 0)
        self.assertEqual(report["buffer_minutes"], 0)
        self.assertEqual(report["utilization_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
