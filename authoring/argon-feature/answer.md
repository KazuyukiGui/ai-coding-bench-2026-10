=== FILE: meta.json ===
{"title": "共有ワークスペース予約システムの機能拡張", "category": "feature", "answer": ["reservation_system.py"]}
=== FILE: prompt.md ===
### 概要
共有ワークスペースの予約管理システム `reservation_system.py` が稼働しています。
現在このシステムは、部屋ごとの営業時間管理、単発の予約作成・キャンセル、および日次の稼働レポート出力に対応しています。

業務の拡大に伴い、以下の4つの新機能を追加することになりました。既存の機能やインターフェース（既存の引数だけで呼び出した場合の挙動や戻り値など）を壊さないよう注意して、`reservation_system.py` を拡張してください。

---

### 追加する仕様

#### 1. 準備時間・片付け時間（バッファ時間）と予約情報の拡張
予約に「準備時間 (`setup_minutes`)」と「片付け時間 (`teardown_minutes`)」を設定できるようにします。

* **`Reservation` データクラスの拡張**
  * 既存のフィールドの末尾に `setup_minutes: int = 0` と `teardown_minutes: int = 0` を追加します。
  * 新規プロパティ `effective_start: datetime`（`start - setup_minutes分`）および `effective_end: datetime`（`end + teardown_minutes分`）を追加します。
  * 新規プロパティ `total_duration_minutes: int`（`effective_start` から `effective_end` までの分数）を追加します。既存の `duration_minutes` は従来通り `start` から `end` までの分数のままとします。

* **`book` メソッドの拡張**
  * シグネチャを `book(self, room_id: str, user: str, start: datetime, end: datetime, setup_minutes: int = 0, teardown_minutes: int = 0) -> Reservation` に変更します。
  * **バリデーション**:
    * `setup_minutes` と `teardown_minutes` は `0` 以上の整数であり、かつ **15の倍数** でなければなりません（違反時は `ReservationError`）。
    * 営業時間チェック、日跨ぎ不可チェック、および他の予約（および後述のメンテナンス枠）との重複チェックは、すべて `effective_start` から `effective_end` の区間（準備・片付けを含めた全体の占有時間帯）に対して行います。
    * 他の予約のバッファ時間と重なる場合も重複とみなします（接しているだけ、すなわち一方の `effective_end` と他方の `effective_start` が等しい場合は重複しません）。
    * 本体時間（`start` から `end`）のバリデーション（`end > start`、15分刻み、15分以上など）も引き続き適用されます。

#### 2. メンテナンス枠の登録と強制キャンセル
部屋の清掃や設備点検のため、特定の日時をメンテナンス枠としてブロックできるようにします。

* **`MaintenanceWindow` データクラスの新設**
  * フィールド: `window_id: int`, `room_id: str`, `start: datetime`, `end: datetime`, `reason: str`
* **`add_maintenance(self, room_id: str, start: datetime, end: datetime, reason: str, force: bool = False) -> tuple[MaintenanceWindow, list[Reservation]]` の追加**
  * **バリデーション**:
    * 部屋の存在確認、日跨ぎ不可（`start.date() == end.date()` または `end` が翌日の `00:00`）、`end > start`、15分刻みを確認します（違反時は `ReservationError`）。
    * ※メンテナンス枠は部屋の営業時間外にはみ出していても構いません。
    * 既存のメンテナンス枠と時間帯が重なる場合は、`force` の値に関わらず常に `ReservationError` を送出します。
  * **予約との重複処理**:
    * 既存の `ACTIVE` な予約（`effective_start` 〜 `effective_end`）と時間帯が重なる場合：
      * `force=False` のときは `ReservationError` を送出し、状態を変更しません。
      * `force=True` のときは、重なっているすべての `ACTIVE` な予約の `status` を `"CANCELLED"` に変更し、キャンセルされた予約のリストを（`reservation_id` の昇順で）戻り値のタプルの第2要素として返します。
  * メンテナンス枠には `1` から始まる連番の `window_id` を採番します（予約のIDとは独立した連番です）。
  * 登録後は、その時間帯に重なる新規予約や定期予約は作成できなくなります。

#### 3. 定期予約（Recurring Bookings）
毎週または隔週などの定期的な予約を一括で登録できるようにします。

* **`book_recurring(self, room_id: str, user: str, start: datetime, end: datetime, interval_days: int, occurrences: int, setup_minutes: int = 0, teardown_minutes: int = 0, skip_conflicts: bool = False) -> list[Reservation]` の追加**
  * **パラメータのバリデーション**:
    * `interval_days >= 1` かつ `occurrences >= 1` でなければなりません（違反時は `ReservationError`）。
  * **各回の生成と検証**:
    * $i = 0, 1, \dots, \text{occurrences}-1$ について、開始時刻を `start + timedelta(days=i * interval_days)`、終了時刻を `end + timedelta(days=i * interval_days)` とする予約候補を生成します。
    * 各候補について、単発の `book` と同じバリデーションを行います。
    * **基本ルールエラー**（部屋が存在しない、`start`/`end` の逆転・日跨ぎ・15分刻み違反、バッファ時間の違反、営業時間外など）が1つでも含まれる場合は、`skip_conflicts` の値に関わらず **1件も予約を作成せず**（IDの採番も進めず）に `ReservationError` を送出します。
    * **競合エラー**（既存の `ACTIVE` な予約、既存のメンテナンス枠、または今回の `book_recurring` 内で先行して確定した回との時間帯の重複）が発生した場合：
      * `skip_conflicts=False` なら、**1件も予約を作成せず**（IDの採番も進めず）に `ReservationError` を送出します（All-or-Nothing）。
      * `skip_conflicts=True` なら、競合した回だけをスキップし、競合しなかった回のみを先頭から順に予約として確定・ID採番します（全回がスキップされた場合は空リスト `[]` を返します）。

#### 4. 空き枠検索と日次レポートの拡張

* **`find_available_slots(self, room_id: str, target_date: date, duration_minutes: int, setup_minutes: int = 0, teardown_minutes: int = 0) -> list[tuple[datetime, datetime]]` の追加**
  * 指定した部屋・日付において、指定した条件で `book` 可能なすべての開始・終了時刻のペア `(start, end)` を、開始時刻の昇順で返します。
  * **バリデーション**:
    * 部屋が存在しない場合、`duration_minutes < 15` または15の倍数でない場合、`setup_minutes` / `teardown_minutes` が0未満または15の倍数でない場合は `ReservationError` を送出します。
  * 返される `(start, end)` はバッファを除いた予約本体の時刻であり、`end - start == timedelta(minutes=duration_minutes)` を満たします。
  * その日の営業時間内に `effective_start` 〜 `effective_end` が収まり、かつ既存の `ACTIVE` な予約（バッファ含む）やメンテナンス枠と重ならないすべての15分刻みの枠を列挙してください（例：10:00〜11:00 が空いていて45分枠を探す場合、`(10:00, 10:45)` と `(10:15, 11:00)` の2つが返ります）。

* **`get_daily_report(self, room_id: str, target_date: date)` の拡張**
  * 既存の戻り値の辞書に、以下のキーを追加・更新します。
    * `"buffer_minutes"`: その日の `ACTIVE` な予約の `setup_minutes + teardown_minutes` の合計（整数）。
    * `"maintenance_minutes"`: その日の **営業時間内** と重なっているメンテナンス枠の合計分数（整数）。営業時間外の部分は除外して計算してください。
    * `"booked_minutes"`: 従来通り、予約本体（`duration_minutes`）の合計のまま変更しません。
    * `"utilization_rate"`: `(booked_minutes + buffer_minutes) / (営業時間の分数 - maintenance_minutes)` を小数第4位で四捨五入（`round(val, 4)`）した値（`float`）。ただし、分母（営業時間の分数 - `maintenance_minutes`）が `0` 以下の場合は `0.0` とします。
=== FILE: given/reservation_system.py ===
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

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


class ReservationSystem:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._reservations: dict[int, Reservation] = {}
        self._next_id: int = 1

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

    def _get_operating_bounds(self, room: Room, target_date: date) -> tuple[datetime, datetime]:
        open_dt = datetime.combine(target_date, room.open_time)
        if room.close_time == time(0, 0):
            close_dt = datetime.combine(target_date + timedelta(days=1), time(0, 0))
        else:
            close_dt = datetime.combine(target_date, room.close_time)
        return open_dt, close_dt

    def _ validate_slot(self, room: Room, start: datetime, end: datetime) -> None:
        if end <= start:
            raise ReservationError("End time must be after start time")
        if not self._is_15min_aligned_dt(start) or not self._is_15min_aligned_dt(end):
            raise ReservationError("Start and end times must be aligned to 15-minute intervals")

        # 日跨ぎの禁止（終了時刻が翌日の00:00ちょうどの場合のみ例外的に同日扱い）
        if start.date() != end.date():
            if not (end.date() == start.date() + timedelta(days=1) and end.time() == time(0, 0)):
                raise ReservationError("Reservation cannot span across multiple days")

        open_dt, close_dt = self._get_operating_bounds(room, start.date())
        if start < open_dt or end > close_dt:
            raise ReservationError("Reservation is outside of room operating hours")

    def book(self, room_id: str, user: str, start: datetime, end: datetime) -> Reservation:
        room = self.get_room(room_id)
        if not user or not user.strip():
            raise ReservationError("User must be specified")

        self._validate_slot(room, start, end)

        for res in self._reservations.values():
            if res.room_id == room_id and res.status == "ACTIVE":
                if not (end <= res.start or start >= res.end):
                    raise ReservationError(f"Time slot overlaps with reservation {res.reservation_id}")

        res = Reservation(
            reservation_id=self._next_id,
            room_id=room_id,
            user=user,
            start=start,
            end=end,
            status="ACTIVE",
        )
        self._reservations[self._next_id] = res
        self._next_id += 1
        return res

    def _validate_slot(self, room: Room, start: datetime, end: datetime) -> None:
        if end <= start:
            raise ReservationError("End time must be after start time")
        if not self._is_15min_aligned_dt(start) or not self._is_15min_aligned_dt(end):
            raise ReservationError("Start and end times must be aligned to 15-minute intervals")

        if start.date() != end.date():
            if not (end.date() == start.date() + timedelta(days=1) and end.time() == time(0, 0)):
                raise ReservationError("Reservation cannot span across multiple days")

        open_dt, close_dt = self._get_operating_bounds(room, start.date())
        if start < open_dt or end > close_dt:
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
        utilization = round(booked_minutes / operating_minutes, 4) if operating_minutes > 0 else 0.0

        return {
            "room_id": room_id,
            "date": target_date.isoformat(),
            "reservation_count": len(reservations),
            "booked_minutes": booked_minutes,
            "operating_minutes": operating_minutes,
            "utilization_rate": utilization,
        }
=== FILE: ref/reservation_system.py ===
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
        self._maintenances: dict[int, MaintenanceWindow] = {}
        self._next_id: int = 1
        self._next_maintenance_id: int = 1

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
        if not isinstance(setup_minutes, int) or not isinstance(teardown_minutes, int):
            raise ReservationError("Buffer minutes must be integers")
        if setup_minutes < 0 or teardown_minutes < 0:
            raise ReservationError("Buffer minutes must be non-negative")
        if setup_minutes % 15 != 0 or teardown_minutes % 15 != 0:
            raise ReservationError("Buffer minutes must be multiples of 15")

    @staticmethod
    def _is_same_day_span(start: datetime, end: datetime) -> bool:
        if start.date() == end.date():
            return True
        return end.date() == start.date() + timedelta(days=1) and end.time() == time(0, 0)

    def _get_operating_bounds(self, room: Room, target_date: date) -> tuple[datetime, datetime]:
        open_dt = datetime.combine(target_date, room.open_time)
        if room.close_time == time(0, 0):
            close_dt = datetime.combine(target_date + timedelta(days=1), time(0, 0))
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
    ) -> tuple[datetime, datetime]:
        if end <= start:
            raise ReservationError("End time must be after start time")
        if not self._is_15min_aligned_dt(start) or not self._is_15min_aligned_dt(end):
            raise ReservationError("Start and end times must be aligned to 15-minute intervals")

        self._validate_buffer_minutes(setup_minutes, teardown_minutes)

        if not self._is_same_day_span(start, end):
            raise ReservationError("Reservation cannot span across multiple days")

        eff_start = start - timedelta(minutes=setup_minutes)
        eff_end = end + timedelta(minutes=teardown_minutes)

        if not self._is_same_day_span(eff_start, eff_end):
            raise ReservationError("Effective reservation cannot span across multiple days")

        open_dt, close_dt = self._get_operating_bounds(room, start.date())
        if eff_start < open_dt or eff_end > close_dt:
            raise ReservationError("Reservation (including buffer) is outside of room operating hours")

        return eff_start, eff_end

    def _has_conflict(self, room_id: str, eff_start: datetime, eff_end: datetime) -> bool:
        for mw in self._maintenances.values():
            if mw.room_id == room_id:
                if not (eff_end <= mw.start or eff_start >= mw.end):
                    return True

        for res in self._reservations.values():
            if res.room_id == room_id and res.status == "ACTIVE":
                if not (eff_end <= res.effective_start or eff_start >= res.effective_end):
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

        eff_start, eff_end = self._validate_slot(room, start, end, setup_minutes, teardown_minutes)

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
        if not isinstance(interval_days, int) or interval_days < 1:
            raise ReservationError("interval_days must be >= 1")
        if not isinstance(occurrences, int) or occurrences < 1:
            raise ReservationError("occurrences must be >= 1")

        candidates: list[tuple[datetime, datetime, datetime, datetime]] = []
        for i in range(occurrences):
            delta = timedelta(days=i * interval_days)
            c_start = start + delta
            c_end = end + delta
            eff_start, eff_end = self._validate_slot(room, c_start, c_end, setup_minutes, teardown_minutes)
            candidates.append((c_start, c_end, eff_start, eff_end))

        accepted: list[tuple[datetime, datetime, datetime, datetime]] = []
        for c_start, c_end, eff_start, eff_end in candidates:
            conflict = self._has_conflict(room_id, eff_start, eff_end)
            if not conflict:
                for _, _, prev_eff_start, prev_eff_end in accepted:
                    if not (eff_end <= prev_eff_start or eff_start >= prev_eff_end):
                        conflict = True
                        break
            if conflict:
                if not skip_conflicts:
                    raise ReservationError("Recurring booking has a conflict")
                continue
            accepted.append((c_start, c_end, eff_start, eff_end))

        created: list[Reservation] = []
        for c_start, c_end, _, _ in accepted:
            res = Reservation(
                reservation_id=self._next_id,
                room_id=room_id,
                user=user,
                start=c_start,
                end=c_end,
                status="ACTIVE",
                setup_minutes=setup_minutes,
                teardown_minutes=teardown_minutes,
            )
            self._reservations[self._next_id] = res
            self._next_id += 1
            created.append(res)

        return created

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
            raise ReservationError("Maintenance end time must be after start time")
        if not self._is_15min_aligned_dt(start) or not self._is_15min_aligned_dt(end):
            raise ReservationError("Maintenance times must be aligned to 15-minute intervals")
        if not self._is_same_day_span(start, end):
            raise ReservationError("Maintenance window cannot span across multiple days")

        for mw in self._maintenances.values():
            if mw.room_id == room_id:
                if not (end <= mw.start or start >= mw.end):
                    raise ReservationError("Overlaps with existing maintenance window")

        overlapping_res: list[Reservation] = []
        for res in self._reservations.values():
            if res.room_id == room_id and res.status == "ACTIVE":
                if not (end <= res.effective_start or start >= res.effective_end):
                    overlapping_res.append(res)

        if overlapping_res and not force:
            raise ReservationError("Maintenance window conflicts with active reservations")

        overlapping_res.sort(key=lambda r: r.reservation_id)
        for res in overlapping_res:
            res.status = "CANCELLED"

        mw = MaintenanceWindow(
            window_id=self._next_maintenance_id,
            room_id=room_id,
            start=start,
            end=end,
            reason=reason,
        )
        self._maintenances[self._next_maintenance_id] = mw
        self._next_maintenance_id += 1
        return mw, overlapping_res

    def find_available_slots(
        self,
        room_id: str,
        target_date: date,
        duration_minutes: int,
        setup_minutes: int = 0,
        teardown_minutes: int = 0,
    ) -> list[tuple[datetime, datetime]]:
        room = self.get_room(room_id)
        if not isinstance(duration_minutes, int) or duration_minutes < 15 or duration_minutes % 15 != 0:
            raise ReservationError("duration_minutes must be a multiple of 15 and >= 15")
        self._validate_buffer_minutes(setup_minutes, teardown_minutes)

        open_dt, close_dt = self._get_operating_bounds(room, target_date)
        slots: list[tuple[datetime, datetime]] = []

        current_eff_start = open_dt
        total_delta = timedelta(minutes=setup_minutes + duration_minutes + teardown_minutes)
        setup_delta = timedelta(minutes=setup_minutes)
        dur_delta = timedelta(minutes=duration_minutes)
        step = timedelta(minutes=15)

        while current_eff_start + total_delta <= close_dt:
            current_eff_end = current_eff_start + total_delta
            if not self._has_conflict(room_id, current_eff_start, current_eff_end):
                slot_start = current_eff_start + setup_delta
                slot_end = slot_start + dur_delta
                slots.append((slot_start, slot_end))
            current_eff_start += step

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
        for mw in self._maintenances.values():
            if mw.room_id == room_id and mw.start.date() == target_date:
                overlap_start = max(open_dt, mw.start)
                overlap_end = min(close_dt, mw.end)
                if overlap_end > overlap_start:
                    maintenance_minutes += int((overlap_end - overlap_start).total_seconds() // 60)

        available_operating_minutes = operating_minutes - maintenance_minutes
        if available_operating_minutes > 0:
            utilization = round((booked_minutes + buffer_minutes) / available_operating_minutes, 4)
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
=== FILE: tests/test_hidden.py ===
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
=== END ===
