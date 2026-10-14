"""Integer-time reservations with atomic, split booking plans."""

from functools import lru_cache


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

    @staticmethod
    def _choose(spans, duration, min_part, max_parts):
        """Find the lexicographically earliest feasible selection.

        Within one maximal available span, shifting all selected units
        to a single prefix cannot hurt feasibility and improves or keeps
        their lexicographic order. Thus each span contributes either
        nothing or one prefix of at least min_part units.
        """
        lengths = tuple(right - left for left, right in spans)

        @lru_cache(maxsize=None)
        def possible(index, remaining, budget):
            if remaining == 0:
                return True
            if index == len(spans) or budget == 0:
                return False
            if remaining < min_part:
                return False
            upper = min(lengths[index], remaining)
            for take in range(upper, min_part - 1, -1):
                if possible(index + 1, remaining - take, budget - 1):
                    return True
            return possible(index + 1, remaining, budget)

        if not possible(0, duration, max_parts):
            return None

        result = []
        remaining = duration
        budget = max_parts
        for index, (left, right) in enumerate(spans):
            if remaining == 0:
                break
            upper = min(right - left, remaining)
            for take in range(upper, min_part - 1, -1):
                if possible(index + 1, remaining - take, budget - 1):
                    result.append((left, left + take))
                    remaining -= take
                    budget -= 1
                    break
        return result

    def plan(self, requests, replace=()):
        """Plan in input order and commit only if every request succeeds."""
        if not isinstance(requests, list):
            raise ValueError("requests must be a list")
        if not isinstance(replace, (list, tuple)):
            raise ValueError("replace must be a list or tuple")

        removed = set()
        for booking_id in replace:
            self._name(booking_id)
            if booking_id in removed:
                raise ValueError("duplicate replacement")
            if booking_id not in self._bookings:
                raise ValueError("unknown replacement")
            removed.add(booking_id)

        # Records contain only immutable values, so a shallow copy suffices.
        working = dict(self._bookings)
        for booking_id in removed:
            del working[booking_id]

        required = {"id", "resource", "start", "end", "duration"}
        allowed = required | {"units", "min_part", "max_parts"}
        result = []
        for request in requests:
            if not isinstance(request, dict):
                raise ValueError("request must be a dictionary")
            if not required <= request.keys() <= allowed:
                raise ValueError("invalid request keys")

            booking_id = self._name(request["id"])
            resource = request["resource"]
            start = request["start"]
            end = request["end"]
            units = request.get("units", 1)
            self._query(resource, start, end, units)
            if end - start > 120:
                raise ValueError("planning window is too wide")
            if booking_id in working:
                raise ValueError("duplicate booking")

            duration = self._positive(request["duration"])
            min_part = self._positive(request.get("min_part", 1))
            max_parts = self._positive(request.get("max_parts", 1))
            if duration > end - start:
                raise ValueError("duration exceeds the window")
            if min_part > duration or max_parts > 6:
                raise ValueError("invalid part limits")

            spans = self._available(
                resource, start, end, units, working
            )
            segments = self._choose(
                spans, duration, min_part, max_parts
            )
            if segments is None:
                raise ValueError("no feasible split reservation")

            record = (resource, units, tuple(segments))
            working[booking_id] = record
            result.append(self._snapshot(booking_id, record))

        self._bookings = working
        return result
