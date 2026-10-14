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
        seen_ids: set[str] = set()
        existing_ids = {a.request_id for a in self.allocator.get_allocations()}
        for req in requests:
            if req.request_id in seen_ids or req.request_id in existing_ids:
                raise ValueError(f"Duplicate request_id in batch: {req.request_id}")
            seen_ids.add(req.request_id)

        ordered = sorted(
            requests,
            key=lambda r: (
                -r.priority,
                r.start,
                -((r.end - r.start) * r.units),
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

        category_allocs: list[Allocation] = []
        allocated = 0
        for r in resources:
            for alloc in self.allocator.get_allocations(r.resource_id):
                if alloc.overlaps(window_start, window_end):
                    category_allocs.append(alloc)
                    overlap_start = max(alloc.start, window_start)
                    overlap_end = min(alloc.end, window_end)
                    allocated += (overlap_end - overlap_start) * alloc.units

        peak = 0
        if category_allocs:
            for t in range(window_start, window_end):
                concurrent = sum(
                    a.units for a in category_allocs if a.start <= t < a.end
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
        all_allocs = {a.request_id: a for a in self.allocator.get_allocations()}
        if request_id not in all_allocs:
            raise KeyError(f"Unknown request_id: {request_id}")

        original = all_allocs[request_id]
        target_units = original.units if new_units is None else new_units

        if new_start < 0 or new_end <= new_start or target_units < 1:
            raise ValueError("Invalid reschedule parameters")

        self.allocator.release(request_id)

        same_res_req = ReservationRequest(
            request_id=request_id,
            category=original.category,
            start=new_start,
            end=new_end,
            priority=original.priority,
            units=target_units,
            min_units=target_units,
            preferred_resource_id=original.resource_id,
        )
        new_alloc = self.allocator.allocate(same_res_req)
        if new_alloc is not None:
            return new_alloc

        any_res_req = ReservationRequest(
            request_id=request_id,
            category=original.category,
            start=new_start,
            end=new_end,
            priority=original.priority,
            units=target_units,
            min_units=target_units,
            preferred_resource_id=None,
        )
        new_alloc = self.allocator.allocate(any_res_req)
        if new_alloc is not None:
            return new_alloc

        rollback_req = ReservationRequest(
            request_id=original.request_id,
            category=original.category,
            start=original.start,
            end=original.end,
            priority=original.priority,
            units=original.units,
            min_units=original.units,
            preferred_resource_id=original.resource_id,
        )
        restored = self.allocator.allocate(rollback_req)
        if restored is None:
            raise RuntimeError("Critical failure during rollback")
        raise RuntimeError(f"Could not reschedule request {request_id}")

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
