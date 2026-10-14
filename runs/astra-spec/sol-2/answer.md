=== FILE: warehouse.py ===
from copy import deepcopy


class Warehouse:
    def __init__(self):
        self._now = 0
        self._lots = {}
        self._holds = {}
        self._used_lot_ids = set()
        self._used_hold_ids = set()
        self._next_receive_order = 0

    def apply(self, events):
        if not events:
            return []

        backup = (
            self._now,
            deepcopy(self._lots),
            deepcopy(self._holds),
            set(self._used_lot_ids),
            set(self._used_hold_ids),
            self._next_receive_order,
        )

        snapshots = []
        try:
            for event in events:
                self._advance(event["at"])
                self._apply_event(event)
                snapshots.append(self.snapshot())
        except ValueError:
            (
                self._now,
                self._lots,
                self._holds,
                self._used_lot_ids,
                self._used_hold_ids,
                self._next_receive_order,
            ) = backup
            raise

        return snapshots

    def snapshot(self):
        reserved_by_lot = self._reserved_by_lot()

        lots = []
        for lot_id in sorted(self._lots):
            lot = self._lots[lot_id]
            reserved = reserved_by_lot.get(lot_id, 0)
            lots.append(
                {
                    "id": lot_id,
                    "sku": lot["sku"],
                    "expires": lot["expires"],
                    "on_hand": lot["on_hand"],
                    "reserved": reserved,
                    "available": lot["on_hand"] - reserved,
                }
            )

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
            holds.append(
                {
                    "id": hold_id,
                    "sku": hold["sku"],
                    "until": hold["until"],
                    "quantity": sum(
                        allocation["quantity"]
                        for allocation in hold["allocations"]
                    ),
                    "allocations": allocations,
                }
            )

        return {
            "now": self._now,
            "lots": lots,
            "holds": holds,
        }

    def _advance(self, at):
        if at < self._now:
            raise ValueError("time cannot move backwards")

        self._now = at
        expired_lots = {
            lot_id
            for lot_id, lot in self._lots.items()
            if lot["expires"] is not None and lot["expires"] <= at
        }

        holds_to_remove = [
            hold_id
            for hold_id, hold in self._holds.items()
            if hold["until"] <= at
            or any(
                allocation["lot"] in expired_lots
                for allocation in hold["allocations"]
            )
        ]

        for hold_id in holds_to_remove:
            del self._holds[hold_id]

        for lot_id in expired_lots:
            del self._lots[lot_id]

    def _apply_event(self, event):
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

        if lot_id in self._used_lot_ids:
            raise ValueError("lot ID has already been used")
        if expires is not None and expires <= self._now:
            raise ValueError("lot is already expired")

        self._lots[lot_id] = {
            "sku": event["sku"],
            "expires": expires,
            "on_hand": event["quantity"],
            "order": self._next_receive_order,
        }
        self._used_lot_ids.add(lot_id)
        self._next_receive_order += 1

    def _reserve(self, event):
        hold_id = event["hold"]

        if hold_id in self._used_hold_ids:
            raise ValueError("hold ID has already been used")
        if event["until"] <= self._now:
            raise ValueError("hold has already expired")

        allocations = self._allocate(event["sku"], event["quantity"])
        self._holds[hold_id] = {
            "sku": event["sku"],
            "until": event["until"],
            "allocations": allocations,
        }
        self._used_hold_ids.add(hold_id)

    def _resize(self, event):
        hold_id = event["hold"]

        if hold_id not in self._holds:
            raise ValueError("hold does not exist")
        if event["until"] <= self._now:
            raise ValueError("hold has already expired")

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
        remaining_quantity = sum(
            allocation["quantity"] for allocation in hold["allocations"]
        )
        if event["quantity"] > remaining_quantity:
            raise ValueError("shipment exceeds reserved quantity")

        to_ship = event["quantity"]
        for allocation in hold["allocations"]:
            if to_ship == 0:
                break
            shipped = min(to_ship, allocation["quantity"])
            self._lots[allocation["lot"]]["on_hand"] -= shipped
            allocation["quantity"] -= shipped
            to_ship -= shipped

        hold["allocations"] = [
            allocation
            for allocation in hold["allocations"]
            if allocation["quantity"] > 0
        ]

        if not hold["allocations"]:
            del self._holds[hold_id]

    def _release(self, event):
        hold_id = event["hold"]
        if hold_id not in self._holds:
            raise ValueError("hold does not exist")
        del self._holds[hold_id]

    def _allocate(self, sku, quantity):
        reserved_by_lot = self._reserved_by_lot()
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

        remaining = quantity
        allocations = []

        for lot_id, lot in candidates:
            available = lot["on_hand"] - reserved_by_lot.get(lot_id, 0)
            allocated = min(available, remaining)
            if allocated > 0:
                allocations.append(
                    {
                        "lot": lot_id,
                        "quantity": allocated,
                    }
                )
                remaining -= allocated
            if remaining == 0:
                break

        if remaining:
            raise ValueError("insufficient available inventory")

        return allocations

    def _reserved_by_lot(self):
        reserved = {}
        for hold in self._holds.values():
            for allocation in hold["allocations"]:
                lot_id = allocation["lot"]
                reserved[lot_id] = (
                    reserved.get(lot_id, 0) + allocation["quantity"]
                )
        return reserved
=== END ===