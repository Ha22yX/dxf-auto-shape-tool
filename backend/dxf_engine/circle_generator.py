"""Generate circles and rays along normal directions from selected edge chain.

Two entry points:
- ``compute_placements`` / ``compute_preview_geometry``: pure geometry for the
  real-time overlay (no DXF mutation).
- ``generate_circles``: writes real entities into a DXF document (download only).
"""
from typing import List, Tuple
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


def compute_placements(doc, chain: List[str], params: CircleParams, closed: bool = False):
    """Pure-math placement of circles/rays along the chain (WCS coordinates).

    Returns a list of dicts: ``{point, ray_start, ray_end, centers}`` where
    ``centers`` is the list of circle centers in WCS. Empty list if nothing
    to generate.
    """
    if not chain or params.ray_count <= 0 or params.circles_per_ray <= 0:
        return []

    sample_closed = closed and params.dedupe_closed_rays
    samples = geom.sample_chain(doc, chain, params.ray_count, closed=sample_closed)
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
            "ray_start": ray_start,
            "ray_end": ray_end,
            "centers": centers,
        })
    if closed and params.dedupe_closed_rays:
        placements = _dedupe_placements_by_source(placements)
    return placements


def compute_preview_geometry(doc, chain: List[str], params: CircleParams,
                             closed: bool, bounds: dict, scale: float) -> dict:
    """Compute overlay geometry expressed in base-SVG output units.

    Does NOT modify any DXF document. ``bounds``/``scale`` come from
    ``svg_exporter.doc_to_base_svg`` and define the WCS -> SVG transform.
    """
    placements = compute_placements(doc, chain, params, closed=closed)

    circles = []
    rays = []
    for p in placements:
        for c in p["centers"]:
            cx, cy = _to_svg(c.x, c.y, bounds, scale)
            circles.append({
                "cx": cx,
                "cy": cy,
                "r": params.circle_radius * scale,
            })
        x1, y1 = _to_svg(p["point"].x, p["point"].y, bounds, scale)
        x2, y2 = _to_svg(p["ray_end"].x, p["ray_end"].y, bounds, scale)
        rays.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})

    chain_path = _chain_path_d(doc, chain, closed, bounds, scale)

    return {
        "circles": circles,
        "rays": rays,
        "selected_chain_path": chain_path,
        "generated_count": len(circles),
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


def generate_circles(doc: ezdxf.document.Drawing, chain: List[str], params: CircleParams, closed: bool = False) -> Tuple[List[str], List[str]]:
    """Write circle and ray entities into ``doc`` (used for the saved DXF).

    Returns (circle_handles, ray_handles).
    """
    placements = compute_placements(doc, chain, params, closed=closed)
    if not placements:
        return [], []

    msp = doc.modelspace()
    if GENERATED_LAYER not in doc.layers:
        doc.layers.add(GENERATED_LAYER)
    circle_handles = []

    for p in placements:
        for center in p["centers"]:
            circle = msp.add_circle(
                center=(center.x, center.y),
                radius=params.circle_radius,
                dxfattribs={"layer": GENERATED_LAYER},
            )
            circle_handles.append(circle.dxf.handle)

    return circle_handles, []
