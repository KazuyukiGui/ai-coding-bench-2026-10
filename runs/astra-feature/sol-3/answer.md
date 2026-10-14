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

    def _choose_segments(
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
        """Return the lexicographically earliest feasible split."""
        width = end - start
        usable = [False] * width
        for left, right in self._available(
            resource, start, end, units, records
        ):
            for offset in range(left - start, right - start):
                usable[offset] = True

        mature = min_part

        @lru_cache(maxsize=None)
        def feasible(position, remaining, parts, run_length):
            if remaining == 0:
                return run_length == 0 or run_length == mature
            if position == width or width - position < remaining:
                return False

            if usable[position]:
                if run_length:
                    next_run = min(mature, run_length + 1)
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
                        min(mature, 1),
                    ):
                        return True

            if run_length == 0 or run_length == mature:
                if feasible(position + 1, remaining, parts, 0):
                    return True

            return False

        if not feasible(0, duration, 0, 0):
            raise ValueError("cannot construct booking")

        selected = []
        position = 0
        remaining = duration
        parts = 0
        run_length = 0

        while remaining:
            selected_here = False
            if usable[position]:
                if run_length:
                    next_parts = parts
                    next_run = min(mature, run_length + 1)
                elif parts < max_parts:
                    next_parts = parts + 1
                    next_run = min(mature, 1)
                else:
                    next_parts = None
                    next_run = None

                if (
                    next_parts is not None
                    and feasible(
                        position + 1,
                        remaining - 1,
                        next_parts,
                        next_run,
                    )
                ):
                    selected.append(start + position)
                    remaining -= 1
                    parts = next_parts
                    run_length = next_run
                    selected_here = True

            if not selected_here:
                if run_length != 0 and run_length != mature:
                    raise ValueError("cannot construct booking")
                run_length = 0

            position += 1

        segments = []
        segment_start = selected[0]
        previous = selected[0]
        for value in selected[1:]:
            if value != previous + 1:
                segments.append((segment_start, previous + 1))
                segment_start = value
            previous = value
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
        """Plan split reservations sequentially and commit them atomically."""
        if type(requests) is not list:
            raise ValueError("requests must be a list")
        if type(replace) not in (list, tuple):
            raise ValueError("replace must be a list or tuple")

        replace_ids = []
        replaced = set()
        for booking_id in replace:
            self._name(booking_id)
            if booking_id in replaced:
                raise ValueError("duplicate replacement")
            if booking_id not in self._bookings:
                raise ValueError("unknown booking")
            replaced.add(booking_id)
            replace_ids.append(booking_id)

        records = dict(self._bookings)
        for booking_id in replace_ids:
            del records[booking_id]

        required_keys = {
            "id",
            "resource",
            "start",
            "end",
            "duration",
        }
        allowed_keys = required_keys | {
            "units",
            "min_part",
            "max_parts",
        }

        new_ids = set()
        result = []

        for request in requests:
            if type(request) is not dict:
                raise ValueError("request must be a dictionary")
            keys = set(request)
            if not required_keys.issubset(keys) or not keys.issubset(
                allowed_keys
            ):
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
            self._resource(resource)
            self._interval(start, end)
            self._positive(duration)
            self._positive(units)
            self._positive(min_part)
            self._positive(max_parts)

            width = end - start
            if width > 120:
                raise ValueError("planning range too long")
            if duration > width:
                raise ValueError("duration exceeds planning range")
            if min_part > duration:
                raise ValueError("minimum part exceeds duration")
            if max_parts > 6:
                raise ValueError("too many parts")
            if booking_id in new_ids or booking_id in records:
                raise ValueError("duplicate booking")

            segments = self._choose_segments(
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
            new_ids.add(booking_id)
            result.append(self._snapshot(booking_id, record))

        self._bookings = records
        return result
=== END ===