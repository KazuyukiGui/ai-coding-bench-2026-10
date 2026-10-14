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

    def _plan_single(
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
        """Find the lexicographically earliest valid segment split."""
        spans = self._available(resource, start, end, units, records)
        length = end - start
        max_reach = list(range(length + 1))
        usable_total = 0
        for left, right in spans:
            rel_left = left - start
            rel_right = right - start
            if rel_right - rel_left >= min_part:
                usable_total += rel_right - rel_left
            for t in range(rel_left, rel_right):
                max_reach[t] = rel_right

        if usable_total < duration:
            raise ValueError("insufficient capacity")

        mask_d = (1 << (duration + 1)) - 1
        dp = [[0] * (length + 2) for _ in range(max_parts + 1)]
        for p in range(max_parts + 1):
            dp[p][length] = 1
            dp[p][length + 1] = 1

        for t in range(length):
            dp[0][t] = 1

        for p in range(1, max_parts + 1):
            dp_prev = dp[p - 1]
            dp_curr = dp[p]
            acc = 0
            for t in range(length - 1, -1, -1):
                reach = max_reach[t]
                e = t + min_part
                if e == reach:
                    acc = dp_prev[e + 1] << e
                    dp_curr[t] = dp_curr[t + 1] | ((acc >> t) & mask_d)
                elif e < reach:
                    acc |= dp_prev[e + 1] << e
                    dp_curr[t] = dp_curr[t + 1] | ((acc >> t) & mask_d)
                else:
                    dp_curr[t] = dp_curr[t + 1]

        if not ((dp[max_parts][0] >> duration) & 1):
            raise ValueError("cannot plan reservation")

        segments = []
        cur_t = 0
        rem_dur = duration
        rem_parts = max_parts
        while rem_dur > 0:
            dp_prev = dp[rem_parts - 1]
            chosen_s = -1
            chosen_e = -1
            for s in range(cur_t, length - min_part + 1):
                max_e = min(max_reach[s], s + rem_dur)
                min_e = s + min_part
                if min_e > max_e:
                    continue
                for e in range(max_e, min_e - 1, -1):
                    if (dp_prev[e + 1] >> (rem_dur - (e - s))) & 1:
                        chosen_s = s
                        chosen_e = e
                        break
                if chosen_s != -1:
                    break
            segments.append((start + chosen_s, start + chosen_e))
            rem_dur -= chosen_e - chosen_s
            rem_parts -= 1
            cur_t = chosen_e + 1

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
        """Plan and atomically apply a batch of segmented reservations."""
        if type(requests) is not list:
            raise ValueError("requests must be a list")
        if type(replace) not in (list, tuple):
            raise ValueError("replace must be a list or tuple")

        working_bookings = dict(self._bookings)
        seen_replace = set()
        for booking_id in replace:
            self._name(booking_id)
            if booking_id in seen_replace or booking_id not in self._bookings:
                raise ValueError("invalid replace booking ID")
            seen_replace.add(booking_id)
            del working_bookings[booking_id]

        results = []
        for req in requests:
            if type(req) is not dict:
                raise ValueError("each request must be a dict")
            keys = req.keys()
            if (
                not self._REQUIRED_PLAN_KEYS.issubset(keys)
                or not self._ALLOWED_PLAN_KEYS.issuperset(keys)
            ):
                raise ValueError("invalid request keys")

            booking_id = self._name(req["id"])
            if booking_id in working_bookings:
                raise ValueError("duplicate booking")
            resource = self._resource(req["resource"])
            start = req["start"]
            end = req["end"]
            self._interval(start, end)
            if end - start > 120:
                raise ValueError("planning interval exceeds maximum length")

            duration = req["duration"]
            if type(duration) is not int or not (1 <= duration <= end - start):
                raise ValueError("invalid duration")

            units = req.get("units", 1)
            self._positive(units)

            min_part = req.get("min_part", 1)
            if type(min_part) is not int or not (1 <= min_part <= duration):
                raise ValueError("invalid min_part")

            max_parts = req.get("max_parts", 1)
            if type(max_parts) is not int or not (1 <= max_parts <= 6):
                raise ValueError("invalid max_parts")

            segments = self._plan_single(
                resource,
                start,
                end,
                duration,
                units,
                min_part,
                max_parts,
                working_bookings,
            )
            record = (resource, units, segments)
            working_bookings[booking_id] = record
            results.append(self._snapshot(booking_id, record))

        self._bookings = working_bookings
        return results
=== END ===
