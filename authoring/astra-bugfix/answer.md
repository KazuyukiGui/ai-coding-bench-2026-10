=== FILE: meta.json ===
{"title":"期限付き在庫予約台帳の修正","category":"bugfix","answer":["stockbook.py"]}
=== FILE: prompt.md ===
# 期限付き在庫予約台帳

倉庫のロット別在庫と出荷予約を管理する `stockbook.py` を修正してください。公開 API は `StockBook()`、`apply(events)`、`snapshot()` です。Python 3.11 の標準ライブラリだけを使用します。

## データと入力検証

時刻は非負整数です。実際の時計は使用しません。数量は正整数です。整数を要求する箇所では `bool` や `float` を受け付けません。整数の上限は設けません。

識別子は空でない文字列です。空白だけの文字列も有効で、大文字・小文字や前後の空白を区別します。文字列の大小比較には Python の通常の文字列比較を使います。

入力値は、組み込みの `dict`、`list`、`str`、`int`、`float`、`bool`、`None` からなる、循環参照のないデータです。辞書のキーは文字列です。独自クラスや組み込み型のサブクラスは対象外です。

`apply(events)` はイベントの **list** を受け取り、記載順に処理して `None` を返します。各イベントは **dict** です。下表のキーをすべて含み、余分なキーを含んではいけません。

すべてのイベントに次の共通キーがあります。

| キー | 内容 |
|---|---|
| `id` | イベント識別子 |
| `kind` | 下表のイベント種別 |
| `at` | イベント時刻 |

各種別に必要な追加キーは次のとおりです。

| `kind` | 追加キー | 操作 |
|---|---|---|
| `receive` | `lot`, `sku`, `quantity`, `expires` | ロットを入庫する |
| `reserve` | `reservation`, `sku`, `quantity`, `until` | 出荷予約を作成する |
| `resize` | `reservation`, `quantity` | 有効な予約の数量を変更する |
| `release` | `reservation` | 有効な予約を解除する |
| `ship` | `reservation` | 有効な予約を出荷する |
| `tick` | なし | 台帳の時刻を進める |

`lot`、`sku`、`reservation`、`id` は識別子です。`quantity` は数量です。`expires` は非負整数または `None`、`until` は非負整数です。

さらに、`receive` の有限の `expires` はそのイベントの `at` より大きく、`reserve` の `until` もそのイベントの `at` より大きくなければいけません。

入力の形式・値・操作条件に違反した場合は `ValueError` を送出します。例外メッセージは問いません。

## 時刻、再送、トランザクション

初期時刻は `0` です。

イベントはまず上記の入力検証を行います。その後、同じ `id` で以前に成功したイベントがある場合、辞書全体が等しければ再送として何も行いません。キーの記載順は関係ありません。内容が異なれば `ValueError` です。

再送は時刻検査や期限処理より先に判定します。したがって、過去の時刻のイベントも、同一内容の再送なら成功し、時刻・在庫・予約を変えません。過去に成功した入庫や予約の再送によって、それらが復活することもありません。

新規イベントの `at` は現在の台帳時刻以上でなければいけません。同時刻のイベントは有効です。新規イベントでは、その操作を行う前に次の期限処理を順番に行います。

1. `active` で `until <= at` の予約をすべて `expired` にし、割り当てを全解除する。
2. 有限の `expires <= at` のロットの残数量を `0` にする。
3. 台帳時刻を `at` にする。

その後にイベントの操作条件を検査し、操作します。

**1 回の `apply` 全体がトランザクションです。** 途中で `ValueError` が起きた場合、その呼び出しによる変更をすべて取り消します。時刻、期限処理、在庫、予約、成功イベントの再送履歴も呼び出し前に戻ります。同じバッチの先行イベントは、後続イベントから参照できます。

空リストは何も変更しません。入力を変更してはいけません。また、渡した入力を呼び出し後に変更しても、台帳や再送判定に影響してはいけません。

## ロットと予約の規則

### 入庫

`receive` は `quantity` を残数量として新しいロットを登録します。`expires=None` は期限なしです。

一度使用した `lot` は、残数量が `0` になっても再利用できません。ロットは履歴として残します。

### 割り当て順序

ロットの残数量には、予約に割り当て済みの数量も含まれます。

```text
利用可能数量 = 残数量 - active な全予約による割り当て数量
```

予約に使えるのは、次のすべてを満たすロットです。

- 予約と `sku` が一致する。
- 利用可能数量が正である。
- `expires=None` または `expires >= 予約の until` である。

`expires` と `until` が等しいロットも使用できます。

使用可能なロットを次の順序で使い、必要なら複数ロットに分割して割り当てます。

1. 有限の `expires` が早い順。
2. 期限なしのロットは、すべての有限期限ロットの後。
3. 期限が同じ場合は `lot` の昇順。期限なし同士も同様。

以下、この順序を「割り当て順」と呼びます。

### 予約作成

`reserve` は指定数量を全量確保し、状態 `active` の予約を作ります。不足する場合は `ValueError` です。

一度使用した `reservation` は、予約が終了しても再利用できません。`sku` と `until` は作成後に変更しません。

イベント識別子、ロット識別子、予約識別子は別々の名前空間です。同じ文字列をそれぞれに使えます。

### 数量変更

`resize` の対象は存在する `active` な予約に限ります。

- 増量時は、既存の割り当てをすべて保持し、増加分だけを割り当て順で追加確保します。同じロットへの追加分は合算します。全量確保できなければ `ValueError` です。
- 減量時は、その予約が現在使用しているロットを**割り当て順の逆順**にたどって必要な分だけ解放します。
- 同じ数量への変更も有効です。
- 数量 `0` への変更はできません。

後から優先順位の高いロットが入庫されても、既存の割り当てを組み替えてはいけません。

### 解除・出荷・失効

`release` と `ship` の対象は存在する `active` な予約に限ります。

- `release` は割り当てを全解除して `released` にします。ロットの残数量は変えません。
- `ship` は割り当て数量を各ロットの残数量から差し引き、割り当てを全解除して `shipped` にします。
- 期限処理での失効は割り当てを全解除して `expired` にします。

終了した予約は履歴として残します。どの終了状態でも `quantity` は終了直前の予約数量を保持し、割り当ては空になります。

予約期限ちょうどの `release`、`ship`、`resize` は、操作前の期限処理によって対象が失効するため `ValueError` です。この場合もトランザクション全体を取り消します。

## スナップショット

`snapshot()` は時刻を進めず、次の形の辞書を返します。記載したキーを過不足なく含めてください。

```python
{
    "at": 0,
    "lots": [],
    "reservations": [],
}
```

`lots` は登録済みの全ロットを `lot` 昇順に並べたリストです。各要素は次の形です。

```python
{
    "lot": "lot-a",
    "sku": "part",
    "expires": None,
    "remaining": 10,
    "available": 7,
}
```

期限切れ・使い切ったロットも含めます。

`reservations` は登録済みの全予約を `reservation` 昇順に並べたリストです。各要素は次の形です。

```python
{
    "reservation": "order-a",
    "sku": "part",
    "until": 12,
    "quantity": 3,
    "status": "active",
    "allocations": [
        {"lot": "lot-a", "quantity": 3},
    ],
}
```

`allocations` は正の割り当てだけを、その予約における割り当て順で並べます。終了した予約では空リストです。

返された辞書や内部のリスト・辞書を変更しても、台帳や後続のスナップショットに影響してはいけません。
=== FILE: given/stockbook.py ===
from copy import deepcopy


_FIELDS = {
    "receive": {"lot", "sku", "quantity", "expires"},
    "reserve": {"reservation", "sku", "quantity", "until"},
    "resize": {"reservation", "quantity"},
    "release": {"reservation"},
    "ship": {"reservation"},
    "tick": set(),
}


class StockBook:
    def __init__(self):
        self._at = 0
        self._lots = {}
        self._reservations = {}
        self._events = {}

    @staticmethod
    def _integer(value, minimum):
        if not isinstance(value, int) or value < minimum:
            raise ValueError("invalid integer")

    @staticmethod
    def _identifier(value):
        if type(value) is not str or not value:
            raise ValueError("invalid identifier")

    def _validate(self, event):
        if type(event) is not dict:
            raise ValueError("event must be a dict")
        kind = event.get("kind")
        if type(kind) is not str or kind not in _FIELDS:
            raise ValueError("unknown event kind")
        expected = {"id", "kind", "at"} | _FIELDS[kind]
        if not expected.issubset(event):
            raise ValueError("invalid event fields")

        self._identifier(event["id"])
        self._integer(event["at"], 0)
        for name in ("lot", "sku", "reservation"):
            if name in event:
                self._identifier(event[name])
        if "quantity" in event:
            self._integer(event["quantity"], 1)
        if kind == "reserve":
            self._integer(event["until"], 0)
            if event["until"] <= event["at"]:
                raise ValueError("reservation deadline must be later")
        if kind == "receive" and event["expires"] is not None:
            self._integer(event["expires"], 0)
            if event["expires"] <= event["at"]:
                raise ValueError("lot expiration must be later")

    def apply(self, events):
        if type(events) is not list:
            raise ValueError("events must be a list")
        for event in events:
            saved = deepcopy(
                (self._at, self._lots, self._reservations, self._events)
            )
            try:
                self._validate(event)
                if event["at"] < self._at:
                    raise ValueError("time cannot move backwards")
                self._advance(event["at"])
                event_id = event["id"]
                if event_id in self._events:
                    if self._events[event_id] != event:
                        raise ValueError("event id conflict")
                    continue
                self._dispatch(event)
                self._events[event_id] = event
            except ValueError:
                (
                    self._at,
                    self._lots,
                    self._reservations,
                    self._events,
                ) = saved
                raise

    def _close(self, reservation, status):
        reservation["status"] = status
        reservation["allocations"] = {}

    def _advance(self, at):
        for reservation in self._reservations.values():
            if (
                reservation["status"] == "active"
                and reservation["until"] < at
            ):
                self._close(reservation, "expired")
        for lot in self._lots.values():
            if lot["expires"] is not None and lot["expires"] <= at:
                lot["remaining"] = 0
        self._at = at

    def _lot_key(self, lot_id):
        expires = self._lots[lot_id]["expires"]
        return (
            expires is not None,
            0 if expires is None else expires,
            lot_id,
        )

    def _held(self):
        held = {}
        for reservation in self._reservations.values():
            if reservation["status"] != "active":
                continue
            for lot_id, quantity in reservation["allocations"].items():
                held[lot_id] = held.get(lot_id, 0) + quantity
        return held

    def _allocate(self, sku, until, quantity):
        held = self._held()
        allocations = {}
        needed = quantity
        for lot_id in sorted(self._lots, key=self._lot_key):
            lot = self._lots[lot_id]
            if lot["sku"] != sku:
                continue
            if lot["expires"] is not None and lot["expires"] <= until:
                continue
            available = lot["remaining"] - held.get(lot_id, 0)
            take = min(needed, available)
            if take <= 0:
                continue
            allocations[lot_id] = take
            needed -= take
            if needed == 0:
                break
        if needed:
            raise ValueError("insufficient stock")
        return allocations

    def _receive(self, event):
        lot_id = event["lot"]
        if lot_id in self._lots:
            raise ValueError("lot id already used")
        self._lots[lot_id] = {
            "sku": event["sku"],
            "expires": event["expires"],
            "remaining": event["quantity"],
        }

    def _reserve(self, event):
        reservation_id = event["reservation"]
        if reservation_id in self._reservations:
            raise ValueError("reservation id already used")
        allocations = self._allocate(
            event["sku"], event["until"], event["quantity"]
        )
        self._reservations[reservation_id] = {
            "sku": event["sku"],
            "until": event["until"],
            "quantity": event["quantity"],
            "status": "active",
            "allocations": allocations,
        }

    def _resize(self, reservation, quantity):
        old_quantity = reservation["quantity"]
        allocations = reservation["allocations"]
        if quantity > old_quantity:
            extra = self._allocate(
                reservation["sku"],
                reservation["until"],
                quantity - old_quantity,
            )
            allocations.update(extra)
        elif quantity < old_quantity:
            to_release = old_quantity - quantity
            for lot_id in sorted(allocations, key=self._lot_key):
                take = min(to_release, allocations[lot_id])
                allocations[lot_id] -= take
                to_release -= take
                if allocations[lot_id] == 0:
                    del allocations[lot_id]
                if to_release == 0:
                    break
        reservation["quantity"] = quantity

    def _dispatch(self, event):
        kind = event["kind"]
        if kind == "tick":
            return
        if kind == "receive":
            self._receive(event)
            return
        if kind == "reserve":
            self._reserve(event)
            return

        reservation = self._reservations.get(event["reservation"])
        if reservation is None or reservation["status"] != "active":
            raise ValueError("reservation is not active")
        if kind == "resize":
            self._resize(reservation, event["quantity"])
            return
        if kind == "ship":
            for lot_id, quantity in reservation["allocations"].items():
                self._lots[lot_id]["remaining"] -= quantity
            self._close(reservation, "shipped")
        else:
            self._close(reservation, "released")

    def snapshot(self):
        held = self._held()
        lots = []
        for lot_id in sorted(self._lots):
            lot = self._lots[lot_id]
            lots.append({
                "lot": lot_id,
                "sku": lot["sku"],
                "expires": lot["expires"],
                "remaining": lot["remaining"],
                "available": lot["remaining"] - held.get(lot_id, 0),
            })

        reservations = []
        for reservation_id in sorted(self._reservations):
            reservation = self._reservations[reservation_id]
            allocations = [
                {
                    "lot": lot_id,
                    "quantity": reservation["allocations"][lot_id],
                }
                for lot_id in sorted(
                    reservation["allocations"], key=self._lot_key
                )
            ]
            reservations.append({
                "reservation": reservation_id,
                "sku": reservation["sku"],
                "until": reservation["until"],
                "quantity": reservation["quantity"],
                "status": reservation["status"],
                "allocations": allocations,
            })
        return {
            "at": self._at,
            "lots": lots,
            "reservations": reservations,
        }
=== FILE: ref/stockbook.py ===
from copy import deepcopy


_FIELDS = {
    "receive": {"lot", "sku", "quantity", "expires"},
    "reserve": {"reservation", "sku", "quantity", "until"},
    "resize": {"reservation", "quantity"},
    "release": {"reservation"},
    "ship": {"reservation"},
    "tick": set(),
}


class StockBook:
    def __init__(self):
        self._at = 0
        self._lots = {}
        self._reservations = {}
        self._events = {}

    @staticmethod
    def _integer(value, minimum):
        if type(value) is not int or value < minimum:
            raise ValueError("invalid integer")

    @staticmethod
    def _identifier(value):
        if type(value) is not str or not value:
            raise ValueError("invalid identifier")

    def _validate(self, event):
        if type(event) is not dict:
            raise ValueError("event must be a dict")
        kind = event.get("kind")
        if type(kind) is not str or kind not in _FIELDS:
            raise ValueError("unknown event kind")
        expected = {"id", "kind", "at"} | _FIELDS[kind]
        if set(event) != expected:
            raise ValueError("invalid event fields")

        self._identifier(event["id"])
        self._integer(event["at"], 0)
        for name in ("lot", "sku", "reservation"):
            if name in event:
                self._identifier(event[name])
        if "quantity" in event:
            self._integer(event["quantity"], 1)
        if kind == "reserve":
            self._integer(event["until"], 0)
            if event["until"] <= event["at"]:
                raise ValueError("reservation deadline must be later")
        if kind == "receive" and event["expires"] is not None:
            self._integer(event["expires"], 0)
            if event["expires"] <= event["at"]:
                raise ValueError("lot expiration must be later")

    def apply(self, events):
        if type(events) is not list:
            raise ValueError("events must be a list")
        saved = deepcopy(
            (self._at, self._lots, self._reservations, self._events)
        )
        try:
            for event in events:
                self._validate(event)
                event_id = event["id"]
                if event_id in self._events:
                    if self._events[event_id] != event:
                        raise ValueError("event id conflict")
                    continue
                if event["at"] < self._at:
                    raise ValueError("time cannot move backwards")
                self._advance(event["at"])
                self._dispatch(event)
                self._events[event_id] = deepcopy(event)
        except ValueError:
            (
                self._at,
                self._lots,
                self._reservations,
                self._events,
            ) = saved
            raise

    def _close(self, reservation, status):
        reservation["status"] = status
        reservation["allocations"] = {}

    def _advance(self, at):
        for reservation in self._reservations.values():
            if (
                reservation["status"] == "active"
                and reservation["until"] <= at
            ):
                self._close(reservation, "expired")
        for lot in self._lots.values():
            if lot["expires"] is not None and lot["expires"] <= at:
                lot["remaining"] = 0
        self._at = at

    def _lot_key(self, lot_id):
        expires = self._lots[lot_id]["expires"]
        return (
            expires is None,
            0 if expires is None else expires,
            lot_id,
        )

    def _held(self):
        held = {}
        for reservation in self._reservations.values():
            if reservation["status"] != "active":
                continue
            for lot_id, quantity in reservation["allocations"].items():
                held[lot_id] = held.get(lot_id, 0) + quantity
        return held

    def _allocate(self, sku, until, quantity):
        held = self._held()
        allocations = {}
        needed = quantity
        for lot_id in sorted(self._lots, key=self._lot_key):
            lot = self._lots[lot_id]
            if lot["sku"] != sku:
                continue
            if lot["expires"] is not None and lot["expires"] < until:
                continue
            available = lot["remaining"] - held.get(lot_id, 0)
            take = min(needed, available)
            if take <= 0:
                continue
            allocations[lot_id] = take
            needed -= take
            if needed == 0:
                break
        if needed:
            raise ValueError("insufficient stock")
        return allocations

    def _receive(self, event):
        lot_id = event["lot"]
        if lot_id in self._lots:
            raise ValueError("lot id already used")
        self._lots[lot_id] = {
            "sku": event["sku"],
            "expires": event["expires"],
            "remaining": event["quantity"],
        }

    def _reserve(self, event):
        reservation_id = event["reservation"]
        if reservation_id in self._reservations:
            raise ValueError("reservation id already used")
        allocations = self._allocate(
            event["sku"], event["until"], event["quantity"]
        )
        self._reservations[reservation_id] = {
            "sku": event["sku"],
            "until": event["until"],
            "quantity": event["quantity"],
            "status": "active",
            "allocations": allocations,
        }

    def _resize(self, reservation, quantity):
        old_quantity = reservation["quantity"]
        allocations = reservation["allocations"]
        if quantity > old_quantity:
            extra = self._allocate(
                reservation["sku"],
                reservation["until"],
                quantity - old_quantity,
            )
            for lot_id, amount in extra.items():
                allocations[lot_id] = allocations.get(lot_id, 0) + amount
        elif quantity < old_quantity:
            to_release = old_quantity - quantity
            for lot_id in sorted(
                allocations, key=self._lot_key, reverse=True
            ):
                take = min(to_release, allocations[lot_id])
                allocations[lot_id] -= take
                to_release -= take
                if allocations[lot_id] == 0:
                    del allocations[lot_id]
                if to_release == 0:
                    break
        reservation["quantity"] = quantity

    def _dispatch(self, event):
        kind = event["kind"]
        if kind == "tick":
            return
        if kind == "receive":
            self._receive(event)
            return
        if kind == "reserve":
            self._reserve(event)
            return

        reservation = self._reservations.get(event["reservation"])
        if reservation is None or reservation["status"] != "active":
            raise ValueError("reservation is not active")
        if kind == "resize":
            self._resize(reservation, event["quantity"])
            return
        if kind == "ship":
            for lot_id, quantity in reservation["allocations"].items():
                self._lots[lot_id]["remaining"] -= quantity
            self._close(reservation, "shipped")
        else:
            self._close(reservation, "released")

    def snapshot(self):
        held = self._held()
        lots = []
        for lot_id in sorted(self._lots):
            lot = self._lots[lot_id]
            lots.append({
                "lot": lot_id,
                "sku": lot["sku"],
                "expires": lot["expires"],
                "remaining": lot["remaining"],
                "available": lot["remaining"] - held.get(lot_id, 0),
            })

        reservations = []
        for reservation_id in sorted(self._reservations):
            reservation = self._reservations[reservation_id]
            allocations = [
                {
                    "lot": lot_id,
                    "quantity": reservation["allocations"][lot_id],
                }
                for lot_id in sorted(
                    reservation["allocations"], key=self._lot_key
                )
            ]
            reservations.append({
                "reservation": reservation_id,
                "sku": reservation["sku"],
                "until": reservation["until"],
                "quantity": reservation["quantity"],
                "status": reservation["status"],
                "allocations": allocations,
            })
        return {
            "at": self._at,
            "lots": lots,
            "reservations": reservations,
        }
=== FILE: tests/test_hidden.py ===
import unittest
from copy import deepcopy

from stockbook import StockBook


def receive(eid, at, lot, quantity, expires=None, sku="S"):
    return {
        "id": eid,
        "kind": "receive",
        "at": at,
        "lot": lot,
        "sku": sku,
        "quantity": quantity,
        "expires": expires,
    }


def reserve(eid, at, reservation, quantity, until, sku="S"):
    return {
        "id": eid,
        "kind": "reserve",
        "at": at,
        "reservation": reservation,
        "sku": sku,
        "quantity": quantity,
        "until": until,
    }


def operation(kind, eid, at, reservation, quantity=None):
    event = {
        "id": eid,
        "kind": kind,
        "at": at,
        "reservation": reservation,
    }
    if kind == "resize":
        event["quantity"] = quantity
    return event


def tick(eid, at):
    return {"id": eid, "kind": "tick", "at": at}


def make_book(*events):
    book = StockBook()
    book.apply(list(events))
    return book


def get_lot(book, lot_id):
    return next(x for x in book.snapshot()["lots"] if x["lot"] == lot_id)


def get_reservation(book, reservation_id):
    return next(
        x for x in book.snapshot()["reservations"]
        if x["reservation"] == reservation_id
    )


def allocations(book, reservation_id):
    return [
        (x["lot"], x["quantity"])
        for x in get_reservation(book, reservation_id)["allocations"]
    ]


class StockBookTests(unittest.TestCase):
    def assert_rejected(self, book, events):
        before = book.snapshot()
        with self.assertRaises(ValueError):
            book.apply(events)
        self.assertEqual(book.snapshot(), before)

    def test_empty_book_and_empty_batch(self):
        book = StockBook()
        expected = {"at": 0, "lots": [], "reservations": []}
        self.assertEqual(book.snapshot(), expected)
        self.assertIsNone(book.apply([]))
        self.assertEqual(book.snapshot(), expected)
        book.apply([tick("t", 7)])
        self.assertIsNone(book.apply([]))
        self.assertEqual(book.snapshot()["at"], 7)

    def test_snapshot_exact_shape(self):
        book = make_book(
            receive("i", 0, "L", 10),
            reserve("r", 1, "R", 3, 12),
        )
        self.assertEqual(book.snapshot(), {
            "at": 1,
            "lots": [{
                "lot": "L",
                "sku": "S",
                "expires": None,
                "remaining": 10,
                "available": 7,
            }],
            "reservations": [{
                "reservation": "R",
                "sku": "S",
                "until": 12,
                "quantity": 3,
                "status": "active",
                "allocations": [{"lot": "L", "quantity": 3}],
            }],
        })

    def test_fefo_split_ties_and_equal_deadline(self):
        book = make_book(
            receive("i1", 0, "z", 5, 10),
            receive("i2", 0, "a", 3, 10),
            receive("i3", 0, "early", 2, 8),
            receive("i4", 0, "none", 9),
            reserve("r", 0, "R", 7, 8),
        )
        self.assertEqual(
            allocations(book, "R"), [("early", 2), ("a", 3), ("z", 2)]
        )
        self.assertEqual(get_lot(book, "none")["available"], 9)
        self.assertEqual(get_lot(book, "z")["available"], 3)

    def test_deadline_eligibility_and_sku_isolation(self):
        book = make_book(
            receive("i1", 0, "short", 50, 5),
            receive("i2", 0, "other", 50, 7, sku="T"),
            receive("i3", 0, "long", 2, 9),
            receive("i4", 0, "none", 5),
            reserve("r", 0, "R", 4, 6),
        )
        self.assertEqual(allocations(book, "R"), [("long", 2), ("none", 2)])
        self.assertEqual(get_lot(book, "short")["available"], 50)
        self.assertEqual(get_lot(book, "other")["available"], 50)
        self.assert_rejected(book, [reserve("x", 1, "X", 1, 8, sku="U")])

    def test_multiple_reservations_share_available_stock(self):
        book = make_book(
            receive("i", 0, "L", 10),
            reserve("r1", 0, "R1", 4, 10),
            reserve("r2", 0, "R2", 5, 10),
        )
        self.assertEqual(get_lot(book, "L")["remaining"], 10)
        self.assertEqual(get_lot(book, "L")["available"], 1)
        self.assert_rejected(book, [reserve("r3", 1, "R3", 2, 10)])
        book.apply([reserve("r3", 1, "R3", 1, 10)])
        self.assertEqual(get_lot(book, "L")["available"], 0)

    def test_reservation_and_lot_expire_at_boundary(self):
        book = make_book(
            receive("i1", 0, "finite", 2, 4),
            receive("i2", 0, "none", 5),
            reserve("r", 0, "R", 3, 4),
        )
        book.apply([tick("t", 4)])
        self.assertEqual(get_lot(book, "finite"), {
            "lot": "finite",
            "sku": "S",
            "expires": 4,
            "remaining": 0,
            "available": 0,
        })
        self.assertEqual(get_lot(book, "none")["available"], 5)
        reservation = get_reservation(book, "R")
        self.assertEqual(reservation["status"], "expired")
        self.assertEqual(reservation["quantity"], 3)
        self.assertEqual(reservation["allocations"], [])

    def test_reservation_expiration_releases_unexpired_stock(self):
        book = make_book(
            receive("i", 0, "L", 6, 10),
            reserve("r", 0, "R", 4, 3),
        )
        book.apply([tick("before", 2)])
        self.assertEqual(get_reservation(book, "R")["status"], "active")
        book.apply([tick("edge", 3)])
        self.assertEqual(get_reservation(book, "R")["status"], "expired")
        self.assertEqual(get_lot(book, "L")["remaining"], 6)
        self.assertEqual(get_lot(book, "L")["available"], 6)
        book.apply([reserve("r2", 3, "R2", 6, 10)])
        self.assertEqual(allocations(book, "R2"), [("L", 6)])

    def test_unreserved_lot_expiration_and_history(self):
        book = make_book(receive("i", 0, "L", 5, 3))
        book.apply([tick("a", 2)])
        self.assertEqual(get_lot(book, "L")["remaining"], 5)
        book.apply([tick("b", 3)])
        self.assertEqual(get_lot(book, "L")["remaining"], 0)
        book.apply([tick("c", 100)])
        self.assertEqual(len(book.snapshot()["lots"]), 1)

    def test_release_preserves_remaining_and_other_reservations(self):
        book = make_book(
            receive("i", 0, "L", 10),
            reserve("r1", 0, "R1", 4, 10),
            reserve("r2", 0, "R2", 3, 10),
        )
        book.apply([operation("release", "rel", 1, "R1")])
        self.assertEqual(get_lot(book, "L")["remaining"], 10)
        self.assertEqual(get_lot(book, "L")["available"], 7)
        self.assertEqual(allocations(book, "R2"), [("L", 3)])
        ended = get_reservation(book, "R1")
        self.assertEqual(ended["status"], "released")
        self.assertEqual(ended["quantity"], 4)
        self.assertEqual(ended["allocations"], [])

    def test_ship_consumes_only_target_allocations(self):
        book = make_book(
            receive("i1", 0, "A", 3, 20),
            receive("i2", 0, "B", 8),
            reserve("r1", 0, "R1", 5, 10),
            reserve("r2", 0, "R2", 2, 10),
        )
        book.apply([operation("ship", "s", 1, "R1")])
        self.assertEqual(get_lot(book, "A")["remaining"], 0)
        self.assertEqual(get_lot(book, "B")["remaining"], 6)
        self.assertEqual(get_lot(book, "B")["available"], 4)
        self.assertEqual(allocations(book, "R2"), [("B", 2)])
        ended = get_reservation(book, "R1")
        self.assertEqual(ended["status"], "shipped")
        self.assertEqual(ended["quantity"], 5)
        self.assertEqual(ended["allocations"], [])

    def test_resize_increase_combines_same_lot(self):
        book = make_book(
            receive("i", 0, "L", 10),
            reserve("r", 0, "R", 2, 10),
        )
        book.apply([operation("resize", "up", 1, "R", 5)])
        self.assertEqual(allocations(book, "R"), [("L", 5)])
        self.assertEqual(get_reservation(book, "R")["quantity"], 5)
        self.assertEqual(get_lot(book, "L")["available"], 5)

    def test_resize_increase_keeps_existing_allocation(self):
        book = make_book(
            receive("i1", 0, "old", 6),
            reserve("r", 0, "R", 3, 10),
            receive("i2", 1, "new", 4, 10),
        )
        book.apply([operation("resize", "up", 2, "R", 5)])
        self.assertEqual(allocations(book, "R"), [("new", 2), ("old", 3)])
        self.assertEqual(get_lot(book, "new")["available"], 2)
        self.assertEqual(get_lot(book, "old")["available"], 3)

    def test_resize_decrease_uses_reverse_fefo(self):
        book = make_book(
            receive("i1", 0, "A", 3, 10),
            receive("i2", 0, "B", 3, 20),
            receive("i3", 0, "N", 3),
            reserve("r", 0, "R", 8, 10),
        )
        book.apply([operation("resize", "down", 1, "R", 4)])
        self.assertEqual(allocations(book, "R"), [("A", 3), ("B", 1)])
        self.assertEqual(get_lot(book, "N")["available"], 3)
        book.apply([operation("resize", "down2", 2, "R", 1)])
        self.assertEqual(allocations(book, "R"), [("A", 1)])

    def test_resize_decrease_tie_breaks_in_reverse(self):
        book = make_book(
            receive("i1", 0, "a", 3, 10),
            receive("i2", 0, "z", 3, 10),
            reserve("r", 0, "R", 5, 9),
        )
        book.apply([operation("resize", "d", 1, "R", 2)])
        self.assertEqual(allocations(book, "R"), [("a", 2)])

    def test_same_quantity_resize_still_advances_time(self):
        book = make_book(
            receive("i", 0, "L", 10),
            reserve("r1", 0, "R1", 3, 10),
            reserve("r2", 0, "R2", 2, 2),
        )
        book.apply([operation("resize", "same", 2, "R1", 3)])
        self.assertEqual(book.snapshot()["at"], 2)
        self.assertEqual(allocations(book, "R1"), [("L", 3)])
        self.assertEqual(get_reservation(book, "R2")["status"], "expired")
        self.assertEqual(get_lot(book, "L")["available"], 7)

    def test_failed_increase_restores_expiration_and_clock(self):
        book = make_book(
            receive("i", 0, "L", 5),
            reserve("r1", 0, "R1", 3, 10),
            reserve("r2", 0, "R2", 2, 2),
        )
        self.assert_rejected(
            book, [operation("resize", "up", 2, "R1", 6)]
        )
        self.assertEqual(get_reservation(book, "R2")["status"], "active")
        book.apply([operation("resize", "up", 2, "R1", 5)])
        self.assertEqual(allocations(book, "R1"), [("L", 5)])
        self.assertEqual(get_reservation(book, "R2")["status"], "expired")

    def test_batch_failure_rolls_back_earlier_events_and_ids(self):
        book = StockBook()
        self.assert_rejected(book, [
            receive("i", 5, "L", 3),
            reserve("r", 5, "R", 4, 9),
        ])
        book.apply([
            receive("i", 0, "L", 7),
            reserve("r", 0, "R", 6, 9),
        ])
        self.assertEqual(allocations(book, "R"), [("L", 6)])
        self.assertEqual(book.snapshot()["at"], 0)

    def test_batch_time_error_undoes_expiration(self):
        book = make_book(
            receive("i", 0, "L", 4, 3),
            reserve("r", 0, "R", 4, 3),
        )
        self.assert_rejected(book, [tick("t1", 3), tick("t2", 2)])
        book.apply([tick("t1", 1)])
        self.assertEqual(book.snapshot()["at"], 1)
        self.assertEqual(get_reservation(book, "R")["status"], "active")

    def test_batch_validation_error_rolls_back_prior_change(self):
        book = make_book(receive("i", 0, "L", 8))
        malformed = tick("bad", 2)
        malformed["extra"] = None
        self.assert_rejected(book, [
            reserve("r", 1, "R", 3, 9),
            malformed,
        ])
        book.apply([reserve("r", 0, "R", 4, 9)])
        self.assertEqual(allocations(book, "R"), [("L", 4)])

    def test_old_replay_does_not_change_clock_or_revive_lot(self):
        original = receive("i", 0, "L", 4, 3)
        book = make_book(original, tick("t", 5))
        before = book.snapshot()
        self.assertIsNone(book.apply([dict(reversed(list(original.items())))]))
        self.assertEqual(book.snapshot(), before)
        book.apply([original, receive("new", 5, "N", 2)])
        self.assertEqual(book.snapshot()["at"], 5)
        self.assertEqual(get_lot(book, "L")["remaining"], 0)

    def test_old_reservation_replay_does_not_revive_reservation(self):
        original = reserve("r", 0, "R", 3, 2)
        book = make_book(
            receive("i", 0, "L", 5),
            original,
            tick("t", 3),
        )
        before = book.snapshot()
        book.apply([original])
        self.assertEqual(book.snapshot(), before)
        self.assertEqual(get_reservation(book, "R")["status"], "expired")

    def test_duplicate_in_batch_and_conflicting_duplicate(self):
        incoming = receive("i", 0, "L", 5)
        booking = reserve("r", 0, "R", 2, 10)
        book = make_book(incoming, deepcopy(incoming), booking, deepcopy(booking))
        self.assertEqual(get_lot(book, "L")["remaining"], 5)
        self.assertEqual(get_lot(book, "L")["available"], 3)
        changed = dict(booking, quantity=3)
        self.assert_rejected(book, [tick("t", 1), changed])
        book.apply([tick("t", 0)])
        self.assertEqual(book.snapshot()["at"], 0)

    def test_caller_mutation_cannot_change_replay_history(self):
        incoming = receive("i", 0, "L", 5)
        original = deepcopy(incoming)
        events = [incoming]
        book = StockBook()
        book.apply(events)
        self.assertEqual(events, [original])
        incoming["quantity"] = 8
        events.append(tick("unused", 100))
        self.assert_rejected(book, [incoming])
        book.apply([original])
        self.assertEqual(get_lot(book, "L")["remaining"], 5)
        self.assertEqual(book.snapshot()["at"], 0)

    def test_validation_precedes_replay_equality(self):
        original = receive("i", 0, "L", 1)
        book = make_book(original)
        self.assert_rejected(book, [dict(original, quantity=True)])
        self.assert_rejected(book, [dict(original, at=False)])
        self.assert_rejected(book, [dict(original, quantity=1.0)])
        self.assert_rejected(book, [dict(original, extra=1)])
        book.apply([original])

    def test_snapshot_is_deeply_independent(self):
        book = make_book(
            receive("i", 0, "L", 8),
            reserve("r", 0, "R", 3, 9),
        )
        before = book.snapshot()
        exposed = book.snapshot()
        exposed["at"] = 99
        exposed["lots"][0]["remaining"] = -1
        exposed["lots"].append({})
        exposed["reservations"][0]["quantity"] = 999
        exposed["reservations"][0]["allocations"][0]["quantity"] = 999
        exposed["reservations"][0]["allocations"].append({})
        exposed["reservations"].append({})
        self.assertEqual(book.snapshot(), before)
        book.apply([operation("ship", "s", 1, "R")])
        self.assertEqual(get_lot(book, "L")["remaining"], 5)

    def test_identifiers_are_permanent_and_namespaces_are_separate(self):
        book = make_book(
            receive("same", 0, "same", 2, 2),
            reserve("r", 0, "same", 1, 2),
            tick("t", 2),
        )
        self.assert_rejected(book, [receive("i2", 2, "same", 3)])
        book.apply([receive("i3", 2, "new", 5)])
        self.assert_rejected(book, [reserve("r2", 2, "same", 1, 8)])

    def test_shipped_lot_and_released_reservation_ids_cannot_be_reused(self):
        book = make_book(
            receive("i", 0, "L", 1),
            reserve("r", 0, "R", 1, 5),
            operation("ship", "s", 1, "R"),
        )
        self.assert_rejected(book, [receive("i2", 1, "L", 2)])
        book.apply([
            receive("i3", 1, "N", 2),
            reserve("r2", 1, "Q", 1, 5),
            operation("release", "rel", 1, "Q"),
        ])
        self.assert_rejected(book, [reserve("r3", 1, "Q", 1, 5)])

    def test_operations_require_active_reservations(self):
        for ended_by in ("release", "ship", "expire"):
            with self.subTest(ended_by=ended_by):
                book = make_book(
                    receive("i", 0, "L", 5),
                    reserve("r", 0, "R", 2, 3),
                )
                if ended_by == "expire":
                    book.apply([tick("end", 3)])
                else:
                    book.apply([operation(ended_by, "end", 1, "R")])
                at = book.snapshot()["at"]
                for kind in ("release", "ship", "resize"):
                    self.assert_rejected(
                        book, [operation(kind, "bad", at, "R", 1)]
                    )
                    self.assert_rejected(
                        book, [operation(kind, "missing", at, "absent", 1)]
                    )

    def test_operations_at_deadline_fail_and_rollback_expiration(self):
        for kind in ("release", "ship", "resize"):
            with self.subTest(kind=kind):
                book = make_book(
                    receive("i", 0, "L", 5, 3),
                    reserve("r", 0, "R", 2, 3),
                )
                self.assert_rejected(
                    book, [operation(kind, "edge", 3, "R", 1)]
                )
                self.assertEqual(get_reservation(book, "R")["status"], "active")
                book.apply([tick("edge", 3)])
                self.assertEqual(get_reservation(book, "R")["status"], "expired")

    def test_time_order_and_equal_timestamps(self):
        book = make_book(receive("i", 4, "L", 5))
        self.assert_rejected(book, [tick("back", 3)])
        book.apply([
            reserve("r", 4, "R", 2, 5),
            operation("resize", "up", 4, "R", 3),
            operation("release", "rel", 4, "R"),
            tick("same", 4),
        ])
        self.assertEqual(book.snapshot()["at"], 4)
        self.assertEqual(get_lot(book, "L")["available"], 5)

    def test_exact_event_schemas_and_container_types(self):
        book = StockBook()
        for invalid in (None, {}, "events", 3, True):
            with self.subTest(container=invalid):
                self.assert_rejected(book, invalid)

        valid_examples = [
            receive("i", 0, "L", 5),
            reserve("r", 0, "R", 2, 10),
            operation("resize", "u", 0, "R", 3),
            operation("release", "d", 0, "R"),
            operation("ship", "s", 0, "R"),
            tick("t", 0),
        ]
        prepared = make_book(
            receive("base_i", 0, "base_L", 20),
            reserve("base_r", 0, "R", 2, 10),
        )
        for valid in valid_examples:
            for field in valid:
                bad = dict(valid)
                del bad[field]
                with self.subTest(kind=valid["kind"], missing=field):
                    self.assert_rejected(prepared, [bad])
            with self.subTest(kind=valid["kind"], extra=True):
                self.assert_rejected(prepared, [dict(valid, extra=None)])

        for invalid in (
            None, [], "event", 1, True, {},
            {"id": "x", "kind": "unknown", "at": 0},
            {"id": "x", "kind": [], "at": 0},
        ):
            with self.subTest(event=invalid):
                self.assert_rejected(prepared, [invalid])

    def test_numeric_validation(self):
        book = make_book(
            receive("base_i", 0, "L", 20),
            reserve("base_r", 0, "R", 2, 10),
        )
        for value in (True, False, 0, -1, 1.0, "1", None):
            for base in (
                receive("i", 0, "N", 1),
                reserve("r", 0, "Q", 1, 10),
                operation("resize", "u", 0, "R", 1),
            ):
                with self.subTest(field="quantity", value=value, kind=base["kind"]):
                    self.assert_rejected(book, [dict(base, quantity=value)])

        for value in (True, False, -1, 0.0, "0", None):
            with self.subTest(field="at", value=value):
                self.assert_rejected(book, [tick("t", value)])

        for value in (True, False, -1, 1.0, "1", None, 0):
            with self.subTest(field="until", value=value):
                self.assert_rejected(book, [reserve("r", 0, "Q", 1, value)])

        for value in (True, False, -1, 1.0, "1", 0):
            with self.subTest(field="expires", value=value):
                self.assert_rejected(book, [receive("i", 0, "N", 1, value)])

        self.assert_rejected(book, [reserve("r", 5, "Q", 1, 5)])
        self.assert_rejected(book, [reserve("r", 5, "Q", 1, 4)])
        self.assert_rejected(book, [receive("i", 5, "N", 1, 5)])
        self.assert_rejected(book, [receive("i", 5, "N", 1, 4)])

    def test_identifier_validation(self):
        book = StockBook()
        examples = [
            receive("i", 0, "L", 1),
            reserve("r", 0, "R", 1, 10),
        ]
        for example in examples:
            for field in ("id", "lot", "sku", "reservation"):
                if field not in example:
                    continue
                for value in ("", None, 0, True, [], {}):
                    with self.subTest(field=field, value=value):
                        self.assert_rejected(book, [dict(example, **{field: value})])

    def test_literal_identifiers_unicode_order_and_case(self):
        names = ["あ", "a", "A", " a", " "]
        events = [
            receive("i" + str(index), 0, name, 1, sku=" ")
            for index, name in enumerate(names)
        ]
        events.append(receive("other", 0, "other", 10, sku=""))
        self.assert_rejected(StockBook(), events)

        book = make_book(*events[:-1])
        book.apply([
            reserve("r", 0, " ", 5, 2, sku=" "),
            receive("case", 0, "case", 5, sku="s"),
        ])
        self.assertEqual(
            allocations(book, " "), [(name, 1) for name in sorted(names)]
        )
        self.assertEqual(
            [x["lot"] for x in book.snapshot()["lots"]],
            sorted(names + ["case"]),
        )
        self.assert_rejected(book, [reserve("bad", 0, "bad", 1, 2, sku="S")])

    def test_reservations_snapshot_sorted_by_identifier(self):
        book = make_book(receive("i", 0, "L", 10))
        book.apply([
            reserve("r1", 0, "z", 1, 5),
            reserve("r2", 0, "あ", 1, 5),
            reserve("r3", 0, "A", 1, 5),
            operation("release", "rel", 1, "z"),
        ])
        self.assertEqual(
            [r["reservation"] for r in book.snapshot()["reservations"]],
            sorted(["z", "あ", "A"]),
        )

    def test_ended_reservation_keeps_resized_quantity(self):
        for kind in ("release", "ship", "expire"):
            with self.subTest(kind=kind):
                book = make_book(
                    receive("i", 0, "L", 10),
                    reserve("r", 0, "R", 2, 5),
                    operation("resize", "u", 1, "R", 6),
                )
                if kind == "expire":
                    book.apply([tick("end", 5)])
                else:
                    book.apply([operation(kind, "end", 2, "R")])
                reservation = get_reservation(book, "R")
                self.assertEqual(reservation["quantity"], 6)
                self.assertEqual(reservation["allocations"], [])
                expected_remaining = 4 if kind == "ship" else 10
                self.assertEqual(
                    get_lot(book, "L")["remaining"], expected_remaining
                )

    def test_ship_replay_cannot_consume_twice(self):
        shipping = operation("ship", "s", 1, "R")
        book = make_book(
            receive("i", 0, "L", 8),
            reserve("r", 0, "R", 3, 10),
            shipping,
            tick("t", 5),
        )
        before = book.snapshot()
        book.apply([shipping, deepcopy(shipping)])
        self.assertEqual(book.snapshot(), before)
        self.assertEqual(get_lot(book, "L")["remaining"], 5)

    def test_batch_conflicting_replay_rolls_back_new_history(self):
        book = make_book(receive("i", 0, "L", 10))
        self.assert_rejected(book, [
            tick("new", 1),
            receive("i", 0, "L", 11),
        ])
        book.apply([tick("new", 0)])
        self.assertEqual(book.snapshot()["at"], 0)

    def test_expiration_runs_before_new_reservation(self):
        book = make_book(
            receive("i", 0, "L", 4),
            reserve("r1", 0, "R1", 4, 3),
        )
        book.apply([reserve("r2", 3, "R2", 4, 8)])
        self.assertEqual(get_reservation(book, "R1")["status"], "expired")
        self.assertEqual(allocations(book, "R2"), [("L", 4)])
        self.assertEqual(get_lot(book, "L")["available"], 0)

    def test_large_integers_and_none_expiration_order(self):
        large = 10 ** 100
        book = make_book(
            receive("i1", large, "finite", large, large + 10),
            receive("i2", large, "none", large),
            reserve("r", large, "R", large + 1, large + 10),
        )
        self.assertEqual(
            allocations(book, "R"), [("finite", large), ("none", 1)]
        )
        book.apply([operation("ship", "s", large + 1, "R")])
        self.assertEqual(get_lot(book, "finite")["remaining"], 0)
        self.assertEqual(get_lot(book, "none")["remaining"], large - 1)

    def test_complete_workflow_preserves_accounting(self):
        book = make_book(
            receive("i1", 0, "A", 5, 20),
            receive("i2", 0, "B", 10),
            reserve("r1", 0, "R1", 7, 10),
            reserve("r2", 0, "R2", 4, 12),
        )
        book.apply([
            operation("resize", "down", 1, "R1", 4),
            operation("resize", "up", 1, "R2", 7),
            operation("ship", "ship", 2, "R2"),
            operation("release", "release", 2, "R1"),
            reserve("r3", 2, "R3", 8, 20),
        ])
        self.assertEqual(get_lot(book, "A")["remaining"], 4)
        self.assertEqual(get_lot(book, "B")["remaining"], 4)
        self.assertEqual(allocations(book, "R3"), [("A", 4), ("B", 4)])
        self.assertEqual(get_lot(book, "A")["available"], 0)
        self.assertEqual(get_lot(book, "B")["available"], 0)
        book.apply([tick("end", 20)])
        self.assertEqual(get_lot(book, "A")["remaining"], 0)
        self.assertEqual(get_lot(book, "B")["available"], 4)
        self.assertEqual(get_reservation(book, "R3")["status"], "expired")


if __name__ == "__main__":
    unittest.main()
=== END ===