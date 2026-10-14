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
        if resource_id not in self._resources:
            raise KeyError(f"Unknown resource: {resource_id}")
        if start < 0 or end <= start:
            raise ValueError("Invalid time window")

        resource = self._resources[resource_id]
        overlapping = [
            allocation
            for allocation in self._allocations[resource_id]
            if allocation.overlaps(start, end)
        ]
        if not overlapping:
            return resource.total_units

        max_used = 0
        for t in range(start, end):
            used = sum(
                allocation.units
                for allocation in overlapping
                if allocation.start <= t < allocation.end
            )
            max_used = max(max_used, used)

        return resource.total_units - max_used

    def allocate(self, request: ReservationRequest) -> Allocation | None:
        if request.request_id in self._by_request_id:
            raise ValueError(f"Duplicate request_id: {request.request_id}")

        if request.preferred_resource_id is not None:
            if request.preferred_resource_id not in self._resources:
                raise KeyError(
                    f"Unknown resource: {request.preferred_resource_id}"
                )
            resource = self._resources[request.preferred_resource_id]
            if resource.category != request.category:
                raise ValueError("Resource category mismatch")
            candidates = [resource]
        else:
            candidates = [
                resource
                for resource in self._resources.values()
                if resource.category == request.category
            ]

        choices: list[tuple[int, int, str, Resource]] = []
        for resource in candidates:
            available = self.available_units(
                resource.resource_id, request.start, request.end
            )
            if available < request.min_units:
                continue

            allocation_units = min(request.units, available)
            remaining = available - allocation_units
            choices.append(
                (
                    -allocation_units,
                    remaining,
                    resource.resource_id,
                    resource,
                )
            )

        if not choices:
            return None

        _, _, _, selected_resource = min(choices)
        available = self.available_units(
            selected_resource.resource_id, request.start, request.end
        )
        allocation_units = min(request.units, available)

        allocation = Allocation(
            request_id=request.request_id,
            resource_id=selected_resource.resource_id,
            category=request.category,
            start=request.start,
            end=request.end,
            priority=request.priority,
            units=allocation_units,
        )
        self._allocations[selected_resource.resource_id].append(allocation)
        self._by_request_id[request.request_id] = allocation
        return allocation

    def release(
        self, request_id: str, units: int | None = None
    ) -> Allocation | None:
        if request_id not in self._by_request_id:
            raise KeyError(f"Unknown request_id: {request_id}")

        allocation = self._by_request_id[request_id]

        if units is not None and (units < 1 or units > allocation.units):
            raise ValueError("Invalid number of units to release")

        if units is None or units == allocation.units:
            del self._by_request_id[request_id]
            self._allocations[allocation.resource_id].remove(allocation)
            return allocation

        updated = replace(allocation, units=allocation.units - units)
        resource_allocations = self._allocations[allocation.resource_id]
        index = resource_allocations.index(allocation)
        resource_allocations[index] = updated
        self._by_request_id[request_id] = updated
        return updated
=== FILE: service.py ===
from allocator import ResourceAllocator
from models import Allocation, ReservationRequest, Resource


class BookingService:
    def __init__(self, allocator: ResourceAllocator | None = None) -> None:
        self.allocator = allocator if allocator is not None else ResourceAllocator()

    def register_resource(
        self, resource_id: str, category: str, total_units: int
    ) -> Resource:
        resource = Resource(
            resource_id=resource_id,
            category=category,
            total_units=total_units,
        )
        self.allocator.add_resource(resource)
        return resource

    def submit_batch(
        self, requests: list[ReservationRequest]
    ) -> dict[str, Allocation | None]:
        request_ids = [request.request_id for request in requests]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("Duplicate request_id in batch")

        existing_ids = {
            allocation.request_id
            for allocation in self.allocator.get_allocations()
        }
        if existing_ids.intersection(request_ids):
            raise ValueError("request_id already allocated")

        ordered = sorted(
            requests,
            key=lambda request: (
                -request.priority,
                request.start,
                -(request.end - request.start) * request.units,
                request.request_id,
            ),
        )

        results: dict[str, Allocation | None] = {}
        for request in ordered:
            results[request.request_id] = self.allocator.allocate(request)
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
            self.allocator.get_resource(resource_id)
            for resource_id in self._resource_ids_by_category(category)
        ]
        duration = window_end - window_start
        total_capacity = sum(
            resource.total_units * duration for resource in resources
        )

        allocations: list[Allocation] = []
        allocated = 0
        for resource in resources:
            for allocation in self.allocator.get_allocations(
                resource.resource_id
            ):
                if not allocation.overlaps(window_start, window_end):
                    continue

                allocations.append(allocation)
                overlap_start = max(allocation.start, window_start)
                overlap_end = min(allocation.end, window_end)
                allocated += (
                    overlap_end - overlap_start
                ) * allocation.units

        peak = 0
        for t in range(window_start, window_end):
            concurrent_units = sum(
                allocation.units
                for allocation in allocations
                if allocation.start <= t < allocation.end
            )
            peak = max(peak, concurrent_units)

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
        existing = next(
            (
                allocation
                for allocation in self.allocator.get_allocations()
                if allocation.request_id == request_id
            ),
            None,
        )
        if existing is None:
            raise KeyError(f"Unknown request_id: {request_id}")

        target_units = existing.units if new_units is None else new_units
        if new_start < 0 or new_end <= new_start or target_units < 1:
            raise ValueError("Invalid reschedule parameters")

        self.allocator.release(request_id)

        same_resource_request = ReservationRequest(
            request_id=request_id,
            category=existing.category,
            start=new_start,
            end=new_end,
            priority=existing.priority,
            units=target_units,
            min_units=target_units,
            preferred_resource_id=existing.resource_id,
        )
        allocation = self.allocator.allocate(same_resource_request)
        if allocation is not None:
            return allocation

        any_resource_request = ReservationRequest(
            request_id=request_id,
            category=existing.category,
            start=new_start,
            end=new_end,
            priority=existing.priority,
            units=target_units,
            min_units=target_units,
            preferred_resource_id=None,
        )
        allocation = self.allocator.allocate(any_resource_request)
        if allocation is not None:
            return allocation

        restore_request = ReservationRequest(
            request_id=existing.request_id,
            category=existing.category,
            start=existing.start,
            end=existing.end,
            priority=existing.priority,
            units=existing.units,
            min_units=existing.units,
            preferred_resource_id=existing.resource_id,
        )
        restored = self.allocator.allocate(restore_request)
        if restored is None:
            raise RuntimeError(
                "Reschedule failed and original allocation could not be restored"
            )

        raise RuntimeError("Unable to reschedule allocation")

    def _resource_ids_by_category(self, category: str) -> list[str]:
        return sorted(
            resource_id
            for resource_id, resource in getattr(
                self.allocator, "_resources", {}
            ).items()
            if resource.category == category
        )
=== END ===