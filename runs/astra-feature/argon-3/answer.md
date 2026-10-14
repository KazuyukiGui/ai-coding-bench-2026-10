=== FILE: capacity_calendar.py ===
"""Integer-time reservations for resources with fixed capacities."""


class CapacityCalendar:
    """Keep reservations in memory and expose independent snapshots."""

    _REQUIRED_PLAN_KEYS = frozenset(
        {"id", "resource", "start", "end", "duration"}
    )
    _ALLOWED_PLAN_KEYS = _REQUIRED_PLAN_KEYS | frozenset(
        {"units", "min_part", "max_parts"}
    )

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
    def _select_segments(start, span_len, duration, min_part, max_parts, usable):
        """Find the lexicographically smallest valid segment decomposition."""
        run = [0] * (span_len + 1)
        for i in range(span_len - 1, -1, -1):
            if usable[i]:
                run[i] = run[i + 1] + 1

        mask = (1 << (duration + 1)) - 1
        dp_false = [[0] * (max_parts + 1) for _ in range(span_len + 1)]
        dp_true = [[0] * (max_parts + 1) for _ in range(span_len + 1)]

        for p in range(max_parts + 1):
            dp_false[span_len][p] = 1
            dp_true[span_len][p] = 1

        for i in range(span_len - 1, -1, -1):
            u = usable[i]
            r = run[i]
            next_false = dp_false[i + 1]
            next_true = dp_true[i + 1]
            cur_false = dp_false[i]
            cur_true = dp_true[i]
            jump_true = dp_true[i + min_part] if r >= min_part else None

            for p in range(max_parts + 1):
                res_true = next_false[p]
                if u:
                    res_true |= (next_true[p] << 1) & mask
                cur_true[p] = res_true

                res_false = next_false[p]
                if p >= 1 and jump_true is not None:
                    res_false |= (jump_true[p - 1] << min_part) & mask
                cur_false[p] = res_false

        if not ((dp_false[0][max_parts] >> duration) & 1):
            raise ValueError("insufficient capacity for split booking")

        segments = []
        i = 0
        rem_dur = duration
        p = max_parts
        in_seg = False

        while rem_dur > 0:
            if not in_seg:
                if (
                    p >= 1
                    and run[i] >= min_part
                    and rem_dur >= min_part
                    and ((dp_true[i + min_part][p - 1] >> (rem_dur - min_part)) & 1)
                ):
                    segments.append([start + i, start + i + min_part])
                    i += min_part
                    rem_dur -= min_part
                    p -= 1
                    in_seg = True
                else:
                    i += 1
            else:
                if (
                    usable[i]
                    and ((dp_true[i + 1][p] >> (rem_dur - 1)) & 1)
                ):
                    segments[-1][1] += 1
                    i += 1
                    rem_dur -= 1
                else:
                    i += 1
                    in_seg = False

        return tuple((left, right) for left, right in segments)

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
        """Plan and atomically apply a batch of split reservations."""
        if not isinstance(requests, list):
            raise ValueError("requests must be a list")
        if not isinstance(replace, (list, tuple)):
            raise ValueError("replace must be a list or tuple")

        records = dict(self._bookings)
        seen_replace = set()
        for booking_id in replace:
            self._name(booking_id)
            if booking_id in seen_replace or booking_id not in self._bookings:
                raise ValueError("invalid or duplicate replace id")
            seen_replace.add(booking_id)
            del records[booking_id]

        planned = []
        for req in requests:
            if not isinstance(req, dict):
                raise ValueError("each request must be a dict")
            keys = req.keys()
            if not (
                self._REQUIRED_PLAN_KEYS <= keys <= self._ALLOWED_PLAN_KEYS
            ):
                raise ValueError("invalid request keys")

            booking_id = self._name(req["id"])
            if booking_id in records:
                raise ValueError("duplicate booking id")

            resource = self._resource(req["resource"])
            start = req["start"]
            end = req["end"]
            self._interval(start, end)
            span_len = end - start
            if span_len > 120:
                raise ValueError("planning range exceeds limit")

            duration = req["duration"]
            if type(duration) is not int or duration < 1 or duration > span_len:
                raise ValueError("invalid duration")

            units = req.get("units", 1)
            self._positive(units)

            min_part = req.get("min_part", 1)
            if type(min_part) is not int or min_part < 1 or min_part > duration:
                raise ValueError("invalid min_part")

            max_parts = req.get("max_parts", 1)
            if type(max_parts) is not int or max_parts < 1 or max_parts > 6:
                raise ValueError("invalid max_parts")

            spans = self._available(resource, start, end, units, records)
            usable = [False] * span_len
            for left, right in spans:
                for t in range(left - start, right - start):
                    usable[t] = True

            segments = self._select_segments(
                start, span_len, duration, min_part, max_parts, usable
            )
            record = (resource, units, segments)
            records[booking_id] = record
            planned.append(self._snapshot(booking_id, record))

        self._bookings = records
        return planned

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
