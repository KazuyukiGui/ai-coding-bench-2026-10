=== FILE: capacity_calendar.py ===
"""Integer-time reservations for resources with fixed capacities."""

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

    def _plan_segments(
        self,
        resource,
        start,
        end,
        duration,
        units,
        min_part,
        max_parts,
        records,
    ):
        spans = self._available(resource, start, end, units, records)
        available = [False] * (end - start)
        for left, right in spans:
            for time in range(left, right):
                available[time - start] = True

        length = len(available)

        @lru_cache(maxsize=None)
        def feasible(position, remaining, parts, run_length):
            if remaining == 0:
                return run_length == 0 or run_length == min_part
            if position == length or remaining > length - position:
                return False

            if available[position]:
                if run_length:
                    next_run = min(min_part, run_length + 1)
                    if feasible(
                        position + 1,
                        remaining - 1,
                        parts,
                        next_run,
                    ):
                        return True
                elif parts < max_parts:
                    if feasible(
                        position + 1,
                        remaining - 1,
                        parts + 1,
                        1,
                    ):
                        return True

            if run_length == 0:
                return feasible(position + 1, remaining, parts, 0)
            if run_length == min_part:
                return feasible(position + 1, remaining, parts, 0)
            return False

        if not feasible(0, duration, 0, 0):
            raise ValueError("cannot construct booking")

        selected = []
        position = 0
        remaining = duration
        parts = 0
        run_length = 0

        while remaining:
            take = False
            if available[position]:
                if run_length:
                    next_parts = parts
                    next_run = min(min_part, run_length + 1)
                    take = feasible(
                        position + 1,
                        remaining - 1,
                        next_parts,
                        next_run,
                    )
                elif parts < max_parts:
                    next_parts = parts + 1
                    next_run = 1
                    take = feasible(
                        position + 1,
                        remaining - 1,
                        next_parts,
                        next_run,
                    )

            if take:
                selected.append(start + position)
                parts = next_parts
                run_length = next_run
                remaining -= 1
            else:
                if run_length == min_part:
                    run_length = 0
            position += 1

        segments = []
        segment_start = selected[0]
        previous = selected[0]
        for time in selected[1:]:
            if time != previous + 1:
                segments.append((segment_start, previous + 1))
                segment_start = time
            previous = time
        segments.append((segment_start, previous + 1))
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
        """Plan split reservations in order and apply them atomically."""
        if type(requests) is not list:
            raise ValueError("requests must be a list")
        if type(replace) not in (list, tuple):
            raise ValueError("replace must be a list or tuple")

        replace_ids = []
        replace_set = set()
        for booking_id in replace:
            self._name(booking_id)
            if booking_id in replace_set:
                raise ValueError("duplicate replacement")
            if booking_id not in self._bookings:
                raise ValueError("unknown booking")
            replace_set.add(booking_id)
            replace_ids.append(booking_id)

        required = {"id", "resource", "start", "end", "duration"}
        allowed = required | {"units", "min_part", "max_parts"}
        normalized = []

        for request in requests:
            if type(request) is not dict:
                raise ValueError("request must be a dictionary")
            keys = set(request)
            if not required <= keys or not keys <= allowed:
                raise ValueError("invalid request keys")

            booking_id = self._name(request["id"])
            resource = request["resource"]
            start = request["start"]
            end = request["end"]
            duration = request["duration"]
            units = request.get("units", 1)
            min_part = request.get("min_part", 1)
            max_parts = request.get("max_parts", 1)

            self._resource(resource)
            self._interval(start, end)
            if end - start > 120:
                raise ValueError("planning range is too large")
            if type(duration) is not int:
                raise ValueError("duration must be an integer")
            if duration < 1 or duration > end - start:
                raise ValueError("invalid duration")
            self._positive(units)
            if type(min_part) is not int:
                raise ValueError("min_part must be an integer")
            if min_part < 1 or min_part > duration:
                raise ValueError("invalid min_part")
            if type(max_parts) is not int:
                raise ValueError("max_parts must be an integer")
            if max_parts < 1 or max_parts > 6:
                raise ValueError("invalid max_parts")

            normalized.append(
                (
                    booking_id,
                    resource,
                    start,
                    end,
                    duration,
                    units,
                    min_part,
                    max_parts,
                )
            )

        retained_ids = set(self._bookings) - replace_set
        new_ids = set()
        for request in normalized:
            booking_id = request[0]
            if booking_id in retained_ids or booking_id in new_ids:
                raise ValueError("duplicate booking")
            new_ids.add(booking_id)

        records = dict(self._bookings)
        for booking_id in replace_ids:
            del records[booking_id]

        created = []
        for (
            booking_id,
            resource,
            start,
            end,
            duration,
            units,
            min_part,
            max_parts,
        ) in normalized:
            segments = self._plan_segments(
                resource,
                start,
                end,
                duration,
                units,
                min_part,
                max_parts,
                records,
            )
            record = (resource, units, segments)
            records[booking_id] = record
            created.append((booking_id, record))

        self._bookings = records
        return [
            self._snapshot(booking_id, record)
            for booking_id, record in created
        ]
=== END ===