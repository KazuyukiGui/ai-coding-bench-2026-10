=== FILE: warehouse.py ===
import copy


class Warehouse:
    def __init__(self):
        self._now = 0
        self._lots = {}
        self._holds = {}
        self._used_lots = set()
        self._used_holds = set()
        self._seq = 0

    def apply(self, events):
        saved = (
            self._now,
            copy.deepcopy(self._lots),
            copy.deepcopy(self._holds),
            set(self._used_lots),
            set(self._used_holds),
            self._seq,
        )
        results = []
        try:
            for event in events:
                self._process(event)
                results.append(self.snapshot())
        except ValueError:
            (
                self._now,
                self._lots,
                self._holds,
                self._used_lots,
                self._used_holds,
                self._seq,
            ) = saved
            raise
        return results

    def snapshot(self):
        reserved = self._reserved_by_lot()
        lots = []
        for lot_id in sorted(self._lots):
            lot = self._lots[lot_id]
            r = reserved.get(lot_id, 0)
            lots.append(
                {
                    "id": lot_id,
                    "sku": lot["sku"],
                    "expires": lot["expires"],
                    "on_hand": lot["on_hand"],
                    "reserved": r,
                    "available": lot["on_hand"] - r,
                }
            )
        holds = []
        for hold_id in sorted(self._holds):
            hold = self._holds[hold_id]
            holds.append(
                {
                    "id": hold_id,
                    "sku": hold["sku"],
                    "until": hold["until"],
                    "quantity": sum(q for _, q in hold["allocations"]),
                    "allocations": [
                        {"lot": lot_id, "quantity": q}
                        for lot_id, q in hold["allocations"]
                    ],
                }
            )
        return {"now": self._now, "lots": lots, "holds": holds}

    def _reserved_by_lot(self):
        reserved = {}
        for hold in self._holds.values():
            for lot_id, q in hold["allocations"]:
                reserved[lot_id] = reserved.get(lot_id, 0) + q
        return reserved

    def _advance(self, at):
        if at < self._now:
            raise ValueError("time went backwards")
        self._now = at
        expired = {
            lot_id
            for lot_id, lot in self._lots.items()
            if lot["expires"] is not None and lot["expires"] <= at
        }
        for hold_id in list(self._holds):
            hold = self._holds[hold_id]
            if hold["until"] <= at or any(
                lot_id in expired for lot_id, _ in hold["allocations"]
            ):
                del self._holds[hold_id]
        for lot_id in expired:
            del self._lots[lot_id]

    def _allocate(self, sku, quantity):
        reserved = self._reserved_by_lot()
        candidates = [
            (lot_id, lot)
            for lot_id, lot in self._lots.items()
            if lot["sku"] == sku
        ]

        def key(item):
            lot = item[1]
            if lot["expires"] is None:
                return (1, 0, lot["seq"])
            return (0, lot["expires"], lot["seq"])

        candidates.sort(key=key)
        allocations = []
        remaining = quantity
        for lot_id, lot in candidates:
            if remaining == 0:
                break
            avail = lot["on_hand"] - reserved.get(lot_id, 0)
            if avail <= 0:
                continue
            take = min(avail, remaining)
            allocations.append([lot_id, take])
            remaining -= take
        if remaining > 0:
            raise ValueError("insufficient stock")
        return allocations

    def _process(self, event):
        at = event["at"]
        self._advance(at)
        op = event["op"]

        if op == "receive":
            lot_id = event["lot"]
            expires = event["expires"]
            if lot_id in self._used_lots:
                raise ValueError("lot id already used")
            if expires is not None and expires <= at:
                raise ValueError("lot already expired")
            self._lots[lot_id] = {
                "sku": event["sku"],
                "expires": expires,
                "on_hand": event["quantity"],
                "seq": self._seq,
            }
            self._seq += 1
            self._used_lots.add(lot_id)

        elif op == "reserve":
            hold_id = event["hold"]
            until = event["until"]
            if hold_id in self._used_holds:
                raise ValueError("hold id already used")
            if until <= at:
                raise ValueError("invalid until")
            allocations = self._allocate(event["sku"], event["quantity"])
            self._holds[hold_id] = {
                "sku": event["sku"],
                "until": until,
                "allocations": allocations,
            }
            self._used_holds.add(hold_id)

        elif op == "resize":
            hold_id = event["hold"]
            until = event["until"]
            if hold_id not in self._holds:
                raise ValueError("unknown hold")
            if until <= at:
                raise ValueError("invalid until")
            hold = self._holds.pop(hold_id)
            allocations = self._allocate(hold["sku"], event["quantity"])
            self._holds[hold_id] = {
                "sku": hold["sku"],
                "until": until,
                "allocations": allocations,
            }

        elif op == "ship":
            hold_id = event["hold"]
            if hold_id not in self._holds:
                raise ValueError("unknown hold")
            hold = self._holds[hold_id]
            total = sum(q for _, q in hold["allocations"])
            quantity = event["quantity"]
            if quantity > total:
                raise ValueError("ship quantity exceeds hold")
            remaining = quantity
            new_allocations = []
            for lot_id, q in hold["allocations"]:
                take = min(q, remaining)
                if take > 0:
                    self._lots[lot_id]["on_hand"] -= take
                    remaining -= take
                left = q - take
                if left > 0:
                    new_allocations.append([lot_id, left])
            if new_allocations:
                hold["allocations"] = new_allocations
            else:
                del self._holds[hold_id]

        elif op == "release":
            hold_id = event["hold"]
            if hold_id not in self._holds:
                raise ValueError("unknown hold")
            del self._holds[hold_id]

        elif op == "tick":
            pass
=== END ===