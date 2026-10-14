=== FILE: capacity_calendar.py ===
"""Integer-time reservations for resources with fixed capacities."""


class CapacityCalendar:
    """Keep reservations in memory and expose independent snapshots."""

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
    def _plan_segments(spans, start, end, duration, min_part, max_parts):
        """Choose the lexicographically earliest feasible occupied times."""
        width = end - start
        available = [False] * width
        for left, right in spans:
            for offset in range(left - start, right - start):
                available[offset] = True

        if sum(available) < duration:
            raise ValueError("insufficient capacity")

        runs = [0] * (width + 1)
        for offset in range(width - 1, -1, -1):
            if available[offset]:
                runs[offset] = runs[offset + 1] + 1

        # Bit d of feasible[p][i] says that exactly d units of time can
        # be selected from offset i onward using at most p segments.
        # The empty selection is feasible in every suffix.
        feasible = [[1] * (width + 1) for _ in range(max_parts + 1)]
        mask = (1 << (duration + 1)) - 1

        for parts in range(1, max_parts + 1):
            previous = feasible[parts - 1]
            current = feasible[parts]
            for offset in range(width - 1, -1, -1):
                totals = current[offset + 1]
                for length in range(
                    min_part, min(runs[offset], duration) + 1
                ):
                    # Leave at least one unselected time unit between
                    # segments, so adjacent segments are never returned.
                    following = min(width, offset + length + 1)
                    totals |= previous[following] << length
                current[offset] = totals & mask

        if not feasible[max_parts][0] & (1 << duration):
            raise ValueError("cannot construct split reservation")

        segments = []
        remaining = duration
        parts = max_parts
        cursor = 0

        while remaining:
            chosen = None
            # Prefer the earliest start. At equal starts, prefer the
            # longest segment whose remaining suffix is feasible.
            for offset in range(cursor, width):
                for length in range(
                    min(runs[offset], remaining), min_part - 1, -1
                ):
                    following = min(width, offset + length + 1)
                    rest = remaining - length
                    if feasible[parts - 1][following] & (1 << rest):
                        chosen = (offset, length, following)
                        break
                if chosen is not None:
                    break

            if chosen is None:
                raise ValueError("cannot construct split reservation")

            offset, length, cursor = chosen
            segments.append((start + offset, start + offset + length))
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
        """Plan requests in order and commit all deletions and additions."""
        if not isinstance(requests, list):
            raise ValueError("expected a list of requests")
        if not isinstance(replace, (list, tuple)):
            raise ValueError("expected a list or tuple of booking IDs")

        removed = set()
        for booking_id in replace:
            self._name(booking_id)
            if booking_id in removed:
                raise ValueError("duplicate replacement ID")
            if booking_id not in self._bookings:
                raise ValueError("unknown booking")
            removed.add(booking_id)

        staged = self._bookings.copy()
        for booking_id in removed:
            del staged[booking_id]

        required = {"id", "resource", "start", "end", "duration"}
        allowed = required | {"units", "min_part", "max_parts"}
        result = []

        for request in requests:
            if not isinstance(request, dict):
                raise ValueError("expected a request dictionary")
            keys = set(request)
            if not required <= keys or not keys <= allowed:
                raise ValueError("invalid request keys")

            booking_id = request["id"]
            resource = request["resource"]
            start = request["start"]
            end = request["end"]
            duration = request["duration"]
            units = request.get("units", 1)
            min_part = request.get("min_part", 1)
            max_parts = request.get("max_parts", 1)

            self._name(booking_id)
            self._query(resource, start, end, units)
            self._positive(duration)
            self._positive(min_part)
            self._positive(max_parts)

            if end - start > 120:
                raise ValueError("planning range is too long")
            if duration > end - start:
                raise ValueError("duration exceeds planning range")
            if min_part > duration:
                raise ValueError("minimum part exceeds duration")
            if max_parts > 6:
                raise ValueError("too many parts")
            if booking_id in staged:
                raise ValueError("duplicate booking")

            spans = self._available(resource, start, end, units, staged)
            segments = self._plan_segments(
                spans, start, end, duration, min_part, max_parts
            )
            record = (resource, units, segments)
            staged[booking_id] = record
            result.append(self._snapshot(booking_id, record))

        self._bookings = staged
        return result

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