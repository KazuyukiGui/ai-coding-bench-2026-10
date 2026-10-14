あなたは、AI のコーディング性能を比べる試験の「審査員」です。別の AI が作った課題を、試験に使う前に点検します。解く側は課題文と添付ファイル（given）だけを読んでファイル全体を書きます。隠し試験（tests）と模範解答（ref）は解く側には見えません。

次の観点で点検し、問題だけを挙げてください。問題が無ければ空の配列を返します。
1. 課題文に書いていない挙動を、隠し試験が問うていないか（エラー文の文言・例外の型・並び順・空白・丸め方など）
2. 課題文の読み方が2通り以上あり、模範解答と違う読み方でも妥当なのに、試験で落ちる所はないか
3. 試験そのものの誤り（模範解答は通るが、課題文に照らすと期待値が違う）
4. 解く側に渡していない情報（given に無い関数名・ファイル名・定数）に試験が頼っていないか
5. 試験が環境に依存していないか（時刻・乱数・ファイルの並び順・ロケール）

答えは JSON だけで返してください（説明・前置き不要）。
{"issues": [{"severity": "high|medium|low", "where": "tests の関数名か課題文の箇所", "problem": "何が問題か", "fix": "課題文をどう直すか、または試験をどう直すか"}]}
severity の目安: high＝正しく解いても落ちる、medium＝妥当な別解が落ちる恐れ、low＝読みにくいが結果は変わらない。

---
=== FILE: given/allocator.py ===
from models import Allocation, ReservationRequest, Resource


class ResourceAllocator:
    def __init__(self) -> None:
        self._resources: dict[str, Resource] = {}
        self._allocations: dict[str, list[Allocation]] = {}
        self._by_request_id: dict[str, Allocation] = {}

    def add_resource(self, resource: Resource) -> None:
        if resource.resource_id in self._resources:
            raise ValueError(f"Resource {resource.resource_id} already exists")
        self._resources[resource.resource_id] = resource
        self._allocations[resource.resource_id] = []

    def get_resource(self, resource_id: str) -> Resource:
        if resource_id not in self._resources:
            raise KeyError(f"Unknown resource: {resource_id}")
        return self._resources[resource_id]

    def get_allocations(self, resource_id: str | None = None) -> list[Allocation]:
        if resource_id is not None:
            if resource_id not in self._resources:
                raise KeyError(f"Unknown resource: {resource_id}")
            result = list(self._allocations[resource_id])
        else:
            result = list(self._by_request_id.values())
        result.sort(key=lambda a: (a.start, a.end, a.request_id))
        return result

    def available_units(self, resource_id: str, start: int, end: int) -> int:
        if resource_id not in self._resources:
            raise KeyError(f"Unknown resource: {resource_id}")
        if start < 0 or end <= start:
            raise ValueError("Invalid time window")

        resource = self._resources[resource_id]
        overlapping = [
            a for a in self._allocations[resource_id] if a.overlaps(start, end)
        ]
        if not overlapping:
            return resource.total_units

        max_used = 0
        for t in range(start, end):
            used = sum(1 for a in overlapping if a.start <= t < a.end)
            if used > max_used:
                max_used = used
        return resource.total_units - max_used

    def allocate(self, request: ReservationRequest) -> Allocation | None:
        if request.request_id in self._by_request_id:
            raise ValueError(f"Duplicate request_id: {request.request_id}")

        if request.resource_id is not None:
            if request.resource_id not in self._resources:
                raise KeyError(f"Unknown resource: {request.resource_id}")
            res = self._resources[request.resource_id]
            if res.category != request.category:
                raise ValueError("Resource category mismatch")
            candidates = [res]
        else:
            candidates = [
                r for r in self._resources.values() if r.category == request.category
            ]
            candidates.sort(key=lambda r: r.resource_id)

        best_resource: Resource | None = None
        for res in candidates:
            avail = self.available_units(res.resource_id, request.start, request.end)
            if avail >= 1:
                best_resource = res
                break

        if best_resource is None:
            return None

        alloc = Allocation(
            request_id=request.request_id,
            resource_id=best_resource.resource_id,
            category=request.category,
            start=request.start,
            end=request.end,
            priority=request.priority,
        )
        self._allocations[best_resource.resource_id].append(alloc)
        self._by_request_id[request.request_id] = alloc
        return alloc

    def release(self, request_id: str) -> Allocation:
        if request_id not in self._by_request_id:
            raise KeyError(f"Unknown request_id: {request_id}")
        alloc = self._by_request_id.pop(request_id)
        self._allocations[alloc.resource_id].remove(alloc)
        return alloc

=== FILE: given/models.py ===
from dataclasses import dataclass


@dataclass(frozen=True)
class Resource:
    resource_id: str
    category: str
    total_units: int

    def __post_init__(self) -> None:
        if self.total_units < 1:
            raise ValueError("total_units must be >= 1")


@dataclass(frozen=True)
class ReservationRequest:
    request_id: str
    category: str
    start: int
    end: int
    priority: int = 0
    resource_id: str | None = None

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Invalid time range")


@dataclass(frozen=True)
class Allocation:
    request_id: str
    resource_id: str
    category: str
    start: int
    end: int
    priority: int

    def overlaps(self, start: int, end: int) -> bool:
        return self.start < end and start < self.end

    def duration(self) -> int:
        return self.end - self.start

=== FILE: given/service.py ===
from allocator import ResourceAllocator
from models import Allocation, ReservationRequest, Resource


class BookingService:
    def __init__(self, allocator: ResourceAllocator | None = None) -> None:
        self.allocator = allocator if allocator is not None else ResourceAllocator()

    def register_resource(
        self, resource_id: str, category: str, total_units: int
    ) -> Resource:
        res = Resource(
            resource_id=resource_id, category=category, total_units=total_units
        )
        self.allocator.add_resource(res)
        return res

    def submit_batch(
        self, requests: list[ReservationRequest]
    ) -> dict[str, Allocation | None]:
        ordered = sorted(
            requests,
            key=lambda r: (-r.priority, r.start, r.end - r.start, r.request_id),
        )
        results: dict[str, Allocation | None] = {}
        for req in ordered:
            results[req.request_id] = self.allocator.allocate(req)
        return results

    def cancel(self, request_id: str) -> bool:
        try:
            self.allocator.release(request_id)
            return True
        except KeyError:
            return False

    def utilization_report(
        self, category: str, window_start: int, window_end: int
    ) -> dict[str, float]:
        if window_start < 0 or window_end <= window_start:
            raise ValueError("Invalid window")

        resources = [
            self.allocator.get_resource(rid)
            for rid in self._resource_ids_by_category(category)
        ]
        duration = window_end - window_start
        total_capacity = sum(r.total_units * duration for r in resources)

        allocated = 0
        for r in resources:
            for alloc in self.allocator.get_allocations(r.resource_id):
                if alloc.overlaps(window_start, window_end):
                    overlap_start = max(alloc.start, window_start)
                    overlap_end = min(alloc.end, window_end)
                    allocated += overlap_end - overlap_start

        rate = allocated / total_capacity if total_capacity > 0 else 0.0
        return {
            "total_capacity_unit_hours": float(total_capacity),
            "allocated_unit_hours": float(allocated),
            "utilization_rate": float(rate),
        }

    def _resource_ids_by_category(self, category: str) -> list[str]:
        all_allocs = self.allocator.get_allocations()
        seen: set[str] = set()
        for a in all_allocs:
            if a.category == category:
                seen.add(a.resource_id)
        for rid, res in getattr(self.allocator, "_resources", {}).items():
            if res.category == category:
                seen.add(rid)
        return sorted(seen)

=== FILE: prompt.md ===
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

=== FILE: ref/allocator.py ===
from models import Allocation, ReservationRequest, Resource


class ResourceAllocator:
    def __init__(self) -> None:
        self._resources: dict[str, Resource] = {}
        self._allocations: dict[str, list[Allocation]] = {}
        self._by_request_id: dict[str, Allocation] = {}

    def add_resource(self, resource: Resource) -> None:
        if resource.resource_id in self._resources:
            raise ValueError(f"Resource {resource.resource_id} already exists")
        self._resources[resource.resource_id] = resource
        self._allocations[resource.resource_id] = []

    def get_resource(self, resource_id: str) -> Resource:
        if resource_id not in self._resources:
            raise KeyError(f"Unknown resource: {resource_id}")
        return self._resources[resource_id]

    def get_allocations(self, resource_id: str | None = None) -> list[Allocation]:
        if resource_id is not None:
            if resource_id not in self._resources:
                raise KeyError(f"Unknown resource: {resource_id}")
            result = list(self._allocations[resource_id])
        else:
            result = list(self._by_request_id.values())
        result.sort(key=lambda a: (a.start, a.end, a.request_id))
        return result

    def available_units(self, resource_id: str, start: int, end: int) -> int:
        if resource_id not in self._resources:
            raise KeyError(f"Unknown resource: {resource_id}")
        if start < 0 or end <= start:
            raise ValueError("Invalid time window")

        resource = self._resources[resource_id]
        overlapping = [
            a for a in self._allocations[resource_id] if a.overlaps(start, end)
        ]
        if not overlapping:
            return resource.total_units

        max_used = 0
        for t in range(start, end):
            used = sum(a.units for a in overlapping if a.start <= t < a.end)
            if used > max_used:
                max_used = used
        return resource.total_units - max_used

    def allocate(self, request: ReservationRequest) -> Allocation | None:
        if request.request_id in self._by_request_id:
            raise ValueError(f"Duplicate request_id: {request.request_id}")

        if request.preferred_resource_id is not None:
            if request.preferred_resource_id not in self._resources:
                raise KeyError(f"Unknown resource: {request.preferred_resource_id}")
            res = self._resources[request.preferred_resource_id]
            if res.category != request.category:
                raise ValueError("Resource category mismatch")
            candidates = [res]
        else:
            candidates = [
                r for r in self._resources.values() if r.category == request.category
            ]

        min_required = request.min_units if request.min_units is not None else request.units
        scored_candidates: list[tuple[int, int, str, Resource, int]] = []

        for res in candidates:
            avail = self.available_units(res.resource_id, request.start, request.end)
            if avail >= min_required:
                alloc_units = min(request.units, avail)
                leftover = avail - alloc_units
                scored_candidates.append(
                    (-alloc_units, leftover, res.resource_id, res, alloc_units)
                )

        if not scored_candidates:
            return None

        scored_candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        _, _, _, best_resource, chosen_units = scored_candidates[0]

        alloc = Allocation(
            request_id=request.request_id,
            resource_id=best_resource.resource_id,
            category=request.category,
            start=request.start,
            end=request.end,
            priority=request.priority,
            units=chosen_units,
        )
        self._allocations[best_resource.resource_id].append(alloc)
        self._by_request_id[request.request_id] = alloc
        return alloc

    def release(self, request_id: str, units: int | None = None) -> Allocation | None:
        if request_id not in self._by_request_id:
            raise KeyError(f"Unknown request_id: {request_id}")

        current = self._by_request_id[request_id]
        if units is None or units == current.units:
            self._by_request_id.pop(request_id)
            self._allocations[current.resource_id].remove(current)
            return current

        if units < 1 or units > current.units:
            raise ValueError("Invalid units to release")

        updated = Allocation(
            request_id=current.request_id,
            resource_id=current.resource_id,
            category=current.category,
            start=current.start,
            end=current.end,
            priority=current.priority,
            units=current.units - units,
        )
        self._by_request_id[request_id] = updated
        res_list = self._allocations[current.resource_id]
        idx = res_list.index(current)
        res_list[idx] = updated
        return updated

=== FILE: ref/models.py ===
from dataclasses import dataclass


@dataclass(frozen=True)
class Resource:
    resource_id: str
    category: str
    total_units: int

    def __post_init__(self) -> None:
        if self.total_units < 1:
            raise ValueError("total_units must be >= 1")


@dataclass(frozen=True)
class ReservationRequest:
    request_id: str
    category: str
    start: int
    end: int
    priority: int = 0
    units: int = 1
    min_units: int | None = None
    preferred_resource_id: str | None = None

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Invalid time range")
        if self.units < 1:
            raise ValueError("units must be >= 1")
        resolved_min = self.units if self.min_units is None else self.min_units
        object.__setattr__(self, "min_units", resolved_min)
        if resolved_min < 1 or resolved_min > self.units:
            raise ValueError("min_units must satisfy 1 <= min_units <= units")


@dataclass(frozen=True)
class Allocation:
    request_id: str
    resource_id: str
    category: str
    start: int
    end: int
    priority: int
    units: int

    def overlaps(self, start: int, end: int) -> bool:
        return self.start < end and start < self.end

    def duration(self) -> int:
        return self.end - self.start

    def unit_hours(self) -> int:
        return self.duration() * self.units

=== FILE: ref/service.py ===
from allocator import ResourceAllocator
from models import Allocation, ReservationRequest, Resource


class BookingService:
    def __init__(self, allocator: ResourceAllocator | None = None) -> None:
        self.allocator = allocator if allocator is not None else ResourceAllocator()

    def register_resource(
        self, resource_id: str, category: str, total_units: int
    ) -> Resource:
        res = Resource(
            resource_id=resource_id, category=category, total_units=total_units
        )
        self.allocator.add_resource(res)
        return res

    def submit_batch(
        self, requests: list[ReservationRequest]
    ) -> dict[str, Allocation | None]:
        seen_ids: set[str] = set()
        existing_ids = {a.request_id for a in self.allocator.get_allocations()}
        for req in requests:
            if req.request_id in seen_ids or req.request_id in existing_ids:
                raise ValueError(f"Duplicate request_id in batch: {req.request_id}")
            seen_ids.add(req.request_id)

        ordered = sorted(
            requests,
            key=lambda r: (
                -r.priority,
                r.start,
                -((r.end - r.start) * r.units),
                r.request_id,
            ),
        )
        results: dict[str, Allocation | None] = {}
        for req in ordered:
            results[req.request_id] = self.allocator.allocate(req)
        return results

    def cancel_or_reduce(self, request_id: str, units: int | None = None) -> bool:
        try:
            self.allocator.release(request_id, units)
            return True
        except KeyError:
            return False

    def utilization_report(
        self, category: str, window_start: int, window_end: int
    ) -> dict[str, float]:
        if window_start < 0 or window_end <= window_start:
            raise ValueError("Invalid window")

        resources = [
            self.allocator.get_resource(rid)
            for rid in self._resource_ids_by_category(category)
        ]
        duration = window_end - window_start
        total_capacity = sum(r.total_units * duration for r in resources)

        category_allocs: list[Allocation] = []
        allocated = 0
        for r in resources:
            for alloc in self.allocator.get_allocations(r.resource_id):
                if alloc.overlaps(window_start, window_end):
                    category_allocs.append(alloc)
                    overlap_start = max(alloc.start, window_start)
                    overlap_end = min(alloc.end, window_end)
                    allocated += (overlap_end - overlap_start) * alloc.units

        peak = 0
        if category_allocs:
            for t in range(window_start, window_end):
                concurrent = sum(
                    a.units for a in category_allocs if a.start <= t < a.end
                )
                if concurrent > peak:
                    peak = concurrent

        rate = allocated / total_capacity if total_capacity > 0 else 0.0
        return {
            "total_capacity_unit_hours": float(total_capacity),
            "allocated_unit_hours": float(allocated),
            "utilization_rate": float(rate),
            "peak_concurrent_units": float(peak),
        }

    def reschedule(
        self,
        request_id: str,
        new_start: int,
        new_end: int,
        new_units: int | None = None,
    ) -> Allocation:
        all_allocs = {a.request_id: a for a in self.allocator.get_allocations()}
        if request_id not in all_allocs:
            raise KeyError(f"Unknown request_id: {request_id}")

        original = all_allocs[request_id]
        target_units = original.units if new_units is None else new_units

        if new_start < 0 or new_end <= new_start or target_units < 1:
            raise ValueError("Invalid reschedule parameters")

        self.allocator.release(request_id)

        same_res_req = ReservationRequest(
            request_id=request_id,
            category=original.category,
            start=new_start,
            end=new_end,
            priority=original.priority,
            units=target_units,
            min_units=target_units,
            preferred_resource_id=original.resource_id,
        )
        new_alloc = self.allocator.allocate(same_res_req)
        if new_alloc is not None:
            return new_alloc

        any_res_req = ReservationRequest(
            request_id=request_id,
            category=original.category,
            start=new_start,
            end=new_end,
            priority=original.priority,
            units=target_units,
            min_units=target_units,
            preferred_resource_id=None,
        )
        new_alloc = self.allocator.allocate(any_res_req)
        if new_alloc is not None:
            return new_alloc

        rollback_req = ReservationRequest(
            request_id=original.request_id,
            category=original.category,
            start=original.start,
            end=original.end,
            priority=original.priority,
            units=original.units,
            min_units=original.units,
            preferred_resource_id=original.resource_id,
        )
        restored = self.allocator.allocate(rollback_req)
        if restored is None:
            raise RuntimeError("Critical failure during rollback")
        raise RuntimeError(f"Could not reschedule request {request_id}")

    def _resource_ids_by_category(self, category: str) -> list[str]:
        all_allocs = self.allocator.get_allocations()
        seen: set[str] = set()
        for a in all_allocs:
            if a.category == category:
                seen.add(a.resource_id)
        for rid, res in getattr(self.allocator, "_resources", {}).items():
            if res.category == category:
                seen.add(rid)
        return sorted(seen)

=== FILE: tests/test_hidden.py ===
import unittest
from models import Allocation, ReservationRequest, Resource
from allocator import ResourceAllocator
from service import BookingService


class TestMultiFileReservation(unittest.TestCase):
    def test_01_models_validation_and_defaults(self) -> None:
        r = ReservationRequest(request_id="req1", category="gpu", start=2, end=5, units=4)
        self.assertEqual(r.units, 4)
        self.assertEqual(r.min_units, 4)
        self.assertIsNone(r.preferred_resource_id)

        r2 = ReservationRequest(
            request_id="req2",
            category="gpu",
            start=0,
            end=1,
            units=4,
            min_units=2,
            preferred_resource_id="resA",
        )
        self.assertEqual(r2.min_units, 2)
        self.assertEqual(r2.preferred_resource_id, "resA")

        with self.assertRaises(ValueError):
            ReservationRequest(request_id="bad1", category="gpu", start=-1, end=3)
        with self.assertRaises(ValueError):
            ReservationRequest(request_id="bad2", category="gpu", start=3, end=3)
        with self.assertRaises(ValueError):
            ReservationRequest(request_id="bad3", category="gpu", start=0, end=3, units=0)
        with self.assertRaises(ValueError):
            ReservationRequest(
                request_id="bad4", category="gpu", start=0, end=3, units=3, min_units=0
            )
        with self.assertRaises(ValueError):
            ReservationRequest(
                request_id="bad5", category="gpu", start=0, end=3, units=3, min_units=4
            )
        with self.assertRaises(ValueError):
            Resource(resource_id="r0", category="gpu", total_units=0)

    def test_02_allocation_unit_hours(self) -> None:
        alloc = Allocation(
            request_id="a1",
            resource_id="res1",
            category="cpu",
            start=3,
            end=8,
            priority=1,
            units=6,
        )
        self.assertEqual(alloc.duration(), 5)
        self.assertEqual(alloc.unit_hours(), 30)
        self.assertTrue(alloc.overlaps(0, 4))
        self.assertFalse(alloc.overlaps(0, 3))
        self.assertFalse(alloc.overlaps(8, 10))

    def test_03_available_units_multi_unit_overlap(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("r1", "gpu", 10))

        alloc.allocate(ReservationRequest("q1", "gpu", 2, 6, units=4))
        alloc.allocate(ReservationRequest("q2", "gpu", 4, 8, units=3))

        self.assertEqual(alloc.available_units("r1", 0, 2), 10)
        self.assertEqual(alloc.available_units("r1", 2, 4), 6)
        self.assertEqual(alloc.available_units("r1", 4, 6), 3)
        self.assertEqual(alloc.available_units("r1", 6, 8), 7)
        self.assertEqual(alloc.available_units("r1", 0, 10), 3)

        with self.assertRaises(KeyError):
            alloc.available_units("unknown", 0, 5)
        with self.assertRaises(ValueError):
            alloc.available_units("r1", 5, 5)
        with self.assertRaises(ValueError):
            alloc.available_units("r1", -1, 5)

    def test_04_allocate_best_fit_and_tie_breaking(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("res_c", "gpu", 8))
        alloc.add_resource(Resource("res_b", "gpu", 6))
        alloc.add_resource(Resource("res_a", "gpu", 6))

        # Request 5 units (min 5):
        # res_c has avail=8 -> alloc=5, leftover=3
        # res_b has avail=6 -> alloc=5, leftover=1
        # res_a has avail=6 -> alloc=5, leftover=1
        # Tie break between res_a and res_b -> res_a
        res1 = alloc.allocate(ReservationRequest("req1", "gpu", 0, 5, units=5))
        self.assertIsNotNone(res1)
        assert res1 is not None
        self.assertEqual(res1.resource_id, "res_a")
        self.assertEqual(res1.units, 5)

        # Next request for 5 units on [0, 5]:
        # res_a has avail=1, res_b has avail=6, res_c has avail=8 -> chooses res_b
        res2 = alloc.allocate(ReservationRequest("req2", "gpu", 0, 5, units=5))
        self.assertIsNotNone(res2)
        assert res2 is not None
        self.assertEqual(res2.resource_id, "res_b")

    def test_05_allocate_partial_units_priority(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("r_small", "gpu", 5))
        alloc.add_resource(Resource("r_med", "gpu", 7))

        # Request wants 8 units, min_units=4
        # r_small can give 5 (leftover 0), r_med can give 7 (leftover 0)
        # Larger alloc_units wins -> r_med with 7 units
        res = alloc.allocate(
            ReservationRequest("req1", "gpu", 0, 4, units=8, min_units=4)
        )
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.resource_id, "r_med")
        self.assertEqual(res.units, 7)

        # Now r_med has 0 avail, r_small has 5 avail.
        # Request wants 8 units, min_units=6 -> neither can satisfy -> None
        res_fail = alloc.allocate(
            ReservationRequest("req2", "gpu", 0, 4, units=8, min_units=6)
        )
        self.assertIsNone(res_fail)

        # Request wants 8 units, min_units=5 -> r_small gives 5
        res_ok = alloc.allocate(
            ReservationRequest("req3", "gpu", 0, 4, units=8, min_units=5)
        )
        self.assertIsNotNone(res_ok)
        assert res_ok is not None
        self.assertEqual(res_ok.resource_id, "r_small")
        self.assertEqual(res_ok.units, 5)

    def test_06_preferred_resource_validation(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("gpu1", "gpu", 4))
        alloc.add_resource(Resource("cpu1", "cpu", 4))

        with self.assertRaises(KeyError):
            alloc.allocate(
                ReservationRequest(
                    "r1", "gpu", 0, 2, preferred_resource_id="nonexistent"
                )
            )

        with self.assertRaises(ValueError):
            alloc.allocate(
                ReservationRequest("r2", "gpu", 0, 2, preferred_resource_id="cpu1")
            )

        res = alloc.allocate(
            ReservationRequest(
                "r3", "gpu", 0, 2, units=4, min_units=2, preferred_resource_id="gpu1"
            )
        )
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.resource_id, "gpu1")
        self.assertEqual(res.units, 4)

        # Duplicate request_id
        with self.assertRaises(ValueError):
            alloc.allocate(ReservationRequest("r3", "gpu", 2, 4))

    def test_07_partial_and_full_release(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("r1", "gpu", 10))
        alloc.allocate(ReservationRequest("req1", "gpu", 0, 5, units=6))

        # Invalid release amounts
        with self.assertRaises(ValueError):
            alloc.release("req1", 0)
        with self.assertRaises(ValueError):
            alloc.release("req1", -2)
        with self.assertRaises(ValueError):
            alloc.release("req1", 7)

        # Ensure state unchanged after failed release
        self.assertEqual(alloc.available_units("r1", 0, 5), 4)

        # Partial release of 2 units -> 4 units remain
        updated = alloc.release("req1", 2)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.units, 4)
        self.assertEqual(alloc.available_units("r1", 0, 5), 6)
        self.assertEqual(len(alloc.get_allocations("r1")), 1)
        self.assertEqual(alloc.get_allocations("r1")[0].units, 4)

        # Release exact remaining units -> full removal
        removed = alloc.release("req1", 4)
        self.assertIsNotNone(removed)
        assert removed is not None
        self.assertEqual(removed.units, 4)
        self.assertEqual(alloc.available_units("r1", 0, 5), 10)
        self.assertEqual(len(alloc.get_allocations("r1")), 0)

        with self.assertRaises(KeyError):
            alloc.release("req1")

    def test_08_release_none_removes_all(self) -> None:
        alloc = ResourceAllocator()
        alloc.add_resource(Resource("r1", "gpu", 10))
        alloc.allocate(ReservationRequest("req1", "gpu", 0, 5, units=6))

        removed = alloc.release("req1", None)
        self.assertIsNotNone(removed)
        assert removed is not None
        self.assertEqual(removed.units, 6)
        self.assertEqual(len(alloc.get_allocations()), 0)

    def test_09_submit_batch_ordering_and_validation(self) -> None:
        svc = BookingService()
        svc.register_resource("r1", "gpu", 4)

        # Duplicate in batch
        batch_dup = [
            ReservationRequest("dup", "gpu", 0, 2, units=2),
            ReservationRequest("dup", "gpu", 2, 4, units=2),
        ]
        with self.assertRaises(ValueError):
            svc.submit_batch(batch_dup)
        self.assertEqual(len(svc.allocator.get_allocations()), 0)

        # Sorting test:
        # Same priority=1, same start=0.
        # req_short_many: duration=2, units=4 -> unit_hours = 8
        # req_long_few: duration=5, units=1 -> unit_hours = 5
        # req_short_many should be processed first and take all 4 units on [0, 2],
        # causing req_long_few (needs 1 unit on [0, 5]) to fail!
        reqs = [
            ReservationRequest("req_long_few", "gpu", 0, 5, priority=1, units=1),
            ReservationRequest("req_short_many", "gpu", 0, 2, priority=1, units=4),
        ]
        results = svc.submit_batch(reqs)
        self.assertIsNotNone(results["req_short_many"])
        self.assertIsNone(results["req_long_few"])

        # Existing request_id conflict in subsequent batch
        with self.assertRaises(ValueError):
            svc.submit_batch(
                [
                    ReservationRequest("new_one", "gpu", 5, 6, units=1),
                    ReservationRequest("req_short_many", "gpu", 6, 7, units=1),
                ]
            )
        # Ensure 'new_one' was not allocated due to atomic pre-check
        self.assertEqual(len(svc.allocator.get_allocations()), 1)

    def test_10_cancel_or_reduce(self) -> None:
        svc = BookingService()
        svc.register_resource("r1", "gpu", 5)
        svc.submit_batch([ReservationRequest("b1", "gpu", 0, 4, units=5)])

        self.assertFalse(svc.cancel_or_reduce("unknown_id"))
        with self.assertRaises(ValueError):
            svc.cancel_or_reduce("b1", units=6)

        self.assertTrue(svc.cancel_or_reduce("b1", units=3))
        self.assertEqual(svc.allocator.available_units("r1", 0, 4), 3)

        self.assertTrue(svc.cancel_or_reduce("b1"))
        self.assertEqual(svc.allocator.available_units("r1", 0, 4), 5)
        self.assertFalse(svc.cancel_or_reduce("b1"))

    def test_11_utilization_report_with_units_and_peak(self) -> None:
        svc = BookingService()
        svc.register_resource("g1", "gpu", 4)
        svc.register_resource("g2", "gpu", 6)
        svc.register_resource("c1", "cpu", 10)

        # Total gpu capacity over [2, 8] (duration 6) = (4 + 6) * 6 = 60.0
        svc.submit_batch(
            [
                # Overlaps [2, 8] on [2, 5] -> 3 hours * 3 units = 9
                ReservationRequest("q1", "gpu", 0, 5, units=3, preferred_resource_id="g1"),
                # Overlaps [2, 8] on [4, 7] -> 3 hours * 5 units = 15
                ReservationRequest("q2", "gpu", 4, 7, units=5, preferred_resource_id="g2"),
                # Different category
                ReservationRequest("q3", "cpu", 2, 8, units=10),
            ]
        )
        # Peak concurrent in [2, 8]:
        # t=2,3: q1(3) = 3
        # t=4: q1(3) + q2(5) = 8
        # t=5,6: q2(5) = 5
        # t=7: 0
        report = svc.utilization_report("gpu", 2, 8)
        self.assertAlmostEqual(report["total_capacity_unit_hours"], 60.0)
        self.assertAlmostEqual(report["allocated_unit_hours"], 24.0)
        self.assertAlmostEqual(report["utilization_rate"], 24.0 / 60.0)
        self.assertAlmostEqual(report["peak_concurrent_units"], 8.0)

        # Empty category report
        empty_rep = svc.utilization_report("tpu", 0, 10)
        self.assertEqual(empty_rep["total_capacity_unit_hours"], 0.0)
        self.assertEqual(empty_rep["allocated_unit_hours"], 0.0)
        self.assertEqual(empty_rep["utilization_rate"], 0.0)
        self.assertEqual(empty_rep["peak_concurrent_units"], 0.0)

    def test_12_reschedule_same_resource(self) -> None:
        svc = BookingService()
        svc.register_resource("g1", "gpu", 4)
        svc.register_resource("g2", "gpu", 4)

        svc.submit_batch(
            [
                ReservationRequest(
                    "req1", "gpu", 0, 4, priority=2, units=3, preferred_resource_id="g2"
                )
            ]
        )
        # Reschedule overlapping with its own previous time on g2, and increase units to 4
        new_alloc = svc.reschedule("req1", 2, 6, new_units=4)
        self.assertEqual(new_alloc.resource_id, "g2")
        self.assertEqual(new_alloc.start, 2)
        self.assertEqual(new_alloc.end, 6)
        self.assertEqual(new_alloc.units, 4)
        self.assertEqual(new_alloc.priority, 2)
        self.assertEqual(svc.allocator.available_units("g2", 0, 2), 4)

    def test_13_reschedule_fallback_to_other_resource(self) -> None:
        svc = BookingService()
        svc.register_resource("g1", "gpu", 4)
        svc.register_resource("g2", "gpu", 6)

        svc.submit_batch(
            [
                ReservationRequest(
                    "req1", "gpu", 0, 4, priority=5, units=3, preferred_resource_id="g1"
                ),
                ReservationRequest(
                    "blocker", "gpu", 4, 8, priority=1, units=2, preferred_resource_id="g1"
                ),
            ]
        )
        # Reschedule req1 to [4, 8] keeping 3 units:
        # g1 only has 2 units free in [4, 8], so g1 fails -> falls back to g2
        moved = svc.reschedule("req1", 4, 8)
        self.assertEqual(moved.resource_id, "g2")
        self.assertEqual(moved.units, 3)
        self.assertEqual(moved.start, 4)
        self.assertEqual(moved.end, 8)
        self.assertEqual(moved.priority, 5)
        self.assertEqual(svc.allocator.available_units("g1", 0, 4), 4)

    def test_14_reschedule_rollback_on_failure(self) -> None:
        svc = BookingService()
        svc.register_resource("g1", "gpu", 4)
        svc.register_resource("g2", "gpu", 4)

        # Partially allocated request (requested 4, min 2, got 3 on g1)
        svc.submit_batch(
            [
                ReservationRequest(
                    " occupy_g1", "gpu", 0, 4, priority=5, units=1, preferred_resource_id="g1"
                ),
                ReservationRequest(
                    "target", "gpu", 0, 4, priority=3, units=4, min_units=2, preferred_resource_id="g1"
                ),
                ReservationRequest(
                    "block_g1", "gpu", 5, 9, units=3, preferred_resource_id="g1"
                ),
                ReservationRequest(
                    "block_g2", "gpu", 5, 9, units=3, preferred_resource_id="g2"
                ),
            ]
        )
        orig = [a for a in svc.allocator.get_allocations() if a.request_id == "target"][0]
        self.assertEqual(orig.units, 3)

        # Try to reschedule "target" (3 units) to [5, 9] where both g1 and g2 only have 1 unit free.
        # Must fail with RuntimeError (no partial allocation allowed on reschedule) and restore original!
        with self.assertRaises(RuntimeError):
            svc.reschedule("target", 5, 9)

        restored = [
            a for a in svc.allocator.get_allocations() if a.request_id == "target"
        ][0]
        self.assertEqual(restored, orig)

    def test_15_reschedule_invalid_args_and_unknown_id(self) -> None:
        svc = BookingService()
        svc.register_resource("g1", "gpu", 4)
        svc.submit_batch([ReservationRequest("r1", "gpu", 2, 5, units=2)])

        with self.assertRaises(KeyError):
            svc.reschedule("unknown", 0, 2)

        with self.assertRaises(ValueError):
            svc.reschedule("r1", -1, 3)
        with self.assertRaises(ValueError):
            svc.reschedule("r1", 4, 4)
        with self.assertRaises(ValueError):
            svc.reschedule("r1", 0, 2, new_units=0)

        # Original allocation must still be intact
        allocs = svc.allocator.get_allocations("g1")
        self.assertEqual(len(allocs), 1)
        self.assertEqual(allocs[0].start, 2)
        self.assertEqual(allocs[0].end, 5)
        self.assertEqual(allocs[0].units, 2)


if __name__ == "__main__":
    unittest.main()

=== END ===
