"""Custom SVG exporter for DXF preview with handle mapping and selection highlight."""
import math
from typing import Optional, List, Tuple
import ezdxf
from ezdxf.math import Vec2, Vec3, Matrix44, bulge_to_arc

from backend.config import SVG_WIDTH, SVG_HEIGHT, SVG_MARGIN, SELECTED_HIGHLIGHT_COLOR, GENERATED_LAYER, RAY_LAYER
from backend.dxf_engine import geometry_utils as geom


def compute_bounds(doc: ezdxf.document.Drawing) -> dict:
    """Public wrapper to compute sampled bounding box of a DXF document."""
    return _compute_bounds(doc)


class SvgResult:
    def __init__(self, svg_string: str, transform: Matrix44, bounds: dict):
        self.svg_string = svg_string
        self.transform = transform
        self.bounds = bounds


def doc_to_svg(doc: ezdxf.document.Drawing,
               selected_chain: Optional[List[str]] = None,
               bounds: Optional[dict] = None,
               width: int = SVG_WIDTH,
               height: int = SVG_HEIGHT,
               margin: int = SVG_MARGIN) -> SvgResult:
    selected_chain = selected_chain or []
    selected_set = set(selected_chain)

    # Compute bounding box using sampled geometry for tight fit
    computed_bounds = _compute_bounds(doc)
    if bounds:
        # Use caller-provided bounds exactly; this keeps the original drawing stable
        # when generated circles are added outside the original viewBox.
        pass
    else:
        bounds = computed_bounds

    min_x, min_y = bounds["min"]
    max_x, max_y = bounds["max"]

    # Use content bounds as viewBox so the drawing fills the preview.
    # SVG y-axis points down, so flip WCS y.
    pad = max(max_x - min_x, max_y - min_y) * 0.05 + 1.0
    view_min_x = min_x - pad
    view_max_y = max_y + pad
    view_width = (max_x - min_x) + 2 * pad
    view_height = (max_y - min_y) + 2 * pad

    if view_width < 1e-6 or view_height < 1e-6:
        svg = _empty_svg(width, height)
        return SvgResult(svg, Matrix44.identity(), bounds)

    # Transform: WCS (x, y) -> SVG (x_svg, y_svg)
    # x_svg = x
    # y_svg = -y
    transform = Matrix44.scale(1, -1, 1)

    # Make grid cover a large area so panning/zooming doesn't reveal edges quickly.
    # With vector-effect='non-scaling-stroke', stroke-widths are in CSS pixels.
    grid_x = view_min_x - view_width * 4
    grid_y = -view_max_y - view_height * 4
    grid_w = view_width * 9
    grid_h = view_height * 9
    grid_cell_w = max(view_width / 20, 1.0)
    grid_cell_h = max(view_height / 20, 1.0)
    grid_stroke = 0.5

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="{view_min_x:.3f} {-view_max_y:.3f} {view_width:.3f} {view_height:.3f}" id="dxf-svg" data-transform="{transform}" preserveAspectRatio="xMidYMid meet" style="background:#1e1e1e;">',
        # Define grid pattern (size relative to view)
        '<defs>',
        f'<pattern id="grid" width="{grid_cell_w:.3f}" height="{grid_cell_h:.3f}" patternUnits="userSpaceOnUse">',
        f'<path d="M {grid_cell_w:.3f} 0 L 0 0 0 {grid_cell_h:.3f}" fill="none" stroke="#2a2a2a" stroke-width="{grid_stroke:.3f}" vector-effect="non-scaling-stroke"/>',
        '</pattern>',
        '</defs>',
        '<g id="dxf-content" stroke-linecap="round" stroke-linejoin="round">',
        f'<rect x="{grid_x:.3f}" y="{grid_y:.3f}" width="{grid_w:.3f}" height="{grid_h:.3f}" fill="url(#grid)" vector-effect="non-scaling-stroke" />',
    ]

    msp = doc.modelspace()
    for entity in msp:
        handle = entity.dxf.handle
        layer = entity.dxf.layer
        is_selected = handle in selected_set
        is_generated = layer == GENERATED_LAYER
        color = _entity_color(entity, is_selected, is_generated)
        stroke_width = _entity_stroke_width(entity, is_selected, is_generated)

        element = _render_entity(entity, transform, color, stroke_width, is_selected, is_generated)
        if element:
            svg_parts.append(element)

    svg_parts.append('</g>')
    svg_parts.append('</svg>')

    svg_string = "\n".join(svg_parts)
    return SvgResult(svg_string, transform, bounds)


def _empty_svg(width: int, height: int) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 {width} {height}" id="dxf-svg" style="background:#1e1e1e;"></svg>'


def _compute_bounds(doc: ezdxf.document.Drawing) -> dict:
    min_x, min_y = float("inf"), float("inf")
    max_x, max_y = float("-inf"), float("-inf")
    any_entity = False

    for entity in doc.modelspace():
        any_entity = True
        pts = _sample_entity(entity)
        if not pts:
            continue
        for p in pts:
            min_x = min(min_x, p.x)
            min_y = min(min_y, p.y)
            max_x = max(max_x, p.x)
            max_y = max(max_y, p.y)

    if not any_entity or not math.isfinite(min_x):
        return {"min": [0, 0], "max": [100, 100]}

    # Add small padding
    pad = max(max_x - min_x, max_y - min_y) * 0.05 + 1.0
    return {
        "min": [min_x - pad, min_y - pad],
        "max": [max_x + pad, max_y + pad],
    }


def _sample_entity(entity, segments: int = 32) -> List[Vec2]:
    """Sample entity into points for tight bounding box computation."""
    dtype = entity.dxftype()

    if dtype == "LINE":
        return [
            Vec2(entity.dxf.start.x, entity.dxf.start.y),
            Vec2(entity.dxf.end.x, entity.dxf.end.y),
        ]

    if dtype == "ARC":
        center = geom.vec2_from_vec3(entity.dxf.center)
        radius = entity.dxf.radius
        sa = math.radians(entity.dxf.start_angle)
        ea = math.radians(entity.dxf.end_angle)
        span = geom.normalize_angle(ea - sa)
        pts = []
        for i in range(segments + 1):
            t = i / segments
            angle = sa + span * t
            pts.append(geom.point_on_arc(center, radius, angle))
        return pts

    if dtype == "CIRCLE":
        center = geom.vec2_from_vec3(entity.dxf.center)
        radius = entity.dxf.radius
        pts = []
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            pts.append(geom.point_on_arc(center, radius, angle))
        return pts

    if dtype == "LWPOLYLINE":
        pts = list(entity.get_points(format="xyb"))
        if not pts:
            return []
        result = []
        n = len(pts)
        segment_count = n if entity.closed else n - 1
        for i in range(segment_count):
            j = (i + 1) % n
            x1, y1, b1 = pts[i][0], pts[i][1], pts[i][2]
            x2, y2 = pts[j][0], pts[j][1]
            p1 = Vec2(x1, y1)
            p2 = Vec2(x2, y2)
            result.append(p1)
            if abs(b1) > 1e-9:
                center, ccw_start, ccw_end, radius = bulge_to_arc(p1, p2, b1)
                included = geom.normalize_angle(ccw_end - ccw_start)
                sub_segments = max(4, int(segments * included / (2 * math.pi)))
                for k in range(1, sub_segments):
                    t = k / sub_segments
                    if b1 > 0:
                        angle = ccw_start + included * t
                    else:
                        angle = ccw_end - included * t
                    result.append(geom.point_on_arc(center, radius, angle))
        return result

    if dtype == "POLYLINE":
        result = []
        try:
            vertices = list(entity.vertices)
            n = len(vertices)
            if n < 2:
                return result
            pts = [
                (v.dxf.location.x, v.dxf.location.y, getattr(v.dxf, "bulge", 0.0))
                for v in vertices
            ]
            segment_count = n if entity.is_closed else n - 1
            for i in range(segment_count):
                j = (i + 1) % n
                x1, y1, b1 = pts[i]
                x2, y2 = pts[j]
                p1 = Vec2(x1, y1)
                p2 = Vec2(x2, y2)
                result.append(p1)
                if abs(b1) > 1e-9:
                    center, ccw_start, ccw_end, radius = bulge_to_arc(p1, p2, b1)
                    included = geom.normalize_angle(ccw_end - ccw_start)
                    sub_segments = max(4, int(segments * included / (2 * math.pi)))
                    for k in range(1, sub_segments):
                        t = k / sub_segments
                        if b1 > 0:
                            angle = ccw_start + included * t
                        else:
                            angle = ccw_end - included * t
                        result.append(geom.point_on_arc(center, radius, angle))
        except Exception:
            pass
        return result

    if dtype == "ELLIPSE":
        # Approximate ellipse with points
        center = geom.vec2_from_vec3(entity.dxf.center)
        major_axis = geom.vec2_from_vec3(entity.dxf.major_axis)
        ratio = entity.dxf.ratio
        start = entity.dxf.start_param
        end = entity.dxf.end_param
        pts = []
        for i in range(segments + 1):
            t = start + (end - start) * (i / segments)
            x = center.x + major_axis.x * math.cos(t) * ratio + (-major_axis.y) * math.sin(t)
            y = center.y + major_axis.y * math.cos(t) * ratio + major_axis.x * math.sin(t)
            pts.append(Vec2(x, y))
        return pts

    if dtype == "SPLINE":
        try:
            pts = list(entity.flattening(distance=1.0))
            return [Vec2(p.x, p.y) for p in pts]
        except Exception:
            return []

    return []


def _entity_color(entity, is_selected: bool, is_generated: bool) -> str:
    if is_selected:
        return SELECTED_HIGHLIGHT_COLOR
    if entity.dxf.layer == RAY_LAYER:
        return "#00BFFF"
    if is_generated:
        return "#FF6B6B"

    color = entity.dxf.color
    if color is not None and color != 256:  # 256 means bylayer
        return _aci_to_hex(color)

    return "#CCCCCC"


def _entity_stroke_width(entity, is_selected: bool, is_generated: bool) -> float:
    if is_selected:
        return 5.0
    if entity.dxf.layer == RAY_LAYER:
        return 1.5
    if is_generated:
        return 3.0
    return 3.0


def _aci_to_hex(index: int) -> str:
    palette = {
        1: "#FF0000", 2: "#FFFF00", 3: "#00FF00", 4: "#00FFFF",
        5: "#0000FF", 6: "#FF00FF", 7: "#FFFFFF", 8: "#808080",
        9: "#C0C0C0", 10: "#FF6666", 11: "#FF9999", 12: "#FFCCCC",
        30: "#66FF66", 50: "#6666FF", 90: "#FFCC66", 120: "#66FFFF",
        140: "#FF66FF", 200: "#CCFF66", 230: "#66CCFF", 250: "#CCCCCC",
    }
    return palette.get(index, "#CCCCCC")


def _render_entity(entity, transform: Matrix44, color: str, stroke_width: float, is_selected: bool, is_generated: bool) -> Optional[str]:
    dtype = entity.dxftype()
    handle = entity.dxf.handle
    attrs = (
        f'data-handle="{handle}" fill="none" stroke="{color}" stroke-width="{stroke_width}" '
        f'vector-effect="non-scaling-stroke"'
    )
    if is_generated:
        attrs += ' pointer-events="none"'
    else:
        attrs += ' pointer-events="stroke"'
    if is_selected:
        attrs += ' class="selected-entity"'

    if dtype == "LINE":
        p1 = _transform_point(Vec2(entity.dxf.start.x, entity.dxf.start.y), transform)
        p2 = _transform_point(Vec2(entity.dxf.end.x, entity.dxf.end.y), transform)
        return f'<line {attrs} x1="{p1.x:.3f}" y1="{p1.y:.3f}" x2="{p2.x:.3f}" y2="{p2.y:.3f}" />'

    if dtype == "ARC":
        center = geom.vec2_from_vec3(entity.dxf.center)
        radius = entity.dxf.radius
        sa = entity.dxf.start_angle
        ea = entity.dxf.end_angle
        path = _arc_to_svg_path(center, radius, sa, ea, transform)
        return f'<path {attrs} d="{path}" />'

    if dtype == "CIRCLE":
        center = geom.vec2_from_vec3(entity.dxf.center)
        radius = entity.dxf.radius
        c = _transform_point(center, transform)
        r = radius * _scale_from_transform(transform)
        return f'<circle {attrs} cx="{c.x:.3f}" cy="{c.y:.3f}" r="{r:.3f}" />'

    if dtype == "LWPOLYLINE":
        pts = list(entity.get_points(format="xyb"))
        if not pts:
            return None
        path = _lwpolyline_to_svg_path(pts, entity.closed, transform)
        return f'<path {attrs} d="{path}" />'

    if dtype == "POLYLINE":
        try:
            pts = [
                (v.dxf.location.x, v.dxf.location.y, getattr(v.dxf, "bulge", 0.0))
                for v in entity.vertices
            ]
            if len(pts) < 2:
                return None
            path = _polyline_to_svg_path(pts, entity.is_closed, transform)
            return f'<path {attrs} d="{path}" />'
        except Exception:
            return None

    if dtype == "ELLIPSE":
        path = _ellipse_to_svg_path(entity, transform)
        if path:
            return f'<path {attrs} d="{path}" />'
        return None

    if dtype == "SPLINE":
        try:
            flat_pts = list(entity.flattening(distance=1.0))
            if len(flat_pts) < 2:
                return None
            path = _points_to_svg_path([Vec2(p.x, p.y) for p in flat_pts], False, transform)
            return f'<path {attrs} d="{path}" />'
        except Exception:
            return None

    return None


def _transform_point(p: Vec2, transform: Matrix44) -> Vec2:
    result = transform.transform(Vec3(p.x, p.y, 0))
    return Vec2(result.x, result.y)


def _scale_from_transform(transform: Matrix44) -> float:
    origin = transform.transform(Vec3(0, 0, 0))
    unit_x = transform.transform(Vec3(1, 0, 0))
    return math.hypot(unit_x.x - origin.x, unit_x.y - origin.y)


def _arc_to_svg_path(center: Vec2, radius: float, start_angle_deg: float,
                     end_angle_deg: float, transform: Matrix44) -> str:
    sa = math.radians(start_angle_deg)
    ea = math.radians(end_angle_deg)
    span = geom.normalize_angle(ea - sa)

    start = geom.point_on_arc(center, radius, sa)
    end = geom.point_on_arc(center, radius, ea)
    large_arc = 1 if span > math.pi else 0
    sweep = 1

    s = _transform_point(start, transform)
    e = _transform_point(end, transform)
    r = radius * _scale_from_transform(transform)

    return f"M {s.x:.3f} {s.y:.3f} A {r:.3f} {r:.3f} 0 {large_arc} {sweep} {e.x:.3f} {e.y:.3f}"


def _lwpolyline_to_svg_path(pts: List[tuple], closed: bool, transform: Matrix44) -> str:
    if not pts:
        return ""

    wcs_pts = [Vec2(p[0], p[1]) for p in pts]
    bulges = [p[2] for p in pts]
    n = len(pts)
    segment_count = n if closed else n - 1

    commands = [f"M {_transform_point(wcs_pts[0], transform).x:.3f} {_transform_point(wcs_pts[0], transform).y:.3f}"]

    for i in range(segment_count):
        j = (i + 1) % n
        p1 = wcs_pts[i]
        p2 = wcs_pts[j]
        b1 = bulges[i]
        t2 = _transform_point(p2, transform)

        if abs(b1) < 1e-9:
            commands.append(f"L {t2.x:.3f} {t2.y:.3f}")
        else:
            center, sa, ea, radius = bulge_to_arc(p1, p2, b1)
            span = geom.normalize_angle(ea - sa)
            large_arc = 1 if span > math.pi else 0
            sweep = 0 if b1 < 0 else 1
            r = radius * _scale_from_transform(transform)
            commands.append(f"A {r:.3f} {r:.3f} 0 {large_arc} {sweep} {t2.x:.3f} {t2.y:.3f}")

    if closed:
        commands.append("Z")

    return " ".join(commands)


def _polyline_to_svg_path(pts: List[Tuple[float, float, float]], closed: bool, transform: Matrix44) -> str:
    if not pts:
        return ""

    wcs_pts = [Vec2(p[0], p[1]) for p in pts]
    bulges = [p[2] for p in pts]
    n = len(pts)
    segment_count = n if closed else n - 1

    commands = [f"M {_transform_point(wcs_pts[0], transform).x:.3f} {_transform_point(wcs_pts[0], transform).y:.3f}"]

    for i in range(segment_count):
        j = (i + 1) % n
        p1 = wcs_pts[i]
        p2 = wcs_pts[j]
        b1 = bulges[i]
        t2 = _transform_point(p2, transform)

        if abs(b1) < 1e-9:
            commands.append(f"L {t2.x:.3f} {t2.y:.3f}")
        else:
            center, sa, ea, radius = bulge_to_arc(p1, p2, b1)
            span = geom.normalize_angle(ea - sa)
            large_arc = 1 if span > math.pi else 0
            sweep = 0 if b1 < 0 else 1
            r = radius * _scale_from_transform(transform)
            commands.append(f"A {r:.3f} {r:.3f} 0 {large_arc} {sweep} {t2.x:.3f} {t2.y:.3f}")

    if closed:
        commands.append("Z")

    return " ".join(commands)


def _points_to_svg_path(pts: List[Vec2], closed: bool, transform: Matrix44) -> str:
    if not pts:
        return ""
    commands = [f"M {_transform_point(pts[0], transform).x:.3f} {_transform_point(pts[0], transform).y:.3f}"]
    for p in pts[1:]:
        t = _transform_point(p, transform)
        commands.append(f"L {t.x:.3f} {t.y:.3f}")
    if closed:
        commands.append("Z")
    return " ".join(commands)


def _ellipse_to_svg_path(entity, transform: Matrix44) -> Optional[str]:
    try:
        center = geom.vec2_from_vec3(entity.dxf.center)
        major_axis = geom.vec2_from_vec3(entity.dxf.major_axis)
        ratio = entity.dxf.ratio
        start = entity.dxf.start_param
        end = entity.dxf.end_param

        segments = 64
        commands = []
        for i in range(segments + 1):
            t = start + (end - start) * (i / segments)
            x = center.x + major_axis.x * math.cos(t) * ratio + (-major_axis.y) * math.sin(t)
            y = center.y + major_axis.y * math.cos(t) * ratio + major_axis.x * math.sin(t)
            pt = _transform_point(Vec2(x, y), transform)
            if i == 0:
                commands.append(f"M {pt.x:.3f} {pt.y:.3f}")
            else:
                commands.append(f"L {pt.x:.3f} {pt.y:.3f}")
        return " ".join(commands)
    except Exception:
        return None
