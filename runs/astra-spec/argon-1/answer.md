=== FILE: warehouse.py ===
from dataclasses import dataclass


@dataclass
class _Lot:
    id: str
    sku: str
    expires: int | None
    on_hand: int
    seq: int

    def copy(self) -> "_Lot":
        return _Lot(self.id, self.sku, self.expires, self.on_hand, self.seq)


@dataclass
class _Hold:
    id: str
    sku: str
    until: int
    allocations: list[tuple[str, int]]

    def copy(self) -> "_Hold":
        return _Hold(self.id, self.sku, self.until, list(self.allocations))


class _State:
    def __init__(self) -> None:
        self.now: int = 0
        self.next_seq: int = 0
        self.used_lot_ids: set[str] = set()
        self.used_hold_ids: set[str] = set()
        self.lots: dict[str, _Lot] = {}
        self.holds: dict[str, _Hold] = {}

    def copy(self) -> "_State":
        new_state = _State()
        new_state.now = self.now
        new_state.next_seq = self.next_seq
        new_state.used_lot_ids = set(self.used_lot_ids)
        new_state.used_hold_ids = set(self.used_hold_ids)
        new_state.lots = {k: v.copy() for k, v in self.lots.items()}
        new_state.holds = {k: v.copy() for k, v in self.holds.items()}
        return new_state


class Warehouse:
    def __init__(self) -> None:
        self._state = _State()

    def snapshot(self) -> dict:
        return self._make_snapshot(self._state)

    def apply(self, events: list[dict]) -> list[dict]:
        if not events:
            return []

        work_state = self._state.copy()
        snapshots: list[dict] = []

        for event in events:
            self._process_event(work_state, event)
            snapshots.append(self._make_snapshot(work_state))

        self._state = work_state
        return snapshots

    def _process_event(self, state: _State, event: dict) -> None:
        at = event["at"]
        if at < state.now:
            raise ValueError("Event timestamp precedes current warehouse time")

        state.now = at

        expired_lots = {
            lot_id
            for lot_id, lot in state.lots.items()
            if lot.expires is not None and lot.expires <= at
        }

        holds_to_remove = [
            hold_id
            for hold_id, hold in state.holds.items()
            if hold.until <= at
            or any(lot_id in expired_lots for lot_id, _ in hold.allocations)
        ]
        for hold_id in holds_to_remove:
            del state.holds[hold_id]

        for lot_id in expired_lots:
            del state.lots[lot_id]

        op = event["op"]
        if op == "receive":
            self._op_receive(state, event, at)
        elif op == "reserve":
            self._op_reserve(state, event, at)
        elif op == "resize":
            self._op_resize(state, event, at)
        elif op == "ship":
            self._op_ship(state, event)
        elif op == "release":
            self._op_release(state, event)
        elif op == "tick":
            pass
        else:
            raise ValueError(f"Unknown operation: {op}")

    def _op_receive(self, state: _State, event: dict, at: int) -> None:
        lot_id = event["lot"]
        if lot_id in state.used_lot_ids:
            raise ValueError("Lot ID has already been used")

        expires = event["expires"]
        if expires is not None and expires <= at:
            raise ValueError("Lot expires at or before arrival")

        state.used_lot_ids.add(lot_id)
        state.lots[lot_id] = _Lot(
            id=lot_id,
            sku=event["sku"],
            expires=expires,
            on_hand=event["quantity"],
            seq=state.next_seq,
        )
        state.next_seq += 1

    def _op_reserve(self, state: _State, event: dict, at: int) -> None:
        hold_id = event["hold"]
        if hold_id in state.used_hold_ids:
            raise ValueError("Hold ID has already been used")

        until = event["until"]
        if until <= at:
            raise ValueError("Hold expiration must be strictly after current time")

        sku = event["sku"]
        quantity = event["quantity"]
        allocations = self._allocate(state, sku, quantity)

        state.used_hold_ids.add(hold_id)
        state.holds[hold_id] = _Hold(
            id=hold_id,
            sku=sku,
            until=until,
            allocations=allocations,
        )

    def _op_resize(self, state: _State, event: dict, at: int) -> None:
        hold_id = event["hold"]
        if hold_id not in state.holds:
            raise ValueError("Hold does not exist")

        until = event["until"]
        if until <= at:
            raise ValueError("Hold expiration must be strictly after current time")

        hold = state.holds[hold_id]
        hold.allocations = []
        new_allocations = self._allocate(state, hold.sku, event["quantity"])
        hold.allocations = new_allocations
        hold.until = until

    def _op_ship(self, state: _State, event: dict) -> None:
        hold_id = event["hold"]
        if hold_id not in state.holds:
            raise ValueError("Hold does not exist")

        hold = state.holds[hold_id]
        total_held = sum(qty for _, qty in hold.allocations)
        ship_qty = event["quantity"]

        if ship_qty > total_held:
            raise ValueError("Cannot ship more than reserved quantity")

        remaining_to_ship = ship_qty
        new_allocations: list[tuple[str, int]] = []

        for lot_id, alloc_qty in hold.allocations:
            if remaining_to_ship > 0:
                take = min(alloc_qty, remaining_to_ship)
                state.lots[lot_id].on_hand -= take
                rem = alloc_qty - take
                remaining_to_ship -= take
                if rem > 0:
                    new_allocations.append((lot_id, rem))
            else:
                new_allocations.append((lot_id, alloc_qty))

        if not new_allocations:
            del state.holds[hold_id]
        else:
            hold.allocations = new_allocations

    def _op_release(self, state: _State, event: dict) -> None:
        hold_id = event["hold"]
        if hold_id not in state.holds:
            raise ValueError("Hold does not exist")
        del state.holds[hold_id]

    def _allocate(
        self, state: _State, sku: str, quantity: int
    ) -> list[tuple[str, int]]:
        reserved_by_lot: dict[str, int] = {lot_id: 0 for lot_id in state.lots}
        for hold in state.holds.values():
            for lot_id, qty in hold.allocations:
                reserved_by_lot[lot_id] += qty

        candidates = [lot for lot in state.lots.values() if lot.sku == sku]
        candidates.sort(
            key=lambda lot: (lot.expires is None, lot.expires or 0, lot.seq)
        )

        allocations: list[tuple[str, int]] = []
        remaining = quantity

        for lot in candidates:
            available = lot.on_hand - reserved_by_lot[lot.id]
            if available <= 0:
                continue
            take = min(available, remaining)
            allocations.append((lot.id, take))
            remaining -= take
            if remaining == 0:
                break

        if remaining > 0:
            raise ValueError("Insufficient available inventory for allocation")

        return allocations

    @staticmethod
    def _make_snapshot(state: _State) -> dict:
        reserved_by_lot: dict[str, int] = {lot_id: 0 for lot_id in state.lots}
        for hold in state.holds.values():
            for lot_id, qty in hold.allocations:
                reserved_by_lot[lot_id] += qty

        lots_list = []
        for lot_id in sorted(state.lots.keys()):
            lot = state.lots[lot_id]
            res = reserved_by_lot[lot_id]
            lots_list.append(
                {
                    "id": lot.id,
                    "sku": lot.sku,
                    "expires": lot.expires,
                    "on_hand": lot.on_hand,
                    "reserved": res,
                    "available": lot.on_hand - res,
                }
            )

        holds_list = []
        for hold_id in sorted(state.holds.keys()):
            hold = state.holds[hold_id]
            total_qty = sum(qty for _, qty in hold.allocations)
            allocs = [
                {"lot": lot_id, "quantity": qty}
                for lot_id, qty in hold.allocations
            ]
            holds_list.append(
                {
                    "id": hold.id,
                    "sku": hold.sku,
                    "until": hold.until,
                    "quantity": total_qty,
                    "allocations": allocs,
                }
            )

        return {
            "now": state.now,
            "lots": lots_list,
            "holds": holds_list,
        }
=== END ===
