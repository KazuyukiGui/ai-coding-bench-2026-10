=== FILE: warehouse.py ===
class _Lot:
    __slots__ = ("id", "sku", "expires", "on_hand", "reserved", "seq")

    def __init__(self, lot_id, sku, expires, on_hand, reserved, seq):
        self.id = lot_id
        self.sku = sku
        self.expires = expires
        self.on_hand = on_hand
        self.reserved = reserved
        self.seq = seq

    def copy(self):
        return _Lot(self.id, self.sku, self.expires, self.on_hand, self.reserved, self.seq)


class _Hold:
    __slots__ = ("id", "sku", "until", "quantity", "allocations")

    def __init__(self, hold_id, sku, until, quantity, allocations):
        self.id = hold_id
        self.sku = sku
        self.until = until
        self.quantity = quantity
        self.allocations = allocations

    def copy(self):
        return _Hold(
            self.id,
            self.sku,
            self.until,
            self.quantity,
            [[lot_id, qty] for lot_id, qty in self.allocations],
        )


class _State:
    __slots__ = ("now", "lots", "holds", "used_lot_ids", "used_hold_ids", "next_seq")

    def __init__(self):
        self.now = 0
        self.lots = {}
        self.holds = {}
        self.used_lot_ids = set()
        self.used_hold_ids = set()
        self.next_seq = 0

    def copy(self):
        s = _State()
        s.now = self.now
        s.lots = {k: v.copy() for k, v in self.lots.items()}
        s.holds = {k: v.copy() for k, v in self.holds.items()}
        s.used_lot_ids = set(self.used_lot_ids)
        s.used_hold_ids = set(self.used_hold_ids)
        s.next_seq = self.next_seq
        return s


class Warehouse:
    def __init__(self):
        self._state = _State()

    def snapshot(self):
        return self._make_snapshot(self._state)

    def apply(self, events):
        if not events:
            return []

        state = self._state.copy()
        snapshots = []

        for event in events:
            self._process_event(state, event)
            snapshots.append(self._make_snapshot(state))

        self._state = state
        return snapshots

    def _process_event(self, state, event):
        at = event["at"]
        if at < state.now:
            raise ValueError("Event timestamp cannot be earlier than current time")

        state.now = at

        expired_lot_ids = {
            lot_id
            for lot_id, lot in state.lots.items()
            if lot.expires is not None and lot.expires <= at
        }

        expired_hold_ids = [
            hold_id
            for hold_id, hold in state.holds.items()
            if hold.until <= at
            or any(lot_id in expired_lot_ids for lot_id, _ in hold.allocations)
        ]

        for hold_id in expired_hold_ids:
            hold = state.holds.pop(hold_id)
            for lot_id, qty in hold.allocations:
                state.lots[lot_id].reserved -= qty

        for lot_id in expired_lot_ids:
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

    def _op_receive(self, state, event, at):
        lot_id = event["lot"]
        sku = event["sku"]
        quantity = event["quantity"]
        expires = event["expires"]

        if lot_id in state.used_lot_ids:
            raise ValueError("Lot ID already used")
        if expires is not None and expires <= at:
            raise ValueError("Lot expires at or before receive time")

        state.used_lot_ids.add(lot_id)
        state.lots[lot_id] = _Lot(lot_id, sku, expires, quantity, 0, state.next_seq)
        state.next_seq += 1

    def _op_reserve(self, state, event, at):
        hold_id = event["hold"]
        sku = event["sku"]
        quantity = event["quantity"]
        until = event["until"]

        if hold_id in state.used_hold_ids:
            raise ValueError("Hold ID already used")
        if until <= at:
            raise ValueError("Hold until must be strictly greater than current time")

        allocations = self._allocate(state, sku, quantity)
        state.used_hold_ids.add(hold_id)
        state.holds[hold_id] = _Hold(hold_id, sku, until, quantity, allocations)

    def _op_resize(self, state, event, at):
        hold_id = event["hold"]
        quantity = event["quantity"]
        until = event["until"]

        if hold_id not in state.holds:
            raise ValueError("Hold does not exist")
        if until <= at:
            raise ValueError("Hold until must be strictly greater than current time")

        hold = state.holds[hold_id]
        for lot_id, qty in hold.allocations:
            state.lots[lot_id].reserved -= qty

        allocations = self._allocate(state, hold.sku, quantity)
        hold.until = until
        hold.quantity = quantity
        hold.allocations = allocations

    def _op_ship(self, state, event):
        hold_id = event["hold"]
        quantity = event["quantity"]

        if hold_id not in state.holds:
            raise ValueError("Hold does not exist")

        hold = state.holds[hold_id]
        if quantity > hold.quantity:
            raise ValueError("Ship quantity exceeds hold quantity")

        rem = quantity
        new_allocations = []
        for lot_id, alloc_qty in hold.allocations:
            if rem > 0:
                take = min(rem, alloc_qty)
                lot = state.lots[lot_id]
                lot.on_hand -= take
                lot.reserved -= take
                rem -= take
                left = alloc_qty - take
                if left > 0:
                    new_allocations.append([lot_id, left])
            else:
                new_allocations.append([lot_id, alloc_qty])

        hold.quantity -= quantity
        if hold.quantity == 0:
            del state.holds[hold_id]
        else:
            hold.allocations = new_allocations

    def _op_release(self, state, event):
        hold_id = event["hold"]
        if hold_id not in state.holds:
            raise ValueError("Hold does not exist")

        hold = state.holds.pop(hold_id)
        for lot_id, qty in hold.allocations:
            state.lots[lot_id].reserved -= qty

    def _allocate(self, state, sku, quantity):
        candidates = [
            lot
            for lot in state.lots.values()
            if lot.sku == sku and (lot.on_hand - lot.reserved) > 0
        ]
        candidates.sort(
            key=lambda lot: (0, lot.expires, lot.seq)
            if lot.expires is not None
            else (1, 0, lot.seq)
        )

        allocations = []
        needed = quantity
        for lot in candidates:
            avail = lot.on_hand - lot.reserved
            take = min(needed, avail)
            if take > 0:
                allocations.append([lot.id, take])
                needed -= take
                if needed == 0:
                    break

        if needed > 0:
            raise ValueError("Insufficient available inventory")

        for lot_id, take in allocations:
            state.lots[lot_id].reserved += take

        return allocations

    @staticmethod
    def _make_snapshot(state):
        lots_list = []
        for lot_id in sorted(state.lots.keys()):
            lot = state.lots[lot_id]
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
        for hold_id in sorted(state.holds.keys()):
            hold = state.holds[hold_id]
            holds_list.append(
                {
                    "id": hold.id,
                    "sku": hold.sku,
                    "until": hold.until,
                    "quantity": hold.quantity,
                    "allocations": [
                        {"lot": lot_id, "quantity": qty}
                        for lot_id, qty in hold.allocations
                    ],
                }
            )

        return {
            "now": state.now,
            "lots": lots_list,
            "holds": holds_list,
        }
=== END ===
