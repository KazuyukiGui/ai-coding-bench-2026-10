=== FILE: stockbook.py ===
from copy import deepcopy


_FIELDS = {
    "receive": {"lot", "sku", "quantity", "expires"},
    "reserve": {"reservation", "sku", "quantity", "until"},
    "resize": {"reservation", "quantity"},
    "release": {"reservation"},
    "ship": {"reservation"},
    "tick": set(),
}


class StockBook:
    def __init__(self):
        self._at = 0
        self._lots = {}
        self._reservations = {}
        self._events = {}

    @staticmethod
    def _integer(value, minimum):
        if type(value) is not int or value < minimum:
            raise ValueError("invalid integer")

    @staticmethod
    def _identifier(value):
        if type(value) is not str or not value:
            raise ValueError("invalid identifier")

    def _validate(self, event):
        if type(event) is not dict:
            raise ValueError("event must be a dict")
        kind = event.get("kind")
        if type(kind) is not str or kind not in _FIELDS:
            raise ValueError("unknown event kind")
        expected = {"id", "kind", "at"} | _FIELDS[kind]
        if set(event) != expected:
            raise ValueError("invalid event fields")

        self._identifier(event["id"])
        self._integer(event["at"], 0)
        for name in ("lot", "sku", "reservation"):
            if name in event:
                self._identifier(event[name])
        if "quantity" in event:
            self._integer(event["quantity"], 1)
        if kind == "reserve":
            self._integer(event["until"], 0)
            if event["until"] <= event["at"]:
                raise ValueError("reservation deadline must be later")
        if kind == "receive" and event["expires"] is not None:
            self._integer(event["expires"], 0)
            if event["expires"] <= event["at"]:
                raise ValueError("lot expiration must be later")

    def apply(self, events):
        if type(events) is not list:
            raise ValueError("events must be a list")
        if not events:
            return None
        saved = deepcopy(
            (self._at, self._lots, self._reservations, self._events)
        )
        try:
            for event in events:
                self._apply_one(event)
        except BaseException:
            (
                self._at,
                self._lots,
                self._reservations,
                self._events,
            ) = saved
            raise
        return None

    def _apply_one(self, event):
        self._validate(event)
        event_id = event["id"]
        if event_id in self._events:
            if self._events[event_id] != event:
                raise ValueError("event id conflict")
            return
        if event["at"] < self._at:
            raise ValueError("time cannot move backwards")
        self._advance(event["at"])
        self._dispatch(event)
        self._events[event_id] = deepcopy(event)

    def _close(self, reservation, status):
        reservation["status"] = status
        reservation["allocations"] = {}

    def _advance(self, at):
        for reservation in self._reservations.values():
            if (
                reservation["status"] == "active"
                and reservation["until"] <= at
            ):
                self._close(reservation, "expired")
        for lot in self._lots.values():
            if lot["expires"] is not None and lot["expires"] <= at:
                lot["remaining"] = 0
        self._at = at

    def _lot_key(self, lot_id):
        expires = self._lots[lot_id]["expires"]
        return (
            expires is None,
            0 if expires is None else expires,
            lot_id,
        )

    def _held(self):
        held = {}
        for reservation in self._reservations.values():
            if reservation["status"] != "active":
                continue
            for lot_id, quantity in reservation["allocations"].items():
                held[lot_id] = held.get(lot_id, 0) + quantity
        return held

    def _allocate(self, sku, until, quantity):
        held = self._held()
        allocations = {}
        needed = quantity
        for lot_id in sorted(self._lots, key=self._lot_key):
            lot = self._lots[lot_id]
            if lot["sku"] != sku:
                continue
            if lot["expires"] is not None and lot["expires"] < until:
                continue
            available = lot["remaining"] - held.get(lot_id, 0)
            take = min(needed, available)
            if take <= 0:
                continue
            allocations[lot_id] = take
            needed -= take
            if needed == 0:
                break
        if needed:
            raise ValueError("insufficient stock")
        return allocations

    def _receive(self, event):
        lot_id = event["lot"]
        if lot_id in self._lots:
            raise ValueError("lot id already used")
        self._lots[lot_id] = {
            "sku": event["sku"],
            "expires": event["expires"],
            "remaining": event["quantity"],
        }

    def _reserve(self, event):
        reservation_id = event["reservation"]
        if reservation_id in self._reservations:
            raise ValueError("reservation id already used")
        allocations = self._allocate(
            event["sku"], event["until"], event["quantity"]
        )
        self._reservations[reservation_id] = {
            "sku": event["sku"],
            "until": event["until"],
            "quantity": event["quantity"],
            "status": "active",
            "allocations": allocations,
        }

    def _resize(self, reservation, quantity):
        old_quantity = reservation["quantity"]
        allocations = reservation["allocations"]
        if quantity > old_quantity:
            extra = self._allocate(
                reservation["sku"],
                reservation["until"],
                quantity - old_quantity,
            )
            for lot_id, amount in extra.items():
                allocations[lot_id] = allocations.get(lot_id, 0) + amount
        elif quantity < old_quantity:
            to_release = old_quantity - quantity
            for lot_id in sorted(
                allocations, key=self._lot_key, reverse=True
            ):
                take = min(to_release, allocations[lot_id])
                allocations[lot_id] -= take
                to_release -= take
                if allocations[lot_id] == 0:
                    del allocations[lot_id]
                if to_release == 0:
                    break
        reservation["quantity"] = quantity

    def _dispatch(self, event):
        kind = event["kind"]
        if kind == "tick":
            return
        if kind == "receive":
            self._receive(event)
            return
        if kind == "reserve":
            self._reserve(event)
            return

        reservation = self._reservations.get(event["reservation"])
        if reservation is None or reservation["status"] != "active":
            raise ValueError("reservation is not active")
        if kind == "resize":
            self._resize(reservation, event["quantity"])
            return
        if kind == "ship":
            for lot_id, quantity in reservation["allocations"].items():
                self._lots[lot_id]["remaining"] -= quantity
            self._close(reservation, "shipped")
        else:
            self._close(reservation, "released")

    def snapshot(self):
        held = self._held()
        lots = []
        for lot_id in sorted(self._lots):
            lot = self._lots[lot_id]
            lots.append({
                "lot": lot_id,
                "sku": lot["sku"],
                "expires": lot["expires"],
                "remaining": lot["remaining"],
                "available": lot["remaining"] - held.get(lot_id, 0),
            })

        reservations = []
        for reservation_id in sorted(self._reservations):
            reservation = self._reservations[reservation_id]
            allocations = [
                {
                    "lot": lot_id,
                    "quantity": reservation["allocations"][lot_id],
                }
                for lot_id in sorted(
                    reservation["allocations"], key=self._lot_key
                )
                if reservation["allocations"][lot_id] > 0
            ]
            reservations.append({
                "reservation": reservation_id,
                "sku": reservation["sku"],
                "until": reservation["until"],
                "quantity": reservation["quantity"],
                "status": reservation["status"],
                "allocations": allocations,
            })
        return {
            "at": self._at,
            "lots": lots,
            "reservations": reservations,
        }
=== END ===