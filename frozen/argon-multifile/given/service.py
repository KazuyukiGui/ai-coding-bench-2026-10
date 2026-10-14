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
        ordered = sorted(
            requests,
            key=lambda r: (-r.priority, r.start, r.end - r.start, r.request_id),
        )
        results: dict[str, Allocation | None] = {}
        for req in ordered:
            results[req.request_id] = self.allocator.allocate(req)
        return results

    def cancel(self, request_id: str) -> bool:
        try:
            self.allocator.release(request_id)
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

        allocated = 0
        for r in resources:
            for alloc in self.allocator.get_allocations(r.resource_id):
                if alloc.overlaps(window_start, window_end):
                    overlap_start = max(alloc.start, window_start)
                    overlap_end = min(alloc.end, window_end)
                    allocated += overlap_end - overlap_start

        rate = allocated / total_capacity if total_capacity > 0 else 0.0
        return {
            "total_capacity_unit_hours": float(total_capacity),
            "allocated_unit_hours": float(allocated),
            "utilization_rate": float(rate),
        }

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
