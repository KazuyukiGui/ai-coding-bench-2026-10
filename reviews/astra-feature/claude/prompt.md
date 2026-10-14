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
=== FILE: given/capacity_calendar.py ===
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

=== FILE: prompt.md ===
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

`requests` はリストで、各要素は辞書です。必須キーは次の5個です。

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

=== FILE: ref/capacity_calendar.py ===
"""Integer-time reservations with atomic, split booking plans."""

from functools import lru_cache


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

    @staticmethod
    def _choose(spans, duration, min_part, max_parts):
        """Find the lexicographically earliest feasible selection.

        Within one maximal available span, shifting all selected units
        to a single prefix cannot hurt feasibility and improves or keeps
        their lexicographic order. Thus each span contributes either
        nothing or one prefix of at least min_part units.
        """
        lengths = tuple(right - left for left, right in spans)

        @lru_cache(maxsize=None)
        def possible(index, remaining, budget):
            if remaining == 0:
                return True
            if index == len(spans) or budget == 0:
                return False
            if remaining < min_part:
                return False
            upper = min(lengths[index], remaining)
            for take in range(upper, min_part - 1, -1):
                if possible(index + 1, remaining - take, budget - 1):
                    return True
            return possible(index + 1, remaining, budget)

        if not possible(0, duration, max_parts):
            return None

        result = []
        remaining = duration
        budget = max_parts
        for index, (left, right) in enumerate(spans):
            if remaining == 0:
                break
            upper = min(right - left, remaining)
            for take in range(upper, min_part - 1, -1):
                if possible(index + 1, remaining - take, budget - 1):
                    result.append((left, left + take))
                    remaining -= take
                    budget -= 1
                    break
        return result

    def plan(self, requests, replace=()):
        """Plan in input order and commit only if every request succeeds."""
        if not isinstance(requests, list):
            raise ValueError("requests must be a list")
        if not isinstance(replace, (list, tuple)):
            raise ValueError("replace must be a list or tuple")

        removed = set()
        for booking_id in replace:
            self._name(booking_id)
            if booking_id in removed:
                raise ValueError("duplicate replacement")
            if booking_id not in self._bookings:
                raise ValueError("unknown replacement")
            removed.add(booking_id)

        # Records contain only immutable values, so a shallow copy suffices.
        working = dict(self._bookings)
        for booking_id in removed:
            del working[booking_id]

        required = {"id", "resource", "start", "end", "duration"}
        allowed = required | {"units", "min_part", "max_parts"}
        result = []
        for request in requests:
            if not isinstance(request, dict):
                raise ValueError("request must be a dictionary")
            if not required <= request.keys() <= allowed:
                raise ValueError("invalid request keys")

            booking_id = self._name(request["id"])
            resource = request["resource"]
            start = request["start"]
            end = request["end"]
            units = request.get("units", 1)
            self._query(resource, start, end, units)
            if end - start > 120:
                raise ValueError("planning window is too wide")
            if booking_id in working:
                raise ValueError("duplicate booking")

            duration = self._positive(request["duration"])
            min_part = self._positive(request.get("min_part", 1))
            max_parts = self._positive(request.get("max_parts", 1))
            if duration > end - start:
                raise ValueError("duration exceeds the window")
            if min_part > duration or max_parts > 6:
                raise ValueError("invalid part limits")

            spans = self._available(
                resource, start, end, units, working
            )
            segments = self._choose(
                spans, duration, min_part, max_parts
            )
            if segments is None:
                raise ValueError("no feasible split reservation")

            record = (resource, units, tuple(segments))
            working[booking_id] = record
            result.append(self._snapshot(booking_id, record))

        self._bookings = working
        return result

=== FILE: tests/test_hidden.py ===
import copy
import itertools
import unittest

from capacity_calendar import CapacityCalendar


def request(booking_id="new", resource="r", start=0, end=10,
            duration=3, **options):
    result = {
        "id": booking_id,
        "resource": resource,
        "start": start,
        "end": end,
        "duration": duration,
    }
    result.update(options)
    return result


def snapshot(booking_id, resource, units, segments):
    return {
        "id": booking_id,
        "resource": resource,
        "units": units,
        "segments": segments,
    }


def segments_of(ticks):
    result = []
    for tick in ticks:
        if result and result[-1][1] == tick:
            result[-1] = (result[-1][0], tick + 1)
        else:
            result.append((tick, tick + 1))
    return result


def brute_plan(available, duration, min_part, max_parts):
    """Enumerate actual selected time units, independently of the solver."""
    for ticks in itertools.combinations(available, duration):
        segments = segments_of(ticks)
        if len(segments) > max_parts:
            continue
        if all(right - left >= min_part for left, right in segments):
            return segments
    return None


class CalendarTests(unittest.TestCase):
    def make_calendar(self, capacity=1):
        calendar = CapacityCalendar()
        calendar.add_resource("r", capacity)
        return calendar

    def assert_failure_unchanged(self, calendar, operation):
        before = calendar.bookings()
        with self.assertRaises(ValueError):
            operation()
        self.assertEqual(calendar.bookings(), before)

    def test_01_empty_and_resource_registration(self):
        calendar = CapacityCalendar()
        self.assertEqual(calendar.bookings(), [])
        self.assertIsNone(calendar.add_resource("r", 2))
        self.assertEqual(calendar.free_spans("r", 0, 4, 2), [(0, 4)])
        with self.assertRaises(ValueError):
            calendar.add_resource("r", 7)
        self.assertEqual(calendar.free_spans("r", 0, 4, 3), [])

    def test_02_original_book_get_cancel(self):
        calendar = self.make_calendar(3)
        expected = snapshot("a", "r", 2, [(2, 7)])
        self.assertEqual(calendar.book("a", "r", 2, 7, 2), expected)
        self.assertEqual(calendar.get("a"), expected)
        self.assertEqual(calendar.cancel("a"), expected)
        self.assertEqual(calendar.bookings(), [])
        with self.assertRaises(ValueError):
            calendar.get("a")

    def test_03_half_open_intervals(self):
        calendar = self.make_calendar()
        calendar.book("a", "r", 0, 3)
        calendar.book("b", "r", 3, 6)
        self.assertEqual(calendar.free_spans("r", 0, 8), [(6, 8)])
        self.assert_failure_unchanged(
            calendar, lambda: calendar.book("c", "r", 2, 4)
        )

    def test_04_capacity_and_clipped_queries(self):
        calendar = self.make_calendar(4)
        calendar.book("a", "r", 0, 8, 2)
        calendar.book("b", "r", 3, 5, 2)
        self.assertEqual(
            calendar.free_spans("r", 2, 7, 2), [(2, 3), (5, 7)]
        )
        self.assertEqual(calendar.free_spans("r", 3, 5), [])
        self.assertEqual(calendar.free_spans("r", 8, 9, 4), [(8, 9)])

    def test_05_merge_through_usage_changes(self):
        calendar = self.make_calendar(4)
        calendar.book("a", "r", 1, 4, 1)
        calendar.book("b", "r", 3, 7, 1)
        calendar.book("c", "r", 7, 9, 2)
        self.assertEqual(calendar.free_spans("r", 0, 10, 2), [(0, 10)])
        self.assertEqual(
            calendar.free_spans("r", 0, 10, 3),
            [(0, 3), (9, 10)],
        )

    def test_06_order_filter_and_literal_names(self):
        calendar = self.make_calendar(5)
        calendar.add_resource(" ", 1)
        calendar.book("あ", "r", 0, 1)
        calendar.book("a", "r", 0, 1)
        calendar.book("B", "r", 0, 1)
        calendar.book(" ", " ", 0, 1)
        self.assertEqual(
            [item["id"] for item in calendar.bookings()],
            [" ", "B", "a", "あ"],
        )
        self.assertEqual(
            [item["id"] for item in calendar.bookings("r")],
            ["B", "a", "あ"],
        )
        self.assertEqual(calendar.get(" ")["resource"], " ")

    def test_07_original_snapshots_are_independent(self):
        calendar = self.make_calendar()
        first = calendar.book("a", "r", 2, 5)
        second = calendar.get("a")
        first["segments"].append((7, 8))
        first["resource"] = "changed"
        second["segments"].clear()
        listed = calendar.bookings()
        listed[0]["segments"][0] = (0, 100)
        listed.clear()
        self.assertEqual(
            calendar.get("a"), snapshot("a", "r", 1, [(2, 5)])
        )
        free = calendar.free_spans("r", 0, 7)
        free.clear()
        self.assertEqual(calendar.free_spans("r", 0, 7), [(0, 2), (5, 7)])

    def test_08_original_invalid_inputs_are_atomic(self):
        calendar = self.make_calendar()
        calendar.book("old", "r", 0, 2)
        operations = [
            lambda: calendar.book("old", "r", 3, 4),
            lambda: calendar.book("", "r", 3, 4),
            lambda: calendar.book("x", "missing", 3, 4),
            lambda: calendar.book("x", "r", -1, 4),
            lambda: calendar.book("x", "r", 4, 4),
            lambda: calendar.book("x", "r", False, 4),
            lambda: calendar.book("x", "r", 3, 4.0),
            lambda: calendar.book("x", "r", 3, 4, True),
            lambda: calendar.book("x", "r", 3, 4, 0),
            lambda: calendar.cancel("missing"),
            lambda: calendar.get([]),
            lambda: calendar.bookings("missing"),
            lambda: calendar.free_spans("r", 2, 2),
            lambda: calendar.free_spans("r", 0, 5, False),
            lambda: calendar.add_resource("bad", True),
        ]
        for operation in operations:
            with self.subTest(operation=operation):
                self.assert_failure_unchanged(calendar, operation)

    def test_09_default_plan_is_earliest_contiguous(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 2, 4)
        result = calendar.plan([request(duration=3)])
        expected = snapshot("new", "r", 1, [(4, 7)])
        self.assertEqual(result, [expected])
        self.assertEqual(calendar.get("new"), expected)

    def test_10_split_uses_earliest_time_units(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 2, 4)
        result = calendar.plan([request(duration=5, max_parts=2)])
        self.assertEqual(result[0]["segments"], [(0, 2), (4, 7)])

    def test_11_shorten_first_part_for_minimum_tail(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 5, 7)
        result = calendar.plan([
            request(end=11, duration=6, min_part=3, max_parts=2)
        ])
        self.assertEqual(result[0]["segments"], [(0, 3), (7, 10)])

    def test_12_small_spans_are_skipped(self):
        calendar = self.make_calendar()
        calendar.book("b1", "r", 2, 4)
        calendar.book("b2", "r", 8, 9)
        result = calendar.plan([
            request(end=13, duration=6, min_part=3, max_parts=2)
        ])
        self.assertEqual(result[0]["segments"], [(4, 7), (9, 12)])

    def test_13_part_limit_can_force_skipping_earliest_span(self):
        calendar = self.make_calendar()
        calendar.book("b1", "r", 2, 3)
        calendar.book("b2", "r", 5, 6)
        result = calendar.plan([
            request(end=11, duration=7, max_parts=2)
        ])
        self.assertEqual(result[0]["segments"], [(0, 2), (6, 11)])

    def test_14_long_contiguous_span_is_one_part(self):
        calendar = self.make_calendar(3)
        calendar.book("b1", "r", 1, 3)
        calendar.book("b2", "r", 3, 5)
        result = calendar.plan([
            request(end=6, duration=6, units=2, min_part=6, max_parts=6)
        ])
        self.assertEqual(result[0]["segments"], [(0, 6)])

    def test_15_capacity_threshold_drives_split(self):
        calendar = self.make_calendar(3)
        calendar.book("background", "r", 0, 10, 1)
        calendar.book("block", "r", 2, 5, 1)
        result = calendar.plan([
            request(duration=6, units=2, max_parts=2)
        ])
        self.assertEqual(result[0]["segments"], [(0, 2), (5, 9)])
        self.assertEqual(calendar.free_spans("r", 0, 10, 2), [(9, 10)])
        self.assertEqual(calendar.free_spans("r", 0, 10), [(2, 5), (9, 10)])

    def test_16_lexicographic_choice_over_fewer_parts(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 1, 3)
        result = calendar.plan([
            request(end=8, duration=4, max_parts=2)
        ])
        self.assertEqual(result[0]["segments"], [(0, 1), (3, 6)])

    def test_17_batch_order_and_return_order(self):
        calendar = self.make_calendar()
        result = calendar.plan([
            request("z", end=8, duration=3),
            request("a", end=8, duration=2),
        ])
        self.assertEqual(
            result,
            [
                snapshot("z", "r", 1, [(0, 3)]),
                snapshot("a", "r", 1, [(3, 5)]),
            ],
        )
        self.assertEqual(
            [item["id"] for item in calendar.bookings()], ["a", "z"]
        )

    def test_18_no_backtracking_between_requests(self):
        calendar = self.make_calendar()
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan([
                request("a", end=4, duration=2),
                request("b", end=2, duration=2),
            ]),
        )
        self.assertEqual(calendar.free_spans("r", 0, 4), [(0, 4)])

    def test_19_all_replacements_removed_before_planning(self):
        calendar = self.make_calendar()
        calendar.book("old_a", "r", 0, 3)
        calendar.book("old_b", "r", 3, 6)
        result = calendar.plan(
            [request("old_a", end=6, duration=6)],
            replace=["old_b", "old_a"],
        )
        self.assertEqual(
            result, [snapshot("old_a", "r", 1, [(0, 6)])]
        )
        with self.assertRaises(ValueError):
            calendar.get("old_b")

    def test_20_replacement_can_move_resource(self):
        calendar = self.make_calendar()
        calendar.add_resource("s", 2)
        calendar.book("old", "r", 0, 5)
        result = calendar.plan(
            [request("old", resource="s", end=5, duration=4, units=2)],
            replace=("old",),
        )
        self.assertEqual(result, [snapshot("old", "s", 2, [(0, 4)])])
        self.assertEqual(calendar.free_spans("r", 0, 5), [(0, 5)])
        self.assertEqual(calendar.bookings("r"), [])

    def test_21_late_capacity_failure_restores_replacements(self):
        calendar = self.make_calendar()
        calendar.book("old", "r", 0, 5)
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan(
                [
                    request("first", end=5, duration=4),
                    request("second", end=5, duration=2),
                ],
                replace=["old"],
            ),
        )
        self.assertEqual(calendar.free_spans("r", 0, 6), [(5, 6)])

    def test_22_late_validation_failure_restores_everything(self):
        calendar = self.make_calendar()
        calendar.book("old", "r", 0, 5)
        invalid = request("second")
        invalid["extra"] = 1
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan(
                [request("first"), invalid], replace=["old"]
            ),
        )

    def test_23_empty_plan_and_delete_only(self):
        calendar = self.make_calendar()
        calendar.book("a", "r", 0, 3)
        calendar.book("b", "r", 3, 6)
        self.assertEqual(calendar.plan([]), [])
        self.assertEqual(calendar.plan([], replace=["a"]), [])
        self.assertEqual(
            calendar.bookings(), [snapshot("b", "r", 1, [(3, 6)])]
        )

    def test_24_duplicate_ids_in_batch_and_existing(self):
        calendar = self.make_calendar(3)
        calendar.book("old", "r", 0, 2)
        calendar.add_resource("s", 3)
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan([request("old", resource="s")]),
        )
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan(
                [request("old"), request("old", resource="s")],
                replace=["old"],
            ),
        )

    def test_25_invalid_replacement_lists(self):
        calendar = self.make_calendar()
        calendar.book("old", "r", 0, 2)
        for replacement in (
            ["old", "old"],
            ["old", "missing"],
            "old",
            {"old"},
            None,
            [""],
            [[]],
        ):
            with self.subTest(replacement=replacement):
                self.assert_failure_unchanged(
                    calendar,
                    lambda replacement=replacement: calendar.plan(
                        [], replace=replacement
                    ),
                )

    def test_26_invalid_request_containers_and_keys(self):
        calendar = self.make_calendar()
        missing = request()
        del missing["duration"]
        extra = request()
        extra["note"] = "unused"
        for requests in ((), {}, None, [None], [[]], [missing], [extra]):
            with self.subTest(requests=requests):
                self.assert_failure_unchanged(
                    calendar,
                    lambda requests=requests: calendar.plan(requests),
                )

    def test_27_invalid_request_values(self):
        calendar = self.make_calendar()
        invalid_values = {
            "id": ["", 1, []],
            "resource": ["missing", "", None, []],
            "start": [-1, True, 1.0, 10],
            "end": [0, -1, False, 10.0, 121],
            "duration": [0, -1, True, 3.0, 11],
            "units": [0, -1, True, 1.0],
            "min_part": [0, -1, True, 1.0, 4],
            "max_parts": [0, -1, True, 1.0, 7],
        }
        for key, values in invalid_values.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    item = request()
                    item[key] = value
                    self.assert_failure_unchanged(
                        calendar,
                        lambda item=item: calendar.plan([item]),
                    )

    def test_28_infeasible_fragmentation(self):
        calendar = self.make_calendar()
        calendar.book("b1", "r", 2, 3)
        calendar.book("b2", "r", 5, 6)
        calendar.book("b3", "r", 8, 9)
        cases = [
            request(end=11, duration=6, min_part=3, max_parts=3),
            request(end=11, duration=7, max_parts=3),
            request(end=11, duration=3, max_parts=1),
        ]
        for item in cases:
            with self.subTest(item=item):
                self.assert_failure_unchanged(
                    calendar, lambda item=item: calendar.plan([item])
                )

    def test_29_units_exceeding_capacity(self):
        calendar = self.make_calendar(2)
        self.assertEqual(calendar.free_spans("r", 0, 5, 3), [])
        self.assert_failure_unchanged(
            calendar, lambda: calendar.book("a", "r", 0, 5, 3)
        )
        self.assert_failure_unchanged(
            calendar, lambda: calendar.plan([request(units=3)])
        )

    def test_30_split_reservation_interoperates_with_existing_api(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 2, 4)
        result = calendar.plan([
            request("split", end=8, duration=5, max_parts=2)
        ])[0]
        self.assertEqual(result["segments"], [(0, 2), (4, 7)])
        self.assertEqual(calendar.get("split"), result)
        self.assertEqual(calendar.free_spans("r", 0, 9), [(7, 9)])
        calendar.book("tail", "r", 7, 9)
        self.assert_failure_unchanged(
            calendar, lambda: calendar.book("bad", "r", 6, 8)
        )
        self.assertEqual(calendar.cancel("split"), result)
        self.assertEqual(calendar.free_spans("r", 0, 9), [(0, 2), (4, 7)])

    def test_31_split_replacement_releases_every_segment(self):
        calendar = self.make_calendar()
        calendar.book("block", "r", 2, 4)
        calendar.plan([
            request("split", end=8, duration=5, max_parts=2)
        ])
        result = calendar.plan(
            [request("whole", end=8, duration=8)],
            replace=["split", "block"],
        )
        self.assertEqual(result, [snapshot("whole", "r", 1, [(0, 8)])])
        self.assertEqual(calendar.bookings(), result)

    def test_32_inputs_and_plan_results_are_independent(self):
        calendar = self.make_calendar(2)
        calendar.book("old", "r", 0, 10)
        requests = [
            request("a", duration=2),
            request("b", duration=2),
        ]
        replacements = ["old"]
        original_requests = copy.deepcopy(requests)
        original_replacements = replacements[:]
        result = calendar.plan(requests, replacements)
        self.assertEqual(requests, original_requests)
        self.assertEqual(replacements, original_replacements)
        requests[0]["duration"] = 9
        requests.clear()
        replacements.clear()
        result[0]["segments"].clear()
        result[0]["units"] = 100
        result[1]["segments"].append((8, 9))
        self.assertEqual(
            calendar.get("a"), snapshot("a", "r", 1, [(0, 2)])
        )
        self.assertEqual(
            calendar.get("b"), snapshot("b", "r", 1, [(0, 2)])
        )

    def test_33_failed_plan_preserves_inputs(self):
        calendar = self.make_calendar()
        calendar.book("old", "r", 0, 5)
        requests = [
            request("a", end=5, duration=4),
            request("b", end=5, duration=4),
        ]
        replacements = ["old"]
        before = copy.deepcopy((requests, replacements))
        self.assert_failure_unchanged(
            calendar, lambda: calendar.plan(requests, replacements)
        )
        self.assertEqual((requests, replacements), before)

    def test_34_window_boundary_and_large_absolute_times(self):
        calendar = self.make_calendar()
        base = 10**15
        calendar.book("earlier", "r", 0, base)
        result = calendar.plan([
            request(
                start=base, end=base + 120,
                duration=120, min_part=120, max_parts=6,
            )
        ])
        self.assertEqual(result[0]["segments"], [(base, base + 120)])
        self.assert_failure_unchanged(
            calendar,
            lambda: calendar.plan([
                request("wide", start=base + 200, end=base + 321)
            ]),
        )
        calendar.book("long", "r", base + 200, base + 1000)
        self.assertEqual(
            calendar.free_spans("r", base + 120, base + 1001),
            [(base + 120, base + 200), (base + 1000, base + 1001)],
        )

    def test_35_six_parts_at_limit(self):
        calendar = self.make_calendar()
        for index in range(5):
            calendar.book(
                "block" + str(index), "r", index * 3 + 2, index * 3 + 3
            )
        result = calendar.plan([
            request(end=17, duration=12, min_part=2, max_parts=6)
        ])
        self.assertEqual(
            result[0]["segments"],
            [(0, 2), (3, 5), (6, 8), (9, 11), (12, 14), (15, 17)],
        )

    def test_36_deterministic_exhaustive_small_windows(self):
        # All availability patterns on six time units, including empty
        # availability, are checked against an independent enumeration.
        horizon = 6
        for mask in range(1 << horizon):
            calendar = self.make_calendar()
            available = []
            for tick in range(horizon):
                if mask & (1 << tick):
                    available.append(tick)
                else:
                    calendar.book(
                        "blocked_" + str(tick), "r", tick, tick + 1
                    )
            original = calendar.bookings()
            for duration in range(1, horizon + 1):
                for min_part in range(1, min(3, duration) + 1):
                    for max_parts in (1, 2, 3):
                        expected = brute_plan(
                            available, duration, min_part, max_parts
                        )
                        with self.subTest(
                            mask=mask,
                            duration=duration,
                            min_part=min_part,
                            max_parts=max_parts,
                        ):
                            item = request(
                                end=horizon,
                                duration=duration,
                                min_part=min_part,
                                max_parts=max_parts,
                            )
                            if expected is None:
                                with self.assertRaises(ValueError):
                                    calendar.plan([item])
                            else:
                                result = calendar.plan([item])
                                self.assertEqual(
                                    result,
                                    [snapshot("new", "r", 1, expected)],
                                )
                                self.assertEqual(
                                    calendar.cancel("new"), result[0]
                                )
                            self.assertEqual(calendar.bookings(), original)


if __name__ == "__main__":
    unittest.main()

=== END ===
