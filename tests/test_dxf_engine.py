import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
from backend.dxf_engine import loader, svg_exporter, entity_mapper, path_analyzer, circle_generator
from backend.state import SessionState, CircleParams


def make_rect_doc():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0))
    msp.add_line((100, 0), (100, 80))
    msp.add_line((100, 80), (0, 80))
    msp.add_line((0, 80), (0, 0))
    return doc


def test_svg_export():
    doc = make_rect_doc()
    result = svg_exporter.doc_to_svg(doc)
    assert result.svg_string.startswith("<svg")
    assert "data-handle" in result.svg_string


def test_path_analyzer_chain():
    doc = make_rect_doc()
    handles = [e.dxf.handle for e in doc.modelspace()]
    chain = path_analyzer.build_chain(doc, [handles[0]])
    assert len(chain) == 4


def test_circle_generator():
    doc = make_rect_doc()
    handles = [e.dxf.handle for e in doc.modelspace()]
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=2,
        circle_spacing=5.0,
        ray_offset=1.0,
        ray_count=4,
        ray_direction="inward",
    )
    circle_handles, ray_handles = circle_generator.generate_circles(doc, handles, params)
    assert len(circle_handles) == 8  # 4 rays * 2 circles

    # Verify circles are on generated layer
    for h in circle_handles:
        entity = doc.entitydb[h]
        assert entity.dxf.layer == "GENERATED_CIRCLES"


def test_entity_mapper():
    doc = make_rect_doc()
    base = svg_exporter.doc_to_base_svg(doc)
    state = SessionState(
        session_id="test",
        original_doc=doc,
        working_doc=doc,
        svg_bounds=base.bounds,
        svg_scale=base.scale,
    )

    # Click near the middle of the bottom line (WCS 50, 0) expressed in base-SVG units.
    svg_x, svg_y = svg_exporter.wcs_to_svg(50, 0, base.bounds, base.scale)
    handle = entity_mapper.find_nearest_entity(state, svg_x, svg_y)
    assert handle is not None


def test_circle_generator_on_arc():
    """Circles generated on an arc should follow the arc curvature (inward)."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # Quarter circle from (10,0) to (0,10), center (0,0). Inward points toward origin.
    msp.add_arc((0, 0), radius=10, start_angle=0, end_angle=90)

    handle = msp[0].dxf.handle
    params = CircleParams(
        circle_radius=0.5,
        circles_per_ray=2,
        circle_spacing=2.0,
        ray_offset=1.0,
        ray_count=4,
        ray_direction="inward",
    )
    circle_handles, _ = circle_generator.generate_circles(doc, [handle], params)
    assert len(circle_handles) == 8  # 4 rays * 2 circles

    # All generated circles should be inside the arc (closer to origin than radius).
    for h in circle_handles:
        circle = doc.entitydb[h]
        center = circle.dxf.center
        assert math.hypot(center.x, center.y) < 10


def test_circle_generator_on_lwpolyline_bulge():
    """Circles generated on a bulged LWPOLYLINE should stay on the correct side."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # Arc below the chord from (0,0) to (2,0) with positive bulge.
    poly = msp.add_lwpolyline([(0, 0), (2, 0)], close=False)
    poly.set_points([(0, 0, 0, 0, 0.5), (2, 0, 0, 0, 0)])

    handle = poly.dxf.handle
    params = CircleParams(
        circle_radius=0.2,
        circles_per_ray=2,
        circle_spacing=1.0,
        ray_offset=0.5,
        ray_count=3,
        ray_direction="inward",
    )
    circle_handles, _ = circle_generator.generate_circles(doc, [handle], params)
    assert len(circle_handles) == 6  # 3 rays * 2 circles

    # For this single arc the centroid is inside the bulge, so inward circles
    # should be below the chord (y < 0) for positive bulge on this segment.
    for h in circle_handles:
        circle = doc.entitydb[h]
        assert circle.dxf.center.y < 0


def test_circle_generator_on_polyline_bulge():
    """Legacy POLYLINE with vertex bulge should behave like LWPOLYLINE."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    poly = msp.add_polyline2d([(0, 0), (2, 0)])
    poly[0].dxf.bulge = 0.5

    handle = poly.dxf.handle
    params = CircleParams(
        circle_radius=0.2,
        circles_per_ray=2,
        circle_spacing=1.0,
        ray_offset=0.5,
        ray_count=3,
        ray_direction="inward",
    )
    circle_handles, _ = circle_generator.generate_circles(doc, [handle], params)
    assert len(circle_handles) == 6

    for h in circle_handles:
        circle = doc.entitydb[h]
        assert circle.dxf.center.y < 0


def test_circle_generator_on_circle():
    """Selecting a full circle should generate evenly spaced inward/outward circles."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_circle((0, 0), radius=10)

    handle = msp[0].dxf.handle
    params = CircleParams(
        circle_radius=0.5,
        circles_per_ray=2,
        circle_spacing=2.0,
        ray_offset=1.0,
        ray_count=8,
        ray_direction="inward",
    )
    circle_handles, _ = circle_generator.generate_circles(doc, [handle], params, closed=True)
    assert len(circle_handles) == 16

    for h in circle_handles:
        circle = doc.entitydb[h]
        center = circle.dxf.center
        assert math.hypot(center.x, center.y) < 10


def test_path_analyzer_with_polyline_bulge():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    poly = msp.add_polyline2d([(0, 0), (2, 0), (2, 2), (0, 2)], close=True)
    poly[0].dxf.bulge = 0.5

    chain = path_analyzer.build_chain(doc, [poly.dxf.handle])
    assert len(chain) == 1
    info = path_analyzer.get_chain_info(doc, chain)
    assert info["is_closed"]
    assert info["total_length"] > 8  # longer than straight rectangle
