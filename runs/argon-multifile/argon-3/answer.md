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
        resolved_min = self.units if self.min_units is None else self.min_units
        object.__setattr__(self, "min_units", resolved_min)
        if resolved_min < 1 or resolved_min > self.units:
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
        if resource_id not in self._resources:
            raise KeyError(f"Unknown resource: {resource_id}")
        if start < 0 or end <= start:
            raise ValueError("Invalid time window")

        resource = self._resources[resource_id]
        overlapping = [
            a for a in self._allocations[resource_id] if a.overlaps(start, end)
        ]
        if not overlapping:
            return resource.total_units

        max_used = 0
        for t in range(start, end):
            used = sum(a.units for a in overlapping if a.start <= t < a.end)
            if used > max_used:
                max_used = used
        return resource.total_units - max_used

    def allocate(self, request: ReservationRequest) -> Allocation | None:
        if request.request_id in self._by_request_id:
            raise ValueError(f"Duplicate request_id: {request.request_id}")

        if request.preferred_resource_id is not None:
            if request.preferred_resource_id not in self._resources:
                raise KeyError(f"Unknown resource: {request.preferred_resource_id}")
            res = self._resources[request.preferred_resource_id]
            if res.category != request.category:
                raise ValueError("Resource category mismatch")
            candidates = [res]
        else:
            candidates = [
                r for r in self._resources.values() if r.category == request.category
            ]

        min_units = (
            request.min_units if request.min_units is not None else request.units
        )
        scored_candidates: list[tuple[int, int, str, Resource, int]] = []
        for res in candidates:
            avail = self.available_units(res.resource_id, request.start, request.end)
            if avail >= min_units:
                alloc_units = min(request.units, avail)
                scored_candidates.append(
                    (
                        -alloc_units,
                        avail - alloc_units,
                        res.resource_id,
                        res,
                        alloc_units,
                    )
                )

        if not scored_candidates:
            return None

        scored_candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        _, _, _, best_resource, best_alloc_units = scored_candidates[0]

        alloc = Allocation(
            request_id=request.request_id,
            resource_id=best_resource.resource_id,
            category=request.category,
            start=request.start,
            end=request.end,
            priority=request.priority,
            units=best_alloc_units,
        )
        self._allocations[best_resource.resource_id].append(alloc)
        self._by_request_id[request.request_id] = alloc
        return alloc

    def release(self, request_id: str, units: int | None = None) -> Allocation | None:
        if request_id not in self._by_request_id:
            raise KeyError(f"Unknown request_id: {request_id}")
        alloc = self._by_request_id[request_id]

        if units is not None:
            if units < 1 or units > alloc.units:
                raise ValueError("Invalid units to release")

        if units is None or units == alloc.units:
            self._by_request_id.pop(request_id)
            self._allocations[alloc.resource_id].remove(alloc)
            return alloc

        updated_alloc = Allocation(
            request_id=alloc.request_id,
            resource_id=alloc.resource_id,
            category=alloc.category,
            start=alloc.start,
            end=alloc.end,
            priority=alloc.priority,
            units=alloc.units - units,
        )
        self._by_request_id[request_id] = updated_alloc
        idx = self._allocations[alloc.resource_id].index(alloc)
        self._allocations[alloc.resource_id][idx] = updated_alloc
        return updated_alloc
=== FILE: service.py ===
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
        existing_ids = {a.request_id for a in self.allocator.get_allocations()}
        seen_ids: set[str] = set()
        for req in requests:
            if req.request_id in seen_ids or req.request_id in existing_ids:
                raise ValueError(f"Duplicate request_id: {req.request_id}")
            seen_ids.add(req.request_id)

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

    def cancel_or_reduce(self, request_id: str, units: int | None = None) -> bool:
        try:
            self.allocator.release(request_id, units)
            return True
        except KeyError:
            return False

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
        total_capacity = sum(r.total_units * duration for r in resources)

        overlapping_allocs: list[Allocation] = []
        allocated = 0
        for r in resources:
            for alloc in self.allocator.get_allocations(r.resource_id):
                if alloc.overlaps(window_start, window_end):
                    overlapping_allocs.append(alloc)
                    overlap_start = max(alloc.start, window_start)
                    overlap_end = min(alloc.end, window_end)
                    allocated += (overlap_end - overlap_start) * alloc.units

        peak = 0
        if overlapping_allocs:
            for t in range(window_start, window_end):
                concurrent = sum(
                    a.units for a in overlapping_allocs if a.start <= t < a.end
                )
                if concurrent > peak:
                    peak = concurrent

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
        current_alloc: Allocation | None = None
        for alloc in self.allocator.get_allocations():
            if alloc.request_id == request_id:
                current_alloc = alloc
                break
        if current_alloc is None:
            raise KeyError(f"Unknown request_id: {request_id}")

        target_units = new_units if new_units is not None else current_alloc.units
        if new_start < 0 or new_end <= new_start or target_units < 1:
            raise ValueError("Invalid reschedule parameters")

        self.allocator.release(request_id)

        preferred_req = ReservationRequest(
            request_id=current_alloc.request_id,
            category=current_alloc.category,
            start=new_start,
            end=new_end,
            priority=current_alloc.priority,
            units=target_units,
            min_units=target_units,
            preferred_resource_id=current_alloc.resource_id,
        )
        new_alloc = self.allocator.allocate(preferred_req)
        if new_alloc is not None:
            return new_alloc

        any_req = ReservationRequest(
            request_id=current_alloc.request_id,
            category=current_alloc.category,
            start=new_start,
            end=new_end,
            priority=current_alloc.priority,
            units=target_units,
            min_units=target_units,
            preferred_resource_id=None,
        )
        new_alloc = self.allocator.allocate(any_req)
        if new_alloc is not None:
            return new_alloc

        restore_req = ReservationRequest(
            request_id=current_alloc.request_id,
            category=current_alloc.category,
            start=current_alloc.start,
            end=current_alloc.end,
            priority=current_alloc.priority,
            units=current_alloc.units,
            min_units=current_alloc.units,
            preferred_resource_id=current_alloc.resource_id,
        )
        self.allocator.allocate(restore_req)
        raise RuntimeError(f"Could not reschedule request: {request_id}")

    def _resource_ids_by_category(self, category: str) -> list[str]:
        all_allocs = self.allocator.get_allocations()
        seen: set[str] = set()
        for a in all_allocs:
            if a.category == category:
                seen.add(a.resource_id)
        for rid, res in getattr(self.allocator, "_resources", {}).items():
            if res.category == category:
                seen.add(rid)
        return sorted(seen)
=== END ===
