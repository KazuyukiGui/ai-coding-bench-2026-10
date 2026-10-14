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
        self._next_id: int = 1
        self._maintenance_windows: dict[int, MaintenanceWindow] = {}
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
    def _is_int(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    @staticmethod
    def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
        return a_start < b_end and b_start < a_end

    def _validate_buffer_minutes(self, value: int, name: str) -> None:
        if not self._is_int(value) or value < 0 or value % 15 != 0:
            raise ReservationError(f"{name} must be a non-negative multiple of 15")

    @staticmethod
    def _validate_single_day(start: datetime, end: datetime, label: str) -> None:
        if start.date() != end.date():
            if not (end.date() == start.date() + timedelta(days=1) and end.time() == time(0, 0)):
                raise ReservationError(f"{label} cannot span across multiple days")

    def _get_operating_bounds(self, room: Room, target_date: date) -> tuple[datetime, datetime]:
        open_dt = datetime.combine(target_date, room.open_time)
        if room.close_time == time(0, 0):
            close_dt = datetime.combine(target_date + timedelta(days=1), time(0, 0))
        else:
            close_dt = datetime.combine(target_date, room.close_time)
        return open_dt, close_dt

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

        effective_start, effective_end = self._validate_slot(room, start, end, setup_minutes, teardown_minutes)

        conflict = self._find_conflict(room_id, effective_start, effective_end)
        if conflict is not None:
            raise ReservationError(conflict)

        return self._create_reservation(room_id, user, start, end, setup_minutes, teardown_minutes)

    def _create_reservation(
        self,
        room_id: str,
        user: str,
        start: datetime,
        end: datetime,
        setup_minutes: int,
        teardown_minutes: int,
    ) -> Reservation:
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

    def _validate_slot(
        self,
        room: Room,
        start: datetime,
        end: datetime,
        setup_minutes: int = 0,
        teardown_minutes: int = 0,
    ) -> tuple[datetime, datetime]:
        if end <= start:
            raise ReservationError("End time must be after start time")
        if not self._is_15min_aligned_dt(start) or not self._is_15min_aligned_dt(end):
            raise ReservationError("Start and end times must be aligned to 15-minute intervals")
        self._validate_buffer_minutes(setup_minutes, "setup_minutes")
        self._validate_buffer_minutes(teardown_minutes, "teardown_minutes")

        effective_start = start - timedelta(minutes=setup_minutes)
        effective_end = end + timedelta(minutes=teardown_minutes)

        self._validate_single_day(effective_start, effective_end, "Reservation")

        open_dt, close_dt = self._get_operating_bounds(room, effective_start.date())
        if effective_start < open_dt or effective_end > close_dt:
            raise ReservationError("Reservation is outside of room operating hours")
        return effective_start, effective_end

    def _find_conflict(
        self,
        room_id: str,
        effective_start: datetime,
        effective_end: datetime,
        pending: Optional[list[tuple[datetime, datetime]]] = None,
    ) -> Optional[str]:
        for res in self._reservations.values():
            if res.room_id == room_id and res.status == "ACTIVE":
                if self._overlaps(effective_start, effective_end, res.effective_start, res.effective_end):
                    return f"Time slot overlaps with reservation {res.reservation_id}"
        for window in self._maintenance_windows.values():
            if window.room_id == room_id:
                if self._overlaps(effective_start, effective_end, window.start, window.end):
                    return f"Time slot overlaps with maintenance window {window.window_id}"
        for p_start, p_end in pending or []:
            if self._overlaps(effective_start, effective_end, p_start, p_end):
                return "Time slot overlaps with another occurrence of this recurring booking"
        return None

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
        if not self._is_int(interval_days) or interval_days < 1:
            raise ReservationError("interval_days must be at least 1")
        if not self._is_int(occurrences) or occurrences < 1:
            raise ReservationError("occurrences must be at least 1")

        candidates: list[tuple[datetime, datetime, datetime, datetime]] = []
        for i in range(occurrences):
            offset = timedelta(days=i * interval_days)
            occ_start = start + offset
            occ_end = end + offset
            effective_start, effective_end = self._validate_slot(
                room, occ_start, occ_end, setup_minutes, teardown_minutes
            )
            candidates.append((occ_start, occ_end, effective_start, effective_end))

        accepted: list[tuple[datetime, datetime, datetime, datetime]] = []
        for occ_start, occ_end, effective_start, effective_end in candidates:
            pending = [(a[2], a[3]) for a in accepted]
            conflict = self._find_conflict(room_id, effective_start, effective_end, pending)
            if conflict is not None:
                if skip_conflicts:
                    continue
                raise ReservationError(f"Occurrence starting at {occ_start.isoformat()} conflicts: {conflict}")
            accepted.append((occ_start, occ_end, effective_start, effective_end))

        return [
            self._create_reservation(room_id, user, occ_start, occ_end, setup_minutes, teardown_minutes)
            for occ_start, occ_end, _, _ in accepted
        ]

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
        self._validate_single_day(start, end, "Maintenance window")

        for window in self._maintenance_windows.values():
            if window.room_id == room_id and self._overlaps(start, end, window.start, window.end):
                raise ReservationError(f"Time slot overlaps with maintenance window {window.window_id}")

        conflicting = sorted(
            (
                res
                for res in self._reservations.values()
                if res.room_id == room_id
                and res.status == "ACTIVE"
                and self._overlaps(start, end, res.effective_start, res.effective_end)
            ),
            key=lambda r: r.reservation_id,
        )
        if conflicting and not force:
            ids = ", ".join(str(r.reservation_id) for r in conflicting)
            raise ReservationError(f"Maintenance window overlaps with reservations: {ids}")

        for res in conflicting:
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
        return window, conflicting

    def find_available_slots(
        self,
        room_id: str,
        target_date: date,
        duration_minutes: int,
        setup_minutes: int = 0,
        teardown_minutes: int = 0,
    ) -> list[tuple[datetime, datetime]]:
        room = self.get_room(room_id)
        if not self._is_int(duration_minutes) or duration_minutes < 15 or duration_minutes % 15 != 0:
            raise ReservationError("duration_minutes must be a multiple of 15 and at least 15")
        self._validate_buffer_minutes(setup_minutes, "setup_minutes")
        self._validate_buffer_minutes(teardown_minutes, "teardown_minutes")

        open_dt, close_dt = self._get_operating_bounds(room, target_date)
        duration = timedelta(minutes=duration_minutes)
        setup = timedelta(minutes=setup_minutes)
        teardown = timedelta(minutes=teardown_minutes)
        step = timedelta(minutes=15)

        slots: list[tuple[datetime, datetime]] = []
        slot_start = open_dt + setup
        while slot_start + duration + teardown <= close_dt:
            slot_end = slot_start + duration
            if self._find_conflict(room_id, slot_start - setup, slot_end + teardown) is None:
                slots.append((slot_start, slot_end))
            slot_start += step
        return slots

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
        for window in self._maintenance_windows.values():
            if window.room_id != room_id:
                continue
            overlap_start = max(window.start, open_dt)
            overlap_end = min(window.end, close_dt)
            if overlap_end > overlap_start:
                maintenance_minutes += int((overlap_end - overlap_start).total_seconds() // 60)

        available_minutes = operating_minutes - maintenance_minutes
        if available_minutes > 0:
            utilization = round((booked_minutes + buffer_minutes) / available_minutes, 4)
        else:
            utilization = 0.0

        return {
            "room_id": room_id,
            "date": target_date.isoformat(),
            "reservation_count": len(reservations),
            "booked_minutes": booked_minutes,
            "operating_minutes": operating_minutes,
            "utilization_rate": utilization,
            "buffer_minutes": buffer_minutes,
            "maintenance_minutes": maintenance_minutes,
        }
=== END ===