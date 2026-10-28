"""Manufacturing boundary regressions, independent of the overlap heuristics."""
import asyncio
import io
import math
import ezdxf
import pytest
from shapely.geometry import Point, Polygon
from ezdxf.math import Vec2
from fastapi import HTTPException, UploadFile
from backend.state import CircleParams
from backend.dxf_engine import circle_generator as cg, geometry_utils as geom, path_analyzer as pa
from backend.dxf_engine.outline import analyze_outline
from backend.app import upload_dxf, select_entity, download_dxf, clear_session


def polygon_doc(points):
    doc = ezdxf.new("R2010")
    entity = doc.modelspace().add_lwpolyline(points, close=True)
    return doc, [entity.dxf.handle]


def preview(doc, chain, params):
    return cg.compute_preview_geometry(doc, chain, params, closed=pa.get_chain_info(doc, chain)["is_closed"],
                                      bounds={"min": [-200, -200], "max": [300, 300]}, scale=2,
                                      require_closed_outline=True)


@pytest.mark.parametrize("kind", ["arc", "circle", "positive_bulge", "negative_bulge"])
def test_curved_tangent_matches_actual_direction_of_travel(kind):
    doc = ezdxf.new()
    msp = doc.modelspace()
    if kind == "arc":
        entity = msp.add_arc((0, 0), 100, 20, 220)
    elif kind == "circle":
        entity = msp.add_circle((0, 0), 100)
    else:
        entity = msp.add_lwpolyline([(0, 0, .7 if kind == "positive_bulge" else -.7), (100, 0, 0)], format="xyb")
    for segment in geom._get_parametrization(entity):
        point, tangent, _ = segment.evaluate(.4)
        derivative = (segment.evaluate(.40001)[0] - segment.evaluate(.39999)[0]).normalize()
        assert derivative.dot(tangent) > .999999


def test_two_curves_with_identical_raw_endpoints_form_a_closed_outline():
    doc = ezdxf.new()
    first = doc.modelspace().add_lwpolyline([(0, 0, .5), (100, 0, 0)], format="xyb")
    second = doc.modelspace().add_lwpolyline([(0, 0, -.5), (100, 0, 0)], format="xyb")
    chain = pa.build_chain(doc, [first.dxf.handle])
    assert set(chain) == {first.dxf.handle, second.dxf.handle}
    assert pa.get_chain_info(doc, chain)["is_closed"]
    assert analyze_outline(doc, chain).ready


def test_endpoint_matching_searches_across_rounding_cell_boundaries():
    doc = ezdxf.new()
    m = doc.modelspace()
    first = m.add_line((0, 0), (100.000049, 0))
    m.add_line((100.000051, 0), (100, 100))
    m.add_line((100, 100), (0, 100))
    m.add_line((0, 100), (0, 0))
    chain = pa.build_chain(doc, [first.dxf.handle])
    assert len(chain) == 4
    assert pa.get_chain_info(doc, chain)["is_closed"]
    assert analyze_outline(doc, chain).ready


def test_matching_first_and_last_raw_endpoints_does_not_hide_a_middle_gap():
    doc = ezdxf.new()
    first = doc.modelspace().add_line((0, 0), (100, 0))
    last = doc.modelspace().add_line((20, 20), (0, 0))
    chain = [first.dxf.handle, last.dxf.handle]
    assert not pa.get_chain_info(doc, chain)["is_closed"]
    assert analyze_outline(doc, chain).status == "open"


def test_circle_center_inside_is_insufficient_when_radius_crosses_edge():
    doc, chain = polygon_doc([(0, 0), (100, 0), (100, 100), (0, 100)])
    outline = analyze_outline(doc, chain)
    assert not outline.allows_circle(Vec2(1, 50), 2)
    assert outline.allows_circle(Vec2(3, 50), 2)


def test_row_cannot_cross_concave_notch_and_reenter_board():
    points = [(0, 0), (100, 0), (100, 100), (70, 100), (70, 30), (30, 30), (30, 100), (0, 100)]
    doc, chain = polygon_doc(points)
    outline = analyze_outline(doc, chain)
    assert outline.allows_circle(Vec2(80, 60), 2)
    assert not outline.allows_circle(Vec2(80, 60), 2, source=Vec2(30, 60))


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("shape", ["rectangle", "concave", "narrow"])
def test_full_disks_remain_inside_and_preview_matches_export(shape, reverse):
    points = {
        "rectangle": [(0, 0), (100, 0), (100, 100), (0, 100)],
        "concave": [(0, 0), (100, 0), (100, 100), (70, 100), (70, 30), (30, 30), (30, 100), (0, 100)],
        "narrow": [(0, 0), (20, 0), (20, 200), (0, 200)],
    }[shape]
    if reverse:
        points = list(reversed(points))
    doc, chain = polygon_doc(points)
    boundary = Polygon(points)
    params = CircleParams(circle_radius=2, ray_offset=5, circle_spacing=40, circles_per_ray=4,
                          ray_count=48, top_gap_distance=0, air_duct_enabled=False)
    result = preview(doc, chain, params)
    assert not result["safety"]["blocked"]
    assert result["safety"]["boundary_rejected_count"] > 0
    assert result["generated_count"] > 0
    for circle in result["circles"] + result["removed_circles"]:
        center = Point(circle["cx"] / 2 - 200, 300 - circle["cy"] / 2)
        assert boundary.contains(center)
        assert boundary.boundary.distance(center) >= circle["r"] / 2
    exported, _ = cg.generate_circles(doc, chain, params, closed=True, require_closed_outline=True)
    actual = sorted((round(doc.entitydb[h].dxf.center.x, 7), round(doc.entitydb[h].dxf.center.y, 7)) for h in exported)
    expected = sorted((round(c["cx"] / 2 - 200, 7), round(300 - c["cy"] / 2, 7)) for c in result["circles"])
    assert actual == expected


@pytest.mark.parametrize("offset", [.2, 30])
def test_boundary_check_applies_even_to_one_circle_or_a_large_offset(offset):
    doc = ezdxf.new()
    entity = doc.modelspace().add_circle((0, 0), 10)
    params = CircleParams(circle_radius=1, ray_offset=offset, circles_per_ray=1, ray_count=1,
                          top_gap_distance=0, air_duct_enabled=False)
    result = preview(doc, [entity.dxf.handle], params)
    assert result["generated_count"] == 0
    assert result["safety"]["boundary_rejected_count"] == 1
    assert not cg.generate_circles(doc, [entity.dxf.handle], params, require_closed_outline=True)[0]


def test_outward_mode_remains_explicit_and_whole_circles_are_outside():
    doc = ezdxf.new()
    circle = doc.modelspace().add_circle((0, 0), 100)
    params = CircleParams(circle_radius=2, ray_offset=10, circles_per_ray=1, ray_count=24,
                          ray_direction="outward", top_gap_distance=0, air_duct_enabled=False)
    handles, _ = cg.generate_circles(doc, [circle.dxf.handle], params, require_closed_outline=True)
    assert len(handles) == 24
    for handle in handles:
        entity = doc.entitydb[handle]
        assert math.hypot(entity.dxf.center.x, entity.dxf.center.y) - entity.dxf.radius >= 100


@pytest.mark.parametrize("status", ["open", "invalid", "nonplanar"])
def test_unrepaired_outline_validator_rejects_ambiguous_geometry_without_mutation(status):
    if status == "invalid":
        doc, chain = polygon_doc([(0, 0), (100, 100), (0, 100), (100, 0)])
    else:
        doc = ezdxf.new()
        points = [(0, 0, 0), (100, 0, 0), (100, 100, 10 if status == "nonplanar" else 0), (0, 100, 0)]
        chain = [doc.modelspace().add_line(a, b).dxf.handle for a, b in zip(points, points[1:])]
        if status == "nonplanar":
            chain.append(doc.modelspace().add_line(points[-1], points[0]).dxf.handle)
    result = preview(doc, chain, CircleParams())
    assert result["safety"]["status"] == status
    assert result["safety"]["blocked"]
    assert not result["circles"]
    count = len(doc.modelspace())
    with pytest.raises(ValueError, match="outline_" + status):
        cg.generate_circles(doc, chain, CircleParams(), require_closed_outline=True)
    assert len(doc.modelspace()) == count


def test_capsule_cannot_cross_notch_even_when_both_endpoints_are_inside():
    points = [(0, 0), (100, 0), (100, 100), (70, 100), (70, 30), (30, 30), (30, 100), (0, 100)]
    doc, chain = polygon_doc(points)
    assert not analyze_outline(doc, chain).allows_capsule({"near": Vec2(20, 60), "far": Vec2(80, 60), "radius": 2})


def test_web_download_rejects_single_line_without_a_recoverable_region():
    async def run():
        doc = ezdxf.new()
        line = doc.modelspace().add_line((0, 0), (100, 0))
        text = io.StringIO()
        doc.write(text)
        result = await upload_dxf(UploadFile(filename="open.dxf", file=io.BytesIO(text.getvalue().encode())))
        sid = result["session_id"]
        try:
            selected = await select_entity(sid, {"handle": line.dxf.handle})
            assert selected["preview_geometry"]["safety"]["blocked"]
            with pytest.raises(HTTPException) as caught:
                await download_dxf(sid)
            assert caught.value.status_code == 422
            assert caught.value.detail == "outline_open"
        finally:
            await clear_session(sid)
    asyncio.run(run())


def test_repository_two_arc_dxf_preserves_valid_inward_rows():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "Test Files" / "Drawing2.dxf"
    doc = ezdxf.readfile(path)
    chain = pa.build_chain(doc, [next(iter(doc.modelspace())).dxf.handle])
    params = CircleParams(circle_radius=2, ray_offset=12, circle_spacing=12, circles_per_ray=2,
                          ray_count=24, top_gap_distance=0, air_duct_enabled=False)
    result = preview(doc, chain, params)
    assert result["generated_count"] == 48
    # Use native high-resolution DXF curves, not the generator's sampled chain.
    outline = analyze_outline(doc, chain)
    handles, _ = cg.generate_circles(doc, chain, params, require_closed_outline=True)
    assert len(handles) == 48
    for handle in handles:
        circle = doc.entitydb[handle]
        point = Point(circle.dxf.center.x, circle.dxf.center.y)
        assert outline.polygon.contains(point)
        assert outline.polygon.boundary.distance(point) >= circle.dxf.radius


@pytest.mark.parametrize("kind", ["circle", "two_arcs", "polyline", "ellipse", "spline"])
def test_mirrored_ocs_uses_world_coordinates_for_sampling_and_containment(kind):
    doc = ezdxf.new()
    msp = doc.modelspace()
    attrs = {"extrusion": (0, 0, -1)}
    if kind == "circle":
        first = msp.add_circle((40, 10), 100, dxfattribs=attrs)
    elif kind == "ellipse":
        first = msp.add_ellipse((40, 10), major_axis=(100, 20), ratio=.5, dxfattribs=attrs)
    elif kind == "spline":
        first = msp.add_spline(fit_points=[(140, 10), (40, 110), (-60, 10), (40, -90), (140, 10)])
    elif kind == "two_arcs":
        first = msp.add_arc((40, 10), 100, 0, 180, dxfattribs=attrs)
        msp.add_arc((40, 10), 100, 180, 360, dxfattribs=attrs)
    else:
        first = msp.add_lwpolyline([(0, 0), (100, 0), (100, 200), (0, 200)], close=True, dxfattribs=attrs)
    chain = pa.build_chain(doc, [first.dxf.handle])
    params = CircleParams(circle_radius=2, ray_offset=10, circles_per_ray=1,
                          ray_count=24, top_gap_distance=0, air_duct_enabled=False)
    result = preview(doc, chain, params)
    assert result["generated_count"] == 24
    outline = analyze_outline(doc, chain)
    handles, _ = cg.generate_circles(doc, chain, params, require_closed_outline=True)
    assert len(handles) == 24
    for handle in handles:
        entity = doc.entitydb[handle]
        assert outline.allows_circle(Vec2(entity.dxf.center.x, entity.dxf.center.y), entity.dxf.radius)
