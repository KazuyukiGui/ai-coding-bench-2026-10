=== FILE: capacity_calendar.py ===
"""Integer-time reservations for resources with fixed capacities."""


class CapacityCalendar:
    """Keep reservations in memory and expose independent snapshots."""

    _PLAN_REQUIRED = frozenset(("id", "resource", "start", "end", "duration"))
    _PLAN_OPTIONAL = frozenset(("units", "min_part", "max_parts"))
    _PLAN_MAX_RANGE = 120
    _PLAN_MAX_PARTS = 6

    def __init__(self):
        self._capacities = {}
        self._bookings = {}

    @staticmethod
    def _name(value):
        if not isinstance(value, str) or not value:
            raise ValueError("expected a nonempty string")
        return value

    @staticmethod
    def _positive(value):
        if type(value) is not int or value <= 0:
            raise ValueError("expected a positive integer")
        return value

    @staticmethod
    def _interval(start, end):
        if type(start) is not int or type(end) is not int:
            raise ValueError("expected integer endpoints")
        if start < 0 or start >= end:
            raise ValueError("invalid interval")

    def _resource(self, resource):
        self._name(resource)
        if resource not in self._capacities:
            raise ValueError("unknown resource")
        return resource

    def _query(self, resource, start, end, units):
        self._resource(resource)
        self._interval(start, end)
        self._positive(units)

    @staticmethod
    def _snapshot(booking_id, record):
        resource, units, segments = record
        return {
            "id": booking_id,
            "resource": resource,
            "units": units,
            "segments": list(segments),
        }

    def _available(self, resource, start, end, units, records):
        """Sweep clipped usage events and merge adjacent usable spans."""
        events = {start: 0, end: 0}
        for stored_resource, stored_units, segments in records.values():
            if stored_resource != resource:
                continue
            for left, right in segments:
                left = max(left, start)
                right = min(right, end)
                if left >= right:
                    continue
                events[left] = events.get(left, 0) + stored_units
                events[right] = events.get(right, 0) - stored_units

        points = sorted(events)
        usage = 0
        spans = []
        capacity = self._capacities[resource]
        for left, right in zip(points, points[1:]):
            usage += events[left]
            if capacity - usage < units:
                continue
            if spans and spans[-1][1] == left:
                spans[-1] = (spans[-1][0], right)
            else:
                spans.append((left, right))
        return spans

    @staticmethod
    def _after(blocks, position):
        """Clip free blocks so that none starts before `position`."""
        result = []
        for left, right in blocks:
            left = max(left, position)
            if left < right:
                result.append((left, right))
        return result

    @staticmethod
    def _fits(blocks, remaining, parts, min_part):
        """Whether `remaining` units fit in at most `parts` pieces.

        Pieces inside one free block can always be merged, so it suffices
        to use at most one piece per block; with `count` blocks the
        reachable totals form [count * min_part, sum of largest lengths].
        """
        if remaining == 0:
            return True
        lengths = sorted(
            (right - left for left, right in blocks
             if right - left >= min_part),
            reverse=True,
        )
        total = 0
        for count, length in enumerate(lengths[:parts], 1):
            total += length
            if count * min_part <= remaining <= total:
                return True
        return False

    def _choose(self, blocks, duration, min_part, max_parts):
        """Pick the lexicographically smallest feasible split reservation.

        The earliest feasible start is always the start of some free block,
        and for a fixed start a longer first piece is lexicographically
        smaller, so pieces are chosen greedily from the left.
        """
        segments = []
        remaining = duration
        parts = max_parts
        while remaining:
            if parts == 0:
                raise ValueError("cannot plan booking")
            chosen = None
            for left, right in blocks:
                longest = min(remaining, right - left)
                for length in range(longest, min_part - 1, -1):
                    rest = self._after(blocks, left + length + 1)
                    if self._fits(rest, remaining - length, parts - 1,
                                  min_part):
                        chosen = (left, left + length)
                        break
                if chosen is not None:
                    break
            if chosen is None:
                raise ValueError("cannot plan booking")
            segments.append(chosen)
            remaining -= chosen[1] - chosen[0]
            parts -= 1
            blocks = self._after(blocks, chosen[1] + 1)
        return tuple(segments)

    def _plan_request(self, request):
        """Validate one plan request and return its normalized fields."""
        if not isinstance(request, dict):
            raise ValueError("expected a dict request")
        keys = set(request.keys())
        if not self._PLAN_REQUIRED <= keys:
            raise ValueError("missing request key")
        if keys - self._PLAN_REQUIRED - self._PLAN_OPTIONAL:
            raise ValueError("unknown request key")

        booking_id = self._name(request["id"])
        resource = self._resource(request["resource"])
        start = request["start"]
        end = request["end"]
        self._interval(start, end)
        if end - start > self._PLAN_MAX_RANGE:
            raise ValueError("planning range too long")

        duration = request["duration"]
        if type(duration) is not int or not 1 <= duration <= end - start:
            raise ValueError("invalid duration")
        units = self._positive(request.get("units", 1))
        min_part = request.get("min_part", 1)
        if type(min_part) is not int or not 1 <= min_part <= duration:
            raise ValueError("invalid min_part")
        max_parts = request.get("max_parts", 1)
        if (type(max_parts) is not int
                or not 1 <= max_parts <= self._PLAN_MAX_PARTS):
            raise ValueError("invalid max_parts")
        return (booking_id, resource, start, end, duration, units,
                min_part, max_parts)

    def add_resource(self, name, capacity):
        """Add a resource; existing capacities cannot be changed."""
        self._name(name)
        self._positive(capacity)
        if name in self._capacities:
            raise ValueError("duplicate resource")
        self._capacities[name] = capacity

    def book(self, booking_id, resource, start, end, units=1):
        """Reserve one complete interval, or leave the calendar unchanged."""
        self._name(booking_id)
        self._query(resource, start, end, units)
        if booking_id in self._bookings:
            raise ValueError("duplicate booking")
        spans = self._available(
            resource, start, end, units, self._bookings
        )
        if spans != [(start, end)]:
            raise ValueError("insufficient capacity")
        record = (resource, units, ((start, end),))
        self._bookings[booking_id] = record
        return self._snapshot(booking_id, record)

    def cancel(self, booking_id):
        """Remove a reservation and return its former contents."""
        self._name(booking_id)
        if booking_id not in self._bookings:
            raise ValueError("unknown booking")
        record = self._bookings.pop(booking_id)
        return self._snapshot(booking_id, record)

    def get(self, booking_id):
        """Return an independent public representation of a reservation."""
        self._name(booking_id)
        if booking_id not in self._bookings:
            raise ValueError("unknown booking")
        return self._snapshot(booking_id, self._bookings[booking_id])

    def bookings(self, resource=None):
        """Return snapshots ordered by booking ID."""
        if resource is not None:
            self._resource(resource)
        result = []
        for booking_id in sorted(self._bookings):
            record = self._bookings[booking_id]
            if resource is None or record[0] == resource:
                result.append(self._snapshot(booking_id, record))
        return result

    def free_spans(self, resource, start, end, units=1):
        """Return maximal intervals able to accept the requested load."""
        self._query(resource, start, end, units)
        return self._available(
            resource, start, end, units, self._bookings
        )

    def plan(self, requests, replace=()):
        """Replace bookings and add split bookings atomically, in order."""
        if not isinstance(requests, list):
            raise ValueError("expected a list of requests")
        if not isinstance(replace, (list, tuple)):
            raise ValueError("expected a list or tuple of booking IDs")

        removed = set()
        for booking_id in replace:
            self._name(booking_id)
            if booking_id in removed:
                raise ValueError("duplicate replaced booking")
            if booking_id not in self._bookings:
                raise ValueError("unknown booking")
            removed.add(booking_id)

        pending = {
            booking_id: record
            for booking_id, record in self._bookings.items()
            if booking_id not in removed
        }
        created = []
        for request in requests:
            (booking_id, resource, start, end, duration, units,
             min_part, max_parts) = self._plan_request(request)
            if booking_id in pending:
                raise ValueError("duplicate booking")
            blocks = self._available(
                resource, start, end, units, pending
            )
            segments = self._choose(blocks, duration, min_part, max_parts)
            record = (resource, units, segments)
            pending[booking_id] = record
            created.append(booking_id)

        self._bookings = pending
        return [
            self._snapshot(booking_id, pending[booking_id])
            for booking_id in created
        ]
=== END ===