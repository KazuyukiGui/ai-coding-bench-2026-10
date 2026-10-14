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

添付ファイル:
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
=== END ===

答え方: 次のファイルの全体（変更しないファイルは不要）を、説明なしで、次の形式だけで返してください。各ファイルは「=== FILE: パス ===」の行で始め、最後に「=== END ===」の行を置きます。ツールは使えません。Python 3.11・標準ライブラリのみ。
返すファイル: reservation_system.py
