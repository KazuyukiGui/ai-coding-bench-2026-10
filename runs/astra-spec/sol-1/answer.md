=== FILE: warehouse.py ===
class Warehouse:
    def __init__(self):
        self._now = 0
        self._lots = {}
        self._holds = {}
        self._used_lots = set()
        self._used_holds = set()
        self._next_order = 0

    def apply(self, events):
        working = Warehouse.__new__(Warehouse)
        working._now = self._now
        working._lots = {
            lot_id: lot.copy()
            for lot_id, lot in self._lots.items()
        }
        working._holds = {
            hold_id: {
                "sku": hold["sku"],
                "until": hold["until"],
                "allocations": [
                    allocation.copy()
                    for allocation in hold["allocations"]
                ],
            }
            for hold_id, hold in self._holds.items()
        }
        working._used_lots = self._used_lots.copy()
        working._used_holds = self._used_holds.copy()
        working._next_order = self._next_order

        snapshots = []
        for event in events:
            working._apply_event(event)
            snapshots.append(working.snapshot())

        self._now = working._now
        self._lots = working._lots
        self._holds = working._holds
        self._used_lots = working._used_lots
        self._used_holds = working._used_holds
        self._next_order = working._next_order

        return snapshots

    def snapshot(self):
        reserved = {lot_id: 0 for lot_id in self._lots}
        for hold in self._holds.values():
            for allocation in hold["allocations"]:
                reserved[allocation["lot"]] += allocation["quantity"]

        lots = []
        for lot_id in sorted(self._lots):
            lot = self._lots[lot_id]
            lot_reserved = reserved[lot_id]
            lots.append({
                "id": lot_id,
                "sku": lot["sku"],
                "expires": lot["expires"],
                "on_hand": lot["on_hand"],
                "reserved": lot_reserved,
                "available": lot["on_hand"] - lot_reserved,
            })

        holds = []
        for hold_id in sorted(self._holds):
            hold = self._holds[hold_id]
            allocations = [
                {
                    "lot": allocation["lot"],
                    "quantity": allocation["quantity"],
                }
                for allocation in hold["allocations"]
            ]
            holds.append({
                "id": hold_id,
                "sku": hold["sku"],
                "until": hold["until"],
                "quantity": sum(
                    allocation["quantity"] for allocation in allocations
                ),
                "allocations": allocations,
            })

        return {
            "now": self._now,
            "lots": lots,
            "holds": holds,
        }

    def _apply_event(self, event):
        at = event["at"]
        if at < self._now:
            raise ValueError("time cannot move backwards")

        self._now = at
        self._expire(at)

        op = event["op"]
        if op == "receive":
            self._receive(event)
        elif op == "reserve":
            self._reserve(event)
        elif op == "resize":
            self._resize(event)
        elif op == "ship":
            self._ship(event)
        elif op == "release":
            self._release(event)
        elif op == "tick":
            return

    def _expire(self, at):
        expired_lots = {
            lot_id
            for lot_id, lot in self._lots.items()
            if lot["expires"] is not None and lot["expires"] <= at
        }

        expired_holds = []
        for hold_id, hold in self._holds.items():
            uses_expired_lot = any(
                allocation["lot"] in expired_lots
                for allocation in hold["allocations"]
            )
            if hold["until"] <= at or uses_expired_lot:
                expired_holds.append(hold_id)

        for hold_id in expired_holds:
            del self._holds[hold_id]

        for lot_id in expired_lots:
            del self._lots[lot_id]

    def _receive(self, event):
        lot_id = event["lot"]
        expires = event["expires"]

        if lot_id in self._used_lots:
            raise ValueError("lot ID has already been used")
        if expires is not None and expires <= event["at"]:
            raise ValueError("lot is already expired")

        self._lots[lot_id] = {
            "sku": event["sku"],
            "expires": expires,
            "on_hand": event["quantity"],
            "order": self._next_order,
        }
        self._next_order += 1
        self._used_lots.add(lot_id)

    def _reserve(self, event):
        hold_id = event["hold"]

        if hold_id in self._used_holds:
            raise ValueError("hold ID has already been used")
        if event["until"] <= event["at"]:
            raise ValueError("hold is already expired")

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
        if event["until"] <= event["at"]:
            raise ValueError("hold is already expired")

        sku = self._holds[hold_id]["sku"]
        del self._holds[hold_id]
        allocations = self._allocate(sku, event["quantity"])
        self._holds[hold_id] = {
            "sku": sku,
            "until": event["until"],
            "allocations": allocations,
        }

    def _ship(self, event):
        hold_id = event["hold"]
        if hold_id not in self._holds:
            raise ValueError("hold does not exist")

        hold = self._holds[hold_id]
        held_quantity = sum(
            allocation["quantity"] for allocation in hold["allocations"]
        )
        if event["quantity"] > held_quantity:
            raise ValueError("shipment exceeds held quantity")

        remaining = event["quantity"]
        new_allocations = []

        for allocation in hold["allocations"]:
            shipped = min(remaining, allocation["quantity"])
            if shipped:
                self._lots[allocation["lot"]]["on_hand"] -= shipped
                remaining -= shipped

            allocation_remaining = allocation["quantity"] - shipped
            if allocation_remaining:
                new_allocations.append({
                    "lot": allocation["lot"],
                    "quantity": allocation_remaining,
                })

        if new_allocations:
            hold["allocations"] = new_allocations
        else:
            del self._holds[hold_id]

    def _release(self, event):
        hold_id = event["hold"]
        if hold_id not in self._holds:
            raise ValueError("hold does not exist")
        del self._holds[hold_id]

    def _allocate(self, sku, quantity):
        reserved = {lot_id: 0 for lot_id in self._lots}
        for hold in self._holds.values():
            for allocation in hold["allocations"]:
                reserved[allocation["lot"]] += allocation["quantity"]

        candidates = [
            (lot_id, lot)
            for lot_id, lot in self._lots.items()
            if lot["sku"] == sku
        ]
        candidates.sort(key=lambda item: (
            item[1]["expires"] is None,
            item[1]["expires"] if item[1]["expires"] is not None else 0,
            item[1]["order"],
        ))

        remaining = quantity
        allocations = []

        for lot_id, lot in candidates:
            available = lot["on_hand"] - reserved[lot_id]
            allocated = min(remaining, available)
            if allocated:
                allocations.append({
                    "lot": lot_id,
                    "quantity": allocated,
                })
                remaining -= allocated
            if remaining == 0:
                break

        if remaining:
            raise ValueError("insufficient available inventory")

        return allocations
=== END ===