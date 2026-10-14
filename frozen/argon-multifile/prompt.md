社内設備・計算リソースの予約管理システムを改修します。
現在、このシステムは `models.py`、`allocator.py`、`service.py` の3つのファイルで構成されており、各予約につき1ユニットのみを割り当てる仕様になっています。

今回の改修では、**1回の予約で複数ユニットを要求できる機能（部分割り当て対応）**と、**予約の一部または全部を解放する機能**を追加し、それに伴って3つのファイルすべてのインターフェースおよび実装を更新してください。

以下の仕様に従って、`models.py`、`allocator.py`、`service.py` を改修してください。

---

### 1. `models.py` の仕様

#### `Resource` (dataclass)
変更ありません（既存のまま維持してください）。
- `resource_id: str`
- `category: str`
- `total_units: int`
- `total_units < 1` の場合は `__post_init__` で `ValueError` を送出します。

#### `ReservationRequest` (dataclass)
フィールドの追加・名称変更とバリデーションの追加を行います。
- フィールド:
  - `request_id: str`
  - `category: str`
  - `start: int`
  - `end: int`
  - `priority: int = 0`
  - `units: int = 1` （新規追加: 要求ユニット数）
  - `min_units: int | None = None` （新規追加: 最小許容ユニット数。`None` の場合は `__post_init__` で `self.units` と同じ値に設定する）
  - `preferred_resource_id: str | None = None` （旧 `resource_id` から名称変更）
- `__post_init__` でのバリデーション（違反時はすべて `ValueError` を送出）:
  - `start < 0` または `end <= start` の場合
  - `units < 1` の場合
  - `min_units`（`None` 解決後）が `1` 未満、または `min_units > units` の場合

#### `Allocation` (dataclass)
フィールドの追加とメソッドの更新を行います。
- フィールド:
  - `request_id: str`
  - `resource_id: str`
  - `category: str`
  - `start: int`
  - `end: int`
  - `priority: int`
  - `units: int` （新規追加: 実際に割り当てられたユニット数）
- メソッド:
  - `overlaps(self, start: int, end: int) -> bool`: 既存の通り、区間 `[self.start, self.end)` と `[start, end)` が重なるかどうか（`self.start < end and start < self.end`）を返します。
  - `duration(self) -> int`: `self.end - self.start` を返します。
  - `unit_hours(self) -> int`: `self.duration() * self.units` を返します（新規追加）。

---

### 2. `allocator.py` の仕様 (`ResourceAllocator` クラス)

#### 既存メソッドの維持・更新
- `add_resource(self, resource: Resource) -> None`: 既存通り（重複 `resource_id` は `ValueError`）。
- `get_resource(self, resource_id: str) -> Resource`: 既存通り（未登録 `resource_id` は `KeyError`）。
- `get_allocations(self, resource_id: str | None = None) -> list[Allocation]`: 既存通り。指定されたリソース（`None` の場合は全リソース）の割当一覧を `(start, end, request_id)` の昇順でソートして返します。

#### `available_units(self, resource_id: str, start: int, end: int) -> int`
- `resource_id` が未登録の場合は `KeyError`、`start < 0` または `end <= start` の場合は `ValueError` を送出します。
- 指定されたリソースにおいて、区間 `[start, end)` 内の**すべての単位時間 `[t, t+1)` で共通して空いているユニット数の最大値**を返します。
  - すなわち、各時刻 $t \in [\text{start}, \text{end}-1]$ における既存割当の `units` の合計を $U(t)$ としたとき、$\min_{t \in [\text{start}, \text{end}-1]} (\text{total\_units} - U(t))$ です。
  - 区間内に重なる割当が1つもなければ `resource.total_units` を返します。

#### `allocate(self, request: ReservationRequest) -> Allocation | None`
- すでに同じ `request.request_id` を持つ割当が存在する場合は `ValueError` を送出します。
- リソースの探索と割当ロジック:
  1. `request.preferred_resource_id` が `None` でない場合:
     - その ID のリソースが登録されていなければ `KeyError` を送出します。
     - そのリソースの `category` が `request.category` と一致しなければ `ValueError` を送出します。
     - 候補リソースはその1つのみとなります。
  2. `request.preferred_resource_id` が `None` の場合:
     - `resource.category == request.category` であるすべての登録済みリソースが候補となります。
  3. 各候補リソースについて、`avail = self.available_units(res.resource_id, request.start, request.end)` を計算します。
  4. `avail >= request.min_units` を満たす候補がない場合は、割当を行わず `None` を返します。
  5. 条件を満たす各候補リソースに対して、実際に割り当てるユニット数 `alloc_units = min(request.units, avail)` を計算します。
  6. 候補の中から、以下の優先順位で1つのリソースを選択します:
     - 第1基準: `alloc_units` が**大きい**方
     - 第2基準: `avail - alloc_units`（割当後の残り空きユニット数）が**小さい**方（ベストフィット）
     - 第3基準: `res.resource_id` の辞書順で**小さい**方
  7. 選択されたリソースに対して `units=alloc_units` で `Allocation` を作成・保存し、それを返します。

#### `release(self, request_id: str, units: int | None = None) -> Allocation | None`
- シグネチャと戻り値の仕様を変更します。
- 指定された `request_id` の割当が存在しない場合は `KeyError` を送出します。
- `units` が `None` の場合、または `units == 現在の割当ユニット数` の場合:
  - その割当を完全に削除し、削除直前に保存されていた `Allocation` オブジェクト（それまでに部分解放があれば、その更新後のもの）を返します。
- `units` が整数で指定された場合:
  - `units < 1` または `units > 現在の割当ユニット数` の場合は `ValueError` を送出します（このとき割当状態は変更しません）。
  - `units < 現在の割当ユニット数` の場合は、その割当の `units` を `units` 分だけ減らし（`新しい units = 元の units - units`）、**更新後の** `Allocation` オブジェクトを返します。

---

### 3. `service.py` の仕様 (`BookingService` クラス)

#### `register_resource(self, resource_id: str, category: str, total_units: int) -> Resource`
- 既存通り。

#### `submit_batch(self, requests: list[ReservationRequest]) -> dict[str, Allocation | None]`
- 以下のバリデーションを追加します:
  - 引数 `requests` のリスト内に同じ `request_id` が複数含まれている場合、または `allocator` 内にすでに同じ `request_id` の割当が存在する場合は、**1件も割当を行わずに** `ValueError` を送出します。
- 処理順序のソート基準を以下の順序（タプル比較）に変更します:
  1. `priority` の**降順**（値が大きい方が先）
  2. `start` の**昇順**（開始が早い方が先）
  3. `(end - start) * units`（要求の総ユニット時間）の**降順**（大きい方が先）
  4. `request_id` の辞書順**昇順**
- ソート順に `allocator.allocate(req)` を呼び出し、各 `request_id` をキー、結果（`Allocation` または `None`）を値とする辞書を返します。

#### `cancel_or_reduce(self, request_id: str, units: int | None = None) -> bool`
- 旧 `cancel(self, request_id: str) -> bool` を置き換えます（新たに `cancel_or_reduce` を実装してください。旧 `cancel` は残しても消してもかまいません。試験は `cancel` を使いません）。
- `allocator.release(request_id, units)` を呼び出します。
- 該当する `request_id` が存在せず `KeyError` となった場合は `False` を返します。
- `units` の指定が不正で `ValueError` となった場合は、そのまま `ValueError` を送出します。
- 正常に解放（完全削除または部分削減）できた場合は `True` を返します。

#### `utilization_report(self, category: str, window_start: int, window_end: int) -> dict[str, float]`
- `window_start < 0` または `window_end <= window_start` の場合は `ValueError` を送出します。
- 返却する辞書のキーと値の計算式を、`Allocation.units` を反映したものに更新します（値はすべて `float` 型とし、丸め処理は行わないでください）:
  - `"total_capacity_unit_hours"`: 対象 `category` に属する全リソースの `total_units` の合計 × `(window_end - window_start)`
  - `"allocated_unit_hours"`: 対象 `category` の全割当について、集計区間 `[window_start, window_end)` と重なる時間長 `(min(alloc.end, window_end) - max(alloc.start, window_start))` × `alloc.units` の総和
  - `"utilization_rate"`: `total_capacity_unit_hours > 0` の場合は `allocated_unit_hours / total_capacity_unit_hours`、対象カテゴリのリソースが存在しない場合（キャパシティが0の場合）は `0.0`
  - `"peak_concurrent_units"`（新規追加）: 集計区間内の各単位時間 $t \in [\text{window\_start}, \text{window\_end}-1]$ において、対象 `category` の全リソースで時刻 $[t, t+1)$ に割り当てられている `units` の合計の最大値（float型。割当が1つもない場合は `0.0`）。

#### `reschedule(self, request_id: str, new_start: int, new_end: int, new_units: int | None = None) -> Allocation`
- 既存の予約を新しい時間帯（および任意で新しいユニット数）に変更します。
- 指定された `request_id` の割当が存在しない場合は `KeyError` を送出します。
- `target_units = new_units if new_units is not None else 現在の割当.units` とします。
- `new_start < 0`、`new_end <= new_start`、または `target_units < 1` の場合は `ValueError` を送出します（このとき元の割当は維持されます）。
- 現在の割当を一度解放した上で、以下の条件の `ReservationRequest` を新たに割り当てます:
  - `request_id`: 元の `request_id`
  - `category`: 元の `category`
  - `start`: `new_start`
  - `end`: `new_end`
  - `priority`: 元の `priority`
  - `units`: `target_units`
  - `min_units`: `target_units` （部分割当は不可とし、要求数を満たせない場合は失敗させます）
  - `preferred_resource_id`: **元の割当の `resource_id`**（まず同じリソースでの再割当を試みます）
- 上記の同じリソースでの割当が成功した場合は、その新しい `Allocation` を返します。
- 同じリソースで空きが足りず割当できなかった場合（`None` が返った場合）は、`preferred_resource_id=None` として再度同カテゴリの任意のリソースへの割当を試みます。
- それでも割当できなかった場合は、**元の割当（元のリソース・時間帯・ユニット数）を完全に復元した上で**、`RuntimeError` を送出します。
