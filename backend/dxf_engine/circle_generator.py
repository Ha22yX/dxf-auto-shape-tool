"""Generate circles and rays along normal directions from selected edge chain.

Two entry points:
- ``compute_placements`` / ``compute_preview_geometry``: pure geometry for the
  real-time overlay (no DXF mutation).
- ``generate_circles``: writes real entities into a DXF document (download only).
"""
from typing import List, Tuple
import math
import ezdxf
from ezdxf.math import Vec2

from backend.state import CircleParams
from backend.config import GENERATED_LAYER, POINT_TOLERANCE
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


def _symmetry_axis_overlay(doc, chain, bounds, scale):
    axis = geom.estimate_chain_symmetry_axis(doc, chain)
    if not axis:
        return None
    x1, y1 = _to_svg(axis["start"].x, axis["start"].y, bounds, scale)
    x2, y2 = _to_svg(axis["end"].x, axis["end"].y, bounds, scale)
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


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
        return geom.orient_normals_for_closed_chain(
            samples,
            inward=(params.ray_direction == "inward"),
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

    groups = _mirror_groups(items, axis_center_x, params.circle_radius)
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
    min_distance = max(0.0, params.circle_radius * 2.0 - POINT_TOLERANCE)

    while True:
        active_ids = [
            item["id"]
            for item in items
            if item["id"] not in removed_ids
        ]
        best_conflict = None
        for i, first_id in enumerate(active_ids):
            first = by_id[first_id]
            for second_id in active_ids[i + 1:]:
                second = by_id[second_id]
                distance = (first["center"] - second["center"]).magnitude
                penetration = min_distance - distance
                if penetration <= 0:
                    continue
                g1 = item_to_group[first_id]
                g2 = item_to_group[second_id]
                conflict = (penetration, g1, g2)
                if best_conflict is None or conflict[0] > best_conflict[0]:
                    best_conflict = conflict

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

    kept_ids = {item["id"] for item in items if item["id"] not in removed_ids}
    for item in sorted(
        items,
        key=lambda candidate: _circle_priority(candidate, axis_center_x),
        reverse=True,
    ):
        item_id = item["id"]
        if item_id in kept_ids:
            continue
        overlaps_kept = any(
            (item["center"] - by_id[kept_id]["center"]).magnitude < min_distance
            for kept_id in kept_ids
        )
        if not overlaps_kept:
            kept_ids.add(item_id)

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

    circles = []
    removed_circles = []
    rays = []
    basis = []
    capsules = []
    for placement_index, p in enumerate(placements):
        x, y = _to_svg(p["point"].x, p["point"].y, bounds, scale)
        basis.append({
            "x": x,
            "y": y,
            "nx": p["normal"].x * scale,
            "ny": -p["normal"].y * scale,
        })
        capsule = _capsule_for_placement(
            p,
            params,
            kept_by_placement.get(placement_index, []),
        )
        if capsule:
            capsules.append({"d": _capsule_svg_path(capsule, bounds, scale)})
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
    apex_marker = None
    apex_sample = _manual_apex_marker(doc, chain, manual_apex_distance)
    if apex_sample is not None:
        ax, ay = _to_svg(apex_sample.point.x, apex_sample.point.y, bounds, scale)
        apex_marker = {"cx": ax, "cy": ay, "r": max(5.0, params.circle_radius * scale)}

    return {
        "circles": circles,
        "removed_circles": removed_circles,
        "rays": rays,
        "capsules": capsules,
        "basis": basis,
        "scale": scale,
        "selected_chain_path": chain_path,
        "apex_marker": apex_marker,
        "symmetry_axis": _symmetry_axis_overlay(doc, chain, bounds, scale),
        "symmetry_snap_point": _symmetry_snap_point_overlay(doc, chain, bounds, scale),
        "generated_count": len(circles),
        "removed_count": len(removed_circles),
    }


def _to_svg(x: float, y: float, bounds: dict, scale: float):
    sx = (x - bounds["min"][0]) * scale
    sy = (bounds["max"][1] - y) * scale
    return sx, sy


def _chain_path_d(doc, chain: List[str], closed: bool, bounds: dict, scale: float) -> str:
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

    parts = []
    for i, s in enumerate(samples):
        sx, sy = _to_svg(s.point.x, s.point.y, bounds, scale)
        cmd = "M" if i == 0 else "L"
        parts.append(f"{cmd} {sx:.1f} {sy:.1f}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


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

    msp = doc.modelspace()
    if GENERATED_LAYER not in doc.layers:
        doc.layers.add(GENERATED_LAYER)
    circle_handles = []

    for item in kept_items:
        center = item["center"]
        circle = msp.add_circle(
            center=(center.x, center.y),
            radius=params.circle_radius,
            dxfattribs={"layer": GENERATED_LAYER},
        )
        circle_handles.append(circle.dxf.handle)

    for placement_index, placement in enumerate(placements):
        capsule = _capsule_for_placement(
            placement,
            params,
            kept_by_placement.get(placement_index, []),
        )
        if capsule:
            _add_capsule_entities(msp, capsule)

    return circle_handles, []
