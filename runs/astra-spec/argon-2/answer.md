=== FILE: warehouse.py ===
from dataclasses import dataclass


@dataclass
class _Lot:
    id: str
    sku: str
    expires: int | None
    on_hand: int
    reserved: int
    seq: int

    def copy(self) -> "_Lot":
        return _Lot(
            id=self.id,
            sku=self.sku,
            expires=self.expires,
            on_hand=self.on_hand,
            reserved=self.reserved,
            seq=self.seq,
        )


@dataclass
class _Hold:
    id: str
    sku: str
    until: int
    allocations: list[tuple[str, int]]

    def copy(self) -> "_Hold":
        return _Hold(
            id=self.id,
            sku=self.sku,
            until=self.until,
            allocations=list(self.allocations),
        )


class _State:
    def __init__(self) -> None:
        self.now: int = 0
        self.lots: dict[str, _Lot] = {}
        self.holds: dict[str, _Hold] = {}
        self.used_lot_ids: set[str] = set()
        self.used_hold_ids: set[str] = set()
        self.lot_seq: int = 0

    def copy(self) -> "_State":
        new_state = _State()
        new_state.now = self.now
        new_state.lots = {k: v.copy() for k, v in self.lots.items()}
        new_state.holds = {k: v.copy() for k, v in self.holds.items()}
        new_state.used_lot_ids = set(self.used_lot_ids)
        new_state.used_hold_ids = set(self.used_hold_ids)
        new_state.lot_seq = self.lot_seq
        return new_state

    def _remove_hold(self, hold_id: str) -> _Hold:
        hold = self.holds.pop(hold_id)
        for lot_id, qty in hold.allocations:
            self.lots[lot_id].reserved -= qty
        return hold

    def _advance_time(self, at: int) -> None:
        if at < self.now:
            raise ValueError("Event timestamp precedes current time")
        self.now = at

        expired_lots = {
            lot_id
            for lot_id, lot in self.lots.items()
            if lot.expires is not None and lot.expires <= at
        }

        holds_to_remove = [
            hold_id
            for hold_id, hold in self.holds.items()
            if hold.until <= at
            or any(lot_id in expired_lots for lot_id, _ in hold.allocations)
        ]

        for hold_id in holds_to_remove:
            self._remove_hold(hold_id)

        for lot_id in expired_lots:
            del self.lots[lot_id]

    def _allocate(self, sku: str, quantity: int) -> list[tuple[str, int]]:
        candidates = [
            lot
            for lot in self.lots.values()
            if lot.sku == sku and (lot.on_hand - lot.reserved) > 0
        ]
        candidates.sort(
            key=lambda lot: (
                lot.expires is None,
                lot.expires if lot.expires is not None else 0,
                lot.seq,
            )
        )

        allocations: list[tuple[str, int]] = []
        remaining = quantity
        for lot in candidates:
            if remaining == 0:
                break
            avail = lot.on_hand - lot.reserved
            take = min(remaining, avail)
            if take > 0:
                allocations.append((lot.id, take))
                remaining -= take

        if remaining > 0:
            raise ValueError("Insufficient available inventory")

        for lot_id, take in allocations:
            self.lots[lot_id].reserved += take

        return allocations

    def process_event(self, event: dict) -> None:
        at = event["at"]
        self._advance_time(at)

        op = event["op"]
        if op == "receive":
            lot_id = event["lot"]
            sku = event["sku"]
            quantity = event["quantity"]
            expires = event["expires"]

            if lot_id in self.used_lot_ids:
                raise ValueError("Lot ID already used")
            if expires is not None and expires <= at:
                raise ValueError("Lot already expired")

            self.used_lot_ids.add(lot_id)
            self.lots[lot_id] = _Lot(
                id=lot_id,
                sku=sku,
                expires=expires,
                on_hand=quantity,
                reserved=0,
                seq=self.lot_seq,
            )
            self.lot_seq += 1

        elif op == "reserve":
            hold_id = event["hold"]
            sku = event["sku"]
            quantity = event["quantity"]
            until = event["until"]

            if hold_id in self.used_hold_ids:
                raise ValueError("Hold ID already used")
            if until <= at:
                raise ValueError("Hold already expired")

            allocations = self._allocate(sku, quantity)
            self.used_hold_ids.add(hold_id)
            self.holds[hold_id] = _Hold(
                id=hold_id,
                sku=sku,
                until=until,
                allocations=allocations,
            )

        elif op == "resize":
            hold_id = event["hold"]
            quantity = event["quantity"]
            until = event["until"]

            if hold_id not in self.holds:
                raise ValueError("Hold not found")
            if until <= at:
                raise ValueError("Hold already expired")

            old_hold = self._remove_hold(hold_id)
            allocations = self._allocate(old_hold.sku, quantity)
            self.holds[hold_id] = _Hold(
                id=hold_id,
                sku=old_hold.sku,
                until=until,
                allocations=allocations,
            )

        elif op == "ship":
            hold_id = event["hold"]
            quantity = event["quantity"]

            if hold_id not in self.holds:
                raise ValueError("Hold not found")

            hold = self.holds[hold_id]
            total_held = sum(qty for _, qty in hold.allocations)
            if quantity > total_held:
                raise ValueError("Ship quantity exceeds held quantity")

            remaining = quantity
            new_allocations: list[tuple[str, int]] = []
            for lot_id, qty in hold.allocations:
                if remaining > 0:
                    take = min(remaining, qty)
                    lot = self.lots[lot_id]
                    lot.on_hand -= take
                    lot.reserved -= take
                    remaining -= take
                    left = qty - take
                    if left > 0:
                        new_allocations.append((lot_id, left))
                else:
                    new_allocations.append((lot_id, qty))

            if new_allocations:
                hold.allocations = new_allocations
            else:
                del self.holds[hold_id]

        elif op == "release":
            hold_id = event["hold"]
            if hold_id not in self.holds:
                raise ValueError("Hold not found")
            self._remove_hold(hold_id)

        elif op == "tick":
            pass

        else:
            raise ValueError(f"Unknown operation: {op}")

    def snapshot(self) -> dict:
        lots_list = []
        for lot_id in sorted(self.lots.keys()):
            lot = self.lots[lot_id]
            lots_list.append(
                {
                    "id": lot.id,
                    "sku": lot.sku,
                    "expires": lot.expires,
                    "on_hand": lot.on_hand,
                    "reserved": lot.reserved,
                    "available": lot.on_hand - lot.reserved,
                }
            )

        holds_list = []
        for hold_id in sorted(self.holds.keys()):
            hold = self.holds[hold_id]
            qty_sum = sum(qty for _, qty in hold.allocations)
            allocs_list = [
                {"lot": lot_id, "quantity": qty}
                for lot_id, qty in hold.allocations
            ]
            holds_list.append(
                {
                    "id": hold.id,
                    "sku": hold.sku,
                    "until": hold.until,
                    "quantity": qty_sum,
                    "allocations": allocs_list,
                }
            )

        return {
            "now": self.now,
            "lots": lots_list,
            "holds": holds_list,
        }


class Warehouse:
    def __init__(self) -> None:
        self._state = _State()

    def apply(self, events: list[dict]) -> list[dict]:
        if not events:
            return []

        working_state = self._state.copy()
        snapshots: list[dict] = []

        for event in events:
            working_state.process_event(event)
            snapshots.append(working_state.snapshot())

        self._state = working_state
        return snapshots

    def snapshot(self) -> dict:
        return self._state.snapshot()
=== END ===
