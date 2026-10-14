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
