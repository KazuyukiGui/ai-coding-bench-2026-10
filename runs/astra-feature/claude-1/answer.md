=== FILE: capacity_calendar.py ===
"""Integer-time reservations for resources with fixed capacities."""


class CapacityCalendar:
    """Keep reservations in memory and expose independent snapshots."""

    _PLAN_REQUIRED = ("id", "resource", "start", "end", "duration")
    _PLAN_DEFAULTS = {"units": 1, "min_part": 1, "max_parts": 1}
    _PLAN_WINDOW = 120
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
    def _bounded(value, low, high):
        if type(value) is not int or not low <= value <= high:
            raise ValueError("integer out of range")
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

    def _plan_request(self, request):
        """Validate one plan request and return its normalized fields."""
        if not isinstance(request, dict):
            raise ValueError("expected a request dictionary")
        allowed = set(self._PLAN_REQUIRED) | set(self._PLAN_DEFAULTS)
        if not set(request) <= allowed:
            raise ValueError("unexpected request key")
        if any(key not in request for key in self._PLAN_REQUIRED):
            raise ValueError("missing request key")
        values = dict(self._PLAN_DEFAULTS)
        values.update(request)

        booking_id = self._name(values["id"])
        resource = self._resource(values["resource"])
        start, end = values["start"], values["end"]
        self._interval(start, end)
        if end - start > self._PLAN_WINDOW:
            raise ValueError("planning window too long")
        duration = self._bounded(values["duration"], 1, end - start)
        units = self._positive(values["units"])
        min_part = self._bounded(values["min_part"], 1, duration)
        max_parts = self._bounded(
            values["max_parts"], 1, self._PLAN_MAX_PARTS
        )
        return (
            booking_id, resource, start, end,
            duration, units, min_part, max_parts,
        )

    @staticmethod
    def _split(spans, start, end, duration, min_part, max_parts):
        """Pick the lexicographically smallest unit set as merged segments."""
        size = end - start
        reach = [0] * (size + 1)
        for left, right in spans:
            for moment in range(left, right):
                reach[moment - start] = right - moment

        # totals[i][p]: bitset of lengths coverable from offset i with at
        # most p parts, assuming offset i - 1 is not selected.
        mask = (1 << (duration + 1)) - 1
        totals = [[1] * (max_parts + 1) for _ in range(size + 2)]
        for offset in range(size - 1, -1, -1):
            row = totals[offset]
            after = totals[offset + 1]
            longest = min(reach[offset], duration)
            for parts in range(1, max_parts + 1):
                bits = after[parts]
                for length in range(min_part, longest + 1):
                    bits |= totals[offset + length + 1][parts - 1] << length
                row[parts] = bits & mask

        if not totals[0][max_parts] >> duration & 1:
            raise ValueError("cannot plan request")

        def next_part(offset, remaining, parts):
            # Earliest start first, then the longest run that still allows
            # the remainder to be completed.
            for left in range(offset, size):
                longest = min(reach[left], remaining)
                for length in range(longest, min_part - 1, -1):
                    rest = totals[left + length + 1][parts - 1]
                    if rest >> (remaining - length) & 1:
                        return left, length
            raise ValueError("cannot plan request")

        segments = []
        offset, remaining, parts = 0, duration, max_parts
        while remaining:
            left, length = next_part(offset, remaining, parts)
            segments.append((start + left, start + left + length))
            offset = left + length + 1
            remaining -= length
            parts -= 1
        return tuple(segments)

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

    def plan(self, requests, replace=()):
        """Replace and add split reservations atomically, in request order."""
        if not isinstance(requests, list):
            raise ValueError("expected a list of requests")
        if not isinstance(replace, (list, tuple)):
            raise ValueError("expected a list or tuple of booking IDs")
        removed = set()
        for booking_id in replace:
            self._name(booking_id)
            if booking_id not in self._bookings:
                raise ValueError("unknown booking")
            if booking_id in removed:
                raise ValueError("duplicate replacement")
            removed.add(booking_id)
        parsed = [self._plan_request(request) for request in requests]

        records = {
            booking_id: record
            for booking_id, record in self._bookings.items()
            if booking_id not in removed
        }
        for (booking_id, resource, start, end,
                duration, units, min_part, max_parts) in parsed:
            if booking_id in records:
                raise ValueError("duplicate booking")
            spans = self._available(resource, start, end, units, records)
            segments = self._split(
                spans, start, end, duration, min_part, max_parts
            )
            records[booking_id] = (resource, units, segments)

        self._bookings = records
        return [
            self._snapshot(item[0], records[item[0]]) for item in parsed
        ]

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
=== END ===