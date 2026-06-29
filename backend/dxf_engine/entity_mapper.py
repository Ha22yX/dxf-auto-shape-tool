"""Map SVG click coordinates back to DXF entity handles."""
import math
from typing import Optional
from ezdxf.math import Vec2, Vec3, Matrix44

from backend.state import SessionState
from backend.config import CLICK_TOLERANCE_PIXELS
from backend.dxf_engine import geometry_utils as geom
from backend.dxf_engine import svg_exporter


def find_nearest_entity(state: SessionState, svg_x: float, svg_y: float) -> Optional[str]:
    """
    Find the nearest edge entity to a click given in base-SVG output units.
    Returns entity handle or None.
    """
    wcs_x, wcs_y = svg_exporter.svg_to_wcs(
        svg_x, svg_y, state.svg_bounds, state.svg_scale
    )
    wcs_point = Vec2(wcs_x, wcs_y)

    # Adaptive tolerance in WCS units, derived from the drawing size.
    bounds = state.svg_bounds
    size = max(
        bounds["max"][0] - bounds["min"][0],
        bounds["max"][1] - bounds["min"][1],
        1.0,
    )
    tolerance = max(size * 0.005, 1e-3)

    best_handle = None
    best_distance = float("inf")

    for entity in state.working_doc.modelspace():
        dtype = entity.dxftype()
        if dtype not in ("LINE", "ARC", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ELLIPSE", "SPLINE"):
            continue

        dist, _, _ = geom.point_entity_distance(wcs_point, entity)
        if dist < tolerance and dist < best_distance:
            best_distance = dist
            best_handle = entity.dxf.handle

    return best_handle


def _doc_bounds(doc) -> tuple:
    min_x, min_y = float("inf"), float("inf")
    max_x, max_y = float("-inf"), float("-inf")
    for entity in doc.modelspace():
        pts = _entity_points(entity)
        for p in pts:
            min_x = min(min_x, p.x)
            min_y = min(min_y, p.y)
            max_x = max(max_x, p.x)
            max_y = max(max_y, p.y)
    if not math.isfinite(min_x):
        return (0, 0, 100, 100)
    return (min_x, min_y, max_x, max_y)


def _entity_points(entity) -> list:
    dtype = entity.dxftype()
    if dtype == "LINE":
        return [Vec2(entity.dxf.start.x, entity.dxf.start.y), Vec2(entity.dxf.end.x, entity.dxf.end.y)]
    if dtype in ("ARC", "CIRCLE"):
        center = geom.vec2_from_vec3(entity.dxf.center)
        r = entity.dxf.radius
        pts = []
        for i in range(8):
            a = 2 * math.pi * i / 8
            pts.append(Vec2(center.x + r * math.cos(a), center.y + r * math.sin(a)))
        return pts
    if dtype == "LWPOLYLINE":
        pts = list(entity.get_points(format="xy"))
        return [Vec2(p[0], p[1]) for p in pts]
    if dtype == "POLYLINE":
        try:
            return [Vec2(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        except Exception:
            return []
    if dtype == "ELLIPSE":
        try:
            center = geom.vec2_from_vec3(entity.dxf.center)
            major_axis = geom.vec2_from_vec3(entity.dxf.major_axis)
            ratio = entity.dxf.ratio
            start = entity.dxf.start_param
            end = entity.dxf.end_param
            pts = []
            for i in range(8):
                t = start + (end - start) * (i / 7)
                x = center.x + major_axis.x * math.cos(t) * ratio + (-major_axis.y) * math.sin(t)
                y = center.y + major_axis.y * math.cos(t) * ratio + major_axis.x * math.sin(t)
                pts.append(Vec2(x, y))
            return pts
        except Exception:
            return []
    if dtype == "SPLINE":
        try:
            pts = list(entity.flattening(distance=1.0))
            return [Vec2(p.x, p.y) for p in pts]
        except Exception:
            return []
    return []


def _uniform_scale(transform: Matrix44) -> float:
    origin = transform.transform(Vec3(0, 0, 0))
    unit_x = transform.transform(Vec3(1, 0, 0))
    return math.hypot(unit_x.x - origin.x, unit_x.y - origin.y)
