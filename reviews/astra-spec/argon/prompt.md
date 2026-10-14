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
=== FILE: given/warehouse.py ===
class Warehouse:
    def __init__(self):
        raise NotImplementedError

    def apply(self, events):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError

=== FILE: prompt.md ===
# 期限付き在庫と引当の台帳

倉庫の在庫ロットと出荷用の引当を管理する `Warehouse` クラスを、`warehouse.py` に実装してください。Python 3.11 の標準ライブラリだけを使用します。

この台帳では、在庫の実数と引当済みの数量を区別します。引当の作成だけでは在庫の実数は減らず、出荷によって減ります。

## 公開 API

- `Warehouse()`：現在時刻が `0`、在庫も引当もない台帳を作ります。
- `apply(events)`：イベントのリストを順番に処理し、各イベントの処理直後のスナップショットをリストで返します。
- `snapshot()`：現在のスナップショットを返します。状態や現在時刻は変更しません。

時刻はすべて非負の整数です。実際の時計は使用しません。

`apply` の呼び出し単位で処理は原子的です。途中のイベントで後述の業務エラーが起きた場合、`ValueError` を送出し、現在時刻、在庫、引当、使用済み ID、入庫順序を含むすべての状態を、その呼び出しの直前に戻します。例外メッセージは問いません。

空のイベントリストには `[]` を返し、状態を変えません。

入力のリストや辞書を変更してはいけません。返すスナップショットは、それぞれ独立したリストと辞書で構成してください。返却値を書き換えても台帳やほかのスナップショットは変化せず、その後の台帳操作によって過去の返却値も変化しません。

## 入力の前提

各イベントは以下に示すキーだけを持つ辞書であり、キーの不足や未知の操作はありません。

- `at` は非負の整数です。
- `quantity` は正の整数です。
- `expires` は非負の整数または `None` です。
- `until` は非負の整数です。
- `lot`、`hold`、`sku` は空でない文字列です。
- 整数として `bool` が渡されることはありません。

この形式から外れる入力への対応は不要です。形式を満たしていても、以下に定める業務エラーは判定してください。

ID と SKU は大文字小文字を区別し、文字列を正規化しません。ロット ID は SKU に関係なく台帳全体で一意です。引当 ID も台帳全体で一意ですが、ロット ID と引当 ID の名前空間は別です。

## イベントの処理順序と期限切れ

各イベントでは、操作本体より先に次を行います。

1. `at` が現在時刻より小さければ業務エラーです。同じ時刻は許されます。
2. 現在時刻を `at` に進めます。
3. `expires` が `None` ではなく、`expires <= at` の在庫ロットを期限切れと判定します。
4. 次のどちらかに該当する引当を、引当全体として解除します。
   - `until <= at` である。
   - 手順 3 の期限切れロットを、現在の割当の中に一つでも含む。
5. 期限切れロットを削除します。
6. イベントの操作本体を実行します。

引当の解除は、まだ期限切れではないロットの在庫の実数を減らしません。そのロットへの割当だけがなくなります。期限切れロットの在庫は、残量に関係なく削除されます。

この処理はイベントがあるときだけ行います。期限切れ処理の結果、操作対象の引当がなくなった場合、操作本体は「存在しない引当」として扱います。その操作が業務エラーなら、期限切れ処理も含めて `apply` 全体が取り消されます。

ロットや引当が削除されても、その ID は使用済みのままです。ただし、取り消された `apply` の中で初めて使われた ID は使用済みになりません。

## 割当規則

ある SKU の引当を作る際は、現在存在する同じ SKU のロットだけを使います。

各ロットの利用可能数は次の値です。

`在庫の実数 − 現在の全引当がそのロットに割り当てている数量の合計`

利用可能数を、次の優先順位で順に使います。

1. 有限の `expires` を持つロットを、期限の小さい順に使う。
2. `expires=None` のロットは、有限の期限のロットすべてより後に使う。
3. 期限が同じ場合は、入庫イベントを処理した順に使う。同じ `at` でもリスト内の処理順が優先される。

一つのロットから可能な限り取り、足りなければ次へ進みます。要求数量の全量を割り当てられなければ業務エラーです。数量が `0` の割当は作りません。

引当の `until` がロットの `expires` より後であっても割当可能です。期限切れ時には、前述の引当全体の解除規則を適用します。

既存の引当を、新しい入庫などを理由に自動的に割り当て直すことはありません。

## 操作

### 入庫：`receive`

```python
{"op": "receive", "at": 0, "lot": "L1", "sku": "PART", "quantity": 8, "expires": 20}
```

指定数量を持つ新しいロットを作ります。

次の場合は業務エラーです。

- ロット ID が一度でも使われている。
- `expires` が `None` ではなく、`expires <= at` である。

在庫の実数が出荷によって `0` になったロットも、期限切れになるまでは台帳に残ります。期限なしのロットは、実数が `0` でも残り続けます。

### 引当作成：`reserve`

```python
{"op": "reserve", "at": 1, "hold": "H1", "sku": "PART", "quantity": 5, "until": 15}
```

指定 SKU・数量・期限で新しい引当を作ります。割当規則に従ってロットを選びます。

次の場合は業務エラーです。

- 引当 ID が一度でも使われている。
- `until <= at` である。
- 利用可能数が不足する。

### 引当変更：`resize`

```python
{"op": "resize", "at": 2, "hold": "H1", "quantity": 3, "until": 18}
```

既存引当の数量と期限を、指定された値に置き換えます。`quantity` は増減量ではなく変更後の総数量です。SKU は変わりません。

対象引当の現在の割当をすべて外したうえで、ほかの引当の割当を維持したまま、変更後の全数量を割当規則に従って割り当て直します。同じ数量への変更でも割り当て直します。

次の場合は業務エラーです。

- 対象引当が現在存在しない。
- `until <= at` である。
- 割り当て直すための利用可能数が不足する。

同じ引当を変更する操作なので、使用済み ID の重複には該当しません。

### 出荷：`ship`

```python
{"op": "ship", "at": 3, "hold": "H1", "quantity": 2}
```

対象引当の現在の割当リストを先頭から使い、指定数量を出荷します。使った数量だけ、そのロットの在庫の実数と引当の割当数量を減らします。

割当数量が `0` になった項目は除きます。引当全体の残数量が `0` になった場合は、その引当を削除します。残数量がある場合、引当の SKU と `until` は変えません。

次の場合は業務エラーです。

- 対象引当が現在存在しない。
- 出荷数量が、その引当の現在の残数量を超える。

### 引当解除：`release`

```python
{"op": "release", "at": 4, "hold": "H1"}
```

対象引当を削除します。在庫の実数は減らしません。対象引当が現在存在しなければ業務エラーです。

### 時刻進行：`tick`

```python
{"op": "tick", "at": 10}
```

共通の時刻進行と期限切れ処理だけを行います。

## スナップショット

スナップショットは、次のキーだけを持つ辞書です。

```python
{
    "now": 3,
    "lots": [
        {
            "id": "L1",
            "sku": "PART",
            "expires": 20,
            "on_hand": 6,
            "reserved": 3,
            "available": 3,
        }
    ],
    "holds": [
        {
            "id": "H1",
            "sku": "PART",
            "until": 15,
            "quantity": 3,
            "allocations": [
                {"lot": "L1", "quantity": 3}
            ],
        }
    ],
}
```

- `lots` には現在存在する全ロットを含め、`id` の昇順に並べます。
- `holds` には現在存在する全引当を含め、`id` の昇順に並べます。
- 文字列の昇順は Python の通常の文字列比較に従います。
- `on_hand` は在庫の実数、`reserved` は全引当による割当数量の合計、`available` はその差です。
- 引当の `quantity` は現在の割当数量の合計です。
- `allocations` は割当規則による優先順を保持します。ID 順には並べ替えません。
- 空の場合も `lots`、`holds` は省略せず、空リストにします。
- 辞書のキーの挿入順は問いません。

例えば、期限 `5` のロットから `2` 個、期限 `20` のロットから `1` 個を割り当てた、期限 `30` の引当があるとします。時刻 `5` に進むと、その引当全体が解除されます。期限 `20` のロットから割り当てていた `1` 個は、在庫の実数を減らさず利用可能な状態に戻ります。

=== FILE: ref/warehouse.py ===
from copy import deepcopy


class Warehouse:
    """期限付きロットと、ロットへの割当を管理する台帳。"""

    def __init__(self):
        self._now = 0
        self._lots = {}
        self._holds = {}
        self._used_lots = set()
        self._used_holds = set()
        self._serial = 0

    def apply(self, events):
        if not events:
            return []

        working = deepcopy(self)
        results = []
        for event in events:
            working._advance(event["at"])
            working._dispatch(event)
            results.append(working.snapshot())

        self._now = working._now
        self._lots = working._lots
        self._holds = working._holds
        self._used_lots = working._used_lots
        self._used_holds = working._used_holds
        self._serial = working._serial
        return results

    def _reserved(self):
        counts = {}
        for hold in self._holds.values():
            for lot_id, quantity in hold["allocations"]:
                counts[lot_id] = counts.get(lot_id, 0) + quantity
        return counts

    def snapshot(self):
        reserved = self._reserved()
        lots = []
        for lot_id in sorted(self._lots):
            lot = self._lots[lot_id]
            count = reserved.get(lot_id, 0)
            lots.append({
                "id": lot_id,
                "sku": lot["sku"],
                "expires": lot["expires"],
                "on_hand": lot["quantity"],
                "reserved": count,
                "available": lot["quantity"] - count,
            })

        holds = []
        for hold_id in sorted(self._holds):
            hold = self._holds[hold_id]
            allocations = [
                {"lot": lot_id, "quantity": quantity}
                for lot_id, quantity in hold["allocations"]
            ]
            holds.append({
                "id": hold_id,
                "sku": hold["sku"],
                "until": hold["until"],
                "quantity": sum(
                    quantity for _, quantity in hold["allocations"]
                ),
                "allocations": allocations,
            })
        return {"now": self._now, "lots": lots, "holds": holds}

    def _advance(self, at):
        if at < self._now:
            raise ValueError("time moved backwards")
        self._now = at
        expired_lots = {
            lot_id
            for lot_id, lot in self._lots.items()
            if lot["expires"] is not None and lot["expires"] <= at
        }
        expired_holds = [
            hold_id
            for hold_id, hold in self._holds.items()
            if hold["until"] <= at or any(
                lot_id in expired_lots
                for lot_id, _ in hold["allocations"]
            )
        ]
        for hold_id in expired_holds:
            del self._holds[hold_id]
        for lot_id in expired_lots:
            del self._lots[lot_id]

    def _dispatch(self, event):
        operation = event["op"]
        if operation == "receive":
            self._receive(event)
        elif operation == "reserve":
            self._reserve(event)
        elif operation == "resize":
            self._resize(event)
        elif operation == "ship":
            self._ship(event)
        elif operation == "release":
            self._release(event)
        elif operation == "tick":
            return

    def _receive(self, event):
        lot_id = event["lot"]
        expires = event["expires"]
        if lot_id in self._used_lots:
            raise ValueError("lot ID already used")
        if expires is not None and expires <= self._now:
            raise ValueError("invalid lot expiry")

        self._lots[lot_id] = {
            "sku": event["sku"],
            "quantity": event["quantity"],
            "expires": expires,
            "serial": self._serial,
        }
        self._serial += 1
        self._used_lots.add(lot_id)

    def _lot_order(self, lot_id):
        lot = self._lots[lot_id]
        expires = lot["expires"]
        return (
            expires is None,
            0 if expires is None else expires,
            lot["serial"],
        )

    def _allocate(self, sku, quantity):
        reserved = self._reserved()
        candidates = [
            lot_id for lot_id, lot in self._lots.items()
            if lot["sku"] == sku
        ]
        candidates.sort(key=self._lot_order)
        allocations = []
        remaining = quantity
        for lot_id in candidates:
            available = (
                self._lots[lot_id]["quantity"] - reserved.get(lot_id, 0)
            )
            taken = min(remaining, available)
            if taken > 0:
                allocations.append((lot_id, taken))
                remaining -= taken
            if remaining == 0:
                return allocations
        raise ValueError("insufficient available stock")

    def _reserve(self, event):
        hold_id = event["hold"]
        if hold_id in self._used_holds:
            raise ValueError("hold ID already used")
        if event["until"] <= self._now:
            raise ValueError("invalid hold expiry")

        allocations = self._allocate(event["sku"], event["quantity"])
        self._holds[hold_id] = {
            "sku": event["sku"],
            "until": event["until"],
            "allocations": allocations,
        }
        self._used_holds.add(hold_id)

    def _resize(self, event):
        hold_id = event["hold"]
        if hold_id not in self._holds:
            raise ValueError("hold does not exist")
        if event["until"] <= self._now:
            raise ValueError("invalid hold expiry")

        old = self._holds.pop(hold_id)
        allocations = self._allocate(old["sku"], event["quantity"])
        self._holds[hold_id] = {
            "sku": old["sku"],
            "until": event["until"],
            "allocations": allocations,
        }

    def _ship(self, event):
        hold_id = event["hold"]
        if hold_id not in self._holds:
            raise ValueError("hold does not exist")
        hold = self._holds[hold_id]
        total = sum(quantity for _, quantity in hold["allocations"])
        if event["quantity"] > total:
            raise ValueError("shipment exceeds held quantity")

        remaining = event["quantity"]
        kept = []
        for lot_id, quantity in hold["allocations"]:
            taken = min(remaining, quantity)
            self._lots[lot_id]["quantity"] -= taken
            remaining -= taken
            if quantity > taken:
                kept.append((lot_id, quantity - taken))

        if kept:
            hold["allocations"] = kept
        else:
            del self._holds[hold_id]

    def _release(self, event):
        hold_id = event["hold"]
        if hold_id not in self._holds:
            raise ValueError("hold does not exist")
        del self._holds[hold_id]

=== FILE: tests/test_hidden.py ===
import copy
import unittest

from warehouse import Warehouse


def receive(at, lot, quantity, expires=None, sku="P"):
    return {
        "op": "receive", "at": at, "lot": lot, "sku": sku,
        "quantity": quantity, "expires": expires,
    }


def reserve(at, hold, quantity, until=100, sku="P"):
    return {
        "op": "reserve", "at": at, "hold": hold, "sku": sku,
        "quantity": quantity, "until": until,
    }


def resize(at, hold, quantity, until=100):
    return {
        "op": "resize", "at": at, "hold": hold,
        "quantity": quantity, "until": until,
    }


def ship(at, hold, quantity):
    return {"op": "ship", "at": at, "hold": hold, "quantity": quantity}


def release(at, hold):
    return {"op": "release", "at": at, "hold": hold}


def tick(at):
    return {"op": "tick", "at": at}


def lot_row(lot, quantity, reserved=0, expires=None, sku="P"):
    return {
        "id": lot, "sku": sku, "expires": expires,
        "on_hand": quantity, "reserved": reserved,
        "available": quantity - reserved,
    }


def hold_row(hold, allocations, until=100, sku="P"):
    return {
        "id": hold, "sku": sku, "until": until,
        "quantity": sum(quantity for _, quantity in allocations),
        "allocations": [
            {"lot": lot, "quantity": quantity}
            for lot, quantity in allocations
        ],
    }


def state(now, lots=(), holds=()):
    return {"now": now, "lots": list(lots), "holds": list(holds)}


class WarehouseTests(unittest.TestCase):
    def setUp(self):
        self.w = Warehouse()

    def assert_rejected(self, events):
        before = self.w.snapshot()
        with self.assertRaises(ValueError):
            self.w.apply(events)
        self.assertEqual(self.w.snapshot(), before)

    def test_initial_and_empty_batch(self):
        self.assertEqual(self.w.snapshot(), state(0))
        self.assertEqual(self.w.apply([]), [])
        self.assertEqual(self.w.snapshot(), state(0))
        self.w.apply([tick(7)])
        self.assertEqual(self.w.apply([]), [])
        self.assertEqual(self.w.snapshot(), state(7))

    def test_each_event_has_its_own_snapshot(self):
        results = self.w.apply([
            receive(0, "L", 5),
            reserve(0, "H", 3, until=10),
            ship(1, "H", 2),
            release(2, "H"),
        ])
        self.assertEqual(results, [
            state(0, [lot_row("L", 5)]),
            state(0, [lot_row("L", 5, 3)], [
                hold_row("H", [("L", 3)], until=10),
            ]),
            state(1, [lot_row("L", 3, 1)], [
                hold_row("H", [("L", 1)], until=10),
            ]),
            state(2, [lot_row("L", 3)]),
        ])

    def test_fefo_and_unlimited_expiry(self):
        self.w.apply([
            receive(0, "unlimited", 4),
            receive(0, "late", 3, expires=20),
            receive(0, "early", 2, expires=10),
            reserve(0, "H", 7),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("early", 2), ("late", 3), ("unlimited", 2)]),
        ])

    def test_equal_expiry_uses_receipt_order(self):
        self.w.apply([
            receive(0, "z", 2, expires=8),
            receive(0, "a", 2, expires=8),
            reserve(0, "H", 3),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("z", 2), ("a", 1)]),
        ])
        self.assertEqual(
            [row["id"] for row in self.w.snapshot()["lots"]],
            ["a", "z"],
        )

    def test_unlimited_expiry_also_uses_receipt_order(self):
        self.w.apply([
            receive(0, "z", 2),
            receive(1, "a", 2),
            reserve(1, "H", 3),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("z", 2), ("a", 1)]),
        ])

    def test_other_holds_reduce_available_quantity(self):
        self.w.apply([
            receive(0, "A", 4, expires=20),
            receive(0, "B", 5, expires=30),
            reserve(0, "first", 3),
            reserve(0, "second", 4),
        ])
        self.assertEqual(self.w.snapshot(), state(0, [
            lot_row("A", 4, 4, expires=20),
            lot_row("B", 5, 3, expires=30),
        ], [
            hold_row("first", [("A", 3)]),
            hold_row("second", [("A", 1), ("B", 3)]),
        ]))
        self.assert_rejected([reserve(0, "third", 3)])

    def test_sku_isolation_and_case_sensitivity(self):
        self.w.apply([
            receive(0, "A", 3, sku="P"),
            receive(0, "B", 9, sku="p"),
        ])
        self.assert_rejected([reserve(1, "H", 4, sku="P")])
        self.w.apply([reserve(1, "H", 9, sku="p")])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("B", 9)], sku="p"),
        ])

    def test_missing_sku_is_insufficient_stock(self):
        self.assert_rejected([reserve(0, "H", 1, sku="UNKNOWN")])

    def test_partial_ship_crosses_lot_boundary(self):
        self.w.apply([
            receive(0, "A", 2, expires=10),
            receive(0, "B", 5, expires=20),
            reserve(0, "H", 6, until=40),
            ship(1, "H", 4),
        ])
        self.assertEqual(self.w.snapshot(), state(1, [
            lot_row("A", 0, expires=10),
            lot_row("B", 3, 2, expires=20),
        ], [
            hold_row("H", [("B", 2)], until=40),
        ]))

    def test_ship_all_keeps_empty_lot_and_used_hold_id(self):
        self.w.apply([
            receive(0, "L", 2),
            reserve(0, "H", 2),
            ship(0, "H", 2),
        ])
        self.assertEqual(self.w.snapshot(), state(0, [lot_row("L", 0)]))
        self.w.apply([receive(0, "M", 3)])
        self.assert_rejected([reserve(0, "H", 1)])
        self.assert_rejected([ship(0, "H", 1)])

    def test_overship_rolls_back(self):
        self.w.apply([receive(0, "L", 5), reserve(0, "H", 3)])
        self.assert_rejected([ship(2, "H", 4)])
        self.w.apply([ship(1, "H", 3)])
        self.assertEqual(self.w.snapshot(), state(1, [lot_row("L", 2)]))

    def test_release_restores_availability(self):
        self.w.apply([
            receive(0, "L", 5),
            reserve(0, "H", 5),
            release(1, "H"),
            reserve(1, "J", 5),
        ])
        self.assertEqual(self.w.snapshot(), state(1, [
            lot_row("L", 5, 5),
        ], [
            hold_row("J", [("L", 5)]),
        ]))
        self.assert_rejected([release(2, "H")])
        self.assert_rejected([reserve(2, "H", 1)])

    def test_hold_expires_at_exact_deadline(self):
        self.w.apply([
            receive(0, "L", 4),
            reserve(0, "H", 3, until=5),
            tick(4),
        ])
        self.assertEqual(len(self.w.snapshot()["holds"]), 1)
        self.w.apply([tick(5)])
        self.assertEqual(self.w.snapshot(), state(5, [lot_row("L", 4)]))
        self.assert_rejected([reserve(5, "H", 1, until=9)])

    def test_expired_lot_voids_whole_hold_only(self):
        self.w.apply([
            receive(0, "A", 2, expires=5),
            receive(0, "B", 4, expires=20),
            reserve(0, "H", 3, until=30),
            reserve(0, "J", 2, until=30),
            tick(5),
        ])
        self.assertEqual(self.w.snapshot(), state(5, [
            lot_row("B", 4, 2, expires=20),
        ], [
            hold_row("J", [("B", 2)], until=30),
        ]))
        self.w.apply([tick(20)])
        self.assertEqual(self.w.snapshot(), state(20))

    def test_shipped_allocation_no_longer_causes_expiration(self):
        self.w.apply([
            receive(0, "A", 2, expires=5),
            receive(0, "B", 4, expires=20),
            reserve(0, "H", 4, until=30),
            ship(1, "H", 2),
            tick(5),
        ])
        self.assertEqual(self.w.snapshot(), state(5, [
            lot_row("B", 4, 2, expires=20),
        ], [
            hold_row("H", [("B", 2)], until=30),
        ]))

    def test_expiration_happens_before_reservation(self):
        self.w.apply([
            receive(0, "L", 3),
            reserve(0, "old", 3, until=5),
            reserve(5, "new", 3, until=10),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("new", [("L", 3)], until=10),
        ])

    def test_operation_on_just_expired_hold_rolls_back_time(self):
        self.w.apply([
            receive(0, "L", 4),
            reserve(0, "H", 3, until=5),
        ])
        for event in (ship(5, "H", 1), release(5, "H"),
                      resize(5, "H", 2, until=10)):
            with self.subTest(event=event):
                self.assert_rejected([event])
        self.w.apply([ship(4, "H", 1)])
        self.assertEqual(self.w.snapshot()["now"], 4)

    def test_expired_lot_processing_is_rolled_back_on_error(self):
        self.w.apply([
            receive(0, "A", 2, expires=5),
            receive(0, "B", 4),
            reserve(0, "H", 3, until=20),
        ])
        self.assert_rejected([ship(5, "H", 1)])
        self.w.apply([ship(4, "H", 1)])
        self.assertEqual(self.w.snapshot()["lots"][0]["on_hand"], 1)

    def test_resize_releases_own_stock_before_reallocation(self):
        self.w.apply([
            receive(0, "L", 5),
            reserve(0, "H", 5, until=10),
            resize(1, "H", 5, until=20),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("L", 5)], until=20),
        ])

    def test_resize_same_quantity_reallocates_after_new_receipt(self):
        self.w.apply([
            receive(0, "late", 5, expires=50),
            reserve(0, "H", 3, until=20),
            receive(1, "early", 2, expires=10),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("late", 3)], until=20),
        ])
        self.w.apply([resize(1, "H", 3, until=30)])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("early", 2), ("late", 1)], until=30),
        ])

    def test_resize_preserves_other_holds(self):
        self.w.apply([
            receive(0, "A", 4, expires=10),
            receive(0, "B", 4, expires=20),
            reserve(0, "H", 3),
            reserve(0, "J", 3),
            resize(1, "H", 4, until=50),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("A", 3), ("B", 1)], until=50),
            hold_row("J", [("A", 1), ("B", 2)]),
        ])

    def test_failed_resize_restores_original_hold(self):
        self.w.apply([
            receive(0, "L", 6),
            reserve(0, "H", 3, until=10),
            reserve(0, "J", 3, until=20),
        ])
        self.assert_rejected([resize(1, "H", 4, until=30)])
        self.w.apply([resize(1, "H", 2, until=15)])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("L", 2)], until=15),
            hold_row("J", [("L", 3)], until=20),
        ])

    def test_resize_after_shipping_uses_absolute_quantity(self):
        self.w.apply([
            receive(0, "L", 10),
            reserve(0, "H", 6),
            ship(1, "H", 4),
            resize(2, "H", 3, until=30),
        ])
        self.assertEqual(self.w.snapshot(), state(2, [
            lot_row("L", 6, 3),
        ], [
            hold_row("H", [("L", 3)], until=30),
        ]))

    def test_resize_can_shorten_deadline(self):
        self.w.apply([
            receive(0, "L", 4),
            reserve(0, "H", 3, until=50),
            resize(1, "H", 2, until=4),
            tick(4),
        ])
        self.assertEqual(self.w.snapshot(), state(4, [lot_row("L", 4)]))

    def test_business_deadline_validation(self):
        for expires in (0, 2):
            with self.subTest(expires=expires):
                self.assert_rejected([
                    receive(2, "bad", 1, expires=expires),
                ])
        self.w.apply([receive(2, "L", 4, expires=3)])
        for until in (0, 2):
            with self.subTest(until=until):
                self.assert_rejected([reserve(2, "H", 1, until=until)])
        self.w.apply([reserve(2, "H", 1, until=20)])
        self.assert_rejected([resize(2, "H", 1, until=2)])

    def test_backwards_time_and_same_time(self):
        self.w.apply([receive(5, "L", 3), reserve(5, "H", 2, until=8)])
        self.assert_rejected([tick(4)])
        self.assert_rejected([ship(4, "H", 1)])
        self.w.apply([ship(5, "H", 1), tick(5)])
        self.assertEqual(self.w.snapshot()["now"], 5)

    def test_lot_ids_global_and_permanently_used(self):
        self.w.apply([receive(0, "L", 2, expires=3, sku="P")])
        self.assert_rejected([receive(1, "L", 2, sku="Q")])
        self.w.apply([tick(3)])
        self.assertEqual(self.w.snapshot()["lots"], [])
        self.assert_rejected([receive(3, "L", 2, sku="Q")])

    def test_hold_id_global_but_separate_from_lot_namespace(self):
        self.w.apply([
            receive(0, "same", 3, sku="P"),
            receive(0, "QLOT", 3, sku="Q"),
            reserve(0, "same", 1, sku="P"),
        ])
        self.assert_rejected([reserve(0, "same", 1, sku="Q")])
        self.w.apply([release(0, "same")])
        self.assert_rejected([reserve(0, "same", 1, sku="Q")])

    def test_lot_expiration_keeps_hold_id_used(self):
        self.w.apply([
            receive(0, "A", 1, expires=2),
            receive(0, "B", 3),
            reserve(0, "H", 1),
            tick(2),
        ])
        self.assert_rejected([reserve(2, "H", 1)])
        self.w.apply([reserve(2, "J", 3)])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("J", [("B", 3)]),
        ])

    def test_entire_batch_rolls_back_and_new_ids_are_reusable(self):
        self.w.apply([receive(0, "base", 2)])
        self.assert_rejected([
            receive(1, "fresh", 4, expires=20),
            reserve(1, "newhold", 3, until=10),
            ship(2, "newhold", 1),
            release(3, "absent"),
        ])
        self.w.apply([
            receive(0, "fresh", 4, expires=20),
            reserve(0, "newhold", 4, until=10),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("newhold", [("fresh", 4)], until=10),
        ])

    def test_batch_rollback_restores_preexisting_ship_and_release(self):
        self.w.apply([
            receive(0, "L", 8),
            reserve(0, "H", 3),
            reserve(0, "J", 2),
        ])
        self.assert_rejected([
            ship(1, "H", 2),
            release(2, "J"),
            receive(3, "extra", 2),
            reserve(4, "K", 100),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("H", [("L", 3)]),
            hold_row("J", [("L", 2)]),
        ])

    def test_backwards_time_late_in_batch_rolls_everything_back(self):
        self.w.apply([receive(2, "L", 5)])
        self.assert_rejected([
            reserve(3, "H", 2),
            ship(4, "H", 1),
            tick(3),
        ])
        self.w.apply([reserve(2, "H", 5)])

    def test_snapshot_order_is_string_order(self):
        self.w.apply([
            receive(0, "あ", 2),
            receive(0, "a", 2),
            receive(0, "Z", 2),
            reserve(0, "z", 1),
            reserve(0, "A", 1),
            reserve(0, "あ", 1),
        ])
        snapshot = self.w.snapshot()
        self.assertEqual(
            [row["id"] for row in snapshot["lots"]], ["Z", "a", "あ"]
        )
        self.assertEqual(
            [row["id"] for row in snapshot["holds"]], ["A", "z", "あ"]
        )
        self.assertEqual(snapshot["holds"][0]["allocations"], [
            {"lot": "あ", "quantity": 1},
        ])

    def test_inputs_are_unchanged(self):
        events = [
            receive(0, "L", 5),
            reserve(0, "H", 3),
            resize(1, "H", 2, until=10),
            ship(2, "H", 1),
        ]
        original = copy.deepcopy(events)
        self.w.apply(events)
        self.assertEqual(events, original)
        failing = [release(3, "H"), ship(4, "H", 1)]
        original_failing = copy.deepcopy(failing)
        self.assert_rejected(failing)
        self.assertEqual(failing, original_failing)

    def test_outputs_are_detached_at_all_nested_levels(self):
        results = self.w.apply([
            receive(0, "L", 5),
            reserve(0, "H", 3),
            tick(1),
        ])
        expected = copy.deepcopy(results)
        results[1]["lots"][0]["on_hand"] = -1
        results[1]["holds"][0]["allocations"][0]["quantity"] = 99
        results[1]["holds"][0]["allocations"].append(
            {"lot": "fake", "quantity": 1}
        )
        results[1]["lots"].clear()
        results[1]["now"] = 999
        self.assertEqual(results[0], expected[0])
        self.assertEqual(results[2], expected[2])
        self.assertEqual(self.w.snapshot(), expected[2])

        detached = self.w.snapshot()
        detached["holds"][0]["allocations"][0]["lot"] = "changed"
        detached["holds"].clear()
        self.assertEqual(self.w.snapshot(), expected[2])

        self.w.apply([ship(2, "H", 1)])
        self.assertEqual(results[2], expected[2])

    def test_simultaneous_expiry_and_large_time_jump(self):
        self.w.apply([
            receive(0, "A", 2, expires=5),
            receive(0, "B", 5, expires=10),
            receive(0, "C", 4),
            reserve(0, "H", 4, until=5),
            reserve(0, "J", 4, until=10),
            tick(10**12),
        ])
        self.assertEqual(self.w.snapshot(), state(
            10**12, [lot_row("C", 4)]
        ))

    def test_missing_hold_operations(self):
        for event in (
            ship(0, "missing", 1),
            release(0, "missing"),
            resize(0, "missing", 1),
        ):
            with self.subTest(event=event):
                self.assert_rejected([event])

    def test_large_integer_quantities(self):
        quantity = 10**30
        self.w.apply([
            receive(0, "L", quantity),
            reserve(0, "H", quantity - 1),
            ship(1, "H", quantity - 2),
        ])
        self.assertEqual(self.w.snapshot(), state(1, [
            lot_row("L", 2, 1),
        ], [
            hold_row("H", [("L", 1)]),
        ]))

    def test_instances_are_independent(self):
        other = Warehouse()
        self.w.apply([receive(0, "L", 3), reserve(0, "H", 2)])
        self.assertEqual(other.snapshot(), state(0))
        other.apply([receive(1, "L", 8), reserve(1, "H", 7)])
        self.assertEqual(self.w.snapshot()["lots"], [lot_row("L", 3, 2)])
        self.assertEqual(other.snapshot()["lots"], [lot_row("L", 8, 7)])

    def test_shortening_hold_changes_future_expiration(self):
        self.w.apply([
            receive(0, "L", 6),
            reserve(0, "H", 4, until=8),
            resize(1, "H", 2, until=3),
            reserve(3, "J", 6, until=9),
        ])
        self.assertEqual(self.w.snapshot(), state(3, [
            lot_row("L", 6, 6),
        ], [
            hold_row("J", [("L", 6)], until=9),
        ]))

    def test_released_stock_is_reallocated_by_fefo(self):
        self.w.apply([
            receive(0, "A", 3, expires=10),
            receive(0, "B", 3, expires=20),
            reserve(0, "H", 3),
            reserve(0, "J", 2),
            release(1, "H"),
            reserve(1, "K", 4),
        ])
        self.assertEqual(self.w.snapshot()["holds"], [
            hold_row("J", [("B", 2)]),
            hold_row("K", [("A", 3), ("B", 1)]),
        ])

    def test_zero_stock_lots_are_skipped_during_allocation(self):
        self.w.apply([
            receive(0, "A", 1, expires=10),
            receive(0, "B", 2, expires=20),
            reserve(0, "H", 1),
            ship(0, "H", 1),
            reserve(0, "J", 2),
        ])
        self.assertEqual(self.w.snapshot(), state(0, [
            lot_row("A", 0, expires=10),
            lot_row("B", 2, 2, expires=20),
        ], [
            hold_row("J", [("B", 2)]),
        ]))


if __name__ == "__main__":
    unittest.main()

=== END ===
