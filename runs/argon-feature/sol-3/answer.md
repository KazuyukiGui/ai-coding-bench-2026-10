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
        return int(
            (self.effective_end - self.effective_start).total_seconds() // 60
        )


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
        if (
            not self._is_15min_aligned_time(open_time)
            or not self._is_15min_aligned_time(close_time)
        ):
            raise ReservationError(
                "Room open/close times must be aligned to 15-minute intervals"
            )

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
    def _overlaps(
        first_start: datetime,
        first_end: datetime,
        second_start: datetime,
        second_end: datetime,
    ) -> bool:
        return first_start < second_end and second_start < first_end

    @staticmethod
    def _validate_buffer_minutes(
        setup_minutes: int,
        teardown_minutes: int,
    ) -> None:
        for name, value in (
            ("setup_minutes", setup_minutes),
            ("teardown_minutes", teardown_minutes),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                or value % 15 != 0
            ):
                raise ReservationError(
                    f"{name} must be a non-negative integer multiple of 15"
                )

    @staticmethod
    def _validate_single_day_interval(
        start: datetime,
        end: datetime,
        message: str,
    ) -> None:
        if start.date() != end.date():
            is_next_midnight = (
                end.date() == start.date() + timedelta(days=1)
                and end.time() == time(0, 0)
            )
            if not is_next_midnight:
                raise ReservationError(message)

    def _get_operating_bounds(
        self,
        room: Room,
        target_date: date,
    ) -> tuple[datetime, datetime]:
        open_dt = datetime.combine(target_date, room.open_time)
        if room.close_time == time(0, 0):
            close_dt = datetime.combine(
                target_date + timedelta(days=1),
                time(0, 0),
            )
        else:
            close_dt = datetime.combine(target_date, room.close_time)
        return open_dt, close_dt

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
        if (
            not self._is_15min_aligned_dt(start)
            or not self._is_15min_aligned_dt(end)
        ):
            raise ReservationError(
                "Start and end times must be aligned to 15-minute intervals"
            )

        self._validate_single_day_interval(
            start,
            end,
            "Reservation cannot span across multiple days",
        )

        effective_start = start - timedelta(minutes=setup_minutes)
        effective_end = end + timedelta(minutes=teardown_minutes)

        self._validate_single_day_interval(
            effective_start,
            effective_end,
            "Reservation including buffers cannot span across multiple days",
        )

        open_dt, close_dt = self._get_operating_bounds(room, start.date())
        if effective_start < open_dt or effective_end > close_dt:
            raise ReservationError("Reservation is outside of room operating hours")

    def _find_conflict(
        self,
        room_id: str,
        effective_start: datetime,
        effective_end: datetime,
        additional_reservations: Optional[list[Reservation]] = None,
    ) -> Optional[str]:
        for res in self._reservations.values():
            if res.room_id != room_id or res.status != "ACTIVE":
                continue
            if self._overlaps(
                effective_start,
                effective_end,
                res.effective_start,
                res.effective_end,
            ):
                return f"Time slot overlaps with reservation {res.reservation_id}"

        if additional_reservations is not None:
            for res in additional_reservations:
                if self._overlaps(
                    effective_start,
                    effective_end,
                    res.effective_start,
                    res.effective_end,
                ):
                    return (
                        "Time slot overlaps with another occurrence in the "
                        "recurring booking"
                    )

        for window in self._maintenance_windows.values():
            if window.room_id != room_id:
                continue
            if self._overlaps(
                effective_start,
                effective_end,
                window.start,
                window.end,
            ):
                return (
                    f"Time slot overlaps with maintenance window "
                    f"{window.window_id}"
                )

        return None

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

        self._validate_slot(
            room,
            start,
            end,
            setup_minutes,
            teardown_minutes,
        )

        effective_start = start - timedelta(minutes=setup_minutes)
        effective_end = end + timedelta(minutes=teardown_minutes)
        conflict = self._find_conflict(
            room_id,
            effective_start,
            effective_end,
        )
        if conflict is not None:
            raise ReservationError(conflict)

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
        if (
            not self._is_15min_aligned_dt(start)
            or not self._is_15min_aligned_dt(end)
        ):
            raise ReservationError(
                "Maintenance start and end times must be aligned to "
                "15-minute intervals"
            )

        self._validate_single_day_interval(
            start,
            end,
            "Maintenance window cannot span across multiple days",
        )

        for window in self._maintenance_windows.values():
            if (
                window.room_id == room_id
                and self._overlaps(start, end, window.start, window.end)
            ):
                raise ReservationError(
                    f"Maintenance window overlaps with window {window.window_id}"
                )

        conflicting_reservations = [
            res
            for res in self._reservations.values()
            if (
                res.room_id == room_id
                and res.status == "ACTIVE"
                and self._overlaps(
                    start,
                    end,
                    res.effective_start,
                    res.effective_end,
                )
            )
        ]
        conflicting_reservations.sort(key=lambda res: res.reservation_id)

        if conflicting_reservations and not force:
            raise ReservationError(
                "Maintenance window overlaps with active reservations"
            )

        window = MaintenanceWindow(
            window_id=self._next_window_id,
            room_id=room_id,
            start=start,
            end=end,
            reason=reason,
        )

        for res in conflicting_reservations:
            res.status = "CANCELLED"

        self._maintenance_windows[self._next_window_id] = window
        self._next_window_id += 1
        return window, conflicting_reservations

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
        if (
            not isinstance(interval_days, int)
            or isinstance(interval_days, bool)
            or interval_days < 1
        ):
            raise ReservationError("interval_days must be an integer of at least 1")
        if (
            not isinstance(occurrences, int)
            or isinstance(occurrences, bool)
            or occurrences < 1
        ):
            raise ReservationError("occurrences must be an integer of at least 1")

        room = self.get_room(room_id)
        if not user or not user.strip():
            raise ReservationError("User must be specified")

        candidates: list[tuple[datetime, datetime]] = []
        for index in range(occurrences):
            offset = timedelta(days=index * interval_days)
            candidate_start = start + offset
            candidate_end = end + offset
            self._validate_slot(
                room,
                candidate_start,
                candidate_end,
                setup_minutes,
                teardown_minutes,
            )
            candidates.append((candidate_start, candidate_end))

        accepted: list[Reservation] = []
        for candidate_start, candidate_end in candidates:
            candidate = Reservation(
                reservation_id=0,
                room_id=room_id,
                user=user,
                start=candidate_start,
                end=candidate_end,
                status="ACTIVE",
                setup_minutes=setup_minutes,
                teardown_minutes=teardown_minutes,
            )
            conflict = self._find_conflict(
                room_id,
                candidate.effective_start,
                candidate.effective_end,
                accepted,
            )
            if conflict is not None:
                if skip_conflicts:
                    continue
                raise ReservationError(conflict)
            accepted.append(candidate)

        created: list[Reservation] = []
        for candidate in accepted:
            candidate.reservation_id = self._next_id
            self._reservations[self._next_id] = candidate
            self._next_id += 1
            created.append(candidate)

        return created

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
            raise ReservationError(
                "duration_minutes must be an integer multiple of 15 "
                "and at least 15"
            )
        self._validate_buffer_minutes(setup_minutes, teardown_minutes)

        open_dt, close_dt = self._get_operating_bounds(room, target_date)
        candidate_start = open_dt + timedelta(minutes=setup_minutes)
        latest_end = close_dt - timedelta(minutes=teardown_minutes)
        duration = timedelta(minutes=duration_minutes)
        step = timedelta(minutes=15)
        slots: list[tuple[datetime, datetime]] = []

        while candidate_start + duration <= latest_end:
            candidate_end = candidate_start + duration
            effective_start = candidate_start - timedelta(
                minutes=setup_minutes
            )
            effective_end = candidate_end + timedelta(
                minutes=teardown_minutes
            )
            if (
                self._find_conflict(
                    room_id,
                    effective_start,
                    effective_end,
                )
                is None
            ):
                slots.append((candidate_start, candidate_end))
            candidate_start += step

        return slots

    def cancel(self, reservation_id: int) -> Reservation:
        if reservation_id not in self._reservations:
            raise ReservationError(f"Reservation not found: {reservation_id}")
        res = self._reservations[reservation_id]
        if res.status == "CANCELLED":
            raise ReservationError(
                f"Reservation {reservation_id} is already cancelled"
            )
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
        operating_minutes = int(
            (close_dt - open_dt).total_seconds() // 60
        )

        reservations = self.get_reservations(
            room_id=room_id,
            target_date=target_date,
            active_only=True,
        )
        booked_minutes = sum(res.duration_minutes for res in reservations)
        buffer_minutes = sum(
            res.setup_minutes + res.teardown_minutes
            for res in reservations
        )

        maintenance_minutes = 0
        for window in self._maintenance_windows.values():
            if window.room_id != room_id:
                continue
            overlap_start = max(open_dt, window.start)
            overlap_end = min(close_dt, window.end)
            if overlap_start < overlap_end:
                maintenance_minutes += int(
                    (overlap_end - overlap_start).total_seconds() // 60
                )

        available_minutes = operating_minutes - maintenance_minutes
        utilization = (
            round(
                (booked_minutes + buffer_minutes) / available_minutes,
                4,
            )
            if available_minutes > 0
            else 0.0
        )

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