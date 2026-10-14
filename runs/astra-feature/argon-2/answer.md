=== FILE: capacity_calendar.py ===
"""Integer-time reservations for resources with fixed capacities."""

_REQUIRED_PLAN_KEYS = frozenset({"id", "resource", "start", "end", "duration"})
_ALLOWED_PLAN_KEYS = _REQUIRED_PLAN_KEYS | frozenset(
    {"units", "min_part", "max_parts"}
)


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
        """Find the lexicographically earliest valid split reservation."""
        spans = self._available(resource, start, end, units, records)
        if sum(right - left for left, right in spans) < duration:
            raise ValueError("insufficient capacity")

        n = end - start
        avail = [False] * n
        run = [0] * (n + 1)
        for left, right in spans:
            rel_left = left - start
            rel_right = right - start
            for t in range(rel_left, rel_right):
                avail[t] = True
                run[t] = rel_right - t

        inf = max_parts + 1
        dp_gap = [[inf] * (duration + 1) for _ in range(n + 1)]
        dp_ext = [[inf] * (duration + 1) for _ in range(n + 1)]
        dp_gap[n][0] = 0
        dp_ext[n][0] = 0

        for t in range(n - 1, -1, -1):
            dp_gap_t = dp_gap[t]
            dp_ext_t = dp_ext[t]
            dp_gap_next = dp_gap[t + 1]
            dp_ext_next = dp_ext[t + 1]
            dp_gap_t[0] = 0
            dp_ext_t[0] = 0

            can_start = run[t] >= min_part
            if can_start:
                dp_ext_jump = dp_ext[t + min_part]
            is_avail = avail[t]

            for d in range(1, duration + 1):
                best_ext = dp_gap_next[d]
                if is_avail:
                    cand = dp_ext_next[d - 1]
                    if cand < best_ext:
                        best_ext = cand
                dp_ext_t[d] = best_ext

                best_gap = dp_gap_next[d]
                if can_start and d >= min_part:
                    cand = 1 + dp_ext_jump[d - min_part]
                    if cand < best_gap:
                        best_gap = cand
                dp_gap_t[d] = best_gap

        if dp_gap[0][duration] > max_parts:
            raise ValueError("cannot satisfy split constraints")

        segments = []
        t = 0
        rem_d = duration
        rem_k = max_parts
        in_ext = False
        seg_start = 0

        while rem_d > 0:
            if not in_ext:
                if (
                    rem_d >= min_part
                    and run[t] >= min_part
                    and 1 + dp_ext[t + min_part][rem_d - min_part] <= rem_k
                ):
                    seg_start = t
                    t += min_part
                    rem_d -= min_part
                    rem_k -= 1
                    in_ext = True
                else:
                    t += 1
            else:
                if avail[t] and dp_ext[t + 1][rem_d - 1] <= rem_k:
                    t += 1
                    rem_d -= 1
                else:
                    segments.append((start + seg_start, start + t))
                    t += 1
                    in_ext = False

        if in_ext:
            segments.append((start + seg_start, start + t))

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
        """Plan and atomically apply a batch of split reservations."""
        if type(requests) is not list:
            raise ValueError("requests must be a list")
        if type(replace) not in (list, tuple):
            raise ValueError("replace must be a list or tuple")

        temp_bookings = dict(self._bookings)
        seen_replace = set()
        for booking_id in replace:
            self._name(booking_id)
            if booking_id in seen_replace or booking_id not in self._bookings:
                raise ValueError("invalid replace booking ID")
            seen_replace.add(booking_id)
            del temp_bookings[booking_id]

        results = []
        for req in requests:
            if type(req) is not dict:
                raise ValueError("each request must be a dict")
            if not _REQUIRED_PLAN_KEYS.issubset(req) or not set(req).issubset(
                _ALLOWED_PLAN_KEYS
            ):
                raise ValueError("invalid request keys")

            booking_id = self._name(req["id"])
            if booking_id in temp_bookings:
                raise ValueError("duplicate booking")

            resource = self._resource(req["resource"])
            start = req["start"]
            end = req["end"]
            self._interval(start, end)
            window = end - start
            if window > 120:
                raise ValueError("planning window exceeds limit")

            duration = self._positive(req["duration"])
            if duration > window:
                raise ValueError("duration exceeds planning window")

            units = self._positive(req.get("units", 1))
            min_part = self._positive(req.get("min_part", 1))
            if min_part > duration:
                raise ValueError("min_part exceeds duration")

            max_parts = self._positive(req.get("max_parts", 1))
            if max_parts > 6:
                raise ValueError("max_parts exceeds limit")

            segments = self._plan_single(
                resource,
                start,
                end,
                duration,
                units,
                min_part,
                max_parts,
                temp_bookings,
            )
            record = (resource, units, segments)
            temp_bookings[booking_id] = record
            results.append(self._snapshot(booking_id, record))

        self._bookings = temp_bookings
        return results

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
