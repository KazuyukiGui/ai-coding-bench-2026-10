=== FILE: reservation_system.py ===
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import Optional


class ReservationError(Exception):
    """予約システムに関するエラーを表す例外クラス"""
    pass


@dataclass
class Room:
    room_id: str
    name: str
    capacity: int
    open_time: time = time(9, 0)
    close_time: time = time(18, 0)


@dataclass
class Reservation:
    reservation_id: int
    room_id: str
    user: str
    start: datetime
    end: datetime
    status: str = "ACTIVE"  # "ACTIVE" or "CANCELLED"
    setup_minutes: int = 0
    teardown_minutes: int = 0

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def effective_start(self) -> datetime:
        return self.start - timedelta(minutes=self.setup_minutes)

    @property
    def effective_end(self) -> datetime:
        return self.end + timedelta(minutes=self.teardown_minutes)

    @property
    def total_duration_minutes(self) -> int:
        return int((self.effective_end - self.effective_start).total_seconds() // 60)


@dataclass
class MaintenanceWindow:
    window_id: int
    room_id: str
    start: datetime
    end: datetime
    reason: str


class ReservationSystem:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._reservations: dict[int, Reservation] = {}
        self._maintenance_windows: dict[int, MaintenanceWindow] = {}
        self._next_id: int = 1
        self._next_window_id: int = 1

    def add_room(
        self,
        room_id: str,
        name: str,
        capacity: int,
        open_time: time = time(9, 0),
        close_time: time = time(18, 0),
    ) -> Room:
        if not room_id or room_id in self._rooms:
            raise ReservationError(f"Invalid or duplicate room_id: {room_id}")
        if capacity <= 0:
            raise ReservationError("Capacity must be positive")
        if open_time >= close_time and close_time != time(0, 0):
            raise ReservationError("open_time must be before close_time")
        if not self._is_15min_aligned_time(open_time) or not self._is_15min_aligned_time(close_time):
            raise ReservationError("Room open/close times must be aligned to 15-minute intervals")

        room = Room(
            room_id=room_id,
            name=name,
            capacity=capacity,
            open_time=open_time,
            close_time=close_time,
        )
        self._rooms[room_id] = room
        return room

    def get_room(self, room_id: str) -> Room:
        if room_id not in self._rooms:
            raise ReservationError(f"Room not found: {room_id}")
        return self._rooms[room_id]

    @staticmethod
    def _is_15min_aligned_time(t: time) -> bool:
        return t.minute % 15 == 0 and t.second == 0 and t.microsecond == 0

    @staticmethod
    def _is_15min_aligned_dt(dt: datetime) -> bool:
        return dt.minute % 15 == 0 and dt.second == 0 and dt.microsecond == 0

    @staticmethod
    def _validate_buffer_minutes(setup_minutes: int, teardown_minutes: int) -> None:
        if (
            not isinstance(setup_minutes, int)
            or isinstance(setup_minutes, bool)
            or setup_minutes < 0
            or setup_minutes % 15 != 0
        ):
            raise ReservationError("setup_minutes must be a non-negative multiple of 15")
        if (
            not isinstance(teardown_minutes, int)
            or isinstance(teardown_minutes, bool)
            or teardown_minutes < 0
            or teardown_minutes % 15 != 0
        ):
            raise ReservationError("teardown_minutes must be a non-negative multiple of 15")

    def _get_operating_bounds(self, room: Room, target_date: date) -> tuple[datetime, datetime]:
        open_dt = datetime.combine(target_date, room.open_time)
        if room.close_time == time(0, 0):
            close_dt = datetime.combine(target_date + timedelta(days=1), time(0, 0))
        else:
            close_dt = datetime.combine(target_date, room.close_time)
        return open_dt, close_dt

    def _has_conflict(self, room_id: str, eff_start: datetime, eff_end: datetime) -> bool:
        for res in self._reservations.values():
            if res.room_id == room_id and res.status == "ACTIVE":
                if not (eff_end <= res.effective_start or eff_start >= res.effective_end):
                    return True
        for mw in self._maintenance_windows.values():
            if mw.room_id == room_id:
                if not (eff_end <= mw.start or eff_start >= mw.end):
                    return True
        return False

    def book(
        self,
        room_id: str,
        user: str,
        start: datetime,
        end: datetime,
        setup_minutes: int = 0,
        teardown_minutes: int = 0,
    ) -> Reservation:
        room = self.get_room(room_id)
        if not user or not user.strip():
            raise ReservationError("User must be specified")

        self._validate_slot(room, start, end, setup_minutes, teardown_minutes)

        eff_start = start - timedelta(minutes=setup_minutes)
        eff_end = end + timedelta(minutes=teardown_minutes)

        if self._has_conflict(room_id, eff_start, eff_end):
            raise ReservationError("Time slot overlaps with an existing reservation or maintenance window")

        res = Reservation(
            reservation_id=self._next_id,
            room_id=room_id,
            user=user,
            start=start,
            end=end,
            status="ACTIVE",
            setup_minutes=setup_minutes,
            teardown_minutes=teardown_minutes,
        )
        self._reservations[self._next_id] = res
        self._next_id += 1
        return res

    def book_recurring(
        self,
        room_id: str,
        user: str,
        start: datetime,
        end: datetime,
        interval_days: int,
        occurrences: int,
        setup_minutes: int = 0,
        teardown_minutes: int = 0,
        skip_conflicts: bool = False,
    ) -> list[Reservation]:
        room = self.get_room(room_id)
        if not user or not user.strip():
            raise ReservationError("User must be specified")
        if (
            not isinstance(interval_days, int)
            or isinstance(interval_days, bool)
            or interval_days < 1
        ):
            raise ReservationError("interval_days must be at least 1")
        if (
            not isinstance(occurrences, int)
            or isinstance(occurrences, bool)
            or occurrences < 1
        ):
            raise ReservationError("occurrences must be at least 1")

        self._validate_buffer_minutes(setup_minutes, teardown_minutes)

        candidates: list[tuple[datetime, datetime, datetime, datetime]] = []
        for i in range(occurrences):
            delta = timedelta(days=i * interval_days)
            curr_start = start + delta
            curr_end = end + delta
            self._validate_slot(room, curr_start, curr_end, setup_minutes, teardown_minutes)
            eff_start = curr_start - timedelta(minutes=setup_minutes)
            eff_end = curr_end + timedelta(minutes=teardown_minutes)
            candidates.append((curr_start, curr_end, eff_start, eff_end))

        accepted: list[tuple[datetime, datetime, datetime, datetime]] = []
        for curr_start, curr_end, eff_start, eff_end in candidates:
            conflict = self._has_conflict(room_id, eff_start, eff_end)
            if not conflict:
                for _, _, prev_eff_start, prev_eff_end in accepted:
                    if not (eff_end <= prev_eff_start or eff_start >= prev_eff_end):
                        conflict = True
                        break

            if conflict:
                if not skip_conflicts:
                    raise ReservationError("Recurring reservation conflicts with existing slot")
                continue

            accepted.append((curr_start, curr_end, eff_start, eff_end))

        created_reservations: list[Reservation] = []
        for curr_start, curr_end, _, _ in accepted:
            res = Reservation(
                reservation_id=self._next_id,
                room_id=room_id,
                user=user,
                start=curr_start,
                end=curr_end,
                status="ACTIVE",
                setup_minutes=setup_minutes,
                teardown_minutes=teardown_minutes,
            )
            self._reservations[self._next_id] = res
            self._next_id += 1
            created_reservations.append(res)

        return created_reservations

    def add_maintenance(
        self,
        room_id: str,
        start: datetime,
        end: datetime,
        reason: str,
        force: bool = False,
    ) -> tuple[MaintenanceWindow, list[Reservation]]:
        self.get_room(room_id)
        if end <= start:
            raise ReservationError("End time must be after start time")
        if not self._is_15min_aligned_dt(start) or not self._is_15min_aligned_dt(end):
            raise ReservationError("Start and end times must be aligned to 15-minute intervals")

        if start.date() != end.date():
            if not (end.date() == start.date() + timedelta(days=1) and end.time() == time(0, 0)):
                raise ReservationError("Maintenance window cannot span across multiple days")

        for mw in self._maintenance_windows.values():
            if mw.room_id == room_id:
                if not (end <= mw.start or start >= mw.end):
                    raise ReservationError(f"Maintenance window overlaps with window {mw.window_id}")

        overlapping_reservations: list[Reservation] = []
        for res in self._reservations.values():
            if res.room_id == room_id and res.status == "ACTIVE":
                if not (end <= res.effective_start or start >= res.effective_end):
                    overlapping_reservations.append(res)

        if overlapping_reservations and not force:
            raise ReservationError("Maintenance window overlaps with active reservations")

        overlapping_reservations.sort(key=lambda r: r.reservation_id)
        for res in overlapping_reservations:
            res.status = "CANCELLED"

        window = MaintenanceWindow(
            window_id=self._next_window_id,
            room_id=room_id,
            start=start,
            end=end,
            reason=reason,
        )
        self._maintenance_windows[self._next_window_id] = window
        self._next_window_id += 1

        return window, overlapping_reservations

    def find_available_slots(
        self,
        room_id: str,
        target_date: date,
        duration_minutes: int,
        setup_minutes: int = 0,
        teardown_minutes: int = 0,
    ) -> list[tuple[datetime, datetime]]:
        room = self.get_room(room_id)
        if (
            not isinstance(duration_minutes, int)
            or isinstance(duration_minutes, bool)
            or duration_minutes < 15
            or duration_minutes % 15 != 0
        ):
            raise ReservationError("duration_minutes must be at least 15 and a multiple of 15")

        self._validate_buffer_minutes(setup_minutes, teardown_minutes)

        open_dt, close_dt = self._get_operating_bounds(room, target_date)

        available_slots: list[tuple[datetime, datetime]] = []
        curr_start = open_dt + timedelta(minutes=setup_minutes)
        duration_delta = timedelta(minutes=duration_minutes)
        setup_delta = timedelta(minutes=setup_minutes)
        teardown_delta = timedelta(minutes=teardown_minutes)
        step_delta = timedelta(minutes=15)

        while True:
            curr_end = curr_start + duration_delta
            eff_end = curr_end + teardown_delta
            if eff_end > close_dt:
                break
            eff_start = curr_start - setup_delta
            if not self._has_conflict(room_id, eff_start, eff_end):
                available_slots.append((curr_start, curr_end))
            curr_start += step_delta

        return available_slots

    def _validate_slot(
        self,
        room: Room,
        start: datetime,
        end: datetime,
        setup_minutes: int = 0,
        teardown_minutes: int = 0,
    ) -> None:
        self._validate_buffer_minutes(setup_minutes, teardown_minutes)

        if end <= start:
            raise ReservationError("End time must be after start time")
        if not self._is_15min_aligned_dt(start) or not self._is_15min_aligned_dt(end):
            raise ReservationError("Start and end times must be aligned to 15-minute intervals")

        if start.date() != end.date():
            if not (end.date() == start.date() + timedelta(days=1) and end.time() == time(0, 0)):
                raise ReservationError("Reservation cannot span across multiple days")

        eff_start = start - timedelta(minutes=setup_minutes)
        eff_end = end + timedelta(minutes=teardown_minutes)

        if eff_start.date() != start.date():
            raise ReservationError("Reservation cannot span across multiple days")

        if eff_start.date() != eff_end.date():
            if not (eff_end.date() == eff_start.date() + timedelta(days=1) and eff_end.time() == time(0, 0)):
                raise ReservationError("Reservation cannot span across multiple days")

        open_dt, close_dt = self._get_operating_bounds(room, start.date())
        if eff_start < open_dt or eff_end > close_dt:
            raise ReservationError("Reservation is outside of room operating hours")

    def cancel(self, reservation_id: int) -> Reservation:
        if reservation_id not in self._reservations:
            raise ReservationError(f"Reservation not found: {reservation_id}")
        res = self._reservations[reservation_id]
        if res.status == "CANCELLED":
            raise ReservationError(f"Reservation {reservation_id} is already cancelled")
        res.status = "CANCELLED"
        return res

    def get_reservation(self, reservation_id: int) -> Reservation:
        if reservation_id not in self._reservations:
            raise ReservationError(f"Reservation not found: {reservation_id}")
        return self._reservations[reservation_id]

    def get_reservations(
        self,
        room_id: Optional[str] = None,
        target_date: Optional[date] = None,
        user: Optional[str] = None,
        active_only: bool = True,
    ) -> list[Reservation]:
        results: list[Reservation] = []
        for res in self._reservations.values():
            if active_only and res.status != "ACTIVE":
                continue
            if room_id is not None and res.room_id != room_id:
                continue
            if target_date is not None and res.start.date() != target_date:
                continue
            if user is not None and res.user != user:
                continue
            results.append(res)
        results.sort(key=lambda r: (r.start, r.reservation_id))
        return results

    def get_daily_report(self, room_id: str, target_date: date) -> dict:
        room = self.get_room(room_id)
        open_dt, close_dt = self._get_operating_bounds(room, target_date)
        operating_minutes = int((close_dt - open_dt).total_seconds() // 60)

        reservations = self.get_reservations(room_id=room_id, target_date=target_date, active_only=True)
        booked_minutes = sum(r.duration_minutes for r in reservations)
        buffer_minutes = sum(r.setup_minutes + r.teardown_minutes for r in reservations)

        maintenance_minutes = 0
        for mw in self._maintenance_windows.values():
            if mw.room_id == room_id:
                overlap_start = max(mw.start, open_dt)
                overlap_end = min(mw.end, close_dt)
                if overlap_end > overlap_start:
                    maintenance_minutes += int((overlap_end - overlap_start).total_seconds() // 60)

        available_operating_minutes = operating_minutes - maintenance_minutes
        if available_operating_minutes <= 0:
            utilization = 0.0
        else:
            utilization = round((booked_minutes + buffer_minutes) / available_operating_minutes, 4)

        return {
            "room_id": room_id,
            "date": target_date.isoformat(),
            "reservation_count": len(reservations),
            "booked_minutes": booked_minutes,
            "buffer_minutes": buffer_minutes,
            "maintenance_minutes": maintenance_minutes,
            "operating_minutes": operating_minutes,
            "utilization_rate": utilization,
        }
=== END ===
