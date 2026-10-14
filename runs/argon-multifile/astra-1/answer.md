=== FILE: models.py ===
from dataclasses import dataclass


@dataclass(frozen=True)
class Resource:
    resource_id: str
    category: str
    total_units: int

    def __post_init__(self) -> None:
        if self.total_units < 1:
            raise ValueError("total_units must be >= 1")


@dataclass(frozen=True)
class ReservationRequest:
    request_id: str
    category: str
    start: int
    end: int
    priority: int = 0
    units: int = 1
    min_units: int | None = None
    preferred_resource_id: str | None = None

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Invalid time range")
        if self.units < 1:
            raise ValueError("units must be >= 1")
        if self.min_units is None:
            object.__setattr__(self, "min_units", self.units)
        if self.min_units < 1 or self.min_units > self.units:
            raise ValueError("min_units must be between 1 and units")


@dataclass(frozen=True)
class Allocation:
    request_id: str
    resource_id: str
    category: str
    start: int
    end: int
    priority: int
    units: int

    def overlaps(self, start: int, end: int) -> bool:
        return self.start < end and start < self.end

    def duration(self) -> int:
        return self.end - self.start

    def unit_hours(self) -> int:
        return self.duration() * self.units
=== FILE: allocator.py ===
from dataclasses import replace

from models import Allocation, ReservationRequest, Resource


class ResourceAllocator:
    def __init__(self) -> None:
        self._resources: dict[str, Resource] = {}
        self._allocations: dict[str, list[Allocation]] = {}
        self._by_request_id: dict[str, Allocation] = {}

    def add_resource(self, resource: Resource) -> None:
        if resource.resource_id in self._resources:
            raise ValueError(f"Resource {resource.resource_id} already exists")
        self._resources[resource.resource_id] = resource
        self._allocations[resource.resource_id] = []

    def get_resource(self, resource_id: str) -> Resource:
        if resource_id not in self._resources:
            raise KeyError(f"Unknown resource: {resource_id}")
        return self._resources[resource_id]

    def get_allocations(self, resource_id: str | None = None) -> list[Allocation]:
        if resource_id is not None:
            if resource_id not in self._resources:
                raise KeyError(f"Unknown resource: {resource_id}")
            result = list(self._allocations[resource_id])
        else:
            result = list(self._by_request_id.values())
        result.sort(key=lambda a: (a.start, a.end, a.request_id))
        return result

    def available_units(self, resource_id: str, start: int, end: int) -> int:
        resource = self.get_resource(resource_id)
        if start < 0 or end <= start:
            raise ValueError("Invalid time window")

        events: dict[int, int] = {}
        for alloc in self._allocations[resource_id]:
            if alloc.overlaps(start, end):
                overlap_start = max(alloc.start, start)
                overlap_end = min(alloc.end, end)
                events[overlap_start] = events.get(overlap_start, 0) + alloc.units
                events[overlap_end] = events.get(overlap_end, 0) - alloc.units

        used = 0
        max_used = 0
        for time in sorted(events):
            used += events[time]
            max_used = max(max_used, used)

        return resource.total_units - max_used

    def allocate(self, request: ReservationRequest) -> Allocation | None:
        if request.request_id in self._by_request_id:
            raise ValueError(f"Duplicate request_id: {request.request_id}")

        if request.preferred_resource_id is not None:
            resource = self.get_resource(request.preferred_resource_id)
            if resource.category != request.category:
                raise ValueError("Resource category mismatch")
            candidates = [resource]
        else:
            candidates = [
                resource
                for resource in self._resources.values()
                if resource.category == request.category
            ]

        best_resource: Resource | None = None
        best_key: tuple[int, int, str] | None = None
        best_units = 0

        for resource in candidates:
            avail = self.available_units(
                resource.resource_id, request.start, request.end
            )
            if avail < request.min_units:
                continue

            alloc_units = min(request.units, avail)
            key = (-alloc_units, avail - alloc_units, resource.resource_id)
            if best_key is None or key < best_key:
                best_resource = resource
                best_key = key
                best_units = alloc_units

        if best_resource is None:
            return None

        alloc = Allocation(
            request_id=request.request_id,
            resource_id=best_resource.resource_id,
            category=request.category,
            start=request.start,
            end=request.end,
            priority=request.priority,
            units=best_units,
        )
        self._allocations[best_resource.resource_id].append(alloc)
        self._by_request_id[request.request_id] = alloc
        return alloc

    def release(
        self, request_id: str, units: int | None = None
    ) -> Allocation | None:
        if request_id not in self._by_request_id:
            raise KeyError(f"Unknown request_id: {request_id}")

        alloc = self._by_request_id[request_id]
        if units is not None and (units < 1 or units > alloc.units):
            raise ValueError("units must be between 1 and allocated units")

        allocations = self._allocations[alloc.resource_id]
        if units is None or units == alloc.units:
            allocations.remove(alloc)
            del self._by_request_id[request_id]
            return alloc

        updated = replace(alloc, units=alloc.units - units)
        allocations[allocations.index(alloc)] = updated
        self._by_request_id[request_id] = updated
        return updated
=== FILE: service.py ===
from dataclasses import replace

from allocator import ResourceAllocator
from models import Allocation, ReservationRequest, Resource


class BookingService:
    def __init__(self, allocator: ResourceAllocator | None = None) -> None:
        self.allocator = allocator if allocator is not None else ResourceAllocator()

    def register_resource(
        self, resource_id: str, category: str, total_units: int
    ) -> Resource:
        res = Resource(
            resource_id=resource_id, category=category, total_units=total_units
        )
        self.allocator.add_resource(res)
        return res

    def submit_batch(
        self, requests: list[ReservationRequest]
    ) -> dict[str, Allocation | None]:
        seen = {alloc.request_id for alloc in self.allocator.get_allocations()}
        for request in requests:
            if request.request_id in seen:
                raise ValueError(f"Duplicate request_id: {request.request_id}")
            seen.add(request.request_id)

        ordered = sorted(
            requests,
            key=lambda r: (
                -r.priority,
                r.start,
                -(r.end - r.start) * r.units,
                r.request_id,
            ),
        )
        results: dict[str, Allocation | None] = {}
        for req in ordered:
            results[req.request_id] = self.allocator.allocate(req)
        return results

    def cancel_or_reduce(
        self, request_id: str, units: int | None = None
    ) -> bool:
        try:
            self.allocator.release(request_id, units)
        except KeyError:
            return False
        return True

    def cancel(self, request_id: str) -> bool:
        return self.cancel_or_reduce(request_id)

    def utilization_report(
        self, category: str, window_start: int, window_end: int
    ) -> dict[str, float]:
        if window_start < 0 or window_end <= window_start:
            raise ValueError("Invalid window")

        resources = [
            self.allocator.get_resource(rid)
            for rid in self._resource_ids_by_category(category)
        ]
        duration = window_end - window_start
        total_capacity = sum(r.total_units for r in resources) * duration

        allocated = 0
        events: dict[int, int] = {}
        for resource in resources:
            for alloc in self.allocator.get_allocations(resource.resource_id):
                if alloc.overlaps(window_start, window_end):
                    overlap_start = max(alloc.start, window_start)
                    overlap_end = min(alloc.end, window_end)
                    allocated += (overlap_end - overlap_start) * alloc.units
                    events[overlap_start] = (
                        events.get(overlap_start, 0) + alloc.units
                    )
                    events[overlap_end] = (
                        events.get(overlap_end, 0) - alloc.units
                    )

        concurrent = 0
        peak = 0
        for time in sorted(events):
            concurrent += events[time]
            peak = max(peak, concurrent)

        rate = allocated / total_capacity if total_capacity > 0 else 0.0
        return {
            "total_capacity_unit_hours": float(total_capacity),
            "allocated_unit_hours": float(allocated),
            "utilization_rate": float(rate),
            "peak_concurrent_units": float(peak),
        }

    def reschedule(
        self,
        request_id: str,
        new_start: int,
        new_end: int,
        new_units: int | None = None,
    ) -> Allocation:
        original = next(
            (
                alloc
                for alloc in self.allocator.get_allocations()
                if alloc.request_id == request_id
            ),
            None,
        )
        if original is None:
            raise KeyError(f"Unknown request_id: {request_id}")

        target_units = original.units if new_units is None else new_units
        request = ReservationRequest(
            request_id=original.request_id,
            category=original.category,
            start=new_start,
            end=new_end,
            priority=original.priority,
            units=target_units,
            min_units=target_units,
            preferred_resource_id=original.resource_id,
        )
        restore_request = ReservationRequest(
            request_id=original.request_id,
            category=original.category,
            start=original.start,
            end=original.end,
            priority=original.priority,
            units=original.units,
            min_units=original.units,
            preferred_resource_id=original.resource_id,
        )

        self.allocator.release(request_id)
        try:
            allocation = self.allocator.allocate(request)
            if allocation is None:
                allocation = self.allocator.allocate(
                    replace(request, preferred_resource_id=None)
                )
            if allocation is None:
                raise RuntimeError(f"Unable to reschedule request: {request_id}")
        except Exception:
            self.allocator.allocate(restore_request)
            raise

        return allocation

    def _resource_ids_by_category(self, category: str) -> list[str]:
        all_allocs = self.allocator.get_allocations()
        seen: set[str] = set()
        for alloc in all_allocs:
            if alloc.category == category:
                seen.add(alloc.resource_id)
        for rid, resource in getattr(self.allocator, "_resources", {}).items():
            if resource.category == category:
                seen.add(rid)
        return sorted(seen)
=== END ===