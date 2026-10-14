=== FILE: capacity_calendar.py ===
"""Integer-time reservations for resources with fixed capacities."""


class CapacityCalendar:
    """Keep reservations in memory and expose independent snapshots."""

    _PLAN_WINDOW = 120
    _PLAN_PARTS = 6
    _REQUIRED_KEYS = frozenset(("id", "resource", "start", "end", "duration"))
    _OPTIONAL_KEYS = frozenset(("units", "min_part", "max_parts"))

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
        if type(value) is not int or value < low or value > high:
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

    def _request(self, request):
        """Validate one plan request and return its normalized fields."""
        if not isinstance(request, dict):
            raise ValueError("expected a dict request")
        keys = set(request)
        if not self._REQUIRED_KEYS <= keys:
            raise ValueError("missing request key")
        if not keys <= self._REQUIRED_KEYS | self._OPTIONAL_KEYS:
            raise ValueError("unknown request key")
        booking_id = self._name(request["id"])
        resource = self._resource(request["resource"])
        start = request["start"]
        end = request["end"]
        self._interval(start, end)
        if end - start > self._PLAN_WINDOW:
            raise ValueError("planning window too long")
        duration = self._bounded(request["duration"], 1, end - start)
        units = self._positive(request.get("units", 1))
        min_part = self._bounded(request.get("min_part", 1), 1, duration)
        max_parts = self._bounded(
            request.get("max_parts", 1), 1, self._PLAN_PARTS
        )
        return (
            booking_id, resource, start, end,
            duration, units, min_part, max_parts,
        )

    @staticmethod
    def _choose(spans, start, end, duration, min_part, max_parts):
        """Pick the lexicographically smallest feasible split, or None."""
        length = end - start
        run = [0] * (length + 1)
        for left, right in spans:
            for t in range(left, right):
                run[t - start] = 1
        for i in range(length - 1, -1, -1):
            if run[i]:
                run[i] = run[i + 1] + 1

        # begin[p][q] has bit k when k units fit in at most p parts with
        # the first part starting exactly at q; reach[p][i] covers q >= i.
        limit = (1 << (duration + 1)) - 1
        low_bits = (1 << min_part) - 1
        begin = [[0] * (length + 1) for _ in range(max_parts + 1)]
        reach = [[0] * (length + 2) for _ in range(max_parts + 1)]
        for parts in range(1, max_parts + 1):
            later = reach[parts - 1]
            for q in range(length - 1, -1, -1):
                longest = min(run[q], duration)
                mask = 0
                if longest >= min_part:
                    mask = ((1 << (longest + 1)) - 1) ^ low_bits
                    if parts > 1:
                        for size in range(min_part, longest + 1):
                            mask |= later[q + size + 1] << size
                    mask &= limit
                begin[parts][q] = mask
                reach[parts][q] = mask | reach[parts][q + 1]

        remaining, parts, cursor = duration, max_parts, 0
        if not (reach[parts][0] >> remaining) & 1:
            return None
        segments = []
        while True:
            q = cursor
            while not (begin[parts][q] >> remaining) & 1:
                q += 1
            # A longer first part keeps the next unit adjacent, so it wins.
            size = min(run[q], remaining)
            while size != remaining and not (
                (reach[parts - 1][q + size + 1] >> (remaining - size)) & 1
            ):
                size -= 1
            segments.append((start + q, start + q + size))
            remaining -= size
            if remaining == 0:
                return segments
            parts -= 1
            cursor = q + size + 1

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
        """Replace bookings and add split reservations all at once."""
        if not isinstance(requests, list):
            raise ValueError("requests must be a list")
        if not isinstance(replace, (list, tuple)):
            raise ValueError("replace must be a list or tuple")

        working = dict(self._bookings)
        removed = set()
        for booking_id in replace:
            self._name(booking_id)
            if booking_id in removed:
                raise ValueError("duplicate replacement")
            if booking_id not in self._bookings:
                raise ValueError("unknown booking")
            removed.add(booking_id)
            del working[booking_id]

        created = []
        for request in requests:
            (
                booking_id, resource, start, end,
                duration, units, min_part, max_parts,
            ) = self._request(request)
            if booking_id in working:
                raise ValueError("duplicate booking")
            spans = self._available(resource, start, end, units, working)
            segments = self._choose(
                spans, start, end, duration, min_part, max_parts
            )
            if segments is None:
                raise ValueError("cannot plan request")
            working[booking_id] = (resource, units, tuple(segments))
            created.append(booking_id)

        self._bookings = working
        return [
            self._snapshot(booking_id, working[booking_id])
            for booking_id in created
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