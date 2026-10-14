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
