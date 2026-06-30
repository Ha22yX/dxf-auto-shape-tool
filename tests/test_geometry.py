import math
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
from ezdxf.math import Vec2
from backend.dxf_engine import geometry_utils as geom


def test_point_segment_distance():
    p = Vec2(1, 1)
    a = Vec2(0, 0)
    b = Vec2(2, 0)
    dist, closest, t = geom.point_segment_distance(p, a, b)
    assert dist == pytest.approx(1.0)
    assert closest.isclose(Vec2(1, 0))
    assert t == pytest.approx(0.5)


def test_bulge_to_arc():
    from ezdxf.math import bulge_to_arc

    # Positive bulge: CCW arc from start to end.
    start = Vec2(0, 0)
    end = Vec2(2, 0)
    center, sa, ea, radius = bulge_to_arc(start, end, 0.5)
    assert radius > 0
    # Arc should bulge to the left (above) of start->end.
    assert center.y > 0

    # Negative bulge: CW arc from start to end.
    center, sa, ea, radius = bulge_to_arc(start, end, -0.5)
    assert radius > 0
    # Arc should bulge to the right (below) of start->end.
    assert center.y < 0
    # ezdxf returns the CCW arc, so for negative bulge the angles are swapped
    # and the arc runs CCW from end back to start.
    assert geom.normalize_angle(ea - sa) > 0


def test_arc_length():
    assert geom.arc_length(10, 0, math.pi) == pytest.approx(10 * math.pi)


def test_sample_chain_rectangle():
    import ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0))
    msp.add_line((100, 0), (100, 80))
    msp.add_line((100, 80), (0, 80))
    msp.add_line((0, 80), (0, 0))

    handles = [e.dxf.handle for e in msp]
    samples = geom.sample_chain(doc, handles, 5)
    assert len(samples) == 5
    assert samples[0].point.isclose(Vec2(0, 0))
    assert samples[-1].point.isclose(Vec2(0, 0))  # closed loop


def test_orient_normals_to_center():
    samples = [
        geom.SamplePoint(Vec2(0, 10), Vec2(0, 1), Vec2(0, 1), "A"),
        geom.SamplePoint(Vec2(10, 0), Vec2(1, 0), Vec2(1, 0), "B"),
        geom.SamplePoint(Vec2(0, -10), Vec2(0, -1), Vec2(0, -1), "C"),
        geom.SamplePoint(Vec2(-10, 0), Vec2(-1, 0), Vec2(-1, 0), "D"),
    ]
    oriented = geom.orient_normals_to_center(samples)
    assert oriented[0].isclose(Vec2(0, -1))
    assert oriented[1].isclose(Vec2(-1, 0))
    assert oriented[2].isclose(Vec2(0, 1))
    assert oriented[3].isclose(Vec2(1, 0))


def test_orient_normals_for_closed_chain():
    # CCW square with inward raw (left-of-tangent) normals.
    samples = [
        geom.SamplePoint(Vec2(0, 0), Vec2(0, 1), Vec2(0, 1), "A"),
        geom.SamplePoint(Vec2(10, 0), Vec2(-1, 0), Vec2(-1, 0), "B"),
        geom.SamplePoint(Vec2(10, 10), Vec2(0, -1), Vec2(0, -1), "C"),
        geom.SamplePoint(Vec2(0, 10), Vec2(1, 0), Vec2(1, 0), "D"),
    ]
    inward = geom.orient_normals_for_closed_chain(samples, inward=True)
    assert inward[0].isclose(Vec2(0, 1))
    assert inward[1].isclose(Vec2(-1, 0))
    assert inward[2].isclose(Vec2(0, -1))
    assert inward[3].isclose(Vec2(1, 0))

    outward = geom.orient_normals_for_closed_chain(samples, inward=False)
    assert outward[0].isclose(Vec2(0, -1))
    assert outward[1].isclose(Vec2(1, 0))
    assert outward[2].isclose(Vec2(0, 1))
    assert outward[3].isclose(Vec2(-1, 0))


def test_closed_chain_normals_use_polygon_inside_test_for_concave_outline():
    boundary_points = [
        Vec2(0, 0),
        Vec2(10, 0),
        Vec2(10, 10),
        Vec2(6, 10),
        Vec2(6, 4),
        Vec2(4, 4),
        Vec2(4, 10),
        Vec2(0, 10),
    ]
    boundary_samples = [
        geom.SamplePoint(point, Vec2(0, 0), Vec2(0, 0), "B")
        for point in boundary_points
    ]
    # This point is on the left inner notch edge. The geometric centroid
    # fallback is not enough for all concave cases, so the inside probe must
    # choose the solid side instead of assuming a global radial direction.
    samples = [
        geom.SamplePoint(Vec2(4, 6), Vec2(0, 1), Vec2(-1, 0), "A"),
    ]

    inward = geom.orient_normals_for_closed_chain(
        samples,
        inward=True,
        boundary_samples=boundary_samples,
    )
    outward = geom.orient_normals_for_closed_chain(
        samples,
        inward=False,
        boundary_samples=boundary_samples,
    )

    assert inward[0].isclose(Vec2(-1, 0))
    assert outward[0].isclose(Vec2(1, 0))


def test_sample_chain_with_arc():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # Quarter circle arc from (10,0) to (0,10), center (0,0).
    msp.add_arc((0, 0), radius=10, start_angle=0, end_angle=90)

    handles = [e.dxf.handle for e in msp]
    samples = geom.sample_chain(doc, handles, 3)
    assert len(samples) == 3
    # First point at start of arc.
    assert samples[0].point.isclose(Vec2(10, 0))
    # Last point at end of arc.
    assert samples[-1].point.isclose(Vec2(0, 10))
    # Middle point should be on the arc (roughly (7.07, 7.07)).
    mid = samples[1].point
    assert abs(mid.magnitude - 10) < 1e-6


def test_sample_chain_with_lwpolyline_bulge():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # Segment (0,0) -> (2,0) with positive bulge: arc below the chord.
    poly = msp.add_lwpolyline([(0, 0), (2, 0)], close=False)
    poly.set_points([(0, 0, 0, 0, 0.5), (2, 0, 0, 0, 0)])

    handles = [e.dxf.handle for e in msp]
    samples = geom.sample_chain(doc, handles, 3)
    assert len(samples) == 3
    assert samples[0].point.isclose(Vec2(0, 0))
    assert samples[-1].point.isclose(Vec2(2, 0))
    # Middle point should be below the chord for positive bulge on this segment.
    assert samples[1].point.y < 0


def test_sample_chain_with_circle():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_circle((0, 0), radius=10)

    handles = [e.dxf.handle for e in msp]
    samples = geom.sample_chain(doc, handles, 4, closed=True)
    assert len(samples) == 4
    for s in samples:
        assert abs(s.point.magnitude - 10) < 1e-6


def test_sample_chain_with_ellipse():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # Full ellipse centered at origin.
    msp.add_ellipse((0, 0), major_axis=(10, 0), ratio=0.5)

    handles = [e.dxf.handle for e in msp]
    samples = geom.sample_chain(doc, handles, 4)
    assert len(samples) == 4


def test_sample_chain_with_spline():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # Simple spline from (0,0) to (10,0).
    s = msp.add_spline()
    s.set_open_uniform([(0, 0), (3, 5), (7, 5), (10, 0)])

    handles = [e.dxf.handle for e in msp]
    samples = geom.sample_chain(doc, handles, 3)
    assert len(samples) == 3
