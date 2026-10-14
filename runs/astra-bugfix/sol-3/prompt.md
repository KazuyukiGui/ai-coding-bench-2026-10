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

`lots` は登録済みの全ロットを `lot` 昇順に並べたリストです。各要素の `remaining` はロットの残数量、`available` は利用可能数量（残数量 − active な全予約による割り当て数量）です。各要素は次の形です。

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

添付ファイル:
=== FILE: stockbook.py ===
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
=== END ===

答え方: 次のファイルの全体（変更しないファイルは不要）を、説明なしで、次の形式だけで返してください。各ファイルは「=== FILE: パス ===」の行で始め、最後に「=== END ===」の行を置きます。ツールは使えません。Python 3.11・標準ライブラリのみ。
返すファイル: stockbook.py
