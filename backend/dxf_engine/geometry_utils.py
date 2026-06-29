"""2D geometry helpers for DXF edge processing."""
import math
from dataclasses import dataclass
from typing import Tuple, List, Callable, Optional
from ezdxf.math import Vec2, Vec3, bulge_to_arc


# ---------------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------------

def vec2_from_vec3(v: Vec3) -> Vec2:
    return Vec2(v.x, v.y)


def normalize(v: Vec2) -> Vec2:
    length = v.magnitude
    if length < 1e-12:
        return Vec2(0, 0)
    return v / length


def perpendicular(v: Vec2, clockwise: bool = False) -> Vec2:
    """Return a perpendicular vector. Default is 90 deg CCW (counter-clockwise)."""
    if clockwise:
        return Vec2(v.y, -v.x)
    return Vec2(-v.y, v.x)


def point_segment_distance(p: Vec2, a: Vec2, b: Vec2) -> Tuple[float, Vec2, float]:
    """
    Distance from point p to segment ab.
    Returns (distance, closest_point_on_segment, parameter_t).
    t in [0, 1] means projection falls within segment.
    """
    ab = b - a
    ab_len_sq = ab.magnitude ** 2
    if ab_len_sq < 1e-18:
        dist = (p - a).magnitude
        return dist, a, 0.0

    ap = p - a
    t = max(0.0, min(1.0, ap.dot(ab) / ab_len_sq))
    closest = a + ab * t
    dist = (p - closest).magnitude
    return dist, closest, t


def point_arc_distance(p: Vec2, center: Vec2, radius: float,
                       start_angle: float, end_angle: float) -> Tuple[float, Vec2, float]:
    """
    Distance from point p to an arc.
    start_angle/end_angle are in radians.
    Returns (distance, closest_point, parameter_t in [0,1]).
    """
    if radius <= 0:
        return float("inf"), center, 0.0

    cp = p - center
    angle = math.atan2(cp.y, cp.x)

    # Normalize angle to arc range
    span = normalize_angle(end_angle - start_angle)
    relative = normalize_angle(angle - start_angle)
    if relative > span:
        # Clamp to nearest endpoint
        d1 = (p - point_on_arc(center, radius, start_angle)).magnitude
        d2 = (p - point_on_arc(center, radius, end_angle)).magnitude
        if d1 <= d2:
            return d1, point_on_arc(center, radius, start_angle), 0.0
        return d2, point_on_arc(center, radius, end_angle), 1.0

    closest = center + normalize(cp) * radius
    t = relative / span if span != 0 else 0.0
    return (p - closest).magnitude, closest, t


def normalize_angle(angle: float) -> float:
    """Normalize angle to [0, 2*pi)."""
    two_pi = 2 * math.pi
    angle = angle % two_pi
    if angle < 0:
        angle += two_pi
    return angle


def point_on_arc(center: Vec2, radius: float, angle: float) -> Vec2:
    return Vec2(
        center.x + radius * math.cos(angle),
        center.y + radius * math.sin(angle),
    )


def _ellipse_point(center: Vec2, major_axis: Vec2, ratio: float, param: float) -> Vec2:
    """Parametric point on an ellipse at parameter `param`."""
    x = center.x + major_axis.x * math.cos(param) * ratio + (-major_axis.y) * math.sin(param)
    y = center.y + major_axis.y * math.cos(param) * ratio + major_axis.x * math.sin(param)
    return Vec2(x, y)


def tangent_on_arc(center: Vec2, point: Vec2, ccw: bool = True) -> Vec2:
    """Tangent direction at point on arc. CCW tangent is perpendicular to radius, rotated CCW."""
    radius_vec = point - center
    if not ccw:
        return normalize(Vec2(-radius_vec.y, radius_vec.x))
    return normalize(Vec2(radius_vec.y, -radius_vec.x))


def arc_length(radius: float, start_angle: float, end_angle: float) -> float:
    span = normalize_angle(end_angle - start_angle)
    return radius * span


def line_segment_length(a: Vec2, b: Vec2) -> float:
    return (b - a).magnitude


# ---------------------------------------------------------------------------
# DXF entity geometry extraction
# ---------------------------------------------------------------------------

def entity_endpoints(entity) -> Optional[Tuple[Vec2, Vec2]]:
    """Return (start, end) endpoints for edge-like entities."""
    dtype = entity.dxftype()

    if dtype == "LINE":
        return (
            vec2_from_vec3(entity.dxf.start),
            vec2_from_vec3(entity.dxf.end),
        )

    if dtype == "ARC":
        center = vec2_from_vec3(entity.dxf.center)
        radius = entity.dxf.radius
        sa = math.radians(entity.dxf.start_angle)
        ea = math.radians(entity.dxf.end_angle)
        return (
            point_on_arc(center, radius, sa),
            point_on_arc(center, radius, ea),
        )

    if dtype == "LWPOLYLINE":
        pts = list(entity.get_points(format="xyb"))
        if not pts:
            return None
        first = segment_point(entity, pts, 0, 0.0)
        last_idx = len(pts) - 1 if entity.closed else len(pts) - 2
        last_t = 1.0
        last = segment_point(entity, pts, last_idx, last_t)
        return (first, last)

    if dtype == "POLYLINE":
        try:
            vertices = list(entity.vertices)
            if len(vertices) < 2:
                return None
            pts = [
                (v.dxf.location.x, v.dxf.location.y, getattr(v.dxf, "bulge", 0.0))
                for v in vertices
            ]
            first = segment_point(entity, pts, 0, 0.0)
            last_idx = len(pts) - 1 if entity.is_closed else len(pts) - 2
            last = segment_point(entity, pts, last_idx, 1.0)
            return (first, last)
        except Exception:
            return None

    if dtype == "CIRCLE":
        # A full circle has no distinct endpoints and cannot connect to other
        # entities. It is handled as a standalone closed chain.
        return None

    if dtype == "ELLIPSE":
        try:
            center = vec2_from_vec3(entity.dxf.center)
            major_axis = vec2_from_vec3(entity.dxf.major_axis)
            ratio = entity.dxf.ratio
            start = entity.dxf.start_param
            end = entity.dxf.end_param
            p_start = _ellipse_point(center, major_axis, ratio, start)
            p_end = _ellipse_point(center, major_axis, ratio, end)
            return (p_start, p_end)
        except Exception:
            return None

    if dtype == "SPLINE":
        try:
            pts = list(entity.flattening(distance=1.0))
            if len(pts) < 2:
                return None
            return (Vec2(pts[0].x, pts[0].y), Vec2(pts[-1].x, pts[-1].y))
        except Exception:
            return None

    return None


def entity_length(entity) -> float:
    dtype = entity.dxftype()

    if dtype == "LINE":
        return line_segment_length(
            vec2_from_vec3(entity.dxf.start),
            vec2_from_vec3(entity.dxf.end),
        )

    if dtype == "ARC":
        return arc_length(
            entity.dxf.radius,
            math.radians(entity.dxf.start_angle),
            math.radians(entity.dxf.end_angle),
        )

    if dtype == "LWPOLYLINE":
        pts = list(entity.get_points(format="xyb"))
        total = 0.0
        n = len(pts)
        for i in range(n - 1):
            total += segment_length(pts[i], pts[i + 1])
        if entity.closed and n >= 2:
            total += segment_length(pts[-1], pts[0])
        return total

    if dtype == "POLYLINE":
        try:
            vertices = list(entity.vertices)
            if len(vertices) < 2:
                return 0.0
            pts = [
                (v.dxf.location.x, v.dxf.location.y, getattr(v.dxf, "bulge", 0.0))
                for v in vertices
            ]
            total = 0.0
            n = len(pts)
            for i in range(n - 1):
                total += segment_length(pts[i], pts[i + 1])
            if entity.is_closed and n >= 2:
                total += segment_length(pts[-1], pts[0])
            return total
        except Exception:
            return 0.0

    if dtype == "CIRCLE":
        return 2 * math.pi * entity.dxf.radius

    if dtype == "ELLIPSE":
        try:
            # Approximate length by flattening
            pts = list(entity.flattening(distance=1.0))
            total = 0.0
            for i in range(len(pts) - 1):
                total += line_segment_length(
                    Vec2(pts[i].x, pts[i].y),
                    Vec2(pts[i + 1].x, pts[i + 1].y),
                )
            return total
        except Exception:
            return 0.0

    if dtype == "SPLINE":
        try:
            pts = list(entity.flattening(distance=1.0))
            total = 0.0
            for i in range(len(pts) - 1):
                total += line_segment_length(
                    Vec2(pts[i].x, pts[i].y),
                    Vec2(pts[i + 1].x, pts[i + 1].y),
                )
            return total
        except Exception:
            return 0.0

    return 0.0


def segment_length(p1: Tuple[float, float, float], p2: Tuple[float, float, float]) -> float:
    """Length of a polyline segment, possibly bulged."""
    x1, y1, b1 = p1
    x2, y2, _ = p2
    chord = math.hypot(x2 - x1, y2 - y1)
    if abs(b1) < 1e-9:
        return chord
    # Arc length from bulge
    # included angle = 4 * atan(|bulge|)
    angle = 4 * math.atan(abs(b1))
    radius = chord / (2 * math.sin(angle / 2))
    return radius * angle


def segment_point(entity, pts: List[Tuple[float, float, float]],
                  segment_index: int, t: float) -> Vec2:
    """
    Point on polyline segment at parameter t in [0,1].
    segment_index refers to the start point index.
    """
    n = len(pts)
    i = segment_index % n
    j = (i + 1) % n
    x1, y1, b1 = pts[i]
    x2, y2, _ = pts[j]

    if abs(b1) < 1e-9:
        return Vec2(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)

    center, ccw_start, ccw_end, radius = bulge_to_arc(
        Vec2(x1, y1), Vec2(x2, y2), b1
    )
    included = normalize_angle(ccw_end - ccw_start)
    if b1 > 0:
        angle = ccw_start + included * t
    else:
        angle = ccw_end - included * t
    return point_on_arc(center, radius, angle)


def segment_tangent(entity, pts: List[Tuple[float, float, float]],
                    segment_index: int, t: float) -> Vec2:
    """Tangent direction on polyline segment at parameter t."""
    n = len(pts)
    i = segment_index % n
    j = (i + 1) % n
    x1, y1, b1 = pts[i]
    x2, y2, _ = pts[j]

    if abs(b1) < 1e-9:
        return normalize(Vec2(x2 - x1, y2 - y1))

    center, ccw_start, ccw_end, radius = bulge_to_arc(
        Vec2(x1, y1), Vec2(x2, y2), b1
    )
    included = normalize_angle(ccw_end - ccw_start)
    if b1 > 0:
        angle = ccw_start + included * t
    else:
        angle = ccw_end - included * t
    point = point_on_arc(center, radius, angle)
    return tangent_on_arc(center, point, ccw=(b1 > 0))


def segment_normal(entity, pts: List[Tuple[float, float, float]],
                   segment_index: int, t: float) -> Vec2:
    """Normal to the left of the segment tangent direction."""
    tangent = segment_tangent(entity, pts, segment_index, t)
    return perpendicular(tangent, clockwise=False)


# ---------------------------------------------------------------------------
# Distance from point to DXF entity
# ---------------------------------------------------------------------------

def point_entity_distance(p: Vec2, entity) -> Tuple[float, Optional[Vec2], Optional[float]]:
    dtype = entity.dxftype()

    if dtype == "LINE":
        dist, closest, t = point_segment_distance(
            p,
            vec2_from_vec3(entity.dxf.start),
            vec2_from_vec3(entity.dxf.end),
        )
        return dist, closest, t

    if dtype == "ARC":
        dist, closest, t = point_arc_distance(
            p,
            vec2_from_vec3(entity.dxf.center),
            entity.dxf.radius,
            math.radians(entity.dxf.start_angle),
            math.radians(entity.dxf.end_angle),
        )
        return dist, closest, t

    if dtype == "CIRCLE":
        dist, closest, t = point_arc_distance(
            p,
            vec2_from_vec3(entity.dxf.center),
            entity.dxf.radius,
            0.0,
            2 * math.pi,
        )
        return dist, closest, t

    if dtype == "LWPOLYLINE":
        pts = list(entity.get_points(format="xyb"))
        return _polyline_distance(p, pts, entity.closed)

    if dtype == "POLYLINE":
        try:
            pts = [(v.dxf.location.x, v.dxf.location.y, 0.0) for v in entity.vertices]
            return _polyline_distance(p, pts, entity.is_closed)
        except Exception:
            return float("inf"), None, None

    if dtype == "ELLIPSE":
        return _ellipse_distance(p, entity)

    if dtype == "SPLINE":
        return _spline_distance(p, entity)

    return float("inf"), None, None


def _polyline_distance(p: Vec2, pts: List[Tuple[float, float, float]], closed: bool) -> Tuple[float, Optional[Vec2], Optional[float]]:
    if not pts:
        return float("inf"), None, None

    best_dist = float("inf")
    best_closest = None
    best_t = None

    n = len(pts)
    segment_count = n if closed else n - 1
    for i in range(segment_count):
        j = (i + 1) % n
        x1, y1, b1 = pts[i]
        x2, y2, _ = pts[j]

        if abs(b1) < 1e-9:
            dist, closest, t = point_segment_distance(p, Vec2(x1, y1), Vec2(x2, y2))
        else:
            center, sa, ea, radius = bulge_to_arc(Vec2(x1, y1), Vec2(x2, y2), b1)
            # ezdxf bulge_to_arc always returns CCW oriented angles.
            dist, closest, t = point_arc_distance(p, center, radius, sa, ea)

        if dist < best_dist:
            best_dist = dist
            best_closest = closest
            best_t = (i, t)

    return best_dist, best_closest, best_t


def _ellipse_distance(p: Vec2, entity) -> Tuple[float, Optional[Vec2], Optional[float]]:
    try:
        center = vec2_from_vec3(entity.dxf.center)
        major_axis = vec2_from_vec3(entity.dxf.major_axis)
        ratio = entity.dxf.ratio
        start = entity.dxf.start_param
        end = entity.dxf.end_param

        best_dist = float("inf")
        best_closest = None
        segments = 64
        prev = None
        for i in range(segments + 1):
            t = start + (end - start) * (i / segments)
            x = center.x + major_axis.x * math.cos(t) * ratio + (-major_axis.y) * math.sin(t)
            y = center.y + major_axis.y * math.cos(t) * ratio + major_axis.x * math.sin(t)
            pt = Vec2(x, y)
            if prev is not None:
                dist, closest, _ = point_segment_distance(p, prev, pt)
                if dist < best_dist:
                    best_dist = dist
                    best_closest = closest
            prev = pt
        return best_dist, best_closest, 0.0
    except Exception:
        return float("inf"), None, None


def _spline_distance(p: Vec2, entity) -> Tuple[float, Optional[Vec2], Optional[float]]:
    try:
        pts = list(entity.flattening(distance=1.0))
        if len(pts) < 2:
            return float("inf"), None, None
        best_dist = float("inf")
        best_closest = None
        for i in range(len(pts) - 1):
            dist, closest, _ = point_segment_distance(p, Vec2(pts[i].x, pts[i].y), Vec2(pts[i + 1].x, pts[i + 1].y))
            if dist < best_dist:
                best_dist = dist
                best_closest = closest
        return best_dist, best_closest, 0.0
    except Exception:
        return float("inf"), None, None


# ---------------------------------------------------------------------------
# Sampling along a chain of entities
# ---------------------------------------------------------------------------

@dataclass
class SamplePoint:
    point: Vec2
    tangent: Vec2
    normal: Vec2
    handle: str
    segment_index: int = 0
    t: float = 0.0
    distance: float = 0.0


def _build_segments(doc, chain: List[str]) -> List["_Segment"]:
    segments = []
    for handle in chain:
        entity = doc.entitydb.get(handle)
        if entity is None:
            continue
        pts_data = _get_parametrization(entity)
        if pts_data:
            segments.extend(pts_data)
    return segments


def _cumulative_lengths(segments: List["_Segment"]) -> List[float]:
    cum_lengths = [0.0]
    for seg in segments:
        cum_lengths.append(cum_lengths[-1] + seg.length)
    return cum_lengths


def chain_length(doc, chain: List[str]) -> float:
    segments = _build_segments(doc, chain)
    if not segments:
        return 0.0
    return _cumulative_lengths(segments)[-1]


def nearest_sample_on_chain(doc, chain: List[str], point: Vec2,
                            sample_count: Optional[int] = None) -> Optional["SamplePoint"]:
    total = chain_length(doc, chain)
    if total <= 1e-9:
        return None
    if sample_count is None:
        sample_count = max(257, min(5001, int(total / 2.0)))
        if sample_count % 2 == 0:
            sample_count += 1
    samples = sample_chain(doc, chain, sample_count, closed=False)
    if not samples:
        return None
    return min(samples, key=lambda sample: (sample.point - point).magnitude)


def sample_chain(doc, chain: List[str], num_points: int, closed: bool = False,
                 smooth_tangents: bool = True) -> List[SamplePoint]:
    """
    Sample `num_points` points evenly along the chain by arc length.
    If `closed` is True, the final duplicated endpoint is skipped.
    Returns list of SamplePoint.
    """
    if num_points <= 0:
        return []

    segments = _build_segments(doc, chain)
    if not segments:
        return []

    cum_lengths = _cumulative_lengths(segments)
    total = cum_lengths[-1]
    if total < 1e-9:
        return []

    if closed:
        step = total / num_points
        distances = [k * step for k in range(num_points)]
    else:
        if num_points == 1:
            distances = [0.0]
        else:
            distances = [total * k / (num_points - 1) for k in range(num_points)]

    return sample_chain_at_distances(
        doc,
        chain,
        distances,
        smooth_tangents=smooth_tangents,
        total=total,
        segments=segments,
        cum_lengths=cum_lengths,
        smooth_window=_smooth_window(total, num_points),
    )


def sample_chain_at_distances(doc, chain: List[str], distances: List[float],
                              smooth_tangents: bool = True,
                              total: Optional[float] = None,
                              segments: Optional[List["_Segment"]] = None,
                              cum_lengths: Optional[List[float]] = None,
                              smooth_window: Optional[float] = None) -> List[SamplePoint]:
    if not distances:
        return []
    if segments is None:
        segments = _build_segments(doc, chain)
    if not segments:
        return []
    if cum_lengths is None:
        cum_lengths = _cumulative_lengths(segments)
    if total is None:
        total = cum_lengths[-1]
    if total < 1e-9:
        return []
    if smooth_window is None:
        smooth_window = _smooth_window(total, len(distances))
    return [
        _sample_at_distance(
            segments,
            cum_lengths,
            distance,
            total,
            smooth_window=smooth_window if smooth_tangents else 0.0,
        )
        for distance in distances
    ]


def _smooth_window(total: float, num_points: int) -> float:
    if num_points <= 1:
        return 0.0
    return max(0.0, min(total * 0.01, total / max(num_points * 2, 16)))


def _raw_sample_at_distance(segments: List["_Segment"], cum_lengths: List[float],
                            target: float, total: float) -> Tuple[Vec2, Vec2, Vec2, "_Segment", float]:
    """Helper to sample a point at a given distance along segments."""
    target = max(0.0, min(total, target))

    idx = 0
    for i in range(1, len(cum_lengths)):
        if cum_lengths[i] >= target:
            idx = i - 1
            break
    else:
        idx = len(segments) - 1

    seg = segments[idx]
    seg_start = cum_lengths[idx]
    seg_len = seg.length
    local_t = 0.0 if seg_len < 1e-9 else (target - seg_start) / seg_len
    local_t = max(0.0, min(1.0, local_t))

    point, tangent, normal = seg.evaluate(local_t)
    return point, tangent, normal, seg, local_t


def _sample_at_distance(segments: List["_Segment"], cum_lengths: List[float],
                        target: float, total: float, smooth_window: float = 0.0) -> SamplePoint:
    """Helper to sample a point at a given distance along segments."""
    target = max(0.0, min(total, target))
    point, tangent, normal, seg, local_t = _raw_sample_at_distance(
        segments, cum_lengths, target, total
    )

    if smooth_window > 1e-9 and seg.smoothable:
        start = max(0.0, target - smooth_window)
        end = min(total, target + smooth_window)
        if end - start > 1e-9:
            p_start, _, _, _, _ = _raw_sample_at_distance(segments, cum_lengths, start, total)
            p_end, _, _, _, _ = _raw_sample_at_distance(segments, cum_lengths, end, total)
            smoothed = normalize(p_end - p_start)
            if smoothed.magnitude > 1e-9:
                tangent = smoothed
                normal = perpendicular(tangent, clockwise=False)

    return SamplePoint(
        point=point,
        tangent=tangent,
        normal=normal,
        handle=seg.handle,
        segment_index=seg.segment_index,
        t=local_t,
        distance=target,
    )


@dataclass
class _Segment:
    handle: str
    segment_index: int
    length: float
    evaluate: Callable[[float], Tuple[Vec2, Vec2, Vec2]]
    smoothable: bool = True


def _get_parametrization(entity) -> List[_Segment]:
    dtype = entity.dxftype()
    result = []

    if dtype == "LINE":
        start = vec2_from_vec3(entity.dxf.start)
        end = vec2_from_vec3(entity.dxf.end)
        length = line_segment_length(start, end)

        def eval_line(t: float):
            p = start + (end - start) * t
            tangent = normalize(end - start)
            normal = perpendicular(tangent, clockwise=False)
            return p, tangent, normal

        result.append(_Segment(handle=entity.dxf.handle, segment_index=0, length=length, evaluate=eval_line))

    elif dtype == "ARC":
        center = vec2_from_vec3(entity.dxf.center)
        radius = entity.dxf.radius
        sa = math.radians(entity.dxf.start_angle)
        ea = math.radians(entity.dxf.end_angle)
        length = arc_length(radius, sa, ea)
        span = normalize_angle(ea - sa)

        def eval_arc(t: float):
            angle = sa + span * t
            p = point_on_arc(center, radius, angle)
            # DXF ARC is always CCW from start_angle to end_angle.
            tangent = tangent_on_arc(center, p, ccw=True)
            normal = perpendicular(tangent, clockwise=False)
            return p, tangent, normal

        result.append(_Segment(
            handle=entity.dxf.handle,
            segment_index=0,
            length=length,
            evaluate=eval_arc,
            smoothable=False,
        ))

    elif dtype == "LWPOLYLINE":
        pts = list(entity.get_points(format="xyb"))
        n = len(pts)
        segment_count = n if entity.closed else n - 1
        for i in range(segment_count):
            j = (i + 1) % n
            x1, y1, b1 = pts[i]
            x2, y2, _ = pts[j]
            length = segment_length(pts[i], pts[j])

            def make_eval(idx: int, x1=x1, y1=y1, x2=x2, y2=y2, b1=b1, pts=pts):
                if abs(b1) < 1e-9:
                    def eval_seg(t: float):
                        p = Vec2(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
                        tangent = normalize(Vec2(x2 - x1, y2 - y1))
                        normal = perpendicular(tangent, clockwise=False)
                        return p, tangent, normal
                else:
                    center, ccw_start, ccw_end, radius = bulge_to_arc(
                        Vec2(x1, y1), Vec2(x2, y2), b1
                    )
                    included = normalize_angle(ccw_end - ccw_start)

                    # ezdxf returns the CCW arc. For positive bulge the arc runs
                    # CCW from p1 to p2; for negative bulge it runs CW from p1 to p2.
                    if b1 > 0:
                        start_angle = ccw_start
                        def eval_seg(t: float):
                            angle = start_angle + included * t
                            p = point_on_arc(center, radius, angle)
                            tangent = tangent_on_arc(center, p, ccw=True)
                            normal = perpendicular(tangent, clockwise=False)
                            return p, tangent, normal
                    else:
                        start_angle = ccw_end  # angle of p1 in the returned CCW arc
                        def eval_seg(t: float):
                            angle = start_angle - included * t
                            p = point_on_arc(center, radius, angle)
                            tangent = tangent_on_arc(center, p, ccw=False)
                            normal = perpendicular(tangent, clockwise=False)
                            return p, tangent, normal
                return eval_seg

            result.append(_Segment(
                handle=entity.dxf.handle,
                segment_index=i,
                length=length,
                evaluate=make_eval(i),
                smoothable=abs(b1) < 1e-9,
            ))

    elif dtype == "POLYLINE":
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
                x2, y2, _ = pts[j]
                length = segment_length(pts[i], pts[j])

                def make_eval_poly(idx: int, x1=x1, y1=y1, x2=x2, y2=y2, b1=b1, pts=pts):
                    if abs(b1) < 1e-9:
                        def eval_seg(t: float):
                            p = Vec2(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
                            tangent = normalize(Vec2(x2 - x1, y2 - y1))
                            normal = perpendicular(tangent, clockwise=False)
                            return p, tangent, normal
                    else:
                        center, ccw_start, ccw_end, radius = bulge_to_arc(
                            Vec2(x1, y1), Vec2(x2, y2), b1
                        )
                        included = normalize_angle(ccw_end - ccw_start)

                        if b1 > 0:
                            start_angle = ccw_start
                            def eval_seg(t: float):
                                angle = start_angle + included * t
                                p = point_on_arc(center, radius, angle)
                                tangent = tangent_on_arc(center, p, ccw=True)
                                normal = perpendicular(tangent, clockwise=False)
                                return p, tangent, normal
                        else:
                            start_angle = ccw_end
                            def eval_seg(t: float):
                                angle = start_angle - included * t
                                p = point_on_arc(center, radius, angle)
                                tangent = tangent_on_arc(center, p, ccw=False)
                                normal = perpendicular(tangent, clockwise=False)
                                return p, tangent, normal
                    return eval_seg

                result.append(_Segment(
                    handle=entity.dxf.handle,
                    segment_index=i,
                    length=length,
                    evaluate=make_eval_poly(i),
                    smoothable=abs(b1) < 1e-9,
                ))
        except Exception:
            pass

    elif dtype == "CIRCLE":
        center = vec2_from_vec3(entity.dxf.center)
        radius = entity.dxf.radius
        length = 2 * math.pi * radius

        def eval_circle(t: float):
            angle = 2 * math.pi * t
            p = point_on_arc(center, radius, angle)
            tangent = tangent_on_arc(center, p, ccw=True)
            normal = perpendicular(tangent, clockwise=False)
            return p, tangent, normal

        result.append(_Segment(
            handle=entity.dxf.handle,
            segment_index=0,
            length=length,
            evaluate=eval_circle,
            smoothable=False,
        ))

    elif dtype == "ELLIPSE":
        try:
            flat_pts = list(entity.flattening(distance=1.0))
            if len(flat_pts) < 2:
                return result
            wcs_pts = [Vec2(p.x, p.y) for p in flat_pts]

            for i in range(len(wcs_pts) - 1):
                a = wcs_pts[i]
                b = wcs_pts[i + 1]
                length = line_segment_length(a, b)

                def make_eval_ellipse(idx: int, a=a, b=b):
                    def eval_seg(t: float):
                        p = a + (b - a) * t
                        tangent = normalize(b - a)
                        normal = perpendicular(tangent, clockwise=False)
                        return p, tangent, normal
                    return eval_seg

                result.append(_Segment(
                    handle=entity.dxf.handle,
                    segment_index=i,
                    length=length,
                    evaluate=make_eval_ellipse(i),
                ))
        except Exception:
            pass

    elif dtype == "SPLINE":
        try:
            flat_pts = list(entity.flattening(distance=1.0))
            if len(flat_pts) < 2:
                return result
            wcs_pts = [Vec2(p.x, p.y) for p in flat_pts]

            for i in range(len(wcs_pts) - 1):
                a = wcs_pts[i]
                b = wcs_pts[i + 1]
                length = line_segment_length(a, b)

                def make_eval_spline(idx: int, a=a, b=b):
                    def eval_seg(t: float):
                        p = a + (b - a) * t
                        tangent = normalize(b - a)
                        normal = perpendicular(tangent, clockwise=False)
                        return p, tangent, normal
                    return eval_seg

                result.append(_Segment(
                    handle=entity.dxf.handle,
                    segment_index=i,
                    length=length,
                    evaluate=make_eval_spline(i),
                ))
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Polygon / chain orientation
# ---------------------------------------------------------------------------

def polygon_signed_area(points: List[Vec2]) -> float:
    """Shoelace formula. Positive = CCW, negative = CW."""
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i].x, points[i].y
        x2, y2 = points[(i + 1) % n].x, points[(i + 1) % n].y
        area += x1 * y2 - x2 * y1
    return area / 2.0


def chain_centroid(samples: List[SamplePoint]) -> Vec2:
    if not samples:
        return Vec2(0, 0)
    total = Vec2(0, 0)
    for s in samples:
        total += s.point
    return total / len(samples)


def orient_normals_to_center(samples: List[SamplePoint]) -> List[Vec2]:
    """
    Flip normals uniformly so they point toward the chain centroid.

    Unlike a per-point flip, this keeps all normals on the same side of the
    chain, which is required for a consistent ray direction along arcs and
    open polylines.
    """
    if not samples:
        return []

    center = chain_centroid(samples)
    avg_dot = sum(s.normal.dot(center - s.point) for s in samples) / len(samples)

    if avg_dot < 0:
        return [-s.normal for s in samples]
    return [s.normal for s in samples]


def orient_normals_for_closed_chain(samples: List[SamplePoint], inward: bool = True) -> List[Vec2]:
    """
    Orient normals for a closed chain based on its signed area.

    All raw normals are assumed to be the left-of-tangent normal. For a
    counter-clockwise chain (positive signed area) the left normal points
    outward; for a clockwise chain it points inward. This function flips the
    whole set uniformly so they all point inward or outward as requested.

    Returns a new list of normals.
    """
    if not samples:
        return []

    points = [s.point for s in samples]
    signed_area = polygon_signed_area(points)

    # For a CCW chain, left normals point outward.
    left_normal_is_outward = signed_area >= 0
    want_outward = not inward

    flip = (left_normal_is_outward and not want_outward) or (not left_normal_is_outward and want_outward)

    if flip:
        return [-s.normal for s in samples]
    return [s.normal for s in samples]
