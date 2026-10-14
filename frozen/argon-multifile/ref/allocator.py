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

        min_required = request.min_units if request.min_units is not None else request.units
        scored_candidates: list[tuple[int, int, str, Resource, int]] = []

        for res in candidates:
            avail = self.available_units(res.resource_id, request.start, request.end)
            if avail >= min_required:
                alloc_units = min(request.units, avail)
                leftover = avail - alloc_units
                scored_candidates.append(
                    (-alloc_units, leftover, res.resource_id, res, alloc_units)
                )

        if not scored_candidates:
            return None

        scored_candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        _, _, _, best_resource, chosen_units = scored_candidates[0]

        alloc = Allocation(
            request_id=request.request_id,
            resource_id=best_resource.resource_id,
            category=request.category,
            start=request.start,
            end=request.end,
            priority=request.priority,
            units=chosen_units,
        )
        self._allocations[best_resource.resource_id].append(alloc)
        self._by_request_id[request.request_id] = alloc
        return alloc

    def release(self, request_id: str, units: int | None = None) -> Allocation | None:
        if request_id not in self._by_request_id:
            raise KeyError(f"Unknown request_id: {request_id}")

        current = self._by_request_id[request_id]
        if units is None or units == current.units:
            self._by_request_id.pop(request_id)
            self._allocations[current.resource_id].remove(current)
            return current

        if units < 1 or units > current.units:
            raise ValueError("Invalid units to release")

        updated = Allocation(
            request_id=current.request_id,
            resource_id=current.resource_id,
            category=current.category,
            start=current.start,
            end=current.end,
            priority=current.priority,
            units=current.units - units,
        )
        self._by_request_id[request_id] = updated
        res_list = self._allocations[current.resource_id]
        idx = res_list.index(current)
        res_list[idx] = updated
        return updated
