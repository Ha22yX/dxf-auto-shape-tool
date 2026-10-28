"""Complete a selected open outline with explicit, inspectable DXF line segments.

Exact endpoint connectivity stays the first choice. Nearby open fragments can
be joined at compatible free ends, then the two remaining ends are connected.
Only a simple, planar polygon is committed; failed attempts leave no entities.
"""
from collections import Counter
from dataclasses import dataclass, field
import math
from ezdxf.math import Vec2
from shapely.geometry import LineString, Point
from shapely.ops import unary_union
from backend.config import POINT_TOLERANCE, AUTO_JOIN_GAP, AUTO_JOIN_RATIO, REPAIRED_OUTLINE_LAYER
from backend.dxf_engine import geometry_utils as geom, path_analyzer as paths
from backend.dxf_engine.outline import analyze_outline, _entity_points


@dataclass
class RepairResult:
    chain: list[str]
    connections: list[dict] = field(default_factory=list)
    joined_entity_count: int = 0


@dataclass
class Fragment:
    handles: list[str]
    start: Vec2
    end: Vec2
    start_tangent: Vec2
    end_tangent: Vec2
    linework: object
    elevation: float


def _fragments(doc, graph, endpoints):
    unseen = set(endpoints)
    fragments, membership = [], {}
    while unseen:
        first = min(unseen)
        pending, component = [first], set()
        while pending:
            handle = pending.pop()
            if handle in component:
                continue
            component.add(handle)
            pending.extend(graph.get(handle, []))
        unseen.difference_update(component)
        degree = Counter(node for handle in component for node in endpoints[handle])
        # Do not absorb closed holes, other complete boards, or branching
        # dimension/annotation networks into the selected contour.
        if sum(value == 1 for value in degree.values()) != 2 or any(value > 2 for value in degree.values()):
            continue
        ordered = paths._order_chain(component, graph, endpoints, doc)
        segments = geom._build_segments(doc, ordered)
        if not segments:
            continue
        try:
            lines, levels = [], []
            for handle in ordered:
                points, _ = _entity_points(doc.entitydb[handle])
                lines.append(LineString([(point.x, point.y) for point in points]))
                levels.extend(getattr(point, "z", 0.0) for point in points)
            if max(levels) - min(levels) > POINT_TOLERANCE:
                continue
            linework = unary_union(lines)
        except (ValueError, TypeError, AttributeError):
            continue
        start, tangent, _ = segments[0].evaluate(0)
        end, end_tangent, _ = segments[-1].evaluate(1)
        index = len(fragments)
        for handle in component:
            membership[handle] = index
        fragments.append(Fragment(ordered, start, end, tangent, end_tangent, linework, levels[0]))
    return fragments, membership


def _clear_connector(start, end, linework):
    if (end - start).magnitude <= POINT_TOLERANCE:
        return True
    connector = LineString([tuple(start), tuple(end)])
    # Meeting the two incident edges at their free endpoints is expected;
    # crossing or retracing another edge anywhere else is not a repair.
    interior = connector.difference(Point(*start).buffer(POINT_TOLERANCE * 2))
    interior = interior.difference(Point(*end).buffer(POINT_TOLERANCE * 2))
    return interior.intersection(linework).is_empty


def remove_connections(doc, connections):
    for connection in connections:
        entity = doc.entitydb.get(connection["handle"])
        if entity is not None:
            doc.modelspace().delete_entity(entity)


def complete_outline(doc, seed_handles):
    original_chain = paths.build_chain(doc, seed_handles)
    original = RepairResult(original_chain)
    status = analyze_outline(doc, original_chain).status
    if status != "open":
        return original
    graph, endpoints = paths._build_adjacency(doc)
    fragments, membership = _fragments(doc, graph, endpoints)
    if not seed_handles or any(handle not in membership for handle in seed_handles):
        return original
    selected = {membership[handle] for handle in seed_handles}
    first_id = membership[seed_handles[0]]
    current = fragments[first_id]
    handles = list(current.handles)
    start, end = current.start, current.end
    start_tangent, end_tangent = current.start_tangent, current.end_tangent
    linework = current.linework
    used, connections = {first_id}, []
    original_entities = set(original_chain)
    first_vertices, _ = _entity_points(doc.entitydb[current.handles[0]])
    elevation = getattr(first_vertices[0], "z", 0.0)

    def bridge(a, b):
        if (b - a).magnitude <= POINT_TOLERANCE:
            return []
        if REPAIRED_OUTLINE_LAYER not in doc.layers:
            doc.layers.add(REPAIRED_OUTLINE_LAYER, color=3)
        start_xyz, end_xyz = (a.x, a.y, elevation), (b.x, b.y, elevation)
        entity = doc.modelspace().add_line(start_xyz, end_xyz, dxfattribs={"layer": REPAIRED_OUTLINE_LAYER})
        connections.append({"handle": entity.dxf.handle, "start": start_xyz, "end": end_xyz,
                            "length": (b - a).magnitude})
        return [entity.dxf.handle]

    # A fragmented outline usually has only a handful of breaks. Bound the
    # search so an annotation-heavy drawing cannot turn into an unbounded walk.
    for _ in range(128):
        remaining_required = selected - used
        closing_distance = (end - start).magnitude
        if not remaining_required and closing_distance <= POINT_TOLERANCE:
            break
        min_x, min_y, max_x, max_y = linework.bounds
        max_gap = max(AUTO_JOIN_GAP, math.hypot(max_x - min_x, max_y - min_y) * AUTO_JOIN_RATIO)
        candidates = []
        for index, fragment in enumerate(fragments):
            if index in used or abs(fragment.elevation - current.elevation) > POINT_TOLERANCE:
                continue
            required = index in remaining_required
            for attach_start, origin, outward in ((False, end, end_tangent), (True, start, -start_tangent)):
                for target_start, target, onward in ((True, fragment.start, fragment.start_tangent),
                                                       (False, fragment.end, -fragment.end_tangent)):
                    distance = (target - origin).magnitude
                    if not required and (distance > max_gap or distance >= closing_distance * .65):
                        continue
                    direction = geom.normalize(target - origin)
                    align_a, align_b = outward.dot(direction), onward.dot(direction)
                    if not required and min(align_a, align_b) < -.25:
                        continue
                    work = unary_union([linework, fragment.linework])
                    if not _clear_connector(origin, target, work):
                        continue
                    score = distance * (1 + .2 * (2 - align_a - align_b))
                    candidates.append((score, distance, index, attach_start, target_start))
        if not candidates:
            break
        _, _, index, attach_start, target_start = min(candidates)
        fragment = fragments[index]
        if attach_start:
            oriented = list(reversed(fragment.handles)) if target_start else list(fragment.handles)
            target = fragment.start if target_start else fragment.end
            handles = oriented + bridge(target, start) + handles
            start = fragment.end if target_start else fragment.start
            start_tangent = -fragment.end_tangent if target_start else fragment.start_tangent
        else:
            oriented = list(fragment.handles) if target_start else list(reversed(fragment.handles))
            target = fragment.start if target_start else fragment.end
            handles += bridge(end, target) + oriented
            end = fragment.end if target_start else fragment.start
            end_tangent = fragment.end_tangent if target_start else -fragment.start_tangent
        used.add(index)
        connector_lines = [LineString([connection["start"][:2], connection["end"][:2]]) for connection in connections]
        linework = unary_union([linework, fragment.linework] + connector_lines)

    if selected - used or not _clear_connector(end, start, linework):
        remove_connections(doc, connections)
        return original
    handles += bridge(end, start)
    if not analyze_outline(doc, handles).ready:
        remove_connections(doc, connections)
        return original
    return RepairResult(handles, connections, len(set(handles) - original_entities - {c["handle"] for c in connections}))


def copy_connections(output_doc, chain, connections):
    """Copy real closure edges and remap their handles for a fresh export clone."""
    if not connections:
        return list(chain)
    if REPAIRED_OUTLINE_LAYER not in output_doc.layers:
        output_doc.layers.add(REPAIRED_OUTLINE_LAYER, color=3)
    mapping = {}
    for connection in connections:
        entity = output_doc.modelspace().add_line(connection["start"], connection["end"],
                                                  dxfattribs={"layer": REPAIRED_OUTLINE_LAYER})
        mapping[connection["handle"]] = entity.dxf.handle
    return [mapping.get(handle, handle) for handle in chain]
