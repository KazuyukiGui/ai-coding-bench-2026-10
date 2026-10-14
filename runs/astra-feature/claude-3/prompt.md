# 容量付き作業枠の分割予約

共有設備の予約を管理する `capacity_calendar.py` に、作業を複数の時間帯へ分割して予約する `CapacityCalendar.plan` を追加してください。既存の公開メソッドの挙動も維持してください。

Python 3.11 の標準ライブラリだけを使用してください。

## 時間と予約の表現

時間は非負整数です。区間 `(start, end)` は半開区間 `[start, end)` を表します。整数 `t` の時間単位とは `[t, t + 1)` です。

設備には正整数の容量があります。予約は、その全区間で一定の正整数 `units` を消費します。同じ設備の予約が重なる場合、消費量を合計します。どの時間単位でも設備の容量を超えてはいけません。

予約の公開表現は、次のキーだけを持つ辞書です。

```python
{
    "id": "job_a",
    "resource": "machine_a",
    "units": 2,
    "segments": [(0, 3), (7, 10)],
}
```

`segments` は開始時刻順のリストで、要素は整数2個のタプルです。

名前・予約IDは空でない文字列です。空白だけの文字列も有効で、空白除去や大文字・小文字の変換は行いません。整数を要求する引数は `type(value) is int` を満たす必要があり、`bool` や浮動小数点数は無効です。

以下に示す入力条件への違反、存在しない設備・予約の参照、予約の重複、容量不足、分割予約を構成できない場合は、すべて `ValueError` にしてください。例外メッセージは問いません。失敗した公開メソッドは状態を変更してはいけません。

返される辞書やリストを呼び出し側が変更しても、内部状態や別の返却値に影響しないようにしてください。

## 維持する既存API

### `CapacityCalendar()`

設備も予約もない状態を作ります。

### `add_resource(name, capacity)`

設備を追加し、`None` を返します。名前の重複は無効です。`capacity` は正整数です。追加済み設備の容量変更や削除は扱いません。

### `book(booking_id, resource, start, end, units=1)`

単一区間の予約を追加し、その予約の公開表現を返します。

- 予約IDは、全設備を通して一意です。
- 設備は登録済みでなければなりません。
- `start` と `end` は整数で、`0 <= start < end` が必要です。
- `units` は正整数です。
- 区間全体で容量を確保できる必要があります。
- `segments` は `[(start, end)]` になります。

### `cancel(booking_id)`

予約を削除し、削除した予約の公開表現を返します。分割予約の場合も全区間を削除します。

### `get(booking_id)`

予約の公開表現を返します。

### `bookings(resource=None)`

予約の公開表現のリストを返します。予約IDに対する Python の通常の文字列昇順で並べます。

`resource` が `None` の場合は全設備が対象です。それ以外の場合は登録済み設備名を指定し、その設備の予約だけを返します。

### `free_spans(resource, start, end, units=1)`

指定範囲内で、さらに `units` を消費できる最大の連続区間を開始時刻順で返します。返り値はタプルのリストです。

設備・時刻・`units` の入力条件は `book` と同じです。ただし、確保できる区間がなければ `[]` を返します。`units` が設備容量より大きい場合も `[]` です。

消費量が変化する時刻が途中にあっても、指定された `units` を引き続き確保できれば同じ区間にまとめます。隣接する空き区間は必ず結合します。

既存APIの時間範囲に上限はありません。

## 追加するAPI

```python
plan(requests, replace=())
```

複数の分割予約を、リスト順に計画して一括反映します。返り値は、新しく作成した予約の公開表現を `requests` と同じ順序で並べたリストです。

### 引数

`requests` は `list` 型でなければなりません（タプル・辞書・`None` など `list` 以外は無効で `ValueError`）。各要素は辞書です。必須キーは次の5個です。

| キー | 意味 |
|---|---|
| `id` | 予約ID |
| `resource` | 登録済みの設備名 |
| `start` | 計画範囲の開始 |
| `end` | 計画範囲の終了 |
| `duration` | 確保する時間単位の総数 |

次の3個のキーは省略できます。

| キー | 既定値 | 意味 |
|---|---:|---|
| `units` | 1 | 各時間単位で消費する容量 |
| `min_part` | 1 | 各分割区間の最小長 |
| `max_parts` | 1 | 分割区間数の上限 |

これ以外のキーは無効です。

- `start` と `end` は整数で、`0 <= start < end` が必要です。
- **このAPIだけ**、`end - start <= 120` に制限します。開始時刻そのものに上限はありません。
- `duration` は整数で、`1 <= duration <= end - start` が必要です。
- `units` は正整数です。
- `min_part` は整数で、`1 <= min_part <= duration` が必要です。
- `max_parts` は整数で、`1 <= max_parts <= 6` が必要です。

`replace` は、削除する既存予約のIDを並べたリストまたはタプルです。IDの重複は無効で、各IDは呼び出し開始時点に存在しなければなりません。

### 一括更新

次の操作を仮の状態に対して行い、すべて成功した場合だけ反映します。

1. `replace` に指定された既存予約を、すべて削除する。
2. `requests` の先頭から順に分割予約を作成する。先に作成した予約は、後続の予約が利用できる容量を消費する。
3. すべて成功したら、削除と追加を一括反映する。

途中で入力条件への違反や計画不能が判明した場合、予約の削除も追加も一切反映してはいけません。

新しい予約IDは、`requests` 内で重複してはいけません。また、`replace` による削除後に残る既存予約のIDとも重複してはいけません。削除対象のIDを新しい予約で再利用でき、その設備を変更することもできます。削除対象すべてを再利用する必要はありません。

空の `requests` は有効です。この場合も `replace` による削除を反映し、`[]` を返します。入力のリストや辞書は変更しないでください。

### 1件の予約の選び方

各要求について、その時点の仮の状態を使い、次の条件をすべて満たす予約を選びます。

- 全区間が `[start, end)` に含まれる。
- 区間端点は整数である。
- 各時間単位で要求された `units` を確保できる。
- 区間の長さの合計が、ちょうど `duration` である。
- 各区間の長さが `min_part` 以上である。最後の区間も例外ではない。
- 区間数が `max_parts` 以下である。
- 区間は開始時刻順で、重ならない。接する区間は結合した状態で扱い、返却する。したがって、複数区間の場合、前区間の終了は次区間の開始より厳密に小さい。

候補が複数ある場合、**確保する時間単位の開始時刻を昇順に並べたタプルが辞書式順序で最小**になるものを選びます。例えば `[(0, 2), (5, 7)]` の比較用タプルは `(0, 1, 5, 6)` です。すべての候補のタプル長は `duration` なので、この規則で予約は一意に決まります。

例として、利用可能な最大連続区間が `[(0, 5), (7, 11)]`、`duration=6`、`min_part=3`、`max_parts=2` の場合、結果は `[(0, 3), (7, 10)]` です。最初に5単位を取ると、残り1単位が最小長を満たせません。

後続要求の成功のために、先行要求の選択をやり直してはいけません。例えば空の容量1の設備で、最初に範囲 `[0, 4)`・長さ2、次に範囲 `[0, 2)`・長さ2の要求を処理すると、最初は `[0, 2)` を選ぶため、一括更新全体が失敗します。

追加後も、`get`、`cancel`、`bookings`、`book`、`free_spans` は分割予約を含めて正しく動作する必要があります。

添付ファイル:
=== FILE: capacity_calendar.py ===
"""Integer-time reservations for resources with fixed capacities."""


class CapacityCalendar:
    """Keep reservations in memory and expose independent snapshots."""

    def __init__(self):
        self._capacities = {}
        self._bookings = {}

    @staticmethod
    def _name(value):
        if not isinstance(value, str) or not value:
            raise ValueError("expected a nonempty string")
        return value

    @staticmethod
    def _positive(value):
        if type(value) is not int or value <= 0:
            raise ValueError("expected a positive integer")
        return value

    @staticmethod
    def _interval(start, end):
        if type(start) is not int or type(end) is not int:
            raise ValueError("expected integer endpoints")
        if start < 0 or start >= end:
            raise ValueError("invalid interval")

    def _resource(self, resource):
        self._name(resource)
        if resource not in self._capacities:
            raise ValueError("unknown resource")
        return resource

    def _query(self, resource, start, end, units):
        self._resource(resource)
        self._interval(start, end)
        self._positive(units)

    @staticmethod
    def _snapshot(booking_id, record):
        resource, units, segments = record
        return {
            "id": booking_id,
            "resource": resource,
            "units": units,
            "segments": list(segments),
        }

    def _available(self, resource, start, end, units, records):
        """Sweep clipped usage events and merge adjacent usable spans."""
        events = {start: 0, end: 0}
        for stored_resource, stored_units, segments in records.values():
            if stored_resource != resource:
                continue
            for left, right in segments:
                left = max(left, start)
                right = min(right, end)
                if left >= right:
                    continue
                events[left] = events.get(left, 0) + stored_units
                events[right] = events.get(right, 0) - stored_units

        points = sorted(events)
        usage = 0
        spans = []
        capacity = self._capacities[resource]
        for left, right in zip(points, points[1:]):
            usage += events[left]
            if capacity - usage < units:
                continue
            if spans and spans[-1][1] == left:
                spans[-1] = (spans[-1][0], right)
            else:
                spans.append((left, right))
        return spans

    def add_resource(self, name, capacity):
        """Add a resource; existing capacities cannot be changed."""
        self._name(name)
        self._positive(capacity)
        if name in self._capacities:
            raise ValueError("duplicate resource")
        self._capacities[name] = capacity

    def book(self, booking_id, resource, start, end, units=1):
        """Reserve one complete interval, or leave the calendar unchanged."""
        self._name(booking_id)
        self._query(resource, start, end, units)
        if booking_id in self._bookings:
            raise ValueError("duplicate booking")
        spans = self._available(
            resource, start, end, units, self._bookings
        )
        if spans != [(start, end)]:
            raise ValueError("insufficient capacity")
        record = (resource, units, ((start, end),))
        self._bookings[booking_id] = record
        return self._snapshot(booking_id, record)

    def cancel(self, booking_id):
        """Remove a reservation and return its former contents."""
        self._name(booking_id)
        if booking_id not in self._bookings:
            raise ValueError("unknown booking")
        record = self._bookings.pop(booking_id)
        return self._snapshot(booking_id, record)

    def get(self, booking_id):
        """Return an independent public representation of a reservation."""
        self._name(booking_id)
        if booking_id not in self._bookings:
            raise ValueError("unknown booking")
        return self._snapshot(booking_id, self._bookings[booking_id])

    def bookings(self, resource=None):
        """Return snapshots ordered by booking ID."""
        if resource is not None:
            self._resource(resource)
        result = []
        for booking_id in sorted(self._bookings):
            record = self._bookings[booking_id]
            if resource is None or record[0] == resource:
                result.append(self._snapshot(booking_id, record))
        return result

    def free_spans(self, resource, start, end, units=1):
        """Return maximal intervals able to accept the requested load."""
        self._query(resource, start, end, units)
        return self._available(
            resource, start, end, units, self._bookings
        )
=== END ===

答え方: 次のファイルの全体（変更しないファイルは不要）を、説明なしで、次の形式だけで返してください。各ファイルは「=== FILE: パス ===」の行で始め、最後に「=== END ===」の行を置きます。ツールは使えません。Python 3.11・標準ライブラリのみ。
返すファイル: capacity_calendar.py
