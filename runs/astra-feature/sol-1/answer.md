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
    def _segments(times):
        segments = []
        left = times[0]
        right = left + 1
        for time in times[1:]:
            if time == right:
                right += 1
            else:
                segments.append((left, right))
                left = time
                right = time + 1
        segments.append((left, right))
        return tuple(segments)

    def _plan_one(
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
        usable = set()
        for left, right in spans:
            usable.update(range(left, right))

        states = {(0, 0, 0): ()}
        for time in range(start, end):
            next_states = {}
            for (used, parts, run_length), chosen in states.items():
                if run_length == 0 or run_length == min_part:
                    state = (used, parts, 0)
                    previous = next_states.get(state)
                    if previous is None or chosen < previous:
                        next_states[state] = chosen

                if time not in usable or used == duration:
                    continue

                next_parts = parts
                if run_length == 0:
                    next_parts += 1
                    if next_parts > max_parts:
                        continue

                next_run = min(min_part, run_length + 1)
                state = (used + 1, next_parts, next_run)
                candidate = chosen + (time,)
                previous = next_states.get(state)
                if previous is None or candidate < previous:
                    next_states[state] = candidate
            states = next_states

        best = None
        for (used, _parts, run_length), chosen in states.items():
            if used != duration:
                continue
            if run_length not in (0, min_part):
                continue
            if best is None or chosen < best:
                best = chosen

        if best is None:
            raise ValueError("cannot construct booking")
        return self._segments(best)

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
        if not isinstance(replace, (list, tuple)):
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

        records = {
            booking_id: record
            for booking_id, record in self._bookings.items()
            if booking_id not in replace_set
        }

        allowed_keys = {
            "id",
            "resource",
            "start",
            "end",
            "duration",
            "units",
            "min_part",
            "max_parts",
        }
        required_keys = {"id", "resource", "start", "end", "duration"}
        new_ids = set()
        result = []

        for request in requests:
            if not isinstance(request, dict):
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
            self._query(resource, start, end, units)

            if end - start > 120:
                raise ValueError("planning interval too long")
            if type(duration) is not int:
                raise ValueError("duration must be an integer")
            if duration < 1 or duration > end - start:
                raise ValueError("invalid duration")
            if type(min_part) is not int:
                raise ValueError("min_part must be an integer")
            if min_part < 1 or min_part > duration:
                raise ValueError("invalid min_part")
            if type(max_parts) is not int:
                raise ValueError("max_parts must be an integer")
            if max_parts < 1 or max_parts > 6:
                raise ValueError("invalid max_parts")

            if booking_id in new_ids or booking_id in records:
                raise ValueError("duplicate booking")
            new_ids.add(booking_id)

            segments = self._plan_one(
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
            result.append(self._snapshot(booking_id, record))

        self._bookings = records
        return result
=== END ===