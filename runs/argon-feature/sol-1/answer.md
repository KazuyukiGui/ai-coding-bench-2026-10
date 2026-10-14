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
        start_a: datetime,
        end_a: datetime,
        start_b: datetime,
        end_b: datetime,
    ) -> bool:
        return start_a < end_b and start_b < end_a

    @staticmethod
    def _validate_minutes(value: int, name: str) -> None:
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
        if start.date() == end.date():
            return
        if (
            end.date() == start.date() + timedelta(days=1)
            and end.time() == time(0, 0)
        ):
            return
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

    def _validate_slot(self, room: Room, start: datetime, end: datetime) -> None:
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

        open_dt, close_dt = self._get_operating_bounds(room, start.date())
        if start < open_dt or end > close_dt:
            raise ReservationError(
                "Reservation is outside of room operating hours"
            )

    def _validate_booking_basics(
        self,
        room_id: str,
        user: str,
        start: datetime,
        end: datetime,
        setup_minutes: int,
        teardown_minutes: int,
    ) -> tuple[Room, datetime, datetime]:
        room = self.get_room(room_id)
        if not user or not user.strip():
            raise ReservationError("User must be specified")

        self._validate_minutes(setup_minutes, "setup_minutes")
        self._validate_minutes(teardown_minutes, "teardown_minutes")
        self._validate_slot(room, start, end)

        effective_start = start - timedelta(minutes=setup_minutes)
        effective_end = end + timedelta(minutes=teardown_minutes)

        self._validate_single_day_interval(
            effective_start,
            effective_end,
            "Reservation including buffer time cannot span across multiple days",
        )

        open_dt, close_dt = self._get_operating_bounds(room, start.date())
        if effective_start < open_dt or effective_end > close_dt:
            raise ReservationError(
                "Reservation including buffer time is outside of room operating hours"
            )

        return room, effective_start, effective_end

    def _find_conflict(
        self,
        room_id: str,
        effective_start: datetime,
        effective_end: datetime,
        additional_reservations: Optional[list[Reservation]] = None,
    ) -> Optional[str]:
        for reservation in self._reservations.values():
            if reservation.room_id != room_id or reservation.status != "ACTIVE":
                continue
            if self._overlaps(
                effective_start,
                effective_end,
                reservation.effective_start,
                reservation.effective_end,
            ):
                return f"reservation {reservation.reservation_id}"

        for window in self._maintenance_windows.values():
            if window.room_id != room_id:
                continue
            if self._overlaps(
                effective_start,
                effective_end,
                window.start,
                window.end,
            ):
                return f"maintenance window {window.window_id}"

        if additional_reservations is not None:
            for reservation in additional_reservations:
                if self._overlaps(
                    effective_start,
                    effective_end,
                    reservation.effective_start,
                    reservation.effective_end,
                ):
                    return "another occurrence in the recurring booking"

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
        _, effective_start, effective_end = self._validate_booking_basics(
            room_id,
            user,
            start,
            end,
            setup_minutes,
            teardown_minutes,
        )

        conflict = self._find_conflict(
            room_id,
            effective_start,
            effective_end,
        )
        if conflict is not None:
            raise ReservationError(f"Time slot overlaps with {conflict}")

        reservation = Reservation(
            reservation_id=self._next_id,
            room_id=room_id,
            user=user,
            start=start,
            end=end,
            status="ACTIVE",
            setup_minutes=setup_minutes,
            teardown_minutes=teardown_minutes,
        )
        self._reservations[self._next_id] = reservation
        self._next_id += 1
        return reservation

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
                "Start and end times must be aligned to 15-minute intervals"
            )
        self._validate_single_day_interval(
            start,
            end,
            "Maintenance window cannot span across multiple days",
        )

        for window in self._maintenance_windows.values():
            if window.room_id != room_id:
                continue
            if self._overlaps(start, end, window.start, window.end):
                raise ReservationError(
                    f"Maintenance window overlaps with maintenance window "
                    f"{window.window_id}"
                )

        conflicting_reservations = [
            reservation
            for reservation in self._reservations.values()
            if reservation.room_id == room_id
            and reservation.status == "ACTIVE"
            and self._overlaps(
                start,
                end,
                reservation.effective_start,
                reservation.effective_end,
            )
        ]
        conflicting_reservations.sort(key=lambda reservation: reservation.reservation_id)

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
        self._maintenance_windows[self._next_window_id] = window
        self._next_window_id += 1

        for reservation in conflicting_reservations:
            reservation.status = "CANCELLED"

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

        candidates: list[tuple[datetime, datetime, datetime, datetime]] = []
        for index in range(occurrences):
            offset = timedelta(days=index * interval_days)
            candidate_start = start + offset
            candidate_end = end + offset
            _, effective_start, effective_end = self._validate_booking_basics(
                room_id,
                user,
                candidate_start,
                candidate_end,
                setup_minutes,
                teardown_minutes,
            )
            candidates.append(
                (
                    candidate_start,
                    candidate_end,
                    effective_start,
                    effective_end,
                )
            )

        accepted: list[Reservation] = []
        for (
            candidate_start,
            candidate_end,
            effective_start,
            effective_end,
        ) in candidates:
            conflict = self._find_conflict(
                room_id,
                effective_start,
                effective_end,
                accepted,
            )
            if conflict is not None:
                if skip_conflicts:
                    continue
                raise ReservationError(
                    f"Recurring booking occurrence overlaps with {conflict}"
                )

            accepted.append(
                Reservation(
                    reservation_id=0,
                    room_id=room_id,
                    user=user,
                    start=candidate_start,
                    end=candidate_end,
                    status="ACTIVE",
                    setup_minutes=setup_minutes,
                    teardown_minutes=teardown_minutes,
                )
            )

        for reservation in accepted:
            reservation.reservation_id = self._next_id
            self._reservations[self._next_id] = reservation
            self._next_id += 1

        return accepted

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
        self._validate_minutes(setup_minutes, "setup_minutes")
        self._validate_minutes(teardown_minutes, "teardown_minutes")

        open_dt, close_dt = self._get_operating_bounds(room, target_date)
        earliest_start = open_dt + timedelta(minutes=setup_minutes)
        latest_end = close_dt - timedelta(minutes=teardown_minutes)
        duration = timedelta(minutes=duration_minutes)

        slots: list[tuple[datetime, datetime]] = []
        candidate_start = earliest_start
        while candidate_start + duration <= latest_end:
            candidate_end = candidate_start + duration
            effective_start = candidate_start - timedelta(minutes=setup_minutes)
            effective_end = candidate_end + timedelta(minutes=teardown_minutes)

            if (
                self._find_conflict(
                    room_id,
                    effective_start,
                    effective_end,
                )
                is None
            ):
                slots.append((candidate_start, candidate_end))

            candidate_start += timedelta(minutes=15)

        return slots

    def cancel(self, reservation_id: int) -> Reservation:
        if reservation_id not in self._reservations:
            raise ReservationError(f"Reservation not found: {reservation_id}")
        reservation = self._reservations[reservation_id]
        if reservation.status == "CANCELLED":
            raise ReservationError(
                f"Reservation {reservation_id} is already cancelled"
            )
        reservation.status = "CANCELLED"
        return reservation

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
        for reservation in self._reservations.values():
            if active_only and reservation.status != "ACTIVE":
                continue
            if room_id is not None and reservation.room_id != room_id:
                continue
            if (
                target_date is not None
                and reservation.start.date() != target_date
            ):
                continue
            if user is not None and reservation.user != user:
                continue
            results.append(reservation)

        results.sort(
            key=lambda reservation: (
                reservation.start,
                reservation.reservation_id,
            )
        )
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
        booked_minutes = sum(
            reservation.duration_minutes for reservation in reservations
        )
        buffer_minutes = sum(
            reservation.setup_minutes + reservation.teardown_minutes
            for reservation in reservations
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

        available_operating_minutes = operating_minutes - maintenance_minutes
        if available_operating_minutes > 0:
            utilization = round(
                (booked_minutes + buffer_minutes)
                / available_operating_minutes,
                4,
            )
        else:
            utilization = 0.0

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