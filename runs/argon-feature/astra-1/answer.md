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
    def _validate_minutes(value: int, name: str, minimum: int = 0) -> None:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < minimum
            or value % 15 != 0
        ):
            raise ReservationError(
                f"{name} must be an integer >= {minimum} "
                "and a multiple of 15"
            )

    @staticmethod
    def _overlaps(
        start: datetime,
        end: datetime,
        other_start: datetime,
        other_end: datetime,
    ) -> bool:
        return start < other_end and other_start < end

    def _get_operating_bounds(
        self, room: Room, target_date: date
    ) -> tuple[datetime, datetime]:
        open_dt = datetime.combine(target_date, room.open_time)
        if room.close_time == time(0, 0):
            close_dt = datetime.combine(
                target_date + timedelta(days=1), time(0, 0)
            )
        else:
            close_dt = datetime.combine(target_date, room.close_time)
        return open_dt, close_dt

    def _validate_interval(self, start: datetime, end: datetime) -> None:
        if end <= start:
            raise ReservationError("End time must be after start time")
        if (
            not self._is_15min_aligned_dt(start)
            or not self._is_15min_aligned_dt(end)
        ):
            raise ReservationError(
                "Start and end times must be aligned to 15-minute intervals"
            )

        if start.date() != end.date():
            if not (
                end.date() == start.date() + timedelta(days=1)
                and end.time() == time(0, 0)
            ):
                raise ReservationError(
                    "Reservation cannot span across multiple days"
                )

    def _validate_slot(
        self, room: Room, start: datetime, end: datetime
    ) -> None:
        self._validate_interval(start, end)
        open_dt, close_dt = self._get_operating_bounds(room, start.date())
        if start < open_dt or end > close_dt:
            raise ReservationError(
                "Reservation is outside of room operating hours"
            )

    def _prepare_reservation(
        self,
        room_id: str,
        user: str,
        start: datetime,
        end: datetime,
        setup_minutes: int,
        teardown_minutes: int,
    ) -> Reservation:
        room = self.get_room(room_id)
        if not user or not user.strip():
            raise ReservationError("User must be specified")

        self._validate_minutes(setup_minutes, "setup_minutes")
        self._validate_minutes(teardown_minutes, "teardown_minutes")
        self._validate_slot(room, start, end)

        res = Reservation(
            reservation_id=0,
            room_id=room_id,
            user=user,
            start=start,
            end=end,
            setup_minutes=setup_minutes,
            teardown_minutes=teardown_minutes,
        )
        try:
            effective_start = res.effective_start
            effective_end = res.effective_end
        except OverflowError as exc:
            raise ReservationError(
                "Buffered reservation exceeds the supported datetime range"
            ) from exc

        self._validate_interval(effective_start, effective_end)
        open_dt, close_dt = self._get_operating_bounds(room, start.date())
        if effective_start < open_dt or effective_end > close_dt:
            raise ReservationError(
                "Reservation is outside of room operating hours"
            )
        return res

    def _validate_no_conflicts(
        self,
        room_id: str,
        start: datetime,
        end: datetime,
        pending: Optional[list[Reservation]] = None,
    ) -> None:
        for res in self._reservations.values():
            if (
                res.room_id == room_id
                and res.status == "ACTIVE"
                and self._overlaps(
                    start, end, res.effective_start, res.effective_end
                )
            ):
                raise ReservationError(
                    f"Time slot overlaps with reservation {res.reservation_id}"
                )

        for window in self._maintenance_windows.values():
            if (
                window.room_id == room_id
                and self._overlaps(start, end, window.start, window.end)
            ):
                raise ReservationError(
                    f"Time slot overlaps with maintenance {window.window_id}"
                )

        if pending is not None:
            for res in pending:
                if (
                    res.room_id == room_id
                    and res.status == "ACTIVE"
                    and self._overlaps(
                        start, end, res.effective_start, res.effective_end
                    )
                ):
                    raise ReservationError(
                        "Time slot overlaps with an earlier recurring occurrence"
                    )

    def _store_reservation(self, res: Reservation) -> Reservation:
        res.reservation_id = self._next_id
        self._reservations[self._next_id] = res
        self._next_id += 1
        return res

    def book(
        self,
        room_id: str,
        user: str,
        start: datetime,
        end: datetime,
        setup_minutes: int = 0,
        teardown_minutes: int = 0,
    ) -> Reservation:
        res = self._prepare_reservation(
            room_id, user, start, end, setup_minutes, teardown_minutes
        )
        self._validate_no_conflicts(
            room_id, res.effective_start, res.effective_end
        )
        return self._store_reservation(res)

    def add_maintenance(
        self,
        room_id: str,
        start: datetime,
        end: datetime,
        reason: str,
        force: bool = False,
    ) -> tuple[MaintenanceWindow, list[Reservation]]:
        self.get_room(room_id)
        self._validate_interval(start, end)

        for window in self._maintenance_windows.values():
            if (
                window.room_id == room_id
                and self._overlaps(start, end, window.start, window.end)
            ):
                raise ReservationError(
                    f"Time slot overlaps with maintenance {window.window_id}"
                )

        conflicts = sorted(
            (
                res
                for res in self._reservations.values()
                if res.room_id == room_id
                and res.status == "ACTIVE"
                and self._overlaps(
                    start, end, res.effective_start, res.effective_end
                )
            ),
            key=lambda res: res.reservation_id,
        )
        if conflicts and not force:
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
        for res in conflicts:
            res.status = "CANCELLED"
        self._maintenance_windows[window.window_id] = window
        self._next_window_id += 1
        return window, conflicts

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
        for name, value in (
            ("interval_days", interval_days),
            ("occurrences", occurrences),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
            ):
                raise ReservationError(
                    f"{name} must be an integer >= 1"
                )

        candidates: list[Reservation] = []
        for i in range(occurrences):
            try:
                offset = timedelta(days=i * interval_days)
                candidate_start = start + offset
                candidate_end = end + offset
            except OverflowError as exc:
                raise ReservationError(
                    "Recurring reservation exceeds the supported datetime range"
                ) from exc

            candidates.append(
                self._prepare_reservation(
                    room_id,
                    user,
                    candidate_start,
                    candidate_end,
                    setup_minutes,
                    teardown_minutes,
                )
            )

        accepted: list[Reservation] = []
        for candidate in candidates:
            try:
                self._validate_no_conflicts(
                    room_id,
                    candidate.effective_start,
                    candidate.effective_end,
                    pending=accepted,
                )
            except ReservationError:
                if not skip_conflicts:
                    raise
                continue
            accepted.append(candidate)

        return [self._store_reservation(res) for res in accepted]

    def find_available_slots(
        self,
        room_id: str,
        target_date: date,
        duration_minutes: int,
        setup_minutes: int = 0,
        teardown_minutes: int = 0,
    ) -> list[tuple[datetime, datetime]]:
        room = self.get_room(room_id)
        self._validate_minutes(duration_minutes, "duration_minutes", minimum=15)
        self._validate_minutes(setup_minutes, "setup_minutes")
        self._validate_minutes(teardown_minutes, "teardown_minutes")

        open_dt, close_dt = self._get_operating_bounds(room, target_date)
        operating_minutes = int((close_dt - open_dt).total_seconds() // 60)
        total_minutes = duration_minutes + setup_minutes + teardown_minutes
        if total_minutes > operating_minutes:
            return []

        setup = timedelta(minutes=setup_minutes)
        duration = timedelta(minutes=duration_minutes)
        teardown = timedelta(minutes=teardown_minutes)
        step = timedelta(minutes=15)
        start = open_dt + setup
        latest_start = close_dt - duration - teardown
        slots: list[tuple[datetime, datetime]] = []

        while start <= latest_start:
            end = start + duration
            try:
                self._validate_no_conflicts(
                    room_id, start - setup, end + teardown
                )
            except ReservationError:
                pass
            else:
                slots.append((start, end))
            start += step

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
        operating_minutes = int((close_dt - open_dt).total_seconds() // 60)

        reservations = self.get_reservations(
            room_id=room_id, target_date=target_date, active_only=True
        )
        booked_minutes = sum(r.duration_minutes for r in reservations)
        buffer_minutes = sum(
            r.setup_minutes + r.teardown_minutes for r in reservations
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
            round((booked_minutes + buffer_minutes) / available_minutes, 4)
            if available_minutes > 0
            else 0.0
        )

        return {
            "room_id": room_id,
            "date": target_date.isoformat(),
            "reservation_count": len(reservations),
            "booked_minutes": booked_minutes,
            "operating_minutes": operating_minutes,
            "buffer_minutes": buffer_minutes,
            "maintenance_minutes": maintenance_minutes,
            "utilization_rate": utilization,
        }
=== END ===