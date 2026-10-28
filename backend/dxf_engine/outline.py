"""Validate the selected contour and enforce whole-hole / whole-slot containment.

Native DXF curves are flattened independently of preview sampling.  The curve
error is added to the clearance test, so a sampled chord cannot admit a hole
across a curved boundary. Open contours are first completed by contour_repair with explicit DXF edges.
This validator then checks that the resulting region is simple and planar.
"""
from dataclasses import dataclass
import math
from typing import Optional
from ezdxf.math import Vec2
from shapely.geometry import LineString, Point, Polygon
from shapely.prepared import prep
from backend.config import POINT_TOLERANCE, CURVE_TOLERANCE


@dataclass
class Outline:
    status: str
    polygon: Optional[Polygon] = None
    curve_error: float = 0.0

    def __post_init__(self):
        self.prepared = prep(self.polygon) if self.polygon is not None else None
        self.ray_region = (
            prep(self.polygon.buffer(2 * self.curve_error + POINT_TOLERANCE))
            if self.polygon is not None else None
        )

    @property
    def ready(self):
        return self.status == "ready"

    def allows_circle(self, center, radius, inward=True, source=None):
        if not self.ready or radius <= 0 or not all(math.isfinite(v) for v in (center.x, center.y, radius)):
            return False
        point = Point(center.x, center.y)
        inside = self.prepared.contains(point)
        if inside != inward:
            return False
        if self.polygon.boundary.distance(point) < radius + self.curve_error + POINT_TOLERANCE:
            return False
        # A normal can cross a concave notch and re-enter the board. A valid
        # endpoint alone must not allow that row to jump across empty space.
        if inward and source is not None:
            ray = LineString([(source.x, source.y), (center.x, center.y)])
            if not self.ray_region.covers(ray):
                return False
        return True

    def allows_capsule(self, capsule, inward=True):
        if not self.ready:
            return False
        near, far = capsule["near"], capsule["far"]
        line = LineString([(near.x, near.y), (far.x, far.y)])
        clearance = capsule["radius"] + self.curve_error + POINT_TOLERANCE
        if inward:
            return self.prepared.covers(line) and self.polygon.boundary.distance(line) >= clearance
        return self.polygon.distance(line) >= clearance


def _entity_points(entity):
    dtype = entity.dxftype()
    if dtype == "LINE":
        return [entity.dxf.start, entity.dxf.end], False
    if dtype in ("ARC", "CIRCLE"):
        return list(entity.flattening(CURVE_TOLERANCE)), True
    if dtype in ("SPLINE", "ELLIPSE"):
        return list(entity.flattening(distance=CURVE_TOLERANCE, segments=8)), True
    if dtype in ("LWPOLYLINE", "POLYLINE"):
        points, curved = [], False
        for piece in entity.virtual_entities():
            part, is_curve = _entity_points(piece)
            if points and (Vec2(points[-1]) - Vec2(part[0])).magnitude > POINT_TOLERANCE:
                raise ValueError("disconnected polyline")
            points.extend(part[1:] if points else part)
            curved = curved or is_curve
        return points, curved
    raise ValueError("unsupported boundary entity")


def analyze_outline(doc, chain):
    if not chain:
        return Outline("empty")
    groups, z_values, curved = [], [], False
    try:
        for handle in chain:
            entity = doc.entitydb.get(handle)
            if entity is None:
                return Outline("invalid")
            vertices, is_curve = _entity_points(entity)
            if len(vertices) < 2:
                return Outline("invalid")
            if not all(math.isfinite(v) for point in vertices for v in point):
                return Outline("invalid")
            z_values.extend(getattr(point, "z", 0.0) for point in vertices)
            groups.append([Vec2(point) for point in vertices])
            curved = curved or is_curve
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        return Outline("invalid")
    if max(z_values) - min(z_values) > POINT_TOLERANCE:
        return Outline("nonplanar")

    if len(groups) > 1:
        first, second = groups[:2]
        if min((first[0] - second[0]).magnitude, (first[0] - second[-1]).magnitude) + POINT_TOLERANCE < min((first[-1] - second[0]).magnitude, (first[-1] - second[-1]).magnitude):
            groups[0] = list(reversed(first))
    points = list(groups[0])
    for group in groups[1:]:
        if (points[-1] - group[-1]).magnitude < (points[-1] - group[0]).magnitude:
            group = list(reversed(group))
        if (points[-1] - group[0]).magnitude > POINT_TOLERANCE:
            return Outline("open")
        points.extend(group[1:])
    if (points[-1] - points[0]).magnitude > POINT_TOLERANCE:
        return Outline("open")
    points[-1] = points[0]
    if len(points) < 4:
        return Outline("invalid")
    polygon = Polygon([(point.x, point.y) for point in points])
    if polygon.is_empty or not polygon.is_valid or polygon.area <= POINT_TOLERANCE ** 2:
        return Outline("invalid")
    return Outline("ready", polygon, CURVE_TOLERANCE if curved else 0.0)
