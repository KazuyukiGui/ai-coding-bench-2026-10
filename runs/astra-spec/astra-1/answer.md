=== FILE: warehouse.py ===
from copy import deepcopy


class Warehouse:
    def __init__(self):
        self._now = 0
        self._lots = {}
        self._holds = {}
        self._used_lots = set()
        self._used_holds = set()
        self._next_order = 0

    def apply(self, events):
        if not events:
            return []

        working = deepcopy(self)
        snapshots = []
        for event in events:
            working._process(event)
            snapshots.append(working.snapshot())

        self.__dict__.update(working.__dict__)
        return snapshots

    def snapshot(self):
        reserved = self._reserved()
        return {
            "now": self._now,
            "lots": [
                {
                    "id": lot_id,
                    "sku": lot["sku"],
                    "expires": lot["expires"],
                    "on_hand": lot["on_hand"],
                    "reserved": reserved.get(lot_id, 0),
                    "available": lot["on_hand"] - reserved.get(lot_id, 0),
                }
                for lot_id, lot in sorted(self._lots.items())
            ],
            "holds": [
                {
                    "id": hold_id,
                    "sku": hold["sku"],
                    "until": hold["until"],
                    "quantity": sum(q for _, q in hold["allocations"]),
                    "allocations": [
                        {"lot": lot_id, "quantity": quantity}
                        for lot_id, quantity in hold["allocations"]
                    ],
                }
                for hold_id, hold in sorted(self._holds.items())
            ],
        }

    def _reserved(self):
        reserved = {}
        for hold in self._holds.values():
            for lot_id, quantity in hold["allocations"]:
                reserved[lot_id] = reserved.get(lot_id, 0) + quantity
        return reserved

    def _advance(self, at):
        if at < self._now:
            raise ValueError("Time cannot move backwards")
        self._now = at

        expired = {
            lot_id
            for lot_id, lot in self._lots.items()
            if lot["expires"] is not None and lot["expires"] <= at
        }
        self._holds = {
            hold_id: hold
            for hold_id, hold in self._holds.items()
            if hold["until"] > at
            and not any(
                lot_id in expired for lot_id, _ in hold["allocations"]
            )
        }
        for lot_id in expired:
            del self._lots[lot_id]

    def _allocate(self, sku, quantity):
        reserved = self._reserved()
        candidates = [
            (lot_id, lot)
            for lot_id, lot in self._lots.items()
            if lot["sku"] == sku
        ]
        candidates.sort(
            key=lambda item: (
                item[1]["expires"] is None,
                item[1]["expires"] if item[1]["expires"] is not None else 0,
                item[1]["order"],
            )
        )

        allocations = []
        remaining = quantity
        for lot_id, lot in candidates:
            available = lot["on_hand"] - reserved.get(lot_id, 0)
            taken = min(available, remaining)
            if taken > 0:
                allocations.append((lot_id, taken))
                remaining -= taken
            if remaining == 0:
                return allocations

        raise ValueError("Insufficient available stock")

    def _process(self, event):
        self._advance(event["at"])
        op = event["op"]

        if op == "tick":
            return

        if op == "receive":
            lot_id = event["lot"]
            expires = event["expires"]
            if lot_id in self._used_lots:
                raise ValueError("Lot ID has already been used")
            if expires is not None and expires <= self._now:
                raise ValueError("Lot must expire in the future")

            self._lots[lot_id] = {
                "sku": event["sku"],
                "expires": expires,
                "on_hand": event["quantity"],
                "order": self._next_order,
            }
            self._next_order += 1
            self._used_lots.add(lot_id)
            return

        hold_id = event["hold"]

        if op == "reserve":
            if hold_id in self._used_holds:
                raise ValueError("Hold ID has already been used")
            if event["until"] <= self._now:
                raise ValueError("Hold must expire in the future")

            allocations = self._allocate(event["sku"], event["quantity"])
            self._holds[hold_id] = {
                "sku": event["sku"],
                "until": event["until"],
                "allocations": allocations,
            }
            self._used_holds.add(hold_id)
            return

        if hold_id not in self._holds:
            raise ValueError("Hold does not exist")

        if op == "release":
            del self._holds[hold_id]
            return

        if op == "resize":
            if event["until"] <= self._now:
                raise ValueError("Hold must expire in the future")

            hold = self._holds.pop(hold_id)
            allocations = self._allocate(hold["sku"], event["quantity"])
            self._holds[hold_id] = {
                "sku": hold["sku"],
                "until": event["until"],
                "allocations": allocations,
            }
            return

        if op == "ship":
            hold = self._holds[hold_id]
            remaining = event["quantity"]
            total = sum(quantity for _, quantity in hold["allocations"])
            if remaining > total:
                raise ValueError("Shipment exceeds remaining hold quantity")

            allocations = []
            for lot_id, quantity in hold["allocations"]:
                shipped = min(quantity, remaining)
                self._lots[lot_id]["on_hand"] -= shipped
                remaining -= shipped
                quantity -= shipped
                if quantity > 0:
                    allocations.append((lot_id, quantity))

            if allocations:
                hold["allocations"] = allocations
            else:
                del self._holds[hold_id]
=== END ===