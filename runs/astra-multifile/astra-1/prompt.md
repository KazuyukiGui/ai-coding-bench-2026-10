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
- 空文字のセルがあるレコードや空白だけのレコードは無視せず、通常のレコードとして検証します。
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

添付ファイル:
=== FILE: inventory.py ===
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
=== FILE: operations.py ===
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
=== FILE: reporting.py ===
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
=== END ===

答え方: 次のファイルの全体（変更しないファイルは不要）を、説明なしで、次の形式だけで返してください。各ファイルは「=== FILE: パス ===」の行で始め、最後に「=== END ===」の行を置きます。ツールは使えません。Python 3.11・標準ライブラリのみ。
返すファイル: inventory.py、operations.py、reporting.py
