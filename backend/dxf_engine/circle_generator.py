"""Generate circles and rays along normal directions from selected edge chain.

Two entry points:
- ``compute_placements`` / ``compute_preview_geometry``: pure geometry for the
  real-time overlay (no DXF mutation).
- ``generate_circles``: writes real entities into a DXF document (download only).
"""
from typing import List, Tuple
import math
import ezdxf
from ezdxf.math import Vec2, offset_vertices_2d

from backend.state import CircleParams
from backend.config import (
    GENERATED_LAYER,
    POINT_TOLERANCE,
    AIR_DUCT_LAYER,
    AIR_DUCT_BASE_PLATE_LAYER,
)
from backend.dxf_engine import geometry_utils as geom


def _keep_normal_continuity(normals):
    """Prevent isolated tangent reversals from sending rays to the other side."""
    continuous = []
    previous = None
    for normal in normals:
        current = normal
        if previous is not None:
            dot = current.x * previous.x + current.y * previous.y
            if dot < 0:
                current = -current
        continuous.append(current)
        if current.magnitude > 1e-9:
            previous = current
    return continuous


def _point_key(point):
    return (
        round(point.x / POINT_TOLERANCE),
        round(point.y / POINT_TOLERANCE),
    )


def _dedupe_placements_by_source(placements):
    seen = set()
    unique = []
    for placement in placements:
        key = _point_key(placement["point"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(placement)
    return unique


def _allocate_counts(lengths, total_count):
    total_length = sum(lengths)
    if total_count <= 0 or total_length <= 1e-9:
        return [0 for _ in lengths]

    raw = [total_count * length / total_length for length in lengths]
    counts = [math.floor(value) for value in raw]
    remaining = total_count - sum(counts)
    order = sorted(range(len(lengths)), key=lambda i: raw[i] - counts[i], reverse=True)
    for idx in order[:remaining]:
        counts[idx] += 1
    return counts


def _distances_in_interval(start, end, count):
    if count <= 0 or end < start:
        return []
    if count == 1:
        return [(start + end) / 2.0]
    step = (end - start) / (count - 1)
    return [start + step * i for i in range(count)]


def _is_effectively_closed(samples):
    if len(samples) < 2:
        return False
    return (samples[0].point - samples[-1].point).magnitude <= POINT_TOLERANCE


def _apex_sample(doc, chain, total, manual_apex_distance=None):
    if manual_apex_distance is not None:
        distance = max(0.0, min(total, manual_apex_distance))
        samples = geom.sample_chain_at_distances(doc, chain, [distance], smooth_tangents=True)
        return samples[0] if samples else None

    dense_count = max(129, min(4001, int(total / 2.0) if total > 0 else 129))
    if dense_count % 2 == 0:
        dense_count += 1
    dense = geom.sample_chain(doc, chain, dense_count, closed=False)
    if not dense:
        return None
    return max(dense, key=lambda sample: sample.point.y)


def _top_gap_distances(doc, chain, ray_count, gap_distance, closed=False,
                       manual_apex_distance=None):
    total = geom.chain_length(doc, chain)
    if total <= 1e-9 or ray_count <= 0:
        return []

    apex = _apex_sample(doc, chain, total, manual_apex_distance=manual_apex_distance)
    if not apex:
        return []

    gap = max(0.0, gap_distance)
    endpoint_samples = geom.sample_chain_at_distances(doc, chain, [0.0, total], smooth_tangents=False)
    cyclic = closed or _is_effectively_closed(endpoint_samples)

    if cyclic:
        usable_length = total - gap * 2
        if usable_length <= 1e-9:
            return []
        if ray_count == 1:
            distances = [apex.distance + gap + usable_length / 2.0]
        else:
            step = usable_length / (ray_count - 1)
            distances = [apex.distance + gap + step * i for i in range(ray_count)]
        return [distance % total for distance in distances]

    intervals = []
    left_end = apex.distance - gap
    right_start = apex.distance + gap
    if left_end > 1e-9:
        intervals.append((0.0, left_end))
    if right_start < total - 1e-9:
        intervals.append((right_start, total))

    lengths = [end - start for start, end in intervals]
    counts = _allocate_counts(lengths, ray_count)

    distances = []
    for (start, end), count in zip(intervals, counts):
        distances.extend(_distances_in_interval(start, end, count))
    return distances


def _manual_apex_marker(doc, chain, manual_apex_distance):
    if manual_apex_distance is None:
        return None
    total = geom.chain_length(doc, chain)
    if total <= 1e-9:
        return None
    return _apex_sample(doc, chain, total, manual_apex_distance=manual_apex_distance)


def _symmetry_axes_overlay(doc, chain, bounds, scale):
    axis = geom.estimate_chain_symmetry_axis(doc, chain)
    if not axis:
        return None
    points = axis.get("points") or []
    if points:
        min_x = min(point.x for point in points)
        max_x = max(point.x for point in points)
        min_y = min(point.y for point in points)
        max_y = max(point.y for point in points)
    else:
        min_x = axis["start"].x
        max_x = axis["end"].x
        min_y = min(axis["start"].y, axis["end"].y)
        max_y = max(axis["start"].y, axis["end"].y)

    width = max_x - min_x
    height = max_y - min_y
    margin = max(height * 0.35, width * 0.25, 1.0)
    center = axis["center"]

    vx1, vy1 = _to_svg(center.x, min_y - margin, bounds, scale)
    vx2, vy2 = _to_svg(center.x, max_y + margin, bounds, scale)
    hx1, hy1 = _to_svg(min_x - margin, center.y, bounds, scale)
    hx2, hy2 = _to_svg(max_x + margin, center.y, bounds, scale)
    return {
        "vertical": {"x1": vx1, "y1": vy1, "x2": vx2, "y2": vy2},
        "horizontal": {"x1": hx1, "y1": hy1, "x2": hx2, "y2": hy2},
    }


def _symmetry_axis_overlay(doc, chain, bounds, scale):
    axes = _symmetry_axes_overlay(doc, chain, bounds, scale)
    return axes["vertical"] if axes else None


def _chain_axis(doc, chain):
    return geom.estimate_chain_symmetry_axis(doc, chain)


def _inside_capsule_axis_gap(placement, axis, params):
    if not axis:
        return False
    above_gap = max(0.0, getattr(params, "capsule_axis_gap_above_distance", 0.0))
    below_gap = max(0.0, getattr(params, "capsule_axis_gap_below_distance", 0.0))
    dy = placement["point"].y - axis["center"].y
    if dy >= 0:
        return above_gap > 0 and dy <= above_gap + POINT_TOLERANCE
    return below_gap > 0 and abs(dy) <= below_gap + POINT_TOLERANCE


def _capsule_gap_guide_overlay(doc, chain, params, bounds, scale):
    axes = _symmetry_axes_overlay(doc, chain, bounds, scale)
    if not axes or not axes.get("horizontal"):
        return None
    above_gap = max(0.0, getattr(params, "capsule_axis_gap_above_distance", 0.0)) * scale
    below_gap = max(0.0, getattr(params, "capsule_axis_gap_below_distance", 0.0)) * scale
    horizontal = axes["horizontal"]
    center_y = (horizontal["y1"] + horizontal["y2"]) / 2.0
    return {
        "upper": {
            "x1": horizontal["x1"],
            "y1": center_y - above_gap,
            "x2": horizontal["x2"],
            "y2": center_y - above_gap,
        },
        "lower": {
            "x1": horizontal["x1"],
            "y1": center_y + below_gap,
            "x2": horizontal["x2"],
            "y2": center_y + below_gap,
        },
    }


def _symmetry_snap_point_overlay(doc, chain, bounds, scale):
    axis = geom.estimate_chain_symmetry_axis(doc, chain)
    sample = geom.nearest_axis_sample_on_chain(doc, chain, axis) if axis else None
    if not sample:
        return None
    cx, cy = _to_svg(sample.point.x, sample.point.y, bounds, scale)
    return {"cx": cx, "cy": cy, "r": 7.0}


def _samples_for_generation(doc, chain, params, closed, manual_apex_distance=None):
    top_gap = max(0.0, getattr(params, "top_gap_distance", 0.0))
    if top_gap > 0:
        distances = _top_gap_distances(
            doc,
            chain,
            params.ray_count,
            top_gap,
            closed=closed,
            manual_apex_distance=manual_apex_distance,
        )
        return geom.sample_chain_at_distances(doc, chain, distances, smooth_tangents=True)

    skip_terminal_endpoint = params.dedupe_closed_rays
    return geom.sample_chain(
        doc,
        chain,
        params.ray_count,
        closed=skip_terminal_endpoint,
        smooth_tangents=True,
    )


def _oriented_normals(doc, chain, samples, params, closed):
    """Compute consistently-oriented normals along the chain (left-of-tangent)."""
    if closed:
        total = geom.chain_length(doc, chain)
        boundary_count = max(129, min(5001, int(total / 2.0) if total > 0 else 129))
        if boundary_count % 2 == 0:
            boundary_count += 1
        boundary_samples = geom.sample_chain(
            doc,
            chain,
            boundary_count,
            closed=True,
            smooth_tangents=False,
        )
        return geom.orient_normals_for_closed_chain(
            samples,
            inward=(params.ray_direction == "inward"),
            boundary_samples=boundary_samples,
        )

    oriented_normals = [s.normal for s in samples]
    is_single_arc = (
        len(chain) == 1
        and doc.entitydb.get(chain[0])
        and doc.entitydb[chain[0]].dxftype() == "ARC"
    )
    if params.ray_direction == "inward":
        if is_single_arc:
            # Standalone ARC raw normals point outward; flip to inward.
            oriented_normals = [-n for n in oriented_normals]
    else:  # outward
        if not is_single_arc:
            oriented_normals = [-n for n in oriented_normals]
    return _keep_normal_continuity(oriented_normals)


def compute_placements(doc, chain: List[str], params: CircleParams, closed: bool = False,
                       manual_apex_distance=None):
    """Pure-math placement of circles/rays along the chain (WCS coordinates).

    Returns a list of dicts: ``{point, ray_start, ray_end, centers}`` where
    ``centers`` is the list of circle centers in WCS. Empty list if nothing
    to generate.
    """
    if not chain or params.ray_count <= 0 or params.circles_per_ray <= 0:
        return []

    top_gap_active = getattr(params, "top_gap_distance", 0.0) > 0
    samples = _samples_for_generation(
        doc, chain, params, closed, manual_apex_distance=manual_apex_distance
    )
    if not samples:
        return []

    normals = _oriented_normals(doc, chain, samples, params, closed)

    placements = []
    for sample, normal in zip(samples, normals):
        ray_start = sample.point + normal * params.ray_offset
        centers = [
            ray_start + normal * (k * params.circle_spacing)
            for k in range(params.circles_per_ray)
        ]
        ray_end = centers[-1] if centers else ray_start
        placements.append({
            "point": sample.point,
            "source_distance": sample.distance,
            "normal": normal,
            "ray_start": ray_start,
            "ray_end": ray_end,
            "centers": centers,
        })
    if params.dedupe_closed_rays and not top_gap_active:
        placements = _dedupe_placements_by_source(placements)
    return placements


def _circle_priority(item, axis_center_x):
    normal = item.get("normal", Vec2(0, 1))
    vertical_bonus = 1.0 - min(1.0, abs(normal.x))
    axis_distance = abs(item["center"].x - axis_center_x)
    # Keep stable straight-bottom rays first, then keep outer circles when the
    # local choice is otherwise ambiguous. The tiny id term keeps decisions
    # deterministic.
    return (
        vertical_bonus * 1000.0
        + axis_distance * 0.01
        - item["circle_index"] * 0.001
        - item["id"] * 0.000001
    )


def _flatten_circle_items(placements, radius):
    items = []
    for placement_index, placement in enumerate(placements):
        for circle_index, center in enumerate(placement["centers"]):
            items.append({
                "id": len(items),
                "center": center,
                "radius": radius,
                "placement_index": placement_index,
                "circle_index": circle_index,
                "source_point": placement["point"],
                "source_distance": placement.get("source_distance", 0.0),
                "normal": placement.get("normal", Vec2(0, 1)),
            })
    return items


def _distance_square(a: Vec2, b: Vec2):
    delta = a - b
    return delta.x * delta.x + delta.y * delta.y


def _grid_key(point: Vec2, cell_size: float):
    return (
        math.floor(point.x / cell_size),
        math.floor(point.y / cell_size),
    )


def _nearby_grid_keys(point: Vec2, cell_size: float):
    ix, iy = _grid_key(point, cell_size)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            yield ix + dx, iy + dy


def _circle_conflict(items, removed_ids, by_id, item_to_group, min_distance):
    active = [item for item in items if item["id"] not in removed_ids]
    if len(active) <= 1:
        return None

    cell_size = max(min_distance, POINT_TOLERANCE * 10.0, 1e-9)
    min_distance_sq = min_distance * min_distance
    cells = {}
    best_conflict = None

    for item in active:
        center = item["center"]
        for key in _nearby_grid_keys(center, cell_size):
            for other_id in cells.get(key, []):
                other = by_id[other_id]
                distance_sq = _distance_square(center, other["center"])
                if distance_sq >= min_distance_sq:
                    continue
                distance = math.sqrt(distance_sq)
                penetration = min_distance - distance
                if penetration <= 0:
                    continue
                g1 = item_to_group[item["id"]]
                g2 = item_to_group[other_id]
                conflict = (penetration, g1, g2)
                if best_conflict is None or conflict[0] > best_conflict[0]:
                    best_conflict = conflict

        key = _grid_key(center, cell_size)
        cells.setdefault(key, []).append(item["id"])

    return best_conflict


def _has_circle_overlap(item, kept_ids, by_id, min_distance):
    if not kept_ids:
        return False
    min_distance_sq = min_distance * min_distance
    return any(
        _distance_square(item["center"], by_id[kept_id]["center"]) < min_distance_sq
        for kept_id in kept_ids
    )


def _segment_distance(a1: Vec2, a2: Vec2, b1: Vec2, b2: Vec2):
    u = a2 - a1
    v = b2 - b1
    w = a1 - b1
    a = u.dot(u)
    b = u.dot(v)
    c = v.dot(v)
    d = u.dot(w)
    e = v.dot(w)
    denominator = a * c - b * b

    if a <= 1e-12 and c <= 1e-12:
        return (a1 - b1).magnitude
    if a <= 1e-12:
        t = max(0.0, min(1.0, e / c if c > 1e-12 else 0.0))
        return (a1 - (b1 + v * t)).magnitude
    if c <= 1e-12:
        s = max(0.0, min(1.0, -d / a if a > 1e-12 else 0.0))
        return ((a1 + u * s) - b1).magnitude

    if denominator > 1e-12:
        s = max(0.0, min(1.0, (b * e - c * d) / denominator))
    else:
        s = 0.0

    t_numerator = b * s + e
    if t_numerator < 0.0:
        t = 0.0
        s = max(0.0, min(1.0, -d / a))
    elif t_numerator > c:
        t = 1.0
        s = max(0.0, min(1.0, (b - d) / a))
    else:
        t = t_numerator / c

    closest_a = a1 + u * s
    closest_b = b1 + v * t
    return (closest_a - closest_b).magnitude


def _capsule_for_placement(placement, params, kept_items=None):
    if params.circle_radius <= 0 or params.circles_per_ray <= 0:
        return None
    normal = placement.get("normal", Vec2(0, 1))
    if normal.magnitude <= 1e-9:
        return None
    direction = normal.normalize()

    max_start = max(0.1, params.ray_offset)
    start_distance = max(0.1, min(getattr(params, "capsule_start_distance", 0.1), max_start))
    near_center = placement["point"] + direction * start_distance

    if kept_items is not None:
        if not kept_items:
            return None
        far_center = max(kept_items, key=lambda item: item["circle_index"])["center"]
    else:
        if placement["centers"]:
            far_center = placement["centers"][-1]
        else:
            far_center = placement["point"] + direction * params.ray_offset

    if (far_center - near_center).magnitude <= POINT_TOLERANCE:
        return None
    if (far_center - near_center).dot(direction) < 0:
        near_center, far_center = far_center, near_center
        direction = -direction
    perp = Vec2(-direction.y, direction.x)
    radius = params.circle_radius
    return {
        "near": near_center,
        "far": far_center,
        "direction": direction,
        "perp": perp,
        "radius": radius,
    }


def _capsule_svg_path(capsule, bounds, scale):
    radius = capsule["radius"] * scale
    near = capsule["near"]
    far = capsule["far"]
    perp = capsule["perp"] * capsule["radius"]

    near_left = near + perp
    far_left = far + perp
    far_right = far - perp
    near_right = near - perp

    n_lx, n_ly = _to_svg(near_left.x, near_left.y, bounds, scale)
    f_lx, f_ly = _to_svg(far_left.x, far_left.y, bounds, scale)
    f_rx, f_ry = _to_svg(far_right.x, far_right.y, bounds, scale)
    n_rx, n_ry = _to_svg(near_right.x, near_right.y, bounds, scale)

    return (
        f"M {n_lx:.1f} {n_ly:.1f} "
        f"L {f_lx:.1f} {f_ly:.1f} "
        f"A {radius:.1f} {radius:.1f} 0 0 1 {f_rx:.1f} {f_ry:.1f} "
        f"L {n_rx:.1f} {n_ry:.1f} "
        f"A {radius:.1f} {radius:.1f} 0 0 1 {n_lx:.1f} {n_ly:.1f} Z"
    )


def _angle_deg(vec: Vec2):
    return math.degrees(math.atan2(vec.y, vec.x))


def _add_capsule_entities(msp, capsule):
    radius = capsule["radius"]
    near = capsule["near"]
    far = capsule["far"]
    perp = capsule["perp"]
    near_left = near + perp * radius
    far_left = far + perp * radius
    far_right = far - perp * radius
    near_right = near - perp * radius

    attrs = {"layer": GENERATED_LAYER}
    handles = []
    handles.append(msp.add_line((near_left.x, near_left.y), (far_left.x, far_left.y), dxfattribs=attrs).dxf.handle)
    handles.append(msp.add_line((near_right.x, near_right.y), (far_right.x, far_right.y), dxfattribs=attrs).dxf.handle)
    handles.append(msp.add_arc(
        center=(far.x, far.y),
        radius=radius,
        start_angle=_angle_deg(-perp),
        end_angle=_angle_deg(perp),
        dxfattribs=attrs,
    ).dxf.handle)
    handles.append(msp.add_arc(
        center=(near.x, near.y),
        radius=radius,
        start_angle=_angle_deg(perp),
        end_angle=_angle_deg(-perp),
        dxfattribs=attrs,
    ).dxf.handle)
    return handles


def _chain_sample_bounds(doc, chain):
    total = geom.chain_length(doc, chain)
    if total <= 1e-9:
        return None
    count = max(65, min(2001, int(total / 3.0)))
    samples = geom.sample_chain(doc, chain, count, closed=False)
    if not samples:
        return None
    xs = [sample.point.x for sample in samples]
    ys = [sample.point.y for sample in samples]
    return {
        "min_x": min(xs),
        "max_x": max(xs),
        "min_y": min(ys),
        "max_y": max(ys),
        "width": max(max(xs) - min(xs), 1.0),
        "height": max(max(ys) - min(ys), 1.0),
    }


def _air_duct_template_offset(doc, chain):
    bounds = _chain_sample_bounds(doc, chain)
    if not bounds:
        return Vec2(0, 0)
    gap = max(bounds["width"] * 0.35, bounds["height"] * 0.08, 100.0)
    return Vec2(bounds["width"] + gap, 0)


def _capsule_template_offset(doc, chain):
    bounds = _chain_sample_bounds(doc, chain)
    if not bounds:
        return Vec2(0, 0)
    gap = max(bounds["width"] * 0.35, bounds["height"] * 0.08, 100.0)
    return Vec2(-(bounds["width"] + gap), 0)


def _shift_capsule(capsule, offset):
    if not offset or offset.magnitude <= POINT_TOLERANCE:
        return capsule
    shifted = dict(capsule)
    shifted["near"] = capsule["near"] + offset
    shifted["far"] = capsule["far"] + offset
    return shifted


def _air_duct_region_key(placement, axis, params):
    if not axis:
        return "all"

    axis_y = axis["center"].y
    dy = placement["point"].y - axis_y
    if dy >= 0:
        gap = max(0.0, getattr(params, "capsule_axis_gap_above_distance", 0.0))
        if gap > 0:
            return "upper_inner" if dy <= gap + POINT_TOLERANCE else "upper_outer"
        return "upper"

    gap = max(0.0, getattr(params, "capsule_axis_gap_below_distance", 0.0))
    if gap > 0:
        return "lower_inner" if abs(dy) <= gap + POINT_TOLERANCE else "lower_outer"
    return "lower"


def _air_duct_record(placement, radius, kept_items=None):
    if radius <= 0:
        return None
    normal = placement.get("normal", Vec2(0, 1))
    if normal.magnitude <= 1e-9:
        return None
    direction = normal.normalize()
    origin = placement["point"]

    if kept_items is not None:
        if not kept_items:
            return None
        centers = [item["center"] for item in kept_items]
    else:
        centers = placement.get("centers") or []
        if not centers:
            return None

    distances = [
        (center - origin).dot(direction)
        for center in centers
    ]
    if not distances:
        return None
    near_center_distance = min(distances)
    far_center_distance = max(distances)
    near_distance = near_center_distance - radius
    far_distance = far_center_distance + radius
    if far_distance <= near_distance + POINT_TOLERANCE:
        return None
    near_center = origin + direction * near_center_distance
    far_center = origin + direction * far_center_distance
    near = origin + direction * near_distance
    far = origin + direction * far_distance
    return {
        "source_distance": placement.get("source_distance", 0.0),
        "source_point": origin,
        "circle_centers": centers,
        "near_center": near_center,
        "far_center": far_center,
        "near": near,
        "far": far,
        "width": (far - near).magnitude,
        "radius": radius,
    }


def _ordered_air_duct_records(records, total_length):
    ordered = sorted(records, key=lambda record: record["source_distance"])
    if len(ordered) <= 2 or total_length <= 1e-9:
        return ordered

    largest_gap = -1.0
    break_index = 0
    for index, record in enumerate(ordered):
        current = record["source_distance"] % total_length
        next_distance = ordered[(index + 1) % len(ordered)]["source_distance"] % total_length
        if index == len(ordered) - 1:
            next_distance += total_length
        gap = next_distance - current
        if gap > largest_gap:
            largest_gap = gap
            break_index = (index + 1) % len(ordered)
    if break_index == 0:
        oriented = ordered
    else:
        oriented = ordered[break_index:] + ordered[:break_index]
    if len(oriented) >= 2 and oriented[0]["source_point"].x > oriented[-1]["source_point"].x:
        oriented = list(reversed(oriented))
    return oriented


def _dedupe_air_duct_points(points):
    cleaned = []
    for point in points:
        if cleaned and (point - cleaned[-1]).magnitude <= POINT_TOLERANCE:
            continue
        cleaned.append(point)
    if len(cleaned) > 1 and (cleaned[0] - cleaned[-1]).magnitude <= POINT_TOLERANCE:
        cleaned.pop()
    return cleaned


def _catmull_rom_closed(points, samples_per_segment=4):
    points = _dedupe_air_duct_points(points)
    if len(points) < 4:
        return points

    smoothed = []
    count = len(points)
    for index in range(count):
        p0 = points[(index - 1) % count]
        p1 = points[index]
        p2 = points[(index + 1) % count]
        p3 = points[(index + 2) % count]
        for step in range(samples_per_segment):
            t = step / samples_per_segment
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * (
                2.0 * p1.x
                + (-p0.x + p2.x) * t
                + (2.0 * p0.x - 5.0 * p1.x + 4.0 * p2.x - p3.x) * t2
                + (-p0.x + 3.0 * p1.x - 3.0 * p2.x + p3.x) * t3
            )
            y = 0.5 * (
                2.0 * p1.y
                + (-p0.y + p2.y) * t
                + (2.0 * p0.y - 5.0 * p1.y + 4.0 * p2.y - p3.y) * t2
                + (-p0.y + 3.0 * p1.y - 3.0 * p2.y + p3.y) * t3
            )
            smoothed.append(Vec2(x, y))
    return _dedupe_air_duct_points(smoothed)


def _remove_hairpin_points(points):
    points = _dedupe_air_duct_points(points)
    if len(points) < 4:
        return points

    changed = True
    while changed and len(points) >= 4:
        changed = False
        cleaned = [points[0]]
        index = 1
        while index < len(points) - 1:
            previous = cleaned[-1]
            current = points[index]
            next_point = points[index + 1]
            incoming = current - previous
            outgoing = next_point - current
            if incoming.magnitude <= POINT_TOLERANCE or outgoing.magnitude <= POINT_TOLERANCE:
                changed = True
                index += 1
                continue
            dot = incoming.normalize().dot(outgoing.normalize())
            # Very sharp backtracks are interpolation artifacts for this use
            # case: the duct edge should follow a smooth envelope, not dip
            # inward and immediately return.
            if dot < -0.82:
                shortcut = next_point - previous
                if shortcut.magnitude <= max(incoming.magnitude + outgoing.magnitude, POINT_TOLERANCE):
                    changed = True
                    index += 1
                    continue
            cleaned.append(current)
            index += 1
        cleaned.append(points[-1])
        points = _dedupe_air_duct_points(cleaned)
    return points


def _extend_open_curve_endpoints(points, distance):
    points = _dedupe_air_duct_points(points)
    if len(points) < 2 or distance <= POINT_TOLERANCE:
        return points

    first_direction = points[0] - points[1]
    last_direction = points[-1] - points[-2]
    extended = list(points)
    if first_direction.magnitude > POINT_TOLERANCE:
        extended.insert(0, points[0] + first_direction.normalize() * distance)
    if last_direction.magnitude > POINT_TOLERANCE:
        extended.append(points[-1] + last_direction.normalize() * distance)
    return _dedupe_air_duct_points(extended)


def _catmull_rom_open(points, samples_per_segment=4):
    points = _dedupe_air_duct_points(points)
    if len(points) < 3:
        return points

    # Use centripetal Catmull-Rom instead of the uniform variant. The uniform
    # formula can create loops around high-curvature "feet"; centripetal
    # parameterization keeps the curve much closer to the source envelope.
    first = points[0] + (points[0] - points[1])
    last = points[-1] + (points[-1] - points[-2])
    padded = [first] + points + [last]

    def next_t(t, a, b):
        return t + max((b - a).magnitude, 1e-9) ** 0.5

    def interpolate(a, b, ta, tb, t):
        if abs(tb - ta) <= 1e-12:
            return a
        return a * ((tb - t) / (tb - ta)) + b * ((t - ta) / (tb - ta))

    smoothed = []
    for index in range(1, len(padded) - 2):
        p0 = padded[index - 1]
        p1 = padded[index]
        p2 = padded[index + 1]
        p3 = padded[index + 2]
        t0 = 0.0
        t1 = next_t(t0, p0, p1)
        t2 = next_t(t1, p1, p2)
        t3 = next_t(t2, p2, p3)
        for step in range(samples_per_segment):
            t = t1 + (t2 - t1) * step / samples_per_segment
            a1 = interpolate(p0, p1, t0, t1, t)
            a2 = interpolate(p1, p2, t1, t2, t)
            a3 = interpolate(p2, p3, t2, t3, t)
            b1 = interpolate(a1, a2, t0, t2, t)
            b2 = interpolate(a2, a3, t1, t3, t)
            smoothed.append(interpolate(b1, b2, t1, t2, t))
    smoothed.append(points[-1])
    return _dedupe_air_duct_points(smoothed)


def _polyline_length(points):
    total = 0.0
    for index in range(1, len(points)):
        total += (points[index] - points[index - 1]).magnitude
    return total


def _horizontal_intersection(a, b, y):
    dy = b.y - a.y
    if abs(dy) <= POINT_TOLERANCE:
        return Vec2(a.x, y)
    t = (y - a.y) / dy
    t = max(0.0, min(1.0, t))
    return Vec2(a.x + (b.x - a.x) * t, y)


def _clip_polyline_to_horizontal(points, y, keep_above):
    segments = _clip_polyline_segments_to_horizontal(points, y, keep_above)
    if not segments:
        return _dedupe_air_duct_points(points)
    return max(segments, key=_polyline_length)


def _clip_polyline_segments_to_horizontal(points, y, keep_above):
    points = _dedupe_air_duct_points(points)
    if len(points) < 2:
        return []

    def inside(point):
        if keep_above:
            return point.y >= y - POINT_TOLERANCE
        return point.y <= y + POINT_TOLERANCE

    segments = []
    current = []
    for index in range(len(points) - 1):
        a = points[index]
        b = points[index + 1]
        a_inside = inside(a)
        b_inside = inside(b)

        if a_inside and not current:
            current.append(a)

        if a_inside and b_inside:
            current.append(b)
        elif a_inside and not b_inside:
            current.append(_horizontal_intersection(a, b, y))
            segments.append(_dedupe_air_duct_points(current))
            current = []
        elif not a_inside and b_inside:
            current = [_horizontal_intersection(a, b, y), b]

    if current:
        segments.append(_dedupe_air_duct_points(current))

    segments = [segment for segment in segments if len(segment) >= 2]
    return segments


def _cross(a, b):
    return a.x * b.y - a.y * b.x


def _point_on_segment(point, a, b, tolerance=POINT_TOLERANCE):
    ab = b - a
    ap = point - a
    if abs(_cross(ab, ap)) > tolerance:
        return False
    dot = ap.dot(ab)
    if dot < -tolerance:
        return False
    if dot > ab.dot(ab) + tolerance:
        return False
    return True


def _segment_intersection_params(a, b, c, d):
    r = b - a
    s = d - c
    denominator = _cross(r, s)
    if abs(denominator) <= POINT_TOLERANCE:
        if abs(_cross(c - a, r)) <= POINT_TOLERANCE:
            params = []
            rr = r.dot(r)
            if rr <= POINT_TOLERANCE:
                return []
            for point in (c, d):
                if _point_on_segment(point, a, b):
                    params.append((point - a).dot(r) / rr)
            return params
        return []
    qp = c - a
    t = _cross(qp, s) / denominator
    u = _cross(qp, r) / denominator
    if -POINT_TOLERANCE <= t <= 1.0 + POINT_TOLERANCE and -POINT_TOLERANCE <= u <= 1.0 + POINT_TOLERANCE:
        return [max(0.0, min(1.0, t))]
    return []


def _split_segment_points(a, b, split_params):
    params = [0.0, 1.0]
    params.extend(max(0.0, min(1.0, value)) for value in split_params)
    params = sorted(params)
    deduped = []
    for value in params:
        if deduped and abs(value - deduped[-1]) <= 1e-9:
            continue
        deduped.append(value)

    pieces = []
    delta = b - a
    for index in range(len(deduped) - 1):
        start_t = deduped[index]
        end_t = deduped[index + 1]
        if end_t - start_t <= 1e-9:
            continue
        start = a + delta * start_t
        end = a + delta * end_t
        if (end - start).magnitude > POINT_TOLERANCE:
            pieces.append((start, end))
    return pieces


def _point_in_polygon(point, polygon):
    if len(polygon) < 3:
        return False
    for index, a in enumerate(polygon):
        b = polygon[(index + 1) % len(polygon)]
        if _point_on_segment(point, a, b):
            return False

    inside = False
    j = len(polygon) - 1
    for i, current in enumerate(polygon):
        previous = polygon[j]
        if (current.y > point.y) != (previous.y > point.y):
            x_intersection = (
                (previous.x - current.x)
                * (point.y - current.y)
                / (previous.y - current.y)
                + current.x
            )
            if point.x < x_intersection:
                inside = not inside
        j = i
    return inside


def _point_inside_or_on_polygon(point, polygon, tolerance=POINT_TOLERANCE):
    if _point_in_polygon(point, polygon):
        return True
    return any(
        _point_on_segment(
            point,
            polygon[index],
            polygon[(index + 1) % len(polygon)],
            tolerance=tolerance,
        )
        for index in range(len(polygon))
    )


def _point_in_rect(point, min_x, min_y, max_x, max_y):
    return (
        min_x + POINT_TOLERANCE < point.x < max_x - POINT_TOLERANCE
        and min_y + POINT_TOLERANCE < point.y < max_y - POINT_TOLERANCE
    )


def _rect_edges(rect):
    return [
        (rect[0], rect[1]),
        (rect[1], rect[2]),
        (rect[2], rect[3]),
        (rect[3], rect[0]),
    ]


def _polygon_edges(points):
    return [
        (points[index], points[(index + 1) % len(points)])
        for index in range(len(points))
    ]


def _polygon_signed_area(points):
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        area += point.x * next_point.y - next_point.x * point.y
    return area * 0.5


def _orient_air_duct_loops(loops):
    cleaned = [
        _dedupe_air_duct_points(loop)
        for loop in loops
        if len(_dedupe_air_duct_points(loop)) >= 3
    ]
    if not cleaned:
        return []

    result = []
    for index, loop in enumerate(cleaned):
        depth = 0
        test_point = loop[0]
        area = abs(_polygon_signed_area(loop))
        for other_index, other in enumerate(cleaned):
            if other_index == index:
                continue
            other_area = abs(_polygon_signed_area(other))
            if other_area <= area + POINT_TOLERANCE:
                continue
            if _point_in_polygon(test_point, other):
                depth += 1

        signed_area = _polygon_signed_area(loop)
        should_be_positive = depth % 2 == 0
        if should_be_positive and signed_area < 0:
            loop = list(reversed(loop))
        elif not should_be_positive and signed_area > 0:
            loop = list(reversed(loop))
        result.append(loop)
    return result


def _boundary_loops_from_segments(segments):
    key_scale = max(POINT_TOLERANCE * 20.0, 1e-6)

    def key(point):
        return (round(point.x / key_scale), round(point.y / key_scale))

    point_by_key = {}
    segment_keys = set()
    for start, end in segments:
        if (end - start).magnitude <= POINT_TOLERANCE:
            continue
        start_key = key(start)
        end_key = key(end)
        if start_key == end_key:
            continue
        segment_key = tuple(sorted((start_key, end_key)))
        if segment_key in segment_keys:
            continue
        segment_keys.add(segment_key)
        point_by_key.setdefault(start_key, start)
        point_by_key.setdefault(end_key, end)

    if not segment_keys:
        return []

    outgoing = {}
    for a_key, b_key in segment_keys:
        outgoing.setdefault(a_key, []).append(b_key)
        outgoing.setdefault(b_key, []).append(a_key)

    for vertex_key, neighbors in outgoing.items():
        origin = point_by_key[vertex_key]
        neighbors.sort(
            key=lambda neighbor_key: math.atan2(
                point_by_key[neighbor_key].y - origin.y,
                point_by_key[neighbor_key].x - origin.x,
            )
        )

    visited = set()
    loops = []
    max_steps = max(16, len(segment_keys) * 4)

    for start_key in outgoing:
        for next_key in outgoing[start_key]:
            edge = (start_key, next_key)
            if edge in visited:
                continue

            loop_keys = []
            current = start_key
            following = next_key
            for _ in range(max_steps):
                visited.add((current, following))
                loop_keys.append(current)
                neighbors = outgoing.get(following, [])
                if not neighbors:
                    break
                try:
                    reverse_index = neighbors.index(current)
                except ValueError:
                    break
                # Keep the traced face on a consistent side by taking the
                # previous directed edge in angular order. This avoids the
                # arbitrary branch choices that used to drop inlet/duct edges.
                next_following = neighbors[(reverse_index - 1) % len(neighbors)]
                current, following = following, next_following
                if current == start_key and following == next_key:
                    points = _dedupe_air_duct_points(
                        [point_by_key[item] for item in loop_keys]
                    )
                    if len(points) >= 3 and abs(_polygon_signed_area(points)) > POINT_TOLERANCE:
                        loops.append(points)
                    break
            else:
                break

    unique_loops = {}
    for loop in loops:
        loop_keys = [key(point) for point in loop]
        canonical = min(
            tuple(loop_keys[index:] + loop_keys[:index])
            for index in range(len(loop_keys))
        )
        reverse = list(reversed(loop_keys))
        reverse_canonical = min(
            tuple(reverse[index:] + reverse[:index])
            for index in range(len(reverse))
        )
        loop_key = min(canonical, reverse_canonical)
        existing = unique_loops.get(loop_key)
        if existing is None or abs(_polygon_signed_area(loop)) > abs(_polygon_signed_area(existing)):
            unique_loops[loop_key] = loop

    result = list(unique_loops.values())
    result.sort(key=lambda loop: abs(_polygon_signed_area(loop)), reverse=True)
    if not result:
        return []

    return result


def _loops_cover_points(loops, points):
    if not points:
        return True
    for point in points:
        if not any(_point_inside_or_on_polygon(point, loop) for loop in loops):
            return False
    return True


def _largest_covering_union_loop(loops, coverage_points):
    loops = [
        _dedupe_air_duct_points(loop)
        for loop in loops
        if len(_dedupe_air_duct_points(loop)) >= 3
    ]
    if not loops:
        return []
    loops.sort(key=lambda loop: abs(_polygon_signed_area(loop)), reverse=True)
    primary = [loops[0]]
    if _loops_cover_points(primary, coverage_points):
        return primary
    return loops


def _union_polygon_with_rect_boundary(polygon, rect):
    polygon = _dedupe_air_duct_points(polygon)
    rect = _dedupe_air_duct_points(rect)
    if len(polygon) < 3 or len(rect) < 3:
        return [polygon] if len(polygon) >= 3 else []

    min_x = min(point.x for point in rect)
    max_x = max(point.x for point in rect)
    min_y = min(point.y for point in rect)
    max_y = max(point.y for point in rect)
    rect_edge_list = _rect_edges(rect)
    polygon_edge_list = _polygon_edges(polygon)
    segments = []

    for start, end in polygon_edge_list:
        split_params = []
        for rect_start, rect_end in rect_edge_list:
            split_params.extend(_segment_intersection_params(start, end, rect_start, rect_end))
        for piece_start, piece_end in _split_segment_points(start, end, split_params):
            midpoint = (piece_start + piece_end) * 0.5
            if not _point_in_rect(midpoint, min_x, min_y, max_x, max_y):
                segments.append((piece_start, piece_end))

    for start, end in rect_edge_list:
        split_params = []
        for poly_start, poly_end in polygon_edge_list:
            split_params.extend(_segment_intersection_params(start, end, poly_start, poly_end))
        for piece_start, piece_end in _split_segment_points(start, end, split_params):
            midpoint = (piece_start + piece_end) * 0.5
            if not _point_in_polygon(midpoint, polygon):
                segments.append((piece_start, piece_end))

    loops = _boundary_loops_from_segments(segments)
    if loops:
        return loops
    return [polygon]


def _union_polygons_boundary(polygons):
    polygons = [
        _dedupe_air_duct_points(polygon)
        for polygon in polygons
        if len(_dedupe_air_duct_points(polygon)) >= 3
    ]
    if not polygons:
        return []
    if len(polygons) == 1:
        return polygons

    polygon_edges = [_polygon_edges(polygon) for polygon in polygons]
    segments = []
    for polygon_index, edges in enumerate(polygon_edges):
        for start, end in edges:
            split_params = []
            for other_index, other_edges in enumerate(polygon_edges):
                if other_index == polygon_index:
                    continue
                for other_start, other_end in other_edges:
                    split_params.extend(_segment_intersection_params(start, end, other_start, other_end))
            for piece_start, piece_end in _split_segment_points(start, end, split_params):
                midpoint = (piece_start + piece_end) * 0.5
                if any(
                    _point_in_polygon(midpoint, other_polygon)
                    for other_index, other_polygon in enumerate(polygons)
                    if other_index != polygon_index
                ):
                    continue
                segments.append((piece_start, piece_end))

    loops = _boundary_loops_from_segments(segments)
    if loops:
        return loops
    return polygons


def _bbox_outline_with_inlet(polygon, rect):
    points = _dedupe_air_duct_points((polygon or []) + (rect or []))
    if len(points) < 3 or len(rect) < 4:
        return polygon
    min_x = min(point.x for point in points)
    max_x = max(point.x for point in points)
    min_y = min(point.y for point in points)
    max_y = max(point.y for point in points)
    rect_min_y = min(point.y for point in rect)
    rect_max_y = max(point.y for point in rect)
    if abs(rect_max_y - max_y) < abs(rect_min_y - min_y):
        y = rect_min_y
        return [
            Vec2(min_x, min_y),
            Vec2(max_x, min_y),
            Vec2(max_x, y),
            Vec2(max_x, max_y),
            Vec2(min_x, max_y),
            Vec2(min_x, y),
        ]
    y = rect_max_y
    return [
        Vec2(min_x, min_y),
        Vec2(max_x, min_y),
        Vec2(max_x, y),
        Vec2(max_x, max_y),
        Vec2(min_x, max_y),
        Vec2(min_x, y),
    ]


def _bridge_air_duct_components_with_inlet(component_polygons, inlet_points):
    components = [
        _dedupe_air_duct_points(polygon)
        for polygon in component_polygons
        if len(_dedupe_air_duct_points(polygon)) >= 3
    ]
    inlet = _dedupe_air_duct_points(inlet_points)
    if len(components) < 2 or len(inlet) < 4:
        return []

    components = sorted(
        components,
        key=lambda polygon: sum(point.x for point in polygon) / len(polygon),
    )
    left = components[0]
    right = components[-1]
    all_points = [point for polygon in components for point in polygon]
    all_points.extend(inlet)
    min_y = min(point.y for point in all_points)
    max_y = max(point.y for point in all_points)
    slot_min_y = max(min_y, min(point.y for point in inlet))
    slot_max_y = min(max_y, max(point.y for point in inlet))
    if slot_max_y - slot_min_y <= POINT_TOLERANCE:
        return []

    left_min_x = min(point.x for point in left)
    left_max_x = max(point.x for point in left)
    right_min_x = min(point.x for point in right)
    right_max_x = max(point.x for point in right)
    if right_min_x <= left_max_x + POINT_TOLERANCE:
        return []

    loop = [
        Vec2(left_min_x, min_y),
        Vec2(left_max_x, min_y),
        Vec2(left_max_x, slot_min_y),
        Vec2(right_min_x, slot_min_y),
        Vec2(right_min_x, min_y),
        Vec2(right_max_x, min_y),
        Vec2(right_max_x, max_y),
        Vec2(right_min_x, max_y),
        Vec2(right_min_x, slot_max_y),
        Vec2(left_max_x, slot_max_y),
        Vec2(left_max_x, max_y),
        Vec2(left_min_x, max_y),
    ]
    return [_dedupe_air_duct_points(loop)]


def _horizontal_extents_at_y(polygons, y):
    intersections = []
    for polygon in polygons:
        for start, end in _polygon_edges(polygon):
            if abs(start.y - end.y) <= POINT_TOLERANCE:
                if abs(y - start.y) <= POINT_TOLERANCE:
                    intersections.extend([start.x, end.x])
                continue
            low = min(start.y, end.y) - POINT_TOLERANCE
            high = max(start.y, end.y) + POINT_TOLERANCE
            if low <= y <= high:
                intersections.append(_horizontal_intersection(start, end, y).x)

    if len(intersections) < 2:
        return None
    intersections = sorted(intersections)
    return intersections[0], intersections[-1]


def _air_duct_inlet_points(records, params, region, polygons=None):
    if len(records) < 2:
        return []
    if not (region.startswith("upper") or region.startswith("lower")):
        return []

    points = []
    for record in records:
        points.append(record["near"])
        points.append(record["far"])
    min_x = min(point.x for point in points)
    max_x = max(point.x for point in points)
    min_y = min(point.y for point in points)
    max_y = max(point.y for point in points)
    if max_x - min_x <= POINT_TOLERANCE:
        return []

    width = max(
        params.circle_radius * 2.0,
        sum(record["width"] for record in records) / len(records),
    )
    distance = max(0.0, getattr(params, "air_duct_inlet_distance", 0.0))

    if region.startswith("upper"):
        near_y = min(min_y + distance, max_y)
        far_y = min(near_y + width, max_y)
    else:
        near_y = max(max_y - distance, min_y)
        far_y = max(near_y - width, min_y)

    if polygons:
        near_extents = _horizontal_extents_at_y(polygons, near_y)
        far_extents = _horizontal_extents_at_y(polygons, far_y)
        if near_extents and far_extents:
            near_min_x, near_max_x = near_extents
            far_min_x, far_max_x = far_extents
            if (
                near_max_x - near_min_x > POINT_TOLERANCE
                and far_max_x - far_min_x > POINT_TOLERANCE
            ):
                # Clamp the inlet to the duct boundary. A tiny outward nudge is
                # applied later only for topology; adding a visible side margin
                # here creates the small tabs seen beside the outer duct.
                return [
                    Vec2(near_min_x, near_y),
                    Vec2(near_max_x, near_y),
                    Vec2(far_max_x, far_y),
                    Vec2(far_min_x, far_y),
                ]

    side_margin = max(0.0, params.circle_radius + _air_duct_envelope_margin(params.circle_radius))
    return [
        Vec2(min_x - side_margin, near_y),
        Vec2(max_x + side_margin, near_y),
        Vec2(max_x + side_margin, far_y),
        Vec2(min_x - side_margin, far_y),
    ]


def _inlet_union_join_margin(params):
    radius = max(0.0, getattr(params, "circle_radius", 0.0))
    if radius <= 0:
        return POINT_TOLERANCE * 20.0
    return max(POINT_TOLERANCE * 20.0, min(radius * 0.02, 0.05))


def _nudge_inlet_points_for_union(points, join_margin=0.0):
    """Move inlet side edges microscopically through the duct before union.

    The inlet is intentionally clamped to the duct boundary so it does not
    protrude visually. That can make boolean union see a pure tangency instead
    of an overlap. A sub-millimeter outward nudge crosses the side duct edges
    so the boundary merger sees one connected channel; the final outline is
    still clamped by the merged outer boundary in normal cases.
    """
    points = _dedupe_air_duct_points(points)
    if len(points) < 4:
        return points

    min_x = min(point.x for point in points)
    max_x = max(point.x for point in points)
    width = max_x - min_x
    if width <= POINT_TOLERANCE:
        return points

    amount = max(float(join_margin or 0.0), POINT_TOLERANCE * 20.0, width * 1e-6)
    amount = min(amount, max(POINT_TOLERANCE * 20.0, width * 0.0005), 0.05)
    center_x = sum(point.x for point in points) / len(points)
    nudged = []
    for point in points:
        if point.x < center_x:
            nudged.append(Vec2(point.x - amount, point.y))
        elif point.x > center_x:
            nudged.append(Vec2(point.x + amount, point.y))
        else:
            nudged.append(point)
    return _dedupe_air_duct_points(nudged)


def _split_air_duct_components(records, total_length, split_disconnected):
    if not records:
        return []
    if not split_disconnected:
        return [_ordered_air_duct_records(records, total_length)]

    min_x = min(record["source_point"].x for record in records)
    max_x = max(record["source_point"].x for record in records)
    if max_x - min_x > POINT_TOLERANCE * 100.0:
        center_x = (min_x + max_x) * 0.5
        left = [
            record
            for record in records
            if record["source_point"].x <= center_x
        ]
        right = [
            record
            for record in records
            if record["source_point"].x > center_x
        ]
        side_components = [
            _ordered_air_duct_records(side_records, total_length)
            for side_records in (left, right)
            if len(side_records) >= 2
        ]
        if len(side_components) >= 2:
            return side_components

    ordered = sorted(records, key=lambda record: record["source_distance"])
    if len(ordered) <= 2:
        return [ordered]

    gaps = [
        ordered[index + 1]["source_distance"] - ordered[index]["source_distance"]
        for index in range(len(ordered) - 1)
    ]
    positive_gaps = sorted(gap for gap in gaps if gap > POINT_TOLERANCE)
    if not positive_gaps:
        return [ordered]
    median_gap = positive_gaps[len(positive_gaps) // 2]
    threshold = max(median_gap * 3.0, total_length * 0.015, POINT_TOLERANCE * 100.0)

    components = []
    current = [ordered[0]]
    for index, gap in enumerate(gaps):
        if gap > threshold:
            if len(current) >= 2:
                components.append(current)
            current = [ordered[index + 1]]
        else:
            current.append(ordered[index + 1])
    if len(current) >= 2:
        components.append(current)
    return components or [ordered]


def _symmetric_x_extents(left_x, right_x, center_x):
    half_width = max(abs(center_x - left_x), abs(right_x - center_x))
    return center_x - half_width, center_x + half_width


def _record_vec(record, key, fallback_key=None):
    value = record.get(key)
    if value is None and fallback_key:
        value = record.get(fallback_key)
    return value


def _quadratic_vec(start, control, end, t):
    omt = 1.0 - t
    return start * (omt * omt) + control * (2.0 * omt * t) + end * (t * t)


def _interpolate_air_duct_record(start, end, t, control_shift, source_distance):
    bridge = {
        "source_distance": source_distance,
        "width": start.get("width", 0.0) * (1.0 - t) + end.get("width", 0.0) * t,
        "radius": start.get("radius", 0.0) * (1.0 - t) + end.get("radius", 0.0) * t,
    }
    for key, fallback_key in (
        ("source_point", None),
        ("near_center", "near"),
        ("far_center", "far"),
        ("near", "near_center"),
        ("far", "far_center"),
    ):
        start_point = _record_vec(start, key, fallback_key)
        end_point = _record_vec(end, key, fallback_key)
        if start_point is None or end_point is None:
            continue
        control = (start_point + end_point) * 0.5 + control_shift
        bridge[key] = _quadratic_vec(start_point, control, end_point, t)

    centers = []
    if bridge.get("near_center") is not None:
        centers.append(bridge["near_center"])
    if bridge.get("far_center") is not None:
        centers.append(bridge["far_center"])
    if centers:
        bridge["circle_centers"] = centers
    return bridge


def _bridge_air_duct_end_gap_records(records, region, params):
    if len(records) < 4:
        return records
    if region.endswith("_inner"):
        return records
    is_simple = region == "simple"
    if not is_simple and not (region.startswith("upper") or region.startswith("lower")):
        return records

    points = [record["source_point"] for record in records]
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    if span_x <= POINT_TOLERANCE or span_y <= POINT_TOLERANCE:
        return records

    first = records[0]["source_point"]
    last = records[-1]["source_point"]
    center_x = (min(xs) + max(xs)) * 0.5
    average_width = sum(record.get("width", 0.0) for record in records) / len(records)
    radius = max(0.0, getattr(params, "circle_radius", 0.0))
    endpoint_band = max(span_y * 0.22, average_width * 2.0, radius * 8.0, POINT_TOLERANCE * 100.0)
    endpoint_gap = (first - last).magnitude
    straddles_axis = (first.x - center_x) * (last.x - center_x) <= POINT_TOLERANCE
    has_visible_gap = endpoint_gap > max(average_width * 0.8, radius * 2.0, POINT_TOLERANCE * 100.0)
    if not straddles_axis or not has_visible_gap:
        return records

    if region.startswith("upper"):
        if min(first.y, last.y) < max(ys) - endpoint_band:
            return records
        direction = 1.0
    elif region.startswith("lower"):
        if max(first.y, last.y) > min(ys) + endpoint_band:
            return records
        direction = -1.0
    else:
        endpoints_at_top = min(first.y, last.y) >= max(ys) - endpoint_band
        endpoints_at_bottom = max(first.y, last.y) <= min(ys) + endpoint_band
        if endpoints_at_top:
            direction = 1.0
        elif endpoints_at_bottom:
            direction = -1.0
        else:
            return records

    gap_width = abs(first.x - last.x)
    bridge_height = max(gap_width * 0.35, average_width * 1.25, radius * 6.0, 1.0)
    control_shift = Vec2(center_x - (first.x + last.x) * 0.5, direction * bridge_height)
    step = max(average_width * 0.6, radius * 4.0, 2.0)
    bridge_count = max(4, min(14, int(math.ceil(gap_width / step))))
    if bridge_count % 2 == 0:
        bridge_count += 1
    start_distance = records[-1].get("source_distance", 0.0)
    end_distance = records[0].get("source_distance", start_distance + endpoint_gap)
    if end_distance <= start_distance:
        end_distance = start_distance + endpoint_gap

    bridged = list(records)
    for index in range(1, bridge_count + 1):
        t = index / (bridge_count + 1)
        bridged.append(_interpolate_air_duct_record(
            records[-1],
            records[0],
            t,
            control_shift,
            start_distance + (end_distance - start_distance) * t,
        ))
    return bridged


def _bridge_air_duct_components_end_gaps(components, region, params):
    return [
        _bridge_air_duct_end_gap_records(component, region, params)
        for component in components
    ]


def _air_duct_curve(points, endpoint_margin=0.0):
    points = _remove_hairpin_points(points)
    points = _extend_open_curve_endpoints(points, endpoint_margin)
    # The ray records are already dense on real surfboard outlines. Keeping the
    # envelope as an ordered polyline is both faster and more predictable than
    # spline interpolation, which can overshoot at rounded feet or tight apexes.
    return _dedupe_air_duct_points(points)


def _air_duct_envelope_margin(radius):
    if radius <= 0:
        return 0.0
    return max(radius * 0.12, 0.25, POINT_TOLERANCE * 20.0)


def _smooth_air_duct_offset_points(records, center_key, points, normals):
    points = _dedupe_air_duct_points(points)
    if len(points) < 5 or len(points) != len(records) or len(points) != len(normals):
        return points

    required_offsets = [
        max(0.0, record.get("radius", 0.0))
        + _air_duct_envelope_margin(max(0.0, record.get("radius", 0.0)))
        for record in records
    ]
    smoothed = list(points)
    for _ in range(2):
        next_points = [smoothed[0]]
        for index in range(1, len(smoothed) - 1):
            previous = smoothed[index - 1]
            current = smoothed[index]
            following = smoothed[index + 1]
            incoming = current - previous
            outgoing = following - current
            if incoming.magnitude <= POINT_TOLERANCE or outgoing.magnitude <= POINT_TOLERANCE:
                next_points.append(current)
                continue

            dot = max(-1.0, min(1.0, incoming.normalize().dot(outgoing.normalize())))
            turn = 1.0 - dot
            if turn <= 0.04:
                next_points.append(current)
                continue

            weight = min(0.28, max(0.08, turn * 0.16))
            candidate = current * (1.0 - weight * 2.0) + (previous + following) * weight

            normal = normals[index]
            center = records[index].get(center_key)
            if center is not None and normal.magnitude > POINT_TOLERANCE:
                normal = normal.normalize()
                required = required_offsets[index]
                offset = (candidate - center).dot(normal)
                if offset < required:
                    candidate = candidate + normal * (required - offset)

            next_points.append(candidate)
        next_points.append(smoothed[-1])
        smoothed = _dedupe_air_duct_points(next_points)

    return smoothed


def _circle_envelope_points(center, radius, samples=24):
    if radius <= 0:
        return [center]
    return [
        center + Vec2(
            math.cos(2.0 * math.pi * index / samples) * radius,
            math.sin(2.0 * math.pi * index / samples) * radius,
        )
        for index in range(samples)
    ]


def _distance_to_segment_square(point, start, end):
    segment = end - start
    length_sq = segment.dot(segment)
    if length_sq <= POINT_TOLERANCE:
        return _distance_square(point, start), 0.0
    t = max(0.0, min(1.0, (point - start).dot(segment) / length_sq))
    closest = start + segment * t
    return _distance_square(point, closest), t


def _nearest_loop_edge(point, loops):
    best = None
    for loop_index, loop in enumerate(loops):
        if len(loop) < 2:
            continue
        for edge_index in range(len(loop)):
            start = loop[edge_index]
            end = loop[(edge_index + 1) % len(loop)]
            distance_sq, t = _distance_to_segment_square(point, start, end)
            key = (distance_sq, loop_index, edge_index)
            if best is None or key < best[0]:
                best = (key, loop_index, edge_index, t)
    return best


def _expand_air_duct_loops_to_cover_records(loops, records, radius):
    expanded = [
        _dedupe_air_duct_points(loop)
        for loop in loops
        if len(_dedupe_air_duct_points(loop)) >= 3
    ]
    # Dense surfboard rows already define the intended duct envelope. The
    # point-by-point cover repair is useful for small synthetic tests, but on
    # real boards it is expensive and can add noisy vertices around tangent
    # regions. Keep large regions fast and stable.
    if len(records) > 32 or not expanded or radius <= 0:
        return expanded

    envelope_radius = radius + _air_duct_envelope_margin(radius)
    for record in records:
        centers = record.get("circle_centers") or [
            record.get("near_center"),
            record.get("far_center"),
        ]
        for center in centers:
            if center is None:
                continue
            for point in _circle_envelope_points(center, envelope_radius, samples=8):
                if _loops_cover_points(expanded, [point]):
                    continue
                nearest = _nearest_loop_edge(point, expanded)
                if not nearest:
                    continue
                _, loop_index, edge_index, _ = nearest
                loop = list(expanded[loop_index])
                loop.insert(edge_index + 1, point)
                expanded[loop_index] = _dedupe_air_duct_points(loop)
    return [
        loop
        for loop in expanded
        if len(loop) >= 3
    ]


def _curve_tangent(points, index):
    if len(points) < 2:
        return Vec2(1, 0)
    if index <= 0:
        tangent = points[1] - points[0]
    elif index >= len(points) - 1:
        tangent = points[-1] - points[-2]
    else:
        tangent = points[index + 1] - points[index - 1]
    if tangent.magnitude <= POINT_TOLERANCE:
        return Vec2(1, 0)
    return tangent.normalize()


def _offset_air_duct_center_curve(records, center_key, opposite_key, endpoint_margin=0.0):
    if not records or any(center_key not in record or opposite_key not in record for record in records):
        return []

    centers = [record[center_key] for record in records]
    offset_points = []
    normals = []
    for index, record in enumerate(records):
        center = record[center_key]
        opposite = record[opposite_key]
        tangent = _curve_tangent(centers, index)
        normal = Vec2(-tangent.y, tangent.x)
        away = center - opposite
        if normal.dot(away) < 0:
            normal = -normal
        radius = max(0.0, record.get("radius", 0.0))
        normals.append(normal)
        offset_points.append(center + normal * (radius + _air_duct_envelope_margin(radius)))

    offset_points = _smooth_air_duct_offset_points(
        records,
        center_key,
        offset_points,
        normals,
    )
    return _air_duct_curve(offset_points, endpoint_margin=endpoint_margin)


def _air_duct_component_curves(records, endpoint_margin=0.0):
    if len(records) < 2:
        return [], []
    outer_curve = _offset_air_duct_center_curve(
        records,
        "near_center",
        "far_center",
        endpoint_margin=endpoint_margin,
    )
    inner_curve = _offset_air_duct_center_curve(
        records,
        "far_center",
        "near_center",
        endpoint_margin=endpoint_margin,
    )
    return outer_curve, inner_curve


def _air_duct_component_polygon(records, endpoint_margin=0.0):
    if len(records) < 2:
        return []
    outer_curve, inner_curve = _air_duct_component_curves(
        records,
        endpoint_margin=endpoint_margin,
    )
    if not outer_curve or not inner_curve:
        outer_curve = _air_duct_curve(
            [record["near"] for record in records],
            endpoint_margin=endpoint_margin,
        )
        inner_curve = _air_duct_curve(
            [record["far"] for record in reversed(records)],
            endpoint_margin=endpoint_margin,
        )
    else:
        inner_curve = list(reversed(inner_curve))
    return _dedupe_air_duct_points(outer_curve + inner_curve)


def _single_component_air_duct_slot_loops(records, params, region, endpoint_margin=0.0):
    polygon = _air_duct_component_polygon(
        records,
        endpoint_margin=endpoint_margin,
    )
    if len(polygon) < 3:
        return []

    inlet = _air_duct_inlet_points(records, params, region, [polygon])
    if len(inlet) < 4:
        loops = [polygon]
    else:
        union_inlet = _nudge_inlet_points_for_union(
            inlet,
            _inlet_union_join_margin(params),
        )
        loops = _union_polygons_boundary([polygon, union_inlet]) or [polygon]

    return [
        loop
        for loop in loops
        if len(loop) >= 3 and abs(_polygon_signed_area(loop)) > POINT_TOLERANCE
    ]


def _air_duct_records_form_end_cap(records, region):
    if len(records) < 8:
        return False
    if region.endswith("_inner"):
        return False
    if not (region.startswith("upper") or region.startswith("lower")):
        return False

    points = [record["source_point"] for record in records]
    ys = [point.y for point in points]
    xs = [point.x for point in points]
    span_y = max(ys) - min(ys)
    span_x = max(xs) - min(xs)
    average_width = sum(record.get("width", 0.0) for record in records) / len(records)
    if span_y <= max(average_width * 1.5, span_x * 0.12, POINT_TOLERANCE * 100.0):
        return False

    edge_count = max(2, min(len(records) // 8, 12))
    edge_ys = ys[:edge_count] + ys[-edge_count:]
    edge_average_y = sum(edge_ys) / len(edge_ys)
    guard = max(edge_count, len(records) // 10)

    if region.startswith("upper"):
        apex_index = max(range(len(ys)), key=lambda index: ys[index])
        if apex_index < guard or apex_index >= len(records) - guard:
            return False
        return max(ys) - edge_average_y >= max(average_width, span_y * 0.35)

    apex_index = min(range(len(ys)), key=lambda index: ys[index])
    if apex_index < guard or apex_index >= len(records) - guard:
        return False
    return edge_average_y - min(ys) >= max(average_width, span_y * 0.35)


def _air_duct_region_contours(records, total_length, params, region):
    if len(records) < 2:
        return []
    split_disconnected = region.endswith("_inner")
    components = _split_air_duct_components(records, total_length, split_disconnected)
    components = _bridge_air_duct_components_end_gaps(components, region, params)
    ordered = [record for component in components for record in component]
    endpoint_radius = max(0.0, getattr(params, "circle_radius", 0.0))
    endpoint_margin = endpoint_radius + _air_duct_envelope_margin(endpoint_radius)
    component_polygons = [
        polygon
        for polygon in (
            _air_duct_component_polygon(component, endpoint_margin=endpoint_margin)
            for component in components
        )
        if len(polygon) >= 3
    ]
    if not component_polygons:
        return []

    if (
        len(components) == 1
        and _air_duct_records_form_end_cap(components[0], region)
    ):
        slot_loops = _single_component_air_duct_slot_loops(
            components[0],
            params,
            region,
            endpoint_margin=endpoint_margin,
        )
        if slot_loops:
            slot_loops = _expand_air_duct_loops_to_cover_records(
                slot_loops,
                records,
                endpoint_radius,
            )
            slot_loops = _orient_air_duct_loops(slot_loops)
            return [
                {"role": f"outline_{index}", "points": loop}
                for index, loop in enumerate(slot_loops)
                if len(loop) >= 3
            ]

    inlet_points = _air_duct_inlet_points(ordered, params, region, component_polygons)
    if inlet_points:
        join_margin = _inlet_union_join_margin(params)
        if len(records) <= 20:
            union_inlet_points = _nudge_inlet_points_for_union(inlet_points, join_margin)
            if len(component_polygons) == 1:
                loops = _union_polygon_with_rect_boundary(
                    component_polygons[0],
                    union_inlet_points,
                )
            else:
                loops = _union_polygons_boundary(component_polygons + [union_inlet_points])
                coverage_points = [
                    point
                    for polygon in component_polygons
                    for point in polygon
                ] + inlet_points
                if not _loops_cover_points(loops, coverage_points):
                    loops = component_polygons + [inlet_points]
            loops = _expand_air_duct_loops_to_cover_records(loops, records, endpoint_radius)
            loops = _orient_air_duct_loops(loops)
            return [
                {"role": f"outline_{index}", "points": loop}
                for index, loop in enumerate(loops)
                if len(loop) >= 3
            ]

        # Dense real board path: keep the complete side duct and merge the
        # horizontal inlet into it. Returning all union boundary loops preserves
        # the groove's inner walls; returning only the largest loop turns the
        # groove into a filled "lake".
        union_inlet_points = _nudge_inlet_points_for_union(inlet_points, join_margin)
        if len(component_polygons) > 1:
            loops = _union_polygons_boundary(component_polygons + [union_inlet_points])
            if not loops:
                loops = component_polygons + [inlet_points]
        else:
            loops = _union_polygon_with_rect_boundary(
                component_polygons[0],
                union_inlet_points,
            )
        loops = _expand_air_duct_loops_to_cover_records(loops, records, endpoint_radius)
        loops = _orient_air_duct_loops(loops)
        return [
            {"role": f"outline_{index}", "points": loop}
            for index, loop in enumerate(loops)
            if len(loop) >= 3
        ]

    component_polygons = _expand_air_duct_loops_to_cover_records(
        component_polygons,
        records,
        endpoint_radius,
    )
    component_polygons = _orient_air_duct_loops(component_polygons)
    return [
        {"role": f"outline_{index}", "points": polygon}
        for index, polygon in enumerate(component_polygons)
        if len(polygon) >= 3
    ]


def _air_duct_simple_ordered_records(records, total_length, params):
    ordered = _ordered_air_duct_records(records, total_length)
    return _bridge_air_duct_end_gap_records(ordered, "simple", params)


def _air_duct_simple_boundary_loops(records, total_length, params):
    ordered = _air_duct_simple_ordered_records(records, total_length, params)
    outer_curve, inner_curve = _air_duct_component_curves(ordered, endpoint_margin=0.0)
    loops = []
    for curve in (outer_curve, inner_curve):
        loop = _dedupe_air_duct_points(curve)
        if len(loop) >= 3 and abs(_polygon_signed_area(loop)) > POINT_TOLERANCE:
            loops.append(loop)
    return _orient_air_duct_loops(loops)


def _air_duct_simple_contours(records, total_length, params):
    if len(records) < 2:
        return []
    loops = _air_duct_simple_boundary_loops(records, total_length, params)
    return [
        {"role": f"outline_{index}", "points": loop}
        for index, loop in enumerate(loops)
        if len(loop) >= 3
    ]


def _air_duct_contours(doc, chain, params, placements, kept_items):
    if not getattr(params, "air_duct_enabled", True):
        return []
    if not placements or not kept_items:
        return []

    axis = _chain_axis(doc, chain)
    total_length = geom.chain_length(doc, chain)
    kept_by_placement = _items_by_placement(kept_items)
    grouped = {}
    for placement_index, placement in enumerate(placements):
        placement_items = kept_by_placement.get(placement_index, [])
        if not placement_items:
            continue
        # The duct is a continuous manifold around the intended hole row. If a
        # few holes are hidden because of overlap pruning, using only the kept
        # holes makes the envelope dent inward. Use the full planned row for
        # the duct shape while still skipping rays that have no kept holes.
        record = _air_duct_record(placement, params.circle_radius, None)
        if not record:
            continue
        region = (
            "simple"
            if getattr(params, "air_duct_simple_mode", False)
            else _air_duct_region_key(placement, axis, params)
        )
        grouped.setdefault(region, []).append(record)

    offset = _air_duct_template_offset(doc, chain)
    contours = []
    region_order = [
        "simple",
        "upper_outer",
        "upper_inner",
        "upper",
        "all",
        "lower_inner",
        "lower_outer",
        "lower",
    ]
    ordered_regions = sorted(
        grouped,
        key=lambda key: (
            region_order.index(key) if key in region_order else len(region_order),
            key,
        ),
    )
    for region in ordered_regions:
        contour_source = (
            _air_duct_simple_contours(grouped[region], total_length, params)
            if region == "simple"
            else _air_duct_region_contours(grouped[region], total_length, params, region)
        )
        for contour in contour_source:
            shifted = [point + offset for point in contour["points"]]
            contours.append({
                "region": region,
                "role": contour["role"],
                "points": shifted,
            })
    return contours


def _air_duct_component_polygons_for_region(records, total_length, params, region):
    if len(records) < 2:
        return []
    if region == "simple":
        return _air_duct_simple_boundary_loops(records, total_length, params)
    split_disconnected = region.endswith("_inner")
    components = _split_air_duct_components(records, total_length, split_disconnected)
    components = _bridge_air_duct_components_end_gaps(components, region, params)
    endpoint_radius = max(0.0, getattr(params, "circle_radius", 0.0))
    endpoint_margin = endpoint_radius + _air_duct_envelope_margin(endpoint_radius)
    return [
        polygon
        for polygon in (
            _air_duct_component_polygon(component, endpoint_margin=endpoint_margin)
            for component in components
        )
        if len(polygon) >= 3
    ]


def _smooth_base_plate_side_x(values, is_left_side):
    if len(values) < 5:
        return values

    original = list(values)
    smoothed = list(values)
    for _ in range(2):
        next_values = [smoothed[0]]
        for index in range(1, len(smoothed) - 1):
            candidate = (
                smoothed[index - 1] * 0.25
                + smoothed[index] * 0.5
                + smoothed[index + 1] * 0.25
            )
            # Smoothing must never shrink the plate inward, otherwise a local
            # dent can stop covering a duct edge. Left sides only move left,
            # right sides only move right.
            if is_left_side:
                candidate = min(candidate, original[index])
            else:
                candidate = max(candidate, original[index])
            next_values.append(candidate)
        next_values.append(smoothed[-1])
        smoothed = next_values
    return smoothed


def _base_plate_side_profile(polygons, margin, radius, min_y=None, max_y=None):
    clean_polygons = [
        _dedupe_air_duct_points(polygon)
        for polygon in polygons
        if len(_dedupe_air_duct_points(polygon)) >= 3
    ]
    if not clean_polygons:
        return []

    all_points = [point for polygon in clean_polygons for point in polygon]
    center_x = (min(point.x for point in all_points) + max(point.x for point in all_points)) * 0.5
    scan_min_y = min(point.y for point in all_points) if min_y is None else float(min_y)
    scan_max_y = max(point.y for point in all_points) if max_y is None else float(max_y)
    span_y = scan_max_y - scan_min_y
    if span_y <= POINT_TOLERANCE:
        return []

    sample_step = max(max(radius, 0.0) * 2.0, margin * 0.35, span_y / 180.0, 1.0)
    sample_count = max(12, min(240, int(math.ceil(span_y / sample_step)) + 1))
    profile = []
    for index in range(sample_count):
        y = scan_min_y + span_y * index / max(1, sample_count - 1)
        extents = _horizontal_extents_at_y(clean_polygons, y)
        if not extents:
            continue
        left_x, right_x = extents
        if right_x - left_x <= POINT_TOLERANCE:
            continue
        left_x, right_x = _symmetric_x_extents(left_x, right_x, center_x)
        profile.append((y, left_x - margin, right_x + margin))

    if len(profile) < 2:
        return profile

    ys = [item[0] for item in profile]
    left_xs = _smooth_base_plate_side_x([item[1] for item in profile], True)
    right_xs = _smooth_base_plate_side_x([item[2] for item in profile], False)
    return list(zip(ys, left_xs, right_xs))


def _base_plate_profile_xs_at(profile, target_y):
    if not profile:
        return None
    target_y = float(target_y)
    ordered = sorted(profile, key=lambda item: item[0])
    if target_y <= ordered[0][0]:
        return ordered[0][1], ordered[0][2]
    if target_y >= ordered[-1][0]:
        return ordered[-1][1], ordered[-1][2]

    for current, nxt in zip(ordered, ordered[1:]):
        y0, left0, right0 = current
        y1, left1, right1 = nxt
        if abs(target_y - y0) <= POINT_TOLERANCE:
            return left0, right0
        if y0 <= target_y <= y1:
            if abs(y1 - y0) <= POINT_TOLERANCE:
                return left0, right0
            t = (target_y - y0) / (y1 - y0)
            return (
                left0 + (left1 - left0) * t,
                right0 + (right1 - right0) * t,
            )
    return ordered[-1][1], ordered[-1][2]


def _base_plate_fallback_polygon(
    all_points,
    margin,
    bottom_y,
    top_y,
    side_profile=None,
):
    raw_min_x = min(point.x for point in all_points)
    raw_max_x = max(point.x for point in all_points)
    center_x = (raw_min_x + raw_max_x) * 0.5
    min_x, max_x = _symmetric_x_extents(raw_min_x - margin, raw_max_x + margin, center_x)
    bottom_xs = _base_plate_profile_xs_at(side_profile, bottom_y)
    top_xs = _base_plate_profile_xs_at(side_profile, top_y)
    bottom_left_x, bottom_right_x = bottom_xs if bottom_xs else (min_x, max_x)
    top_left_x, top_right_x = top_xs if top_xs else (min_x, max_x)
    return [
        Vec2(bottom_left_x, bottom_y),
        Vec2(bottom_right_x, bottom_y),
        Vec2(top_right_x, top_y),
        Vec2(top_left_x, top_y),
    ]


def _clip_polygon_by_horizontal_line(points, boundary_y, keep_above):
    points = _dedupe_air_duct_points(points)
    if len(points) < 3:
        return points

    boundary_y = float(boundary_y)

    def is_inside(point):
        if keep_above:
            return point.y >= boundary_y - POINT_TOLERANCE
        return point.y <= boundary_y + POINT_TOLERANCE

    def intersection(start, end):
        if abs(end.y - start.y) <= POINT_TOLERANCE:
            return Vec2(end.x, boundary_y)
        t = (boundary_y - start.y) / (end.y - start.y)
        return Vec2(start.x + (end.x - start.x) * t, boundary_y)

    clipped = []
    for start, end in _polygon_edges(points):
        start_inside = is_inside(start)
        end_inside = is_inside(end)
        if start_inside and end_inside:
            clipped.append(end)
        elif start_inside and not end_inside:
            clipped.append(intersection(start, end))
        elif not start_inside and end_inside:
            clipped.append(intersection(start, end))
            clipped.append(end)

    return _dedupe_air_duct_points(clipped)


def _force_flat_base_plate_boundary(points, boundary_y, xs, is_lower_boundary):
    points = _dedupe_air_duct_points(points)
    if len(points) < 3 or not xs:
        return points

    left_x, right_x = xs
    boundary_y = float(boundary_y)
    flat_points = [
        point
        for point in points
        if abs(point.y - boundary_y) <= POINT_TOLERANCE * 10.0
    ]
    if len(flat_points) < 2:
        return points

    flat_a = Vec2(left_x, boundary_y)
    flat_b = Vec2(right_x, boundary_y)

    non_flat = [
        point
        for point in points
        if abs(point.y - boundary_y) > POINT_TOLERANCE * 10.0
    ]
    if len(non_flat) < 2:
        return [flat_a, flat_b]

    if is_lower_boundary:
        left_side = sorted(
            [point for point in non_flat if point.x <= (left_x + right_x) * 0.5],
            key=lambda point: point.y,
        )
        right_side = sorted(
            [point for point in non_flat if point.x > (left_x + right_x) * 0.5],
            key=lambda point: point.y,
            reverse=True,
        )
        return _dedupe_air_duct_points([flat_a] + left_side + right_side + [flat_b])

    left_side = sorted(
        [point for point in non_flat if point.x <= (left_x + right_x) * 0.5],
        key=lambda point: point.y,
    )
    right_side = sorted(
        [point for point in non_flat if point.x > (left_x + right_x) * 0.5],
        key=lambda point: point.y,
        reverse=True,
    )
    return _dedupe_air_duct_points(left_side + [flat_a, flat_b] + right_side)


def _base_plate_offset_polygon_from_samples(samples, margin):
    if len(samples) < 2:
        return []

    left_side = [Vec2(left_x, y) for y, left_x, _ in samples]
    right_side = [Vec2(right_x, y) for y, _, right_x in reversed(samples)]
    envelope = _dedupe_air_duct_points(left_side + right_side)
    if len(envelope) < 3:
        return []

    # Build the envelope clockwise so a positive ezdxf offset expands outward.
    if _polygon_signed_area(envelope) > 0:
        envelope = list(reversed(envelope))

    if margin <= POINT_TOLERANCE:
        return envelope

    try:
        offset_points = list(offset_vertices_2d(envelope, margin, closed=True))
    except Exception:
        return []
    return _dedupe_air_duct_points([Vec2(point.x, point.y) for point in offset_points])


def _air_duct_base_plate_polygon(
    component_polygons,
    margin,
    radius,
    lower_flat_y=None,
    upper_flat_y=None,
    side_profile=None,
    extent_polygons=None,
):
    polygons = [
        _dedupe_air_duct_points(polygon)
        for polygon in component_polygons
        if len(_dedupe_air_duct_points(polygon)) >= 3
    ]
    if not polygons:
        return []

    margin = max(0.0, float(margin or 0.0))
    extent_source = polygons
    if extent_polygons:
        extent_source = [
            _dedupe_air_duct_points(polygon)
            for polygon in extent_polygons
            if len(_dedupe_air_duct_points(polygon)) >= 3
        ] or polygons
    symmetric_samples = bool(extent_polygons)
    all_points = [point for polygon in polygons for point in polygon]
    extent_points = [point for polygon in extent_source for point in polygon]
    center_x = (
        min(point.x for point in extent_points)
        + max(point.x for point in extent_points)
    ) * 0.5
    min_y = min(point.y for point in all_points)
    max_y = max(point.y for point in all_points)
    scan_min_y = min_y
    scan_max_y = max_y
    if lower_flat_y is not None:
        scan_min_y = max(scan_min_y, float(lower_flat_y))
    if upper_flat_y is not None:
        scan_max_y = min(scan_max_y, float(upper_flat_y))
    span_y = scan_max_y - scan_min_y
    if span_y <= POINT_TOLERANCE:
        bottom_y = float(lower_flat_y) if lower_flat_y is not None else min_y - margin
        top_y = float(upper_flat_y) if upper_flat_y is not None else max_y + margin
        if top_y - bottom_y <= POINT_TOLERANCE:
            bottom_y = min_y - margin
            top_y = max_y + margin
        return _base_plate_fallback_polygon(
            all_points,
            margin,
            bottom_y,
            top_y,
            side_profile,
        )

    sample_step = max(max(radius, 0.0) * 1.2, margin * 0.2, span_y / 220.0, 0.5)
    sample_count = max(16, min(320, int(math.ceil(span_y / sample_step)) + 1))
    samples = []
    for index in range(sample_count):
        y = scan_min_y + span_y * index / max(1, sample_count - 1)
        extents = _horizontal_extents_at_y(extent_source, y)
        if not extents:
            continue
        left_x, right_x = extents
        if right_x - left_x <= POINT_TOLERANCE:
            is_natural_lower_tip = index == 0 and lower_flat_y is None
            is_natural_upper_tip = index == sample_count - 1 and upper_flat_y is None
            if not (is_natural_lower_tip or is_natural_upper_tip):
                continue
        if symmetric_samples:
            left_x, right_x = _symmetric_x_extents(left_x, right_x, center_x)
        samples.append((y, left_x, right_x))

    if len(samples) < 2:
        bottom_y = float(lower_flat_y) if lower_flat_y is not None else min_y - margin
        top_y = float(upper_flat_y) if upper_flat_y is not None else max_y + margin
        if top_y - bottom_y <= POINT_TOLERANCE:
            bottom_y = min_y - margin
            top_y = max_y + margin
        return _base_plate_fallback_polygon(
            all_points,
            margin,
            bottom_y,
            top_y,
            side_profile,
        )

    offset_polygon = _base_plate_offset_polygon_from_samples(samples, margin)
    if len(offset_polygon) < 3:
        bottom_y = float(lower_flat_y) if lower_flat_y is not None else min_y - margin
        top_y = float(upper_flat_y) if upper_flat_y is not None else max_y + margin
        if top_y - bottom_y <= POINT_TOLERANCE:
            bottom_y = min_y - margin
            top_y = max_y + margin
        return _base_plate_fallback_polygon(
            all_points,
            margin,
            bottom_y,
            top_y,
            side_profile,
        )

    if lower_flat_y is not None:
        lower_flat_y = float(lower_flat_y)
        offset_polygon = _clip_polygon_by_horizontal_line(
            offset_polygon,
            lower_flat_y,
            keep_above=True,
        )
        profile_xs = _base_plate_profile_xs_at(side_profile, lower_flat_y)
        if profile_xs:
            offset_polygon = _force_flat_base_plate_boundary(
                offset_polygon,
                lower_flat_y,
                profile_xs,
                is_lower_boundary=True,
            )

    if upper_flat_y is not None:
        upper_flat_y = float(upper_flat_y)
        offset_polygon = _clip_polygon_by_horizontal_line(
            offset_polygon,
            upper_flat_y,
            keep_above=False,
        )
        profile_xs = _base_plate_profile_xs_at(side_profile, upper_flat_y)
        if profile_xs:
            offset_polygon = _force_flat_base_plate_boundary(
                offset_polygon,
                upper_flat_y,
                profile_xs,
                is_lower_boundary=False,
            )

    return _dedupe_air_duct_points(offset_polygon)


def _air_duct_base_plate_region_data(grouped, total_length, params):
    region_data = {}
    for region in _ordered_air_duct_regions(grouped):
        component_polygons = _air_duct_component_polygons_for_region(
            grouped[region],
            total_length,
            params,
            region,
        )
        points = [
            point
            for polygon in component_polygons
            for point in polygon
        ]
        if not points:
            continue
        min_y = min(point.y for point in points)
        max_y = max(point.y for point in points)
        region_data[region] = {
            "records": grouped[region],
            "component_polygons": component_polygons,
            "min_y": min_y,
            "max_y": max_y,
            "center_y": (min_y + max_y) * 0.5,
        }
    return region_data


def _air_duct_base_plate_flat_bounds_from_regions(region_data):
    bounds = {
        region: [None, None]
        for region in region_data
    }
    ordered_regions = sorted(
        region_data,
        key=lambda region: region_data[region]["center_y"],
        reverse=True,
    )
    for upper_region, lower_region in zip(ordered_regions, ordered_regions[1:]):
        upper_low_y = region_data[upper_region]["min_y"]
        lower_high_y = region_data[lower_region]["max_y"]
        split_y = (upper_low_y + lower_high_y) * 0.5
        bounds[upper_region][0] = split_y
        bounds[lower_region][1] = split_y
    return {
        region: tuple(values)
        for region, values in bounds.items()
    }


def _air_duct_base_plate_region_contours(
    records,
    total_length,
    params,
    region,
    flat_bounds=None,
    component_polygons=None,
    side_profile=None,
    extent_polygons=None,
):
    if component_polygons is None:
        component_polygons = _air_duct_component_polygons_for_region(
            records,
            total_length,
            params,
            region,
        )
    lower_flat_y, upper_flat_y = flat_bounds or (None, None)
    polygon = _air_duct_base_plate_polygon(
        component_polygons,
        getattr(params, "air_duct_base_plate_margin", 0.0),
        getattr(params, "circle_radius", 0.0),
        lower_flat_y=lower_flat_y,
        upper_flat_y=upper_flat_y,
        side_profile=side_profile,
        extent_polygons=extent_polygons,
    )
    if len(polygon) < 3:
        return []
    return [{"role": "base_plate", "points": polygon}]


def _air_duct_group_records(doc, chain, params, placements, kept_items):
    if not getattr(params, "air_duct_enabled", True):
        return {}, 0.0
    if not placements or not kept_items:
        return {}, 0.0

    axis = _chain_axis(doc, chain)
    total_length = geom.chain_length(doc, chain)
    kept_by_placement = _items_by_placement(kept_items)
    grouped = {}
    for placement_index, placement in enumerate(placements):
        if not kept_by_placement.get(placement_index, []):
            continue
        record = _air_duct_record(placement, params.circle_radius, None)
        if not record:
            continue
        region = (
            "simple"
            if getattr(params, "air_duct_simple_mode", False)
            else _air_duct_region_key(placement, axis, params)
        )
        grouped.setdefault(region, []).append(record)
    return grouped, total_length


def _ordered_air_duct_regions(grouped):
    region_order = [
        "simple",
        "upper_outer",
        "upper_inner",
        "upper",
        "all",
        "lower_inner",
        "lower_outer",
        "lower",
    ]
    return sorted(
        grouped,
        key=lambda key: (
            region_order.index(key) if key in region_order else len(region_order),
            key,
        ),
    )


def _air_duct_base_plate_contours(doc, chain, params, placements, kept_items):
    grouped, total_length = _air_duct_group_records(
        doc,
        chain,
        params,
        placements,
        kept_items,
    )
    if not grouped:
        return []

    offset = _air_duct_template_offset(doc, chain)
    region_data = _air_duct_base_plate_region_data(grouped, total_length, params)
    flat_bounds_by_region = _air_duct_base_plate_flat_bounds_from_regions(region_data)
    all_component_polygons = [
        polygon
        for data in region_data.values()
        for polygon in data["component_polygons"]
    ]
    all_points = [
        point
        for polygon in all_component_polygons
        for point in polygon
    ]
    side_profile = []
    if all_points:
        margin = getattr(params, "air_duct_base_plate_margin", 0.0)
        side_profile = _base_plate_side_profile(
            all_component_polygons,
            max(0.0, float(margin or 0.0)),
            getattr(params, "circle_radius", 0.0),
            min(point.y for point in all_points),
            max(point.y for point in all_points),
        )
    contours = []
    for region in _ordered_air_duct_regions(region_data):
        data = region_data[region]
        for contour in _air_duct_base_plate_region_contours(
            data["records"],
            total_length,
            params,
            region,
            flat_bounds=flat_bounds_by_region.get(region),
            component_polygons=data["component_polygons"],
            side_profile=side_profile,
            extent_polygons=all_component_polygons,
        ):
            shifted = [point + offset for point in contour["points"]]
            contours.append({
                "region": region,
                "role": contour["role"],
                "points": shifted,
            })
    return contours


def _contour_svg_path(points, bounds, scale):
    if not points:
        return ""
    parts = []
    for index, point in enumerate(points):
        x, y = _to_svg(point.x, point.y, bounds, scale)
        command = "M" if index == 0 else "L"
        parts.append(f"{command} {x:.1f} {y:.1f}")
    parts.append("Z")
    return " ".join(parts)


def _add_air_duct_entities(msp, doc, contours):
    if not contours:
        return []
    if AIR_DUCT_LAYER not in doc.layers:
        doc.layers.add(AIR_DUCT_LAYER)
    handles = []
    for contour in contours:
        points = contour.get("points") or []
        if len(points) < 3:
            continue
        polyline = msp.add_lwpolyline(
            [(point.x, point.y) for point in points],
            close=True,
            dxfattribs={"layer": AIR_DUCT_LAYER},
        )
        handles.append(polyline.dxf.handle)
    return handles


def _add_air_duct_base_plate_entities(msp, doc, contours):
    if not contours:
        return []
    if AIR_DUCT_BASE_PLATE_LAYER not in doc.layers:
        doc.layers.add(AIR_DUCT_BASE_PLATE_LAYER)
    handles = []
    for contour in contours:
        points = contour.get("points") or []
        if len(points) < 3:
            continue
        polyline = msp.add_lwpolyline(
            [(point.x, point.y) for point in points],
            close=True,
            dxfattribs={"layer": AIR_DUCT_BASE_PLATE_LAYER},
        )
        handles.append(polyline.dxf.handle)
    return handles


def _mirror_groups(items, axis_center_x, radius):
    unused = {item["id"] for item in items}
    by_id = {item["id"]: item for item in items}
    groups = []
    pair_limit_sq = max(radius * 4.0, POINT_TOLERANCE * 10.0) ** 2

    for item in items:
        item_id = item["id"]
        if item_id not in unused:
            continue
        unused.remove(item_id)

        mirror = Vec2(2.0 * axis_center_x - item["center"].x, item["center"].y)
        candidates = [
            by_id[other_id]
            for other_id in unused
            if by_id[other_id]["circle_index"] == item["circle_index"]
            and (by_id[other_id]["center"].x - axis_center_x) * (item["center"].x - axis_center_x) <= 0
        ]
        partner = None
        if candidates:
            partner = min(candidates, key=lambda other: _distance_square(other["center"], mirror))
            if _distance_square(partner["center"], mirror) > pair_limit_sq:
                partner = None

        ids = [item_id]
        if partner is not None:
            ids.append(partner["id"])
            unused.remove(partner["id"])
        groups.append(ids)
    return groups


def _overlap_pruned_circle_items(doc, chain, params, placements):
    items = _flatten_circle_items(placements, params.circle_radius)
    if len(items) <= 1 or params.circle_radius <= 0:
        return items, []

    axis = geom.estimate_chain_symmetry_axis(doc, chain)
    axis_center_x = axis["center"].x if axis else (
        sum(item["center"].x for item in items) / len(items)
    )

    groups = (
        _mirror_groups(items, axis_center_x, params.circle_radius)
        if axis
        else [[item["id"]] for item in items]
    )
    item_to_group = {}
    for group_index, ids in enumerate(groups):
        for item_id in ids:
            item_to_group[item_id] = group_index

    by_id = {item["id"]: item for item in items}
    group_scores = [
        sum(_circle_priority(by_id[item_id], axis_center_x) for item_id in ids)
        for ids in groups
    ]
    removed_ids = set()
    capsule_removed_ids = set()
    min_distance = max(0.0, params.circle_radius * 2.0 - POINT_TOLERANCE)

    while True:
        best_conflict = _circle_conflict(
            items,
            removed_ids,
            by_id,
            item_to_group,
            min_distance,
        )
        if best_conflict is None:
            break

        _, g1, g2 = best_conflict
        if g1 == g2:
            group_active_ids = [
                item_id for item_id in groups[g1]
                if item_id not in removed_ids
            ]
            if len(group_active_ids) <= 1:
                break
            loser = min(
                group_active_ids,
                key=lambda item_id: _circle_priority(by_id[item_id], axis_center_x),
            )
            removed_ids.add(loser)
            continue
        if group_scores[g1] < group_scores[g2]:
            removed_ids.update(groups[g1])
        elif group_scores[g2] < group_scores[g1]:
            removed_ids.update(groups[g2])
        else:
            # Same score: remove the smaller/inner group first, deterministic.
            g1_axis = sum(abs(by_id[item_id]["center"].x - axis_center_x) for item_id in groups[g1])
            g2_axis = sum(abs(by_id[item_id]["center"].x - axis_center_x) for item_id in groups[g2])
            loser_group = g1 if (len(groups[g1]), g1_axis, -g1) < (len(groups[g2]), g2_axis, -g2) else g2
            removed_ids.update(groups[loser_group])

    while True:
        active_items = [
            item
            for item in items
            if item["id"] not in removed_ids
        ]
        best_conflict = _best_capsule_conflict(
            placements,
            params,
            axis,
            active_items,
        )
        if best_conflict is None:
            break

        _, first_capsule, second_capsule = best_conflict
        candidate_groups = []
        for capsule_info in (first_capsule, second_capsule):
            group_ids = {
                item_to_group[item_id]
                for item_id in capsule_info["outer_ids"]
                if item_id in item_to_group
            }
            for group_id in group_ids:
                active_group_ids = [
                    item_id
                    for item_id in groups[group_id]
                    if item_id not in removed_ids
                ]
                if active_group_ids:
                    candidate_groups.append((group_id, active_group_ids))

        if not candidate_groups:
            break

        def removal_key(candidate):
            group_id, active_group_ids = candidate
            max_circle_index = max(by_id[item_id]["circle_index"] for item_id in active_group_ids)
            return (
                max_circle_index,
                -group_scores[group_id],
                -len(active_group_ids),
                -group_id,
            )

        loser_group, loser_ids = max(candidate_groups, key=removal_key)
        removed_ids.update(loser_ids)
        capsule_removed_ids.update(loser_ids)

    kept_ids = {item["id"] for item in items if item["id"] not in removed_ids}
    for item in sorted(
        items,
        key=lambda candidate: _circle_priority(candidate, axis_center_x),
        reverse=True,
    ):
        item_id = item["id"]
        if item_id in kept_ids:
            continue
        if item_id in capsule_removed_ids:
            continue
        overlaps_kept = _has_circle_overlap(item, kept_ids, by_id, min_distance)
        if not overlaps_kept:
            kept_ids.add(item_id)

    while True:
        active_items = [item for item in items if item["id"] in kept_ids]
        best_conflict = _best_capsule_conflict(
            placements,
            params,
            axis,
            active_items,
        )
        if best_conflict is None:
            break

        _, first_capsule, second_capsule = best_conflict
        candidate_ids = []
        for capsule_info in (first_capsule, second_capsule):
            candidate_ids.extend(
                item_id
                for item_id in capsule_info["outer_ids"]
                if item_id in kept_ids
            )
        if not candidate_ids:
            break
        loser = max(
            candidate_ids,
            key=lambda item_id: (
                by_id[item_id]["circle_index"],
                -_circle_priority(by_id[item_id], axis_center_x),
                -item_id,
            ),
        )
        loser_group = item_to_group.get(loser)
        if loser_group is None:
            kept_ids.remove(loser)
        else:
            for item_id in groups[loser_group]:
                kept_ids.discard(item_id)

    kept = []
    removed = []
    for item in items:
        if item["id"] in kept_ids:
            kept.append(item)
        else:
            removed.append(item)
    return kept, removed


def _items_by_placement(items):
    by_placement = {}
    for item in items:
        by_placement.setdefault(item["placement_index"], []).append(item)
    return by_placement


def _capsules_from_active_items(placements, params, axis, active_items):
    capsules = []
    by_placement = _items_by_placement(active_items)
    for placement_index, placement_items in by_placement.items():
        placement = placements[placement_index]
        if _inside_capsule_axis_gap(placement, axis, params):
            continue
        capsule = _capsule_for_placement(placement, params, placement_items)
        if not capsule:
            continue
        outer_index = max(item["circle_index"] for item in placement_items)
        outer_ids = [
            item["id"]
            for item in placement_items
            if item["circle_index"] == outer_index
        ]
        capsules.append({
            "placement_index": placement_index,
            "capsule": capsule,
            "outer_ids": outer_ids,
            "outer_index": outer_index,
        })
    return capsules


def _best_capsule_conflict(placements, params, axis, active_items):
    capsules = _capsules_from_active_items(placements, params, axis, active_items)
    if len(capsules) <= 1:
        return None

    clearance = max(0.0, getattr(params, "capsule_clearance_distance", 0.0))
    min_distance = max(0.0, params.circle_radius * 2.0 + clearance - POINT_TOLERANCE)
    best_conflict = None
    cell_size = max(min_distance, POINT_TOLERANCE * 10.0, 1e-9)
    cells = {}
    checked = set()

    for index, first in enumerate(capsules):
        first_capsule = first["capsule"]
        min_x = min(first_capsule["near"].x, first_capsule["far"].x) - min_distance
        max_x = max(first_capsule["near"].x, first_capsule["far"].x) + min_distance
        min_y = min(first_capsule["near"].y, first_capsule["far"].y) - min_distance
        max_y = max(first_capsule["near"].y, first_capsule["far"].y) + min_distance
        ix1 = math.floor(min_x / cell_size)
        ix2 = math.floor(max_x / cell_size)
        iy1 = math.floor(min_y / cell_size)
        iy2 = math.floor(max_y / cell_size)

        candidate_indexes = set()
        for ix in range(ix1, ix2 + 1):
            for iy in range(iy1, iy2 + 1):
                candidate_indexes.update(cells.get((ix, iy), []))

        for second_index in candidate_indexes:
            pair = (second_index, index) if second_index < index else (index, second_index)
            if pair in checked:
                continue
            checked.add(pair)
            second = capsules[second_index]
            if first["placement_index"] == second["placement_index"]:
                continue
            second_capsule = second["capsule"]
            distance = _segment_distance(
                first_capsule["near"],
                first_capsule["far"],
                second_capsule["near"],
                second_capsule["far"],
            )
            penetration = min_distance - distance
            if penetration <= 0:
                continue
            conflict = (penetration, first, second)
            if best_conflict is None or conflict[0] > best_conflict[0]:
                best_conflict = conflict

        for ix in range(ix1, ix2 + 1):
            for iy in range(iy1, iy2 + 1):
                cells.setdefault((ix, iy), []).append(index)
    return best_conflict


def compute_preview_geometry(doc, chain: List[str], params: CircleParams,
                             closed: bool, bounds: dict, scale: float,
                             manual_apex_distance=None) -> dict:
    """Compute overlay geometry expressed in base-SVG output units.

    Does NOT modify any DXF document. ``bounds``/``scale`` come from
    ``svg_exporter.doc_to_base_svg`` and define the WCS -> SVG transform.
    """
    placements = compute_placements(
        doc, chain, params, closed=closed, manual_apex_distance=manual_apex_distance
    )
    kept_items, removed_items = _overlap_pruned_circle_items(doc, chain, params, placements)
    kept_by_placement = _items_by_placement(kept_items)
    axis = _chain_axis(doc, chain)
    air_duct_contours = _air_duct_contours(doc, chain, params, placements, kept_items)
    air_duct_base_plate_contours = _air_duct_base_plate_contours(
        doc,
        chain,
        params,
        placements,
        kept_items,
    )
    air_duct_template_offset = _air_duct_template_offset(doc, chain)
    capsule_template_offset = _capsule_template_offset(doc, chain)

    circles = []
    removed_circles = []
    rays = []
    basis = []
    capsules = []
    air_duct_base_plates = []
    air_ducts = []
    for contour in air_duct_base_plate_contours:
        d = _contour_svg_path(contour["points"], bounds, scale)
        if d:
            air_duct_base_plates.append({
                "d": d,
                "region": contour["region"],
                "role": contour.get("role", "base_plate"),
            })
    for contour in air_duct_contours:
        d = _contour_svg_path(contour["points"], bounds, scale)
        if d:
            air_ducts.append({
                "d": d,
                "region": contour["region"],
                "role": contour.get("role", "outline"),
            })
    for placement_index, p in enumerate(placements):
        x, y = _to_svg(p["point"].x, p["point"].y, bounds, scale)
        basis.append({
            "x": x,
            "y": y,
            "nx": p["normal"].x * scale,
            "ny": -p["normal"].y * scale,
        })
        if not _inside_capsule_axis_gap(p, axis, params):
            capsule = _capsule_for_placement(
                p,
                params,
                kept_by_placement.get(placement_index, []),
            )
            if capsule:
                capsules.append({
                    "d": _capsule_svg_path(
                        _shift_capsule(capsule, capsule_template_offset),
                        bounds,
                        scale,
                    )
                })
    for item in kept_items:
        c = item["center"]
        cx, cy = _to_svg(c.x, c.y, bounds, scale)
        circles.append({
            "cx": cx,
            "cy": cy,
            "r": params.circle_radius * scale,
        })
    for item in removed_items:
        c = item["center"]
        cx, cy = _to_svg(c.x, c.y, bounds, scale)
        removed_circles.append({
            "cx": cx,
            "cy": cy,
            "r": params.circle_radius * scale,
        })
    for p in placements:
        x1, y1 = _to_svg(p["point"].x, p["point"].y, bounds, scale)
        x2, y2 = _to_svg(p["ray_end"].x, p["ray_end"].y, bounds, scale)
        rays.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})

    chain_path = _chain_path_d(doc, chain, closed, bounds, scale)
    capsule_chain_path = _chain_path_d(doc, chain, closed, bounds, scale, capsule_template_offset)
    apex_marker = None
    total = geom.chain_length(doc, chain)
    apex_sample = (
        _apex_sample(doc, chain, total, manual_apex_distance=manual_apex_distance)
        if total > 1e-9
        else None
    )
    if apex_sample is not None:
        ax, ay = _to_svg(apex_sample.point.x, apex_sample.point.y, bounds, scale)
        apex_marker = {"cx": ax, "cy": ay, "r": max(5.0, params.circle_radius * scale)}

    return {
        "circles": circles,
        "removed_circles": removed_circles,
        "rays": rays,
        "capsules": capsules,
        "air_duct_base_plates": air_duct_base_plates,
        "air_ducts": air_ducts,
        "air_duct_template_offset": {
            "x": air_duct_template_offset.x * scale,
            "y": -air_duct_template_offset.y * scale,
        },
        "capsule_template_offset": {
            "x": capsule_template_offset.x * scale,
            "y": -capsule_template_offset.y * scale,
        },
        "basis": basis,
        "scale": scale,
        "selected_chain_path": chain_path,
        "capsule_chain_path": capsule_chain_path,
        "apex_marker": apex_marker,
        "symmetry_axis": _symmetry_axis_overlay(doc, chain, bounds, scale),
        "symmetry_axes": _symmetry_axes_overlay(doc, chain, bounds, scale),
        "capsule_gap_guide": _capsule_gap_guide_overlay(doc, chain, params, bounds, scale),
        "symmetry_snap_point": _symmetry_snap_point_overlay(doc, chain, bounds, scale),
        "generated_count": len(circles),
        "removed_count": len(removed_circles),
        "air_duct_base_plate_count": len(air_duct_base_plates),
        "air_duct_count": len(air_ducts),
    }


def _to_svg(x: float, y: float, bounds: dict, scale: float):
    sx = (x - bounds["min"][0]) * scale
    sy = (bounds["max"][1] - y) * scale
    return sx, sy


def _chain_path_d(
    doc,
    chain: List[str],
    closed: bool,
    bounds: dict,
    scale: float,
    offset: Vec2 | None = None,
) -> str:
    """Build an SVG path 'd' for the selected chain in SVG output units."""
    if not chain:
        return ""

    # Sample densely enough for a smooth highlight.
    total = 0.0
    for handle in chain:
        entity = doc.entitydb.get(handle)
        if entity:
            total += geom.entity_length(entity)
    num = max(32, min(2000, int(total / 2.0))) if total > 0 else 64

    samples = geom.sample_chain(doc, chain, num, closed=closed)
    if not samples:
        return ""

    offset = offset or Vec2(0, 0)
    parts = []
    for i, s in enumerate(samples):
        point = s.point + offset
        sx, sy = _to_svg(point.x, point.y, bounds, scale)
        cmd = "M" if i == 0 else "L"
        parts.append(f"{cmd} {sx:.1f} {sy:.1f}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


def _add_chain_copy_entity(msp, doc, chain: List[str], closed: bool, offset: Vec2):
    if not chain or offset.magnitude <= POINT_TOLERANCE:
        return None
    total = geom.chain_length(doc, chain)
    if total <= 1e-9:
        return None
    count = max(64, min(4000, int(total / 2.0)))
    samples = geom.sample_chain(doc, chain, count, closed=closed)
    if len(samples) < 2:
        return None
    points = [(sample.point.x + offset.x, sample.point.y + offset.y) for sample in samples]
    return msp.add_lwpolyline(
        points,
        close=closed,
        dxfattribs={"layer": GENERATED_LAYER},
    ).dxf.handle


def generate_circles(doc: ezdxf.document.Drawing, chain: List[str], params: CircleParams,
                     closed: bool = False, manual_apex_distance=None) -> Tuple[List[str], List[str]]:
    """Write circle and ray entities into ``doc`` (used for the saved DXF).

    Returns (circle_handles, ray_handles).
    """
    placements = compute_placements(
        doc, chain, params, closed=closed, manual_apex_distance=manual_apex_distance
    )
    if not placements:
        return [], []
    kept_items, _ = _overlap_pruned_circle_items(doc, chain, params, placements)
    kept_by_placement = _items_by_placement(kept_items)
    axis = _chain_axis(doc, chain)
    capsule_template_offset = _capsule_template_offset(doc, chain)
    air_duct_contours = _air_duct_contours(doc, chain, params, placements, kept_items)
    air_duct_base_plate_contours = _air_duct_base_plate_contours(
        doc,
        chain,
        params,
        placements,
        kept_items,
    )

    msp = doc.modelspace()
    if GENERATED_LAYER not in doc.layers:
        doc.layers.add(GENERATED_LAYER)
    circle_handles = []
    _add_chain_copy_entity(msp, doc, chain, closed, capsule_template_offset)

    for item in kept_items:
        center = item["center"]
        circle = msp.add_circle(
            center=(center.x, center.y),
            radius=params.circle_radius,
            dxfattribs={"layer": GENERATED_LAYER},
        )
        circle_handles.append(circle.dxf.handle)

    for placement_index, placement in enumerate(placements):
        if _inside_capsule_axis_gap(placement, axis, params):
            continue
        capsule = _capsule_for_placement(
            placement,
            params,
            kept_by_placement.get(placement_index, []),
        )
        if capsule:
            _add_capsule_entities(msp, _shift_capsule(capsule, capsule_template_offset))
    _add_air_duct_base_plate_entities(msp, doc, air_duct_base_plate_contours)
    _add_air_duct_entities(msp, doc, air_duct_contours)

    return circle_handles, []
