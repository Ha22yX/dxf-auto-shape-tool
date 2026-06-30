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
            is_closed = _entity_is_closed(entity)
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
    Order reachable handles by walking endpoint nodes.

    The old implementation followed the first unvisited handle-neighbor. That
    works for very simple drawings, but it loses which endpoint a neighbor was
    connected through. In multi-entity closed outlines a handle can be connected
    at both ends, and choosing only by handle adjacency can make the chain jump
    across the outline. Rebuilding the path as node(edge endpoint) -> edge ->
    next node preserves the true head-to-tail order.
    """
    if not reachable:
        return []
    if len(reachable) == 1:
        return [next(iter(reachable))]

    doc_order = {
        entity.dxf.handle: index
        for index, entity in enumerate(doc.modelspace())
        if hasattr(entity.dxf, "handle")
    }

    def handle_sort_key(handle: str):
        return (doc_order.get(handle, 10**9), handle)

    node_edges: Dict[str, List[str]] = defaultdict(list)
    for handle in reachable:
        endpoints = handle_endpoints.get(handle, [])
        if len(endpoints) < 2:
            continue
        for key in set(endpoints):
            node_edges[key].append(handle)

    # Handles without usable endpoints, such as circles, are standalone chains.
    if not node_edges:
        return sorted(reachable, key=handle_sort_key)

    remaining = set(reachable)
    ordered: List[str] = []

    def active_degree(node: str) -> int:
        return len([h for h in node_edges.get(node, []) if h in remaining])

    def other_endpoint(handle: str, current_node: str) -> Optional[str]:
        endpoints = handle_endpoints.get(handle, [])
        if len(endpoints) < 2:
            return None
        a, b = endpoints[0], endpoints[1]
        if a == current_node:
            return b
        if b == current_node:
            return a
        return None

    def choose_start_node() -> Optional[str]:
        open_nodes = [
            node for node in node_edges
            if active_degree(node) == 1
        ]
        if open_nodes:
            return min(
                open_nodes,
                key=lambda node: min(handle_sort_key(h) for h in node_edges[node] if h in remaining),
            )
        active_nodes = [node for node in node_edges if active_degree(node) > 0]
        if not active_nodes:
            return None
        return min(
            active_nodes,
            key=lambda node: min(handle_sort_key(h) for h in node_edges[node] if h in remaining),
        )

    def choose_next_handle(node: str) -> Optional[str]:
        candidates = [h for h in node_edges.get(node, []) if h in remaining]
        if not candidates:
            return None
        return min(candidates, key=handle_sort_key)

    while remaining:
        current_node = choose_start_node()
        if current_node is None:
            break

        while remaining:
            next_handle = choose_next_handle(current_node)
            if next_handle is None:
                break

            ordered.append(next_handle)
            remaining.remove(next_handle)

            next_node = other_endpoint(next_handle, current_node)
            if next_node is None:
                break
            current_node = next_node

    # Preserve any unusual entities that were reachable but did not participate
    # in endpoint traversal.
    if remaining:
        ordered.extend(sorted(remaining, key=handle_sort_key))

    return ordered


def _point_key(p: Vec2) -> str:
    """Round point to tolerance-based key for endpoint matching."""
    x = round(p.x / POINT_TOLERANCE)
    y = round(p.y / POINT_TOLERANCE)
    return f"{x},{y}"


def _points_equal(a: Vec2, b: Vec2) -> bool:
    return (a - b).magnitude < POINT_TOLERANCE


def _entity_is_closed(entity) -> bool:
    dtype = entity.dxftype()
    if dtype == "CIRCLE":
        return True
    if dtype == "LWPOLYLINE":
        return bool(entity.closed)
    if dtype == "POLYLINE":
        return bool(entity.is_closed)
    if bool(getattr(entity, "closed", False)):
        return True

    endpoints = geom.entity_endpoints(entity)
    if not endpoints:
        return False
    start, end = endpoints
    return _points_equal(start, end) and geom.entity_length(entity) > POINT_TOLERANCE
