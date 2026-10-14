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
=== FILE: given/inventory.py ===
from copy import deepcopy


class Ledger:
    """Single-lot reservations without expiration."""

    def __init__(self, today):
        self.today = today
        self._lots = {}
        self._reservations = {}

    def add(self, lot_id, sku, quantity):
        if lot_id in self._lots:
            raise ValueError("duplicate lot")
        self._lots[lot_id] = {
            "sku": sku,
            "received": quantity,
            "available": quantity,
            "held": 0,
            "shipped": 0,
            "expired": 0,
        }

    def reserve(self, reservation_id, sku, quantity):
        if reservation_id in self._reservations:
            raise ValueError("duplicate reservation")
        for lot_id, lot in self._lots.items():
            if lot["sku"] == sku and lot["available"] >= quantity:
                lot["available"] -= quantity
                lot["held"] += quantity
                self._reservations[reservation_id] = {
                    "sku": sku,
                    "quantity": quantity,
                    "status": "active",
                    "lot_id": lot_id,
                }
                return lot_id
        raise ValueError("insufficient single lot")

    def _finish(self, reservation_id, status):
        if reservation_id not in self._reservations:
            raise ValueError("unknown reservation")
        reservation = self._reservations[reservation_id]
        if reservation["status"] == status:
            return reservation["lot_id"]
        if reservation["status"] != "active":
            raise ValueError("closed reservation")
        lot = self._lots[reservation["lot_id"]]
        quantity = reservation["quantity"]
        lot["held"] -= quantity
        target = "available" if status == "cancelled" else "shipped"
        lot[target] += quantity
        reservation["status"] = status
        return reservation["lot_id"]

    def cancel(self, reservation_id):
        return self._finish(reservation_id, "cancelled")

    def commit(self, reservation_id):
        return self._finish(reservation_id, "committed")

    def advance(self, day):
        if day < self.today:
            raise ValueError("cannot go backward")
        self.today = day

    def copy(self):
        return deepcopy(self)

    def replace_from(self, other):
        state = deepcopy(other.__dict__)
        self.__dict__.clear()
        self.__dict__.update(state)

    def snapshot(self):
        stock = {}
        for lot in self._lots.values():
            row = stock.setdefault(
                lot["sku"],
                {
                    "sku": lot["sku"],
                    "available": 0,
                    "held": 0,
                    "shipped": 0,
                    "expired": 0,
                },
            )
            for field in ("available", "held", "shipped", "expired"):
                row[field] += lot[field]
        reservations = []
        for reservation_id in sorted(self._reservations):
            row = deepcopy(self._reservations[reservation_id])
            row["reservation_id"] = reservation_id
            reservations.append(row)
        return {
            "today": self.today.isoformat(),
            "stock": [stock[sku] for sku in sorted(stock)],
            "reservations": reservations,
        }

=== FILE: given/operations.py ===
import csv
import io
from datetime import date


def run(ledger, text):
    results = []
    for cells in csv.reader(io.StringIO(text, newline=""), strict=True):
        if not cells:
            continue
        cells = [cell.strip(" \t") for cell in cells]
        operation = cells[0]
        if operation == "ADD" and len(cells) == 4:
            result = ledger.add(cells[1], cells[2], int(cells[3]))
        elif operation == "RESERVE" and len(cells) == 4:
            result = ledger.reserve(cells[1], cells[2], int(cells[3]))
        elif operation == "CANCEL" and len(cells) == 2:
            result = ledger.cancel(cells[1])
        elif operation == "COMMIT" and len(cells) == 2:
            result = ledger.commit(cells[1])
        elif operation == "ADVANCE" and len(cells) == 2:
            result = ledger.advance(date.fromisoformat(cells[1]))
        else:
            raise ValueError("unknown operation or wrong field count")
        results.append(result)
    return results

=== FILE: given/reporting.py ===
import csv
import io


def render(ledger):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["sku", "available", "held", "shipped", "expired"])
    for row in ledger.snapshot()["stock"]:
        writer.writerow([
            row["sku"],
            row["available"],
            row["held"],
            row["shipped"],
            row["expired"],
        ])
    return output.getvalue()

=== FILE: prompt.md ===
# 期限付きロット在庫と一括操作

資材倉庫の在庫管理モジュールを改修してください。添付の実装は、1件の引当を単一ロットから行い、在庫の集計結果を公開しています。期限付きロット、複数ロットにまたがる引当、一括操作の原子性に対応し、公開するスナップショットを詳細形式に変更します。

変更対象は `inventory.py`、`operations.py`、`reporting.py` です。以下に示す改修後の仕様をすべて満たしてください。添付コードと以下の仕様が異なる場合は、以下が優先されます。

Python 3.11 の標準ライブラリだけを使用してください。現在日時、外部ファイル、ネットワークは使用しません。

## 1. 在庫モデル

`inventory.Ledger(today)` は、業務日 `today` の空の台帳を作成します。

直接メソッドを呼ぶ場合、次の引数条件は呼出側が保証します。この条件外の動作は問いません。

- 日付は `datetime.date` のインスタンスで、`datetime.datetime` ではありません。
- ロットID、引当ID、品目名は空でない `str` です。空白、カンマ、改行、Unicode文字を含む場合があります。
- 数量は `bool` ではない `int` で、1以上1,000,000,000以下です。
- `expires` は日付または `None` です。

IDと品目名は大文字・小文字を区別し、直接呼出しでは空白除去などの正規化をしません。ロットIDと引当IDは別の名前空間なので、両者が同じ文字列でも構いません。

ロットは次の数量を保持します。

| 名前 | 意味 |
| --- | --- |
| `received` | 入庫時の数量。不変 |
| `available` | 引当可能な数量 |
| `held` | 有効な引当で確保している数量 |
| `shipped` | 確定した数量 |
| `expired` | 期限切れとして除外した数量 |

常に `received == available + held + shipped + expired` が成立します。ロットと引当の履歴は削除しません。

期限日その日は有効で、`expires < today` となったときに期限切れです。`None` は無期限です。

以下の業務上の不成立は `ValueError` とし、そのメソッド呼出しによる状態変更を一切残してはいけません。例外のメッセージは自由です。

### `add(lot_id, sku, quantity, expires=None)`

- 未使用のロットIDで入庫します。
- 既存のロットIDは、残数や品目にかかわらず再利用できません。
- `expires < today` の入庫は不成立です。
- 初期値は `received = available = quantity`、残りの数量は0です。
- 戻り値は `None` です。

### `reserve(reservation_id, sku, quantity)`

- 未使用の引当IDを用いて、その品目の `available` から数量を確保します。
- 引当IDは取消・確定後も再利用できません。
- 品目がない場合を含め、利用可能な総量が不足する場合は不成立です。不成立時には引当IDも消費しません。
- ロットの選択順序は、期限が早いものからです。無期限は、日付 `9999-12-31` を含むすべての有期限ロットより後です。
- 期限が等しい場合、ロットIDのPython文字列としての昇順で選びます。無期限同士も同様です。
- この順に各ロットを必要なだけ使います。複数ロットにまたがって構いません。数量0の明細は作りません。
- 使用数量を各ロットの `available` から `held` へ移します。
- 引当の状態は `"active"` になります。
- 戻り値は、使用順の `((lot_id, quantity), ...)` というタプルです。

### `cancel(reservation_id)`

- `"active"` の引当を `"cancelled"` にします。
- 元の各ロットの `held` を減らします。そのロットが現在の業務日で有効なら `available` に、期限切れなら `expired` に同量を加えます。
- 既に `"cancelled"` なら何も変更しません。
- 未登録の引当、または `"committed"` の引当は不成立です。
- 戻り値は、初回の引当時と同じ明細タプルです。

### `commit(reservation_id)`

- `"active"` の引当を `"committed"` にします。
- 元の各ロットの `held` を `shipped` に移します。
- 引当後に期限切れになったロットも確定できます。業務日の進行で、確保済み数量の権利は失われません。
- 既に `"committed"` なら何も変更しません。
- 未登録の引当、または `"cancelled"` の引当は不成立です。
- 戻り値は、初回の引当時と同じ明細タプルです。

### `advance(day)`

- 業務日を `day` にします。
- 現在より前の日付は不成立です。同じ日付への進行は許されます。
- 新しい業務日で期限切れのロットについて、`available` の全量を `expired` へ移します。
- `held`、`shipped`、既存の `expired`、引当の状態は変更しません。
- 戻り値は `None` です。

### `copy()` と `replace_from(other)`

- `copy()` は同じ状態を持つ独立した `Ledger` を返します。
- `replace_from(other)` は、受け手の全状態を `other` の状態で置き換えます。業務日も置き換え、通常の `advance` の前進制約は適用しません。戻り値は `None` です。
- `other` は `Ledger` であることを保証します。自分自身を渡しても構いません。
- どちらも可変状態を共有してはいけません。以後の片方への操作がもう片方を変えてはいけません。

## 2. 詳細スナップショット

`snapshot()` は次の形式の新しい辞書を返します。示したキー以外は含めません。

```python
{
    "today": "2032-06-10",
    "lots": [
        {
            "lot_id": "L1",
            "sku": "PART",
            "received": 7,
            "expires": "2032-06-12",
            "available": 3,
            "held": 4,
            "shipped": 0,
            "expired": 0,
        }
    ],
    "reservations": [
        {
            "reservation_id": "R1",
            "sku": "PART",
            "quantity": 4,
            "status": "active",
            "allocations": [
                {"lot_id": "L1", "quantity": 4}
            ],
        }
    ],
}
```

- 日付は `date.isoformat()` の文字列、無期限は `None` です。
- `lots` はロットID順、`reservations` は引当ID順です。いずれもPython文字列としての昇順です。
- `allocations` は引当時の使用順で、取消・確定後も保持します。
- 空の場合も `lots` と `reservations` は空リストとして存在します。
- 返された辞書・リストを変更しても台帳は変化しません。台帳を操作しても過去のスナップショットは変化しません。

## 3. CSVによる一括操作

`operations.run(ledger, text, atomic=True)` はCSVテキストを解析して操作し、各操作の戻り値を順番に格納したリストを返します。

CSVの解釈は、Python 3.11 の次の呼出しに従います。

```python
csv.reader(io.StringIO(text, newline=""), strict=True)
```

各セルを読み取った後、先頭と末尾のASCII空白およびタブだけを `strip(" \t")` で除きます。引用符内のセルにもこの処理を行います。セル内部の空白・改行は保持します。

- CSVリーダーが空リスト `[]` として返したレコードだけを無視します。
- 空文字のセルがあるレコードや空白だけのレコードは、無条件には無視しません。
- コメント、ヘッダー、BOMの特別扱いはありません。
- 操作名は次の大文字表記だけを許可します。
- 各操作のセル数は厳密です。

| 操作 | セル |
| --- | --- |
| 入庫 | `ADD,lot_id,sku,quantity,expires` |
| 引当 | `RESERVE,reservation_id,sku,quantity` |
| 取消 | `CANCEL,reservation_id` |
| 確定 | `COMMIT,reservation_id` |
| 日付進行 | `ADVANCE,day` |

入庫の期限セルは必須ですが、空文字なら無期限です。それ以外の日付セルは、ASCII数字による厳密な `YYYY-MM-DD` 形式で、実在する日付でなければなりません。

数量はASCII数字による `[1-9][0-9]*` 形式で、1以上1,000,000,000以下です。符号、小数、先頭の0は許可しません。

IDと品目名は、セルの空白除去後に空文字であってはいけません。

CSV構文エラー、未知の操作、セル数不一致、セル値の形式エラーは `ValueError` にしてください。

### 解析と適用の順序

最初にテキスト全体を解析し、全レコードの操作名・セル数・セル値の形式を検証します。この段階では台帳を操作しません。形式エラーが末尾にあっても、`atomic` の値にかかわらず台帳は完全に元のままです。

その後、先頭から操作を適用します。IDの重複、在庫不足、業務日の後退など、台帳の状態に依存する条件は、この適用段階で検証します。

- `atomic=True`：すべて成功した場合だけ、渡された台帳の内容を更新します。途中の業務上の不成立では台帳全体を呼出し前に戻し、`ValueError` を送出します。
- `atomic=False`：途中の業務上の不成立では、先行する成功操作の結果を残し、失敗した操作以降を適用せず `ValueError` を送出します。
- 失敗時は結果リストを返しません。
- 空の操作列は `[]` を返し、状態を変えません。
- 成功時も、渡された `ledger` オブジェクト自体を別オブジェクトに差し替えることはありません。

## 4. 品目別CSV帳票

`reporting.render(ledger)` は詳細スナップショットを利用し、品目別に `available`、`held`、`shipped`、`expired` を合計したCSV文字列を返します。台帳を変更してはいけません。

- ヘッダーは `sku,available,held,shipped,expired` です。
- 登録済みロットのある品目をすべて含めます。利用可能数量が0でも含めます。
- 品目名のPython文字列としての昇順で並べます。
- 数量は通常の10進整数表記です。
- CSV出力は `csv.writer` の既定のdialectと引用規則を使い、`lineterminator="\n"` を指定します。
- ヘッダーを含む各レコードの末尾に改行を付けます。空の台帳ではヘッダーとその末尾改行だけを返します。

## 5. 例

```python
from datetime import date
from inventory import Ledger
from operations import run
from reporting import render

ledger = Ledger(date(2032, 6, 10))
results = run(
    ledger,
    "ADD,L2,PART,4,\n"
    "ADD,L1,PART,3,2032-06-10\n"
    "RESERVE,R1,PART,5\n"
    "ADVANCE,2032-06-11\n"
    "CANCEL,R1\n"
)
```

`results` は次の値です。

```python
[
    None,
    None,
    (("L1", 3), ("L2", 2)),
    None,
    (("L1", 3), ("L2", 2)),
]
```

`render(ledger)` は次の文字列です。

```text
sku,available,held,shipped,expired
PART,4,0,0,3
```

=== FILE: ref/inventory.py ===
from copy import deepcopy


class Ledger:
    def __init__(self, today):
        self.today = today
        self._lots = {}
        self._reservations = {}

    def add(self, lot_id, sku, quantity, expires=None):
        if lot_id in self._lots:
            raise ValueError("duplicate lot")
        if expires is not None and expires < self.today:
            raise ValueError("already expired")
        self._lots[lot_id] = {
            "lot_id": lot_id,
            "sku": sku,
            "received": quantity,
            "expires": expires,
            "available": quantity,
            "held": 0,
            "shipped": 0,
            "expired": 0,
        }

    def _expired(self, lot):
        expires = lot["expires"]
        return expires is not None and expires < self.today

    def reserve(self, reservation_id, sku, quantity):
        if reservation_id in self._reservations:
            raise ValueError("duplicate reservation")
        candidates = [
            lot for lot in self._lots.values()
            if lot["sku"] == sku
            and lot["available"] > 0
            and not self._expired(lot)
        ]
        candidates.sort(
            key=lambda lot: (
                lot["expires"] is None,
                lot["expires"],
                lot["lot_id"],
            )
        )
        if sum(lot["available"] for lot in candidates) < quantity:
            raise ValueError("insufficient stock")

        remaining = quantity
        allocations = []
        for lot in candidates:
            if remaining == 0:
                break
            taken = min(remaining, lot["available"])
            lot["available"] -= taken
            lot["held"] += taken
            allocations.append((lot["lot_id"], taken))
            remaining -= taken
        allocations = tuple(allocations)
        self._reservations[reservation_id] = {
            "reservation_id": reservation_id,
            "sku": sku,
            "quantity": quantity,
            "status": "active",
            "allocations": allocations,
        }
        return allocations

    def _finish(self, reservation_id, status):
        if reservation_id not in self._reservations:
            raise ValueError("unknown reservation")
        reservation = self._reservations[reservation_id]
        if reservation["status"] == status:
            return reservation["allocations"]
        if reservation["status"] != "active":
            raise ValueError("closed reservation")

        for lot_id, quantity in reservation["allocations"]:
            lot = self._lots[lot_id]
            lot["held"] -= quantity
            if status == "committed":
                destination = "shipped"
            elif self._expired(lot):
                destination = "expired"
            else:
                destination = "available"
            lot[destination] += quantity
        reservation["status"] = status
        return reservation["allocations"]

    def cancel(self, reservation_id):
        return self._finish(reservation_id, "cancelled")

    def commit(self, reservation_id):
        return self._finish(reservation_id, "committed")

    def advance(self, day):
        if day < self.today:
            raise ValueError("cannot go backward")
        self.today = day
        for lot in self._lots.values():
            if self._expired(lot):
                lot["expired"] += lot["available"]
                lot["available"] = 0

    def copy(self):
        return deepcopy(self)

    def replace_from(self, other):
        state = deepcopy(other.__dict__)
        self.__dict__.clear()
        self.__dict__.update(state)

    def snapshot(self):
        lots = []
        for lot_id in sorted(self._lots):
            row = self._lots[lot_id].copy()
            expires = row["expires"]
            row["expires"] = expires.isoformat() if expires is not None else None
            lots.append(row)

        reservations = []
        for reservation_id in sorted(self._reservations):
            reservation = self._reservations[reservation_id]
            row = reservation.copy()
            row["allocations"] = [
                {"lot_id": lot_id, "quantity": quantity}
                for lot_id, quantity in reservation["allocations"]
            ]
            reservations.append(row)
        return {
            "today": self.today.isoformat(),
            "lots": lots,
            "reservations": reservations,
        }

=== FILE: ref/operations.py ===
import csv
import io
import re
from datetime import date


_ARITIES = {
    "ADD": 5,
    "RESERVE": 4,
    "CANCEL": 2,
    "COMMIT": 2,
    "ADVANCE": 2,
}


def _name(value):
    if not value:
        raise ValueError("empty name")
    return value


def _quantity(value):
    if re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise ValueError("invalid quantity")
    quantity = int(value)
    if quantity > 1_000_000_000:
        raise ValueError("quantity too large")
    return quantity


def _day(value):
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("invalid date format")
    return date.fromisoformat(value)


def _parse(text):
    commands = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        for cells in reader:
            if not cells:
                continue
            cells = [cell.strip(" \t") for cell in cells]
            operation = cells[0]
            if operation not in _ARITIES or len(cells) != _ARITIES[operation]:
                raise ValueError("unknown operation or wrong field count")

            if operation == "ADD":
                args = (
                    _name(cells[1]),
                    _name(cells[2]),
                    _quantity(cells[3]),
                    _day(cells[4]) if cells[4] else None,
                )
            elif operation == "RESERVE":
                args = (
                    _name(cells[1]),
                    _name(cells[2]),
                    _quantity(cells[3]),
                )
            elif operation in ("CANCEL", "COMMIT"):
                args = (_name(cells[1]),)
            else:
                args = (_day(cells[1]),)
            commands.append((operation.lower(), args))
    except csv.Error as exc:
        raise ValueError("invalid CSV") from exc
    return commands


def run(ledger, text, atomic=True):
    commands = _parse(text)
    target = ledger.copy() if atomic else ledger
    results = []
    for method, args in commands:
        results.append(getattr(target, method)(*args))
    if atomic:
        ledger.replace_from(target)
    return results

=== FILE: ref/reporting.py ===
import csv
import io


_FIELDS = ("available", "held", "shipped", "expired")


def render(ledger):
    totals = {}
    for lot in ledger.snapshot()["lots"]:
        row = totals.setdefault(lot["sku"], [0, 0, 0, 0])
        for index, field in enumerate(_FIELDS):
            row[index] += lot[field]

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["sku", *_FIELDS])
    for sku in sorted(totals):
        writer.writerow([sku, *totals[sku]])
    return output.getvalue()

=== FILE: tests/test_hidden.py ===
import csv
import io
import unittest
from copy import deepcopy
from datetime import date

from inventory import Ledger
from operations import run
from reporting import render


D = date(2032, 6, 10)
NEXT = date(2032, 6, 11)
LATER = date(2032, 6, 12)
HEADER = "sku,available,held,shipped,expired\n"


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(D)

    def lots(self, ledger=None):
        ledger = self.ledger if ledger is None else ledger
        return {row["lot_id"]: row for row in ledger.snapshot()["lots"]}

    def reservations(self, ledger=None):
        ledger = self.ledger if ledger is None else ledger
        return {
            row["reservation_id"]: row
            for row in ledger.snapshot()["reservations"]
        }

    def assert_counts(self, lot_id, available, held, shipped, expired):
        row = self.lots()[lot_id]
        self.assertEqual(
            tuple(row[key] for key in ("available", "held", "shipped", "expired")),
            (available, held, shipped, expired),
        )
        self.assertEqual(
            row["received"], available + held + shipped + expired
        )

    def assert_rejected_without_change(self, callback):
        before = deepcopy(self.ledger.snapshot())
        with self.assertRaises(ValueError):
            callback()
        self.assertEqual(self.ledger.snapshot(), before)

    def test_empty_contract(self):
        self.assertEqual(
            self.ledger.snapshot(),
            {"today": "2032-06-10", "lots": [], "reservations": []},
        )
        self.assertEqual(render(self.ledger), HEADER)
        self.assertEqual(run(self.ledger, "\n\r\n"), [])

    def test_exact_snapshot_and_return_types(self):
        self.assertIsNone(self.ledger.add("L1", "PART", 7, LATER))
        self.assertEqual(self.ledger.reserve("R1", "PART", 4), (("L1", 4),))
        self.assertEqual(
            self.ledger.snapshot(),
            {
                "today": "2032-06-10",
                "lots": [{
                    "lot_id": "L1",
                    "sku": "PART",
                    "received": 7,
                    "expires": "2032-06-12",
                    "available": 3,
                    "held": 4,
                    "shipped": 0,
                    "expired": 0,
                }],
                "reservations": [{
                    "reservation_id": "R1",
                    "sku": "PART",
                    "quantity": 4,
                    "status": "active",
                    "allocations": [{"lot_id": "L1", "quantity": 4}],
                }],
            },
        )

    def test_plain_single_lot_lifecycle(self):
        self.ledger.add("L", "PART", 9)
        self.assertEqual(self.ledger.reserve("R", "PART", 4), (("L", 4),))
        self.assertEqual(self.ledger.commit("R"), (("L", 4),))
        self.assertEqual(self.lots()["L"]["expires"], None)
        self.assert_counts("L", 5, 0, 4, 0)
        self.assertEqual(render(self.ledger), HEADER + "PART,5,0,4,0\n")

    def test_split_priority_and_id_tie_break(self):
        self.ledger.add("u", "X", 4)
        self.ledger.add("z", "X", 3, NEXT)
        self.ledger.add("b", "X", 2, D)
        self.ledger.add("a", "X", 1, D)
        self.ledger.add("other", "Y", 100, D)
        self.assertEqual(
            self.ledger.reserve("R", "X", 8),
            (("a", 1), ("b", 2), ("z", 3), ("u", 2)),
        )
        self.assert_counts("u", 2, 2, 0, 0)
        self.assert_counts("other", 100, 0, 0, 0)

    def test_none_sorts_after_date_max(self):
        self.ledger.add("a", "X", 2)
        self.ledger.add("z", "X", 2, date.max)
        self.assertEqual(
            self.ledger.reserve("R", "X", 3),
            (("z", 2), ("a", 1)),
        )

    def test_unlimited_lots_use_string_order(self):
        for name in ("あ", "a", "A", "10", "2"):
            self.ledger.add(name, "X", 1)
        self.assertEqual(
            self.ledger.reserve("R", "X", 5),
            tuple((name, 1) for name in sorted(("あ", "a", "A", "10", "2"))),
        )

    def test_exact_fill_has_no_zero_allocations(self):
        self.ledger.add("a", "X", 2, D)
        self.ledger.add("b", "X", 3, NEXT)
        self.assertEqual(self.ledger.reserve("R1", "X", 2), (("a", 2),))
        self.assertEqual(self.ledger.reserve("R2", "X", 1), (("b", 1),))

    def test_insufficient_reservation_is_atomic_and_id_reusable(self):
        self.ledger.add("a", "X", 2, D)
        self.ledger.add("b", "X", 3)
        self.assert_rejected_without_change(
            lambda: self.ledger.reserve("R", "X", 6)
        )
        self.ledger.add("c", "X", 1)
        self.assertEqual(
            self.ledger.reserve("R", "X", 6),
            (("a", 2), ("b", 3), ("c", 1)),
        )

    def test_unknown_sku_does_not_consume_id(self):
        self.assert_rejected_without_change(
            lambda: self.ledger.reserve("R", "missing", 1)
        )
        self.ledger.add("L", "missing", 1)
        self.assertEqual(self.ledger.reserve("R", "missing", 1), (("L", 1),))

    def test_expiry_inclusive_and_forward_only(self):
        self.ledger.add("L", "X", 5, D)
        self.assertIsNone(self.ledger.advance(D))
        self.assert_counts("L", 5, 0, 0, 0)
        self.ledger.reserve("R", "X", 2)
        self.assertIsNone(self.ledger.advance(NEXT))
        self.assert_counts("L", 0, 2, 0, 3)
        self.ledger.advance(NEXT)
        self.assert_counts("L", 0, 2, 0, 3)
        self.assert_rejected_without_change(lambda: self.ledger.advance(D))

    def test_cancel_splits_valid_and_expired_returns(self):
        self.ledger.add("early", "X", 3, D)
        self.ledger.add("late", "X", 4, LATER)
        self.ledger.add("forever", "X", 5)
        expected = (("early", 3), ("late", 4), ("forever", 2))
        self.assertEqual(self.ledger.reserve("R", "X", 9), expected)
        self.ledger.advance(NEXT)
        self.assertEqual(self.ledger.cancel("R"), expected)
        self.assert_counts("early", 0, 0, 0, 3)
        self.assert_counts("late", 4, 0, 0, 0)
        self.assert_counts("forever", 5, 0, 0, 0)
        self.assertEqual(self.reservations()["R"]["status"], "cancelled")

    def test_commit_expired_held_stock(self):
        self.ledger.add("L", "X", 7, D)
        self.ledger.reserve("R", "X", 5)
        self.ledger.advance(LATER)
        self.assertEqual(self.ledger.commit("R"), (("L", 5),))
        self.assert_counts("L", 0, 0, 5, 2)
        self.assertEqual(self.reservations()["R"]["status"], "committed")

    def test_idempotent_terminal_operations_and_opposite_rejection(self):
        for terminal, opposite in (("cancel", "commit"), ("commit", "cancel")):
            with self.subTest(terminal=terminal):
                ledger = Ledger(D)
                ledger.add("L", "X", 4, D)
                expected = ledger.reserve("R", "X", 3)
                self.assertEqual(getattr(ledger, terminal)("R"), expected)
                ledger.advance(NEXT)
                before = deepcopy(ledger.snapshot())
                self.assertEqual(getattr(ledger, terminal)("R"), expected)
                self.assertEqual(ledger.snapshot(), before)
                with self.assertRaises(ValueError):
                    getattr(ledger, opposite)("R")
                self.assertEqual(ledger.snapshot(), before)

    def test_missing_terminal_operations(self):
        self.assert_rejected_without_change(lambda: self.ledger.cancel("R"))
        self.assert_rejected_without_change(lambda: self.ledger.commit("R"))

    def test_duplicate_ids_remain_used_after_closure(self):
        self.ledger.add("L", "X", 5)
        self.ledger.reserve("R", "X", 5)
        self.assert_rejected_without_change(
            lambda: self.ledger.reserve("R", "X", 1)
        )
        self.ledger.cancel("R")
        self.assert_rejected_without_change(
            lambda: self.ledger.reserve("R", "X", 1)
        )
        self.ledger.reserve("S", "X", 5)
        self.ledger.commit("S")
        self.assert_rejected_without_change(
            lambda: self.ledger.reserve("S", "X", 1)
        )
        self.assert_rejected_without_change(
            lambda: self.ledger.add("L", "Y", 8)
        )

    def test_expired_add_rejected_without_consuming_lot_id(self):
        self.assert_rejected_without_change(
            lambda: self.ledger.add("L", "X", 2, date(2032, 6, 9))
        )
        self.ledger.add("L", "X", 2, D)
        self.assert_counts("L", 2, 0, 0, 0)

    def test_exact_names_and_separate_id_namespaces(self):
        self.ledger.add(" same ", " X ", 2)
        self.ledger.add("same", "X", 3)
        self.ledger.add("lower", "x", 4)
        self.assertEqual(
            self.ledger.reserve(" same ", " X ", 2),
            ((" same ", 2),),
        )
        self.assert_counts("same", 3, 0, 0, 0)
        self.assert_counts("lower", 4, 0, 0, 0)

    def test_snapshot_order_and_deep_isolation(self):
        self.ledger.add("z", "X", 3, D)
        self.ledger.add("a", "X", 4)
        self.ledger.reserve("z", "X", 2)
        self.ledger.reserve("a", "X", 2)
        snap = self.ledger.snapshot()
        self.assertEqual([r["lot_id"] for r in snap["lots"]], ["a", "z"])
        self.assertEqual(
            [r["reservation_id"] for r in snap["reservations"]], ["a", "z"]
        )
        self.assertEqual(
            snap["reservations"][0]["allocations"],
            [{"lot_id": "z", "quantity": 1}, {"lot_id": "a", "quantity": 1}],
        )
        original = deepcopy(snap)
        snap["lots"][0]["available"] = -99
        snap["reservations"][0]["allocations"][0]["quantity"] = -99
        snap["lots"].clear()
        self.assertEqual(self.ledger.snapshot(), original)
        self.ledger.commit("a")
        self.assertEqual(original["reservations"][0]["status"], "active")
        self.assertEqual(original["lots"][0]["shipped"], 0)

    def test_copy_is_independent_in_both_directions(self):
        self.ledger.add("L", "X", 10, D)
        self.ledger.reserve("R", "X", 4)
        copied = self.ledger.copy()
        self.assertIsInstance(copied, Ledger)
        self.assertIsNot(copied, self.ledger)
        self.assertEqual(copied.snapshot(), self.ledger.snapshot())
        copied.cancel("R")
        copied.add("M", "X", 2)
        self.assert_counts("L", 6, 4, 0, 0)
        self.ledger.advance(NEXT)
        self.ledger.commit("R")
        self.assertEqual(self.lots(copied)["L"]["available"], 10)
        self.assertEqual(copied.snapshot()["today"], "2032-06-10")
        self.assertNotIn("M", self.lots())

    def test_replace_independence_backward_date_and_self(self):
        source = Ledger(date(2031, 1, 1))
        source.add("L", "X", 5)
        source.reserve("R", "X", 2)
        self.ledger.add("obsolete", "Y", 8)
        self.assertIsNone(self.ledger.replace_from(source))
        self.assertEqual(self.ledger.snapshot(), source.snapshot())
        source.cancel("R")
        self.assert_counts("L", 3, 2, 0, 0)
        self.ledger.commit("R")
        self.assertEqual(self.lots(source)["L"]["shipped"], 0)
        before = deepcopy(self.ledger.snapshot())
        self.assertIsNone(self.ledger.replace_from(self.ledger))
        self.assertEqual(self.ledger.snapshot(), before)

    def test_multiple_reservations_conserve_quantities(self):
        self.ledger.add("A", "X", 8, D)
        self.ledger.add("B", "X", 5)
        self.ledger.reserve("R1", "X", 3)
        self.ledger.reserve("R2", "X", 7)
        self.ledger.advance(NEXT)
        self.ledger.cancel("R1")
        self.ledger.commit("R2")
        self.assert_counts("A", 0, 0, 5, 3)
        self.assert_counts("B", 3, 0, 2, 0)
        self.assertEqual(
            self.ledger.reserve("R3", "X", 3), (("B", 3),)
        )


class OperationTests(unittest.TestCase):
    def test_prompt_example(self):
        ledger = Ledger(D)
        results = run(
            ledger,
            "ADD,L2,PART,4,\n"
            "ADD,L1,PART,3,2032-06-10\n"
            "RESERVE,R1,PART,5\n"
            "ADVANCE,2032-06-11\n"
            "CANCEL,R1\n",
        )
        allocations = (("L1", 3), ("L2", 2))
        self.assertEqual(results, [None, None, allocations, None, allocations])
        self.assertEqual(render(ledger), HEADER + "PART,4,0,0,3\n")

    def test_atomic_failure_restores_all_state(self):
        ledger = Ledger(D)
        ledger.add("L", "X", 5, D)
        ledger.reserve("old", "X", 2)
        before = deepcopy(ledger.snapshot())
        with self.assertRaises(ValueError):
            run(
                ledger,
                "COMMIT,old\n"
                "ADVANCE,2032-06-11\n"
                "ADD,new,X,3,\n"
                "RESERVE,new_r,X,2\n"
                "RESERVE,fail,X,2\n",
            )
        self.assertEqual(ledger.snapshot(), before)
        self.assertEqual(ledger.cancel("old"), (("L", 2),))
        ledger.add("new", "X", 3)
        self.assertEqual(ledger.reserve("new_r", "X", 1), (("L", 1),))

    def test_nonatomic_failure_keeps_prefix_and_stops(self):
        ledger = Ledger(D)
        ledger.add("L", "X", 5, D)
        with self.assertRaises(ValueError):
            run(
                ledger,
                "RESERVE,R,X,2\n"
                "ADVANCE,2032-06-11\n"
                "RESERVE,bad,X,1\n"
                "COMMIT,R\n",
                atomic=False,
            )
        snap = ledger.snapshot()
        self.assertEqual(snap["today"], "2032-06-11")
        self.assertEqual(snap["reservations"][0]["status"], "active")
        self.assertEqual(len(snap["reservations"]), 1)
        self.assertEqual(
            render(ledger), HEADER + "X,0,2,0,3\n"
        )

    def test_syntax_error_anywhere_precedes_business_application(self):
        bad_tails = [
            "UNKNOWN,L\n",
            "ADD,L,X,1\n",
            "ADD,L,X,1,,extra\n",
            "ADD,L,X,01,\n",
            "ADD,L,X,1,2032-02-30\n",
            'ADD,L,"unterminated,1,\n',
            " \t \n",
            '""\n',
        ]
        for atomic in (False, True):
            for tail in bad_tails:
                with self.subTest(atomic=atomic, tail=tail):
                    ledger = Ledger(D)
                    ledger.add("base", "X", 2)
                    before = deepcopy(ledger.snapshot())
                    with self.assertRaises(ValueError):
                        run(
                            ledger,
                            "RESERVE,R,X,1\n" + tail,
                            atomic=atomic,
                        )
                    self.assertEqual(ledger.snapshot(), before)

    def test_numeric_grammar_and_bounds(self):
        invalid = [
            "0", "-1", "+1", "01", "1.0", "1e2",
            "１", "١", "1 0", "", "1000000001",
        ]
        for quantity in invalid:
            for operation in (
                f"ADD,L,X,{quantity},\n",
                f"RESERVE,R,X,{quantity}\n",
            ):
                with self.subTest(operation=operation):
                    ledger = Ledger(D)
                    ledger.add("base", "X", 1_000_000_000)
                    before = ledger.snapshot()
                    with self.assertRaises(ValueError):
                        run(ledger, operation, atomic=False)
                    self.assertEqual(ledger.snapshot(), before)
        ledger = Ledger(D)
        self.assertEqual(
            run(
                ledger,
                "ADD,L,X,1000000000,\n"
                "RESERVE,R,X,1000000000\n"
                "COMMIT,R\n",
            ),
            [None, (("L", 1_000_000_000),), (("L", 1_000_000_000),)],
        )

    def test_date_grammar_and_calendar(self):
        invalid = [
            "", "20320611", "2032-6-11", "2032-06-1",
            "2032-W24-5", "2032-02-30", "2031-02-29",
            "0000-01-01", "２０３２-06-11",
        ]
        for value in invalid:
            with self.subTest(value=value):
                ledger = Ledger(D)
                before = ledger.snapshot()
                with self.assertRaises(ValueError):
                    run(ledger, f"ADVANCE,{value}\n")
                self.assertEqual(ledger.snapshot(), before)
        ledger = Ledger(date(2032, 2, 28))
        self.assertEqual(
            run(ledger, "ADD,L,X,1,2032-02-29\nADVANCE,2032-02-29\n"),
            [None, None],
        )
        self.assertEqual(render(ledger), HEADER + "X,1,0,0,0\n")
        run(ledger, "ADVANCE,2032-03-01\n")
        self.assertEqual(render(ledger), HEADER + "X,0,0,0,1\n")

    def test_date_extremes(self):
        ledger = Ledger(date.min)
        run(
            ledger,
            "ADD,min,X,1,0001-01-01\n"
            "ADD,max,X,1,9999-12-31\n"
            "ADD,none,X,1,\n"
            "ADVANCE,9999-12-31\n",
        )
        self.assertEqual(
            ledger.reserve("R", "X", 2),
            (("max", 1), ("none", 1)),
        )
        self.assertEqual(ledger.snapshot()["lots"][1]["expires"], "0001-01-01")

    def test_csv_quotes_multiline_and_ascii_trimming(self):
        ledger = Ledger(D)
        text = (
            "\n"
            ' ADD , "L,1" , " A,\n""B"" " , 3 , \t\n'
            'RESERVE, R ,"A,\n""B""", 2\n'
        )
        # csv.reader does not treat a quote after an unquoted leading space
        # as an opening quote. Use valid quoted cells for the actual input.
        text = (
            "\n"
            ' ADD ," L,1 "," A,\n""B"" ", 3 , \t\n'
            'RESERVE, R ,"A,\n""B""", 2\n'
        )
        self.assertEqual(
            run(ledger, text),
            [None, (("L,1", 2),)],
        )
        lot = ledger.snapshot()["lots"][0]
        self.assertEqual(lot["sku"], 'A,\n"B"')
        self.assertEqual(lot["lot_id"], "L,1")
        rows = list(csv.reader(io.StringIO(render(ledger), newline="")))
        self.assertEqual(
            rows,
            [
                ["sku", "available", "held", "shipped", "expired"],
                ['A,\n"B"', "1", "2", "0", "0"],
            ],
        )

    def test_only_ascii_space_and_tab_are_trimmed(self):
        ledger = Ledger(D)
        nbsp = "\u00a0"
        self.assertEqual(
            run(
                ledger,
                f"ADD,{nbsp}L{nbsp},{nbsp}X{nbsp},1,\n"
                f"RESERVE,{nbsp}R{nbsp},{nbsp}X{nbsp},1\n",
            ),
            [None, ((f"{nbsp}L{nbsp}", 1),)],
        )
        self.assertEqual(
            ledger.snapshot()["reservations"][0]["reservation_id"],
            f"{nbsp}R{nbsp}",
        )

    def test_empty_names_unknown_ops_and_record_rules(self):
        invalid = [
            "ADD,,X,1,\n",
            "ADD,L, \t,1,\n",
            "RESERVE,,X,1\n",
            "RESERVE,R,,1\n",
            "CANCEL, \t\n",
            "COMMIT,\n",
            "add,L,X,1,\n",
            "\ufeffADD,L,X,1,\n",
            "# comment\n",
            "operation,id\n",
            ",\n",
            "CANCEL,R,extra\n",
            "ADVANCE,2032-06-11,extra\n",
        ]
        for text in invalid:
            with self.subTest(text=text):
                ledger = Ledger(D)
                before = ledger.snapshot()
                with self.assertRaises(ValueError):
                    run(ledger, text)
                self.assertEqual(ledger.snapshot(), before)

    def test_crlf_input_and_terminal_results(self):
        ledger = Ledger(D)
        self.assertEqual(
            run(
                ledger,
                "\r\nADD,L,X,3,\r\n"
                "RESERVE,R,X,2\r\nCOMMIT,R\r\nCOMMIT,R\r\n",
                atomic=False,
            ),
            [None, (("L", 2),), (("L", 2),), (("L", 2),)],
        )
        self.assertEqual(render(ledger), HEADER + "X,1,0,2,0\n")

    def test_atomic_success_updates_original_object(self):
        ledger = Ledger(D)
        alias = ledger
        old_snapshot = ledger.snapshot()
        self.assertEqual(run(ledger, "ADD,L,X,2,\n"), [None])
        self.assertIs(alias, ledger)
        self.assertEqual(render(alias), HEADER + "X,2,0,0,0\n")
        self.assertEqual(old_snapshot["lots"], [])
        before = ledger.snapshot()
        self.assertEqual(run(ledger, ""), [])
        self.assertEqual(ledger.snapshot(), before)

    def test_duplicate_add_is_business_error(self):
        for atomic in (False, True):
            with self.subTest(atomic=atomic):
                ledger = Ledger(D)
                with self.assertRaises(ValueError):
                    run(
                        ledger,
                        "ADD,L,X,1,\nADD,L,Y,2,\nADD,M,X,1,\n",
                        atomic=atomic,
                    )
                expected = HEADER if atomic else HEADER + "X,1,0,0,0\n"
                self.assertEqual(render(ledger), expected)

    def test_backward_day_is_business_error(self):
        ledger = Ledger(D)
        with self.assertRaises(ValueError):
            run(
                ledger,
                "ADD,L,X,1,\nADVANCE,2032-06-09\n",
                atomic=False,
            )
        self.assertEqual(render(ledger), HEADER + "X,1,0,0,0\n")
        self.assertEqual(ledger.snapshot()["today"], "2032-06-10")


class ReportTests(unittest.TestCase):
    def test_aggregation_order_zero_available_and_no_mutation(self):
        ledger = Ledger(D)
        ledger.add("z1", "z", 2)
        ledger.add("a1", "A", 4, D)
        ledger.add("a2", "A", 5)
        ledger.add("b1", "a", 3, D)
        ledger.reserve("r1", "A", 6)
        ledger.commit("r1")
        ledger.reserve("r2", "z", 2)
        ledger.advance(NEXT)
        before = deepcopy(ledger.snapshot())
        self.assertEqual(
            render(ledger),
            HEADER + "A,3,0,6,0\na,0,0,0,3\nz,0,2,0,0\n",
        )
        self.assertEqual(ledger.snapshot(), before)

    def test_csv_escaping_and_unicode_sort(self):
        ledger = Ledger(D)
        ledger.add("L1", '部品,"甲"\n乙', 2)
        ledger.add("L2", " Z ", 1)
        ledger.add("L3", "A,B", 3)
        before = ledger.snapshot()
        self.assertEqual(
            render(ledger),
            HEADER
            + " Z ,1,0,0,0\n"
            + '"A,B",3,0,0,0\n'
            + '"部品,""甲""\n乙",2,0,0,0\n',
        )
        self.assertEqual(ledger.snapshot(), before)


if __name__ == "__main__":
    unittest.main()

=== END ===
