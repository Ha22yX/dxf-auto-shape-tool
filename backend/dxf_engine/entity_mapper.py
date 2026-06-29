"""Map SVG click coordinates back to DXF entity handles."""
import math
from typing import Optional
from ezdxf.math import Vec2

from backend.state import SessionState
from backend.dxf_engine import geometry_utils as geom
from backend.dxf_engine import svg_exporter

EDGE_TYPES = ("LINE", "ARC", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ELLIPSE", "SPLINE")


def entity_to_svg_path(state: SessionState, handle: str) -> str:
    """Build an SVG path 'd' string for a single entity in base-SVG output units.

    Used for hover highlighting so the frontend can render an overlay path
    that exactly matches the entity in the base SVG.
    """
    entity = state.working_doc.entitydb.get(handle)
    if entity is None:
        return ""

    dtype = entity.dxftype()
    length = geom.entity_length(entity)
    num = max(16, min(500, int(length / 1.0))) if length > 0 else 32

    closed = False
    if dtype == "CIRCLE":
        closed = True
    elif dtype == "LWPOLYLINE" and entity.closed:
        closed = True
    elif dtype == "POLYLINE" and entity.is_closed:
        closed = True

    samples = geom.sample_chain(state.working_doc, [handle], num, closed=closed)
    if not samples:
        return ""

    parts = []
    for i, s in enumerate(samples):
        sx, sy = svg_exporter.wcs_to_svg(
            s.point.x, s.point.y, state.svg_bounds, state.svg_scale
        )
        cmd = "M" if i == 0 else "L"
        parts.append(f"{cmd} {sx:.1f} {sy:.1f}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


def find_nearest_entity(state: SessionState, svg_x: float, svg_y: float,
                        tol: Optional[float] = None) -> Optional[str]:
    """Find the nearest edge entity to a click given in base-SVG output units.

    ``tol`` is an optional pick tolerance already expressed in WCS units
    (e.g. a fixed pixel aperture converted by the frontend). When omitted a
    fraction-of-drawing fallback is used. A cached bounding-box prefilter keeps
    this fast on large drawings (avoids flattening every spline per click).
    """
    wcs_x, wcs_y = svg_exporter.svg_to_wcs(
        svg_x, svg_y, state.svg_bounds, state.svg_scale
    )
    wcs_point = Vec2(wcs_x, wcs_y)

    bounds = state.svg_bounds
    size = max(
        bounds["max"][0] - bounds["min"][0],
        bounds["max"][1] - bounds["min"][1],
        1.0,
    )
    fallback_tol = max(size * 0.005, 1e-3)
    # Older front-end builds sent an inverted pixel-to-WCS value that was almost
    # zero. Treat only impossible/absurdly tiny tolerances as missing; otherwise
    # trust the screen-pixel aperture from the viewer.
    if tol is None or tol <= 0 or tol < max(size * 1e-7, 1e-9):
        tol = fallback_tol
    tolerance = max(tol, 1e-9)

    bbox_cache = _get_bbox_cache(state)

    best_handle = None
    best_distance = float("inf")

    for entity in state.working_doc.modelspace():
        dtype = entity.dxftype()
        if dtype not in EDGE_TYPES:
            continue

        # Bounding-box prefilter: skip entities that cannot be within tolerance.
        bb = _cached_bbox(entity, bbox_cache)
        if bb is not None:
            (mnx, mny, mxx, mxy) = bb
            if (wcs_x < mnx - tolerance or wcs_x > mxx + tolerance or
                    wcs_y < mny - tolerance or wcs_y > mxy + tolerance):
                continue

        dist, _, _ = geom.point_entity_distance(wcs_point, entity)
        if dist < tolerance and dist < best_distance:
            best_distance = dist
            best_handle = entity.dxf.handle

    return best_handle


def _get_bbox_cache(state: SessionState) -> dict:
    cache = getattr(state, "_entity_bbox_cache", None)
    if cache is None:
        cache = {}
        setattr(state, "_entity_bbox_cache", cache)
    return cache


def _cached_bbox(entity, cache: dict):
    key = entity.dxf.handle
    if key in cache:
        return cache[key]
    value = _entity_bbox(entity)
    cache[key] = value
    return value


def _entity_bbox(entity):
    """Return (min_x, min_y, max_x, max_y) or None if it cannot be computed."""
    try:
        bb = entity.bbox()
        if not bb.has_data or not math.isfinite(bb.extmin.x):
            return None
        return (bb.extmin.x, bb.extmin.y, bb.extmax.x, bb.extmax.y)
    except Exception:
        return None
