"""Analyze connected edge chains in DXF modelspace."""
from typing import List, Dict, Tuple, Optional
from collections import defaultdict, deque
from ezdxf.math import Vec2

from backend.config import POINT_TOLERANCE
from backend.dxf_engine import geometry_utils as geom


def build_chain(doc, seed_handles: List[str]) -> List[str]:
    """
    From the given seed handles, expand to all connected edge entities
    and return them in ordered chain form.
    """
    if not seed_handles:
        return []

    graph, endpoint_map = _build_adjacency(doc)

    # BFS from all seeds
    reachable = set()
    queue = deque(seed_handles)
    while queue:
        handle = queue.popleft()
        if handle in reachable:
            continue
        reachable.add(handle)
        for neighbor in graph.get(handle, []):
            if neighbor not in reachable:
                queue.append(neighbor)

    # Order the reachable handles into a chain
    ordered = _order_chain(reachable, graph, endpoint_map, doc)
    return ordered


def get_chain_info(doc, chain: List[str]) -> dict:
    total = 0.0
    is_closed = False

    if len(chain) == 1:
        entity = doc.entitydb.get(chain[0])
        if entity:
            dtype = entity.dxftype()
            if dtype == "CIRCLE":
                is_closed = True
            elif dtype == "LWPOLYLINE":
                is_closed = entity.closed
            elif dtype == "POLYLINE":
                is_closed = entity.is_closed
    elif len(chain) >= 2:
        # Build adjacency restricted to chain
        graph, _ = _build_adjacency(doc)
        handles_in_chain = set(chain)
        all_two_neighbors = all(
            len([n for n in graph.get(h, []) if n in handles_in_chain]) == 2
            for h in chain
        )

        # Also check geometric closure: first start == last end
        ep_first = geom.entity_endpoints(doc.entitydb[chain[0]])
        ep_last = geom.entity_endpoints(doc.entitydb[chain[-1]])
        geometric_closed = False
        if ep_first and ep_last:
            geometric_closed = _points_equal(ep_first[0], ep_last[1])

        is_closed = all_two_neighbors or geometric_closed

    for handle in chain:
        entity = doc.entitydb.get(handle)
        if entity:
            total += geom.entity_length(entity)

    return {
        "total_length": round(total, 4),
        "segment_count": len(chain),
        "is_closed": is_closed,
    }


def _build_adjacency(doc) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """
    Build endpoint adjacency graph.
    Returns (handle -> neighbors, handle -> endpoint_keys).
    """
    endpoint_index: Dict[str, List[str]] = defaultdict(list)  # rounded_point -> handles
    handle_endpoints: Dict[str, List[str]] = {}

    for entity in doc.modelspace():
        dtype = entity.dxftype()
        if dtype not in ("LINE", "ARC", "LWPOLYLINE", "POLYLINE", "ELLIPSE", "SPLINE", "CIRCLE"):
            continue

        endpoints = geom.entity_endpoints(entity)
        if not endpoints:
            continue

        handle = entity.dxf.handle
        keys = []
        for pt in endpoints:
            key = _point_key(pt)
            keys.append(key)
            endpoint_index[key].append(handle)
        handle_endpoints[handle] = keys

    graph: Dict[str, List[str]] = defaultdict(list)
    for key, handles in endpoint_index.items():
        if len(handles) < 2:
            continue
        for h1 in handles:
            for h2 in handles:
                if h1 != h2 and h2 not in graph[h1]:
                    graph[h1].append(h2)

    return graph, handle_endpoints


def _order_chain(reachable: set, graph: Dict[str, List[str]],
                 handle_endpoints: Dict[str, List[str]], doc) -> List[str]:
    """
    Order reachable handles into a path from one end to the other.
    If closed, start anywhere and follow around.
    """
    if not reachable:
        return []

    remaining = set(reachable)

    # Find an endpoint handle (one with fewer than 2 connections within reachable)
    start = None
    for handle in reachable:
        neighbors_in_set = [n for n in graph.get(handle, []) if n in remaining]
        if len(neighbors_in_set) < 2:
            start = handle
            break

    if start is None:
        # Closed loop: pick any
        start = next(iter(remaining))

    ordered = [start]
    remaining.remove(start)

    # Build helper to find connecting endpoint between two handles
    def find_next(current: str, prev: Optional[str]) -> Optional[str]:
        current_eps = handle_endpoints.get(current, [])
        for neighbor in graph.get(current, []):
            if neighbor not in remaining or neighbor == prev:
                continue
            neighbor_eps = handle_endpoints.get(neighbor, [])
            # Check if they share an endpoint key
            for k1 in current_eps:
                if k1 in neighbor_eps:
                    return neighbor
        return None

    prev = None
    current = start
    while True:
        next_handle = find_next(current, prev)
        if not next_handle:
            break
        ordered.append(next_handle)
        remaining.remove(next_handle)
        prev = current
        current = next_handle

    # If there are remaining disconnected pieces (shouldn't happen with BFS), append them
    # but log a warning implicitly by keeping them out of order.
    # For our use case we only expect one connected component.
    ordered.extend(sorted(remaining))

    # For LWPOLYLINE entities that are themselves closed, we treat them as a single segment.
    return ordered


def _point_key(p: Vec2) -> str:
    """Round point to tolerance-based key for endpoint matching."""
    x = round(p.x / POINT_TOLERANCE)
    y = round(p.y / POINT_TOLERANCE)
    return f"{x},{y}"


def _points_equal(a: Vec2, b: Vec2) -> bool:
    return (a - b).magnitude < POINT_TOLERANCE
