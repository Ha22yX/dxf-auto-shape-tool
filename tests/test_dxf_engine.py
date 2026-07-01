import os
import sys
import math
import asyncio
from io import BytesIO, StringIO
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
from ezdxf.math import Vec2
from fastapi import UploadFile
from backend.app import upload_dxf, download_dxf, _apply_selection, _select_handle
from backend.config import AIR_DUCT_LAYER, AIR_DUCT_BASE_PLATE_LAYER, DEFAULT_PARAMS
from backend.dxf_engine import loader, svg_exporter, entity_mapper, path_analyzer, circle_generator, geometry_utils
from backend.state import SessionState, CircleParams


def make_rect_doc():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0))
    msp.add_line((100, 0), (100, 80))
    msp.add_line((100, 80), (0, 80))
    msp.add_line((0, 80), (0, 0))
    return doc


def air_duct_point_inside_or_on(point, polygon, tolerance=1e-3):
    return circle_generator._point_in_polygon(point, polygon) or any(
        circle_generator._point_on_segment(
            point,
            polygon[index],
            polygon[(index + 1) % len(polygon)],
            tolerance=tolerance,
        )
        for index in range(len(polygon))
    )


def circle_extent_points(center, radius, samples=24):
    return [
        center + Vec2(math.cos(2.0 * math.pi * index / samples) * radius,
                      math.sin(2.0 * math.pi * index / samples) * radius)
        for index in range(samples)
    ]


def assert_air_ducts_cover_kept_circles(doc, chain, params, placements, kept_items):
    contours = circle_generator._air_duct_contours(doc, chain, params, placements, kept_items)
    offset = circle_generator._air_duct_template_offset(doc, chain)
    axis = circle_generator._chain_axis(doc, chain)
    by_region = {}
    for contour in contours:
        by_region.setdefault(contour["region"], []).append(
            [point - offset for point in contour["points"]]
        )

    for item in kept_items:
        region = circle_generator._air_duct_region_key(
            placements[item["placement_index"]],
            axis,
            params,
        )
        polygons = by_region.get(region, [])
        assert polygons
        assert any(
            air_duct_point_inside_or_on(item["center"], polygon)
            for polygon in polygons
        ), (region, item["placement_index"], item["circle_index"], item["center"])


def test_svg_export():
    doc = make_rect_doc()
    result = svg_exporter.doc_to_svg(doc)
    assert result.svg_string.startswith("<svg")
    assert "data-handle" in result.svg_string


def test_upload_returns_default_params():
    doc = make_rect_doc()
    stream = StringIO()
    doc.write(stream)
    upload = UploadFile(
        filename="defaults.dxf",
        file=BytesIO(stream.getvalue().encode("utf-8")),
    )

    response = asyncio.run(upload_dxf(upload))

    assert response["params"] == DEFAULT_PARAMS


def test_download_streams_dxf_without_temp_file_dependency():
    doc = make_rect_doc()
    stream = StringIO()
    doc.write(stream)
    upload = UploadFile(
        filename="download-test.dxf",
        file=BytesIO(stream.getvalue().encode("utf-8")),
    )

    upload_response = asyncio.run(upload_dxf(upload))
    response = asyncio.run(download_dxf(upload_response["session_id"]))

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert b"SECTION" in response.body


def test_path_analyzer_chain():
    doc = make_rect_doc()
    handles = [e.dxf.handle for e in doc.modelspace()]
    chain = path_analyzer.build_chain(doc, [handles[0]])
    assert len(chain) == 4


def test_multi_entity_closed_outline_samples_head_to_tail_when_entity_direction_differs():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    left = msp.add_lwpolyline([(0, 100), (-20, 50), (0, 0)], close=False)
    bottom = msp.add_line((0, 0), (10, 0))
    right = msp.add_lwpolyline([(10, 0), (30, 50), (10, 100)], close=False)
    # This closing edge is intentionally stored in the opposite direction from
    # the chain traversal needed after `right`.
    top = msp.add_line((0, 100), (10, 100))

    chain = path_analyzer.build_chain(doc, [left.dxf.handle])

    assert set(chain) == {left.dxf.handle, bottom.dxf.handle, right.dxf.handle, top.dxf.handle}
    assert path_analyzer.get_chain_info(doc, chain)["is_closed"]

    segments = geometry_utils._build_segments(doc, chain)
    assert len(segments) >= 4
    for prev, current in zip(segments, segments[1:]):
        prev_end = prev.evaluate(1.0)[0]
        current_start = current.evaluate(0.0)[0]
        assert (prev_end - current_start).magnitude < 1e-6
    first_start = segments[0].evaluate(0.0)[0]
    last_end = segments[-1].evaluate(1.0)[0]
    assert (first_start - last_end).magnitude < 1e-6


def test_closed_multi_entity_outline_normals_point_to_same_side_as_whole_shape():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    left = msp.add_line((0, 100), (0, 0))
    bottom = msp.add_line((0, 0), (10, 0))
    right = msp.add_line((10, 0), (10, 100))
    top = msp.add_line((0, 100), (10, 100))
    chain = path_analyzer.build_chain(doc, [left.dxf.handle])
    total = geometry_utils.chain_length(doc, chain)
    samples = geometry_utils.sample_chain_at_distances(
        doc,
        chain,
        [50.0, 105.0, 160.0, 215.0],
        smooth_tangents=False,
        total=total,
    )
    params = CircleParams(ray_direction="inward", top_gap_distance=0.0)

    normals = circle_generator._oriented_normals(doc, chain, samples, params, closed=True)

    center = geometry_utils.chain_centroid(samples)
    for sample, normal in zip(samples, normals):
        assert normal.dot(center - sample.point) > 0


def test_single_closed_spline_is_treated_as_closed_outline_for_inward_rays():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    spline = msp.add_spline(
        fit_points=[(100, 0), (0, 100), (-100, 0), (0, -100), (100, 0)]
    )

    chain = path_analyzer.build_chain(doc, [spline.dxf.handle])
    info = path_analyzer.get_chain_info(doc, chain)

    assert info["is_closed"]

    params = CircleParams(
        ray_direction="inward",
        ray_count=16,
        circles_per_ray=1,
        circle_spacing=10.0,
        ray_offset=10.0,
        top_gap_distance=0.0,
    )
    placements = circle_generator.compute_placements(
        doc,
        chain,
        params,
        closed=info["is_closed"],
    )
    boundary = geometry_utils.sample_chain(doc, chain, 401, closed=True, smooth_tangents=False)
    polygon = [sample.point for sample in boundary]

    assert placements
    assert all(
        geometry_utils.point_in_polygon(placement["centers"][0], polygon)
        for placement in placements
    )


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
        top_gap_distance=0.0,
        capsule_clearance_distance=0.0,
    )
    circle_handles, ray_handles = circle_generator.generate_circles(doc, handles, params)
    assert len(circle_handles) == 8  # 4 rays * 2 circles
    assert ray_handles == []

    # Verify circles are on generated layer
    for h in circle_handles:
        entity = doc.entitydb[h]
        assert entity.dxf.layer == "GENERATED_CIRCLES"
    assert not list(doc.modelspace().query('LINE[layer=="GENERATED_RAYS"]'))


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


def test_select_handle_prefers_frontend_hover_handle():
    doc = make_rect_doc()
    base = svg_exporter.doc_to_base_svg(doc)
    state = SessionState(
        session_id="test",
        original_doc=doc,
        working_doc=doc,
        svg_bounds=base.bounds,
        svg_scale=base.scale,
    )
    handle = next(e.dxf.handle for e in doc.modelspace())

    selected = _select_handle(state, {
        "handle": handle,
        "svg_x": -999999,
        "svg_y": -999999,
        "tol": 0.001,
    })

    assert selected == handle


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
        top_gap_distance=0.0,
        capsule_clearance_distance=0.0,
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
        top_gap_distance=0.0,
        capsule_clearance_distance=0.0,
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
        top_gap_distance=0.0,
        capsule_clearance_distance=0.0,
    )
    circle_handles, _ = circle_generator.generate_circles(doc, [handle], params)
    assert len(circle_handles) == 6

    for h in circle_handles:
        circle = doc.entitydb[h]
        assert circle.dxf.center.y < 0


def test_polyline_arc_uses_smoothed_curve_normal():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    points = []
    for i in range(13):
        angle = math.pi - math.pi * i / 12
        points.append((10 * math.cos(angle), 10 * math.sin(angle)))
    poly = msp.add_lwpolyline(points, close=False)

    samples = geometry_utils.sample_chain(doc, [poly.dxf.handle], 3, closed=False)

    top_sample = samples[1]
    assert abs(top_sample.point.x) < 1e-6
    assert abs(top_sample.normal.x) < 0.15


def test_top_gap_skips_apex_but_keeps_ray_count():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    poly = msp.add_lwpolyline([(-10, 0), (0, 10), (10, 0)], close=False)
    params = CircleParams(
        circle_radius=0.5,
        circles_per_ray=1,
        circle_spacing=2.0,
        ray_offset=1.0,
        ray_count=4,
        ray_direction="outward",
        dedupe_closed_rays=True,
        top_gap_distance=2.0,
    )

    placements = circle_generator.compute_placements(
        doc, [poly.dxf.handle], params, closed=False
    )

    assert len(placements) == 4
    apex = Vec2(0, 10)
    assert all((p["point"] - apex).magnitude >= 2.0 - 1e-6 for p in placements)
    assert sum(1 for p in placements if p["point"].x < 0) == 2
    assert sum(1 for p in placements if p["point"].x > 0) == 2


def test_top_gap_controls_source_points_not_generated_circle_reach():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    poly = msp.add_lwpolyline([(-10, 0), (0, 10), (10, 0)], close=False)
    params = CircleParams(
        circle_radius=0.5,
        circles_per_ray=2,
        circle_spacing=1.0,
        ray_offset=3.0,
        ray_count=4,
        ray_direction="outward",
        top_gap_distance=2.0,
    )

    placements = circle_generator.compute_placements(
        doc, [poly.dxf.handle], params, closed=False
    )

    apex = Vec2(0, 10)
    assert len(placements) == 4
    assert all((p["point"] - apex).magnitude >= params.top_gap_distance - 1e-6 for p in placements)
    assert any((p["point"] - apex).magnitude < params.ray_offset for p in placements)


def test_top_gap_skips_apex_when_closed_chain_starts_at_top():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    poly = msp.add_lwpolyline([(0, 10), (10, 0), (0, -10), (-10, 0)], close=True)
    params = CircleParams(
        circle_radius=0.5,
        circles_per_ray=1,
        circle_spacing=2.0,
        ray_offset=1.0,
        ray_count=6,
        ray_direction="outward",
        dedupe_closed_rays=True,
        top_gap_distance=3.0,
    )

    placements = circle_generator.compute_placements(
        doc, [poly.dxf.handle], params, closed=True
    )

    assert len(placements) == 6
    apex = Vec2(0, 10)
    assert all((p["point"] - apex).magnitude >= 3.0 - 1e-6 for p in placements)


def test_manual_apex_distance_overrides_auto_top():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    poly = msp.add_lwpolyline([(0, 0), (10, 10), (20, 0)], close=False)
    params = CircleParams(
        circle_radius=0.5,
        circles_per_ray=1,
        circle_spacing=2.0,
        ray_offset=1.0,
        ray_count=4,
        ray_direction="outward",
        top_gap_distance=2.0,
    )

    placements = circle_generator.compute_placements(
        doc,
        [poly.dxf.handle],
        params,
        closed=False,
        manual_apex_distance=0.0,
    )

    start = Vec2(0, 0)
    assert all((p["point"] - start).magnitude >= 2.0 - 1e-6 for p in placements)


def test_symmetry_axis_snaps_manual_apex_to_center_crossing():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    poly = msp.add_lwpolyline([(0, 0), (10, 10), (20, 0)], close=False)

    sample = geometry_utils.snapped_apex_sample_on_chain(
        doc,
        [poly.dxf.handle],
        Vec2(10.2, 9.7),
        snap_tolerance=1.0,
    )

    assert sample is not None
    assert (sample.point - Vec2(10, 10)).magnitude < 0.1


def test_symmetry_axis_default_uses_topmost_crossing():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    poly = msp.add_lwpolyline([(0, 0), (10, 10), (20, 0), (10, 20), (0, 0)], close=False)
    axis = geometry_utils.estimate_chain_symmetry_axis(doc, [poly.dxf.handle])

    sample = geometry_utils.top_axis_sample_on_chain(doc, [poly.dxf.handle], axis)

    assert sample is not None
    assert (sample.point - Vec2(10, 20)).magnitude < 0.2


def test_axis_crossing_point_is_projected_onto_axis():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    line = msp.add_line((0, 0), (20, 10))
    axis = {
        "center": Vec2(10, 0),
        "direction": Vec2(0, 1),
        "normal": Vec2(1, 0),
    }

    sample = geometry_utils.top_axis_sample_on_chain(doc, [line.dxf.handle], axis)

    assert sample is not None
    assert abs(sample.point.x - axis["center"].x) < 1e-9
    assert abs(sample.point.y - 5) < 1e-6


def test_selection_sets_default_apex_to_top_axis_crossing():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    poly = msp.add_lwpolyline([(0, 0), (10, 10), (20, 0), (10, 20), (0, 0)], close=False)
    state = SessionState(
        session_id="test",
        original_doc=doc,
        working_doc=doc,
    )

    changed = _apply_selection(state, poly.dxf.handle, append=False)
    sample = geometry_utils.sample_chain_at_distances(
        doc,
        [poly.dxf.handle],
        [state.manual_apex_distance],
    )[0]

    assert changed is True
    assert state.manual_apex_distance is not None
    assert (sample.point - Vec2(10, 20)).magnitude < 0.2


def test_preview_returns_symmetry_axis_overlay():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    poly = msp.add_lwpolyline([(0, 0), (10, 10), (20, 0)], close=False)
    params = CircleParams(ray_count=1, circles_per_ray=1, top_gap_distance=0.0)

    preview = circle_generator.compute_preview_geometry(
        doc,
        [poly.dxf.handle],
        params,
        closed=False,
        bounds={"min": [0, 0], "max": [20, 10]},
        scale=1.0,
    )

    axis = preview["symmetry_axis"]
    assert axis is not None
    assert abs(axis["x1"] - 10) < 0.2
    assert abs(axis["x2"] - 10) < 0.2
    assert abs(axis["y1"] - axis["y2"]) > 10

    axes = preview["symmetry_axes"]
    assert axes is not None
    assert abs(axes["vertical"]["x1"] - 10) < 0.2
    assert abs(axes["vertical"]["x2"] - 10) < 0.2
    assert abs(axes["horizontal"]["y1"] - 5) < 0.2
    assert abs(axes["horizontal"]["y2"] - 5) < 0.2

    snap = preview["symmetry_snap_point"]
    assert snap is not None
    assert abs(snap["cx"] - 10) < 0.2
    assert abs(snap["cy"] - 0) < 0.2


def test_preview_returns_manual_apex_marker():
    doc = make_rect_doc()
    handle = next(e.dxf.handle for e in doc.modelspace())
    params = CircleParams(ray_count=1, circles_per_ray=1, top_gap_distance=0.0)

    preview = circle_generator.compute_preview_geometry(
        doc,
        [handle],
        params,
        closed=False,
        bounds={"min": [0, 0], "max": [100, 80]},
        scale=1.0,
        manual_apex_distance=50.0,
    )

    assert preview["apex_marker"] == {"cx": 50.0, "cy": 80.0, "r": 5.0}


def test_preview_returns_default_apex_marker_without_manual_selection():
    doc = make_rect_doc()
    handles = [e.dxf.handle for e in doc.modelspace()]
    params = CircleParams(ray_count=4, circle_radius=2.0, top_gap_distance=0.0)

    preview = circle_generator.compute_preview_geometry(
        doc,
        handles,
        params,
        closed=True,
        bounds={"min": [0, 0], "max": [100, 80]},
        scale=1.0,
    )

    assert preview["apex_marker"] is not None
    assert preview["apex_marker"]["cy"] == 0.0


def test_overlap_pruning_marks_removed_circles_and_skips_export():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    line = msp.add_line((0, 0), (10, 0))
    params = CircleParams(
        circle_radius=3.0,
        circles_per_ray=1,
        circle_spacing=1.0,
        ray_offset=0.0,
        ray_count=3,
        ray_direction="outward",
        dedupe_closed_rays=False,
        top_gap_distance=0.0,
    )

    preview = circle_generator.compute_preview_geometry(
        doc,
        [line.dxf.handle],
        params,
        closed=False,
        bounds={"min": [0, -5], "max": [10, 5]},
        scale=1.0,
    )

    assert len(preview["circles"]) == 2
    assert len(preview["removed_circles"]) == 1
    assert preview["generated_count"] == 2
    assert preview["removed_count"] == 1

    export_doc = ezdxf.new("R2010")
    export_line = export_doc.modelspace().add_line((0, 0), (10, 0))
    circle_handles, _ = circle_generator.generate_circles(
        export_doc,
        [export_line.dxf.handle],
        params,
        closed=False,
    )
    assert len(circle_handles) == 2


def test_overlap_pruning_does_not_delete_both_circles_in_same_mirror_group():
    doc = ezdxf.new("R2010")
    params = CircleParams(circle_radius=3.0, top_gap_distance=0.0)
    placements = [
        {
            "point": Vec2(-1, 0),
            "centers": [Vec2(-1, 0)],
            "source_distance": 0.0,
            "normal": Vec2(0, 1),
        },
        {
            "point": Vec2(1, 0),
            "centers": [Vec2(1, 0)],
            "source_distance": 1.0,
            "normal": Vec2(0, 1),
        },
    ]

    kept, removed = circle_generator._overlap_pruned_circle_items(
        doc,
        [],
        params,
        placements,
    )

    assert len(kept) == 1
    assert len(removed) == 1


def test_capsule_overlap_pruning_removes_outer_circles_first_symmetrically():
    doc = ezdxf.new("R2010")
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=2,
        circle_spacing=10.0,
        ray_offset=4.0,
        capsule_start_distance=4.0,
        top_gap_distance=0.0,
        capsule_clearance_distance=0.0,
    )
    placements = [
        {
            "point": Vec2(-8, 0),
            "centers": [Vec2(-1, 0), Vec2(12, 0)],
            "source_distance": 0.0,
            "normal": Vec2(1, 0),
        },
        {
            "point": Vec2(8, 1),
            "centers": [Vec2(3.2, 1), Vec2(-12, 1)],
            "source_distance": 1.0,
            "normal": Vec2(-1, 0),
        },
    ]

    kept, removed = circle_generator._overlap_pruned_circle_items(
        doc,
        [],
        params,
        placements,
    )

    assert sorted(item["circle_index"] for item in kept) == [0, 0]
    assert sorted(item["circle_index"] for item in removed) == [1, 1]
    assert circle_generator._best_capsule_conflict(
        placements,
        params,
        None,
        kept,
    ) is None


def test_capsule_clearance_pruning_removes_only_one_conflicting_side_without_axis():
    doc = ezdxf.new("R2010")
    params = CircleParams(
        circle_radius=2.0,
        capsule_clearance_distance=2.5,
        circles_per_ray=2,
        circle_spacing=10.0,
        ray_offset=4.0,
        capsule_start_distance=4.0,
        top_gap_distance=0.0,
    )
    placements = [
        {
            "point": Vec2(0, 0),
            "centers": [Vec2(4, 0), Vec2(20, 0)],
            "source_distance": 0.0,
            "normal": Vec2(1, 0),
        },
        {
            "point": Vec2(20, 12),
            "centers": [Vec2(20, 10), Vec2(20, 4.5)],
            "source_distance": 1.0,
            "normal": Vec2(0, -1),
        },
    ]

    kept, removed = circle_generator._overlap_pruned_circle_items(
        doc,
        [],
        params,
        placements,
    )

    assert len(removed) == 1
    assert removed[0]["circle_index"] == 1
    assert len(kept) == 3
    assert circle_generator._best_capsule_conflict(
        placements,
        params,
        None,
        kept,
    ) is None


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
        top_gap_distance=0.0,
    )
    circle_handles, _ = circle_generator.generate_circles(doc, [handle], params, closed=True)
    assert len(circle_handles) == 16

    for h in circle_handles:
        circle = doc.entitydb[h]
        center = circle.dxf.center
        assert math.hypot(center.x, center.y) < 10


def test_closed_chain_endpoint_rays_can_be_deduped():
    doc = make_rect_doc()
    handles = [e.dxf.handle for e in doc.modelspace()]
    params = CircleParams(
        circle_radius=0.5,
        circles_per_ray=1,
        circle_spacing=2.0,
        ray_offset=1.0,
        ray_count=5,
        ray_direction="inward",
        dedupe_closed_rays=True,
        top_gap_distance=0.0,
    )
    placements = circle_generator.compute_placements(doc, handles, params, closed=True)
    assert len(placements) == 5
    assert (placements[0]["point"] - placements[-1]["point"]).magnitude > 1e-6

    params.dedupe_closed_rays = False
    placements = circle_generator.compute_placements(doc, handles, params, closed=True)
    assert len(placements) == 5
    assert (placements[0]["point"] - placements[-1]["point"]).magnitude < 1e-6


def test_dedupe_switch_skips_terminal_endpoint_even_if_open():
    doc = ezdxf.new("R2010")
    line = doc.modelspace().add_line((0, 0), (10, 0))
    params = CircleParams(
        circle_radius=0.5,
        circles_per_ray=1,
        circle_spacing=2.0,
        ray_offset=1.0,
        ray_count=3,
        ray_direction="inward",
        dedupe_closed_rays=True,
        top_gap_distance=0.0,
    )

    placements = circle_generator.compute_placements(
        doc, [line.dxf.handle], params, closed=False
    )
    assert len(placements) == 3
    assert all(p["point"].x < 10 for p in placements)

    params.dedupe_closed_rays = False
    placements = circle_generator.compute_placements(
        doc, [line.dxf.handle], params, closed=False
    )
    assert placements[-1]["point"].x == 10


def test_preview_rays_start_on_selected_edge():
    doc = make_rect_doc()
    handle = next(e.dxf.handle for e in doc.modelspace())
    bounds = {"min": [0, 0], "max": [100, 80]}
    scale = 1.0
    params = CircleParams(
        circle_radius=1.0,
        circles_per_ray=1,
        circle_spacing=5.0,
        ray_offset=10.0,
        ray_count=1,
        ray_direction="outward",
        top_gap_distance=0.0,
    )

    preview = circle_generator.compute_preview_geometry(
        doc, [handle], params, closed=False, bounds=bounds, scale=scale
    )

    ray = preview["rays"][0]
    circle = preview["circles"][0]
    assert ray["x1"] == 0
    assert ray["y1"] == 80
    assert (ray["x1"], ray["y1"]) != (circle["cx"], circle["cy"])


def test_preview_returns_basis_for_fast_frontend_redraw():
    doc = make_rect_doc()
    handle = next(e.dxf.handle for e in doc.modelspace())
    params = CircleParams(
        circle_radius=1.0,
        circles_per_ray=2,
        circle_spacing=5.0,
        ray_offset=10.0,
        ray_count=3,
        ray_direction="outward",
        top_gap_distance=0.0,
    )

    preview = circle_generator.compute_preview_geometry(
        doc,
        [handle],
        params,
        closed=False,
        bounds={"min": [0, 0], "max": [100, 80]},
        scale=2.0,
    )

    assert preview["scale"] == 2.0
    assert len(preview["basis"]) == 3
    assert {"x", "y", "nx", "ny"} <= set(preview["basis"][0])


def test_preview_returns_capsule_paths_for_each_ray():
    doc = make_rect_doc()
    handle = next(e.dxf.handle for e in doc.modelspace())
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=3,
        circle_spacing=5.0,
        ray_offset=10.0,
        capsule_start_distance=4.0,
        ray_count=2,
        ray_direction="outward",
        top_gap_distance=0.0,
    )

    preview = circle_generator.compute_preview_geometry(
        doc,
        [handle],
        params,
        closed=False,
        bounds={"min": [0, -20], "max": [100, 80]},
        scale=1.0,
    )

    assert len(preview["capsules"]) == 2
    assert all("A 2.0 2.0" in capsule["d"] for capsule in preview["capsules"])
    assert preview["capsule_template_offset"]["x"] < 0
    assert preview["capsule_chain_path"].startswith("M -")


def test_generate_circles_exports_capsule_outline_entities():
    doc = ezdxf.new("R2010")
    line = doc.modelspace().add_line((0, 0), (10, 0))
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=2,
        circle_spacing=5.0,
        ray_offset=3.0,
        capsule_start_distance=1.0,
        ray_count=1,
        ray_direction="outward",
        top_gap_distance=0.0,
    )

    circle_handles, ray_handles = circle_generator.generate_circles(
        doc,
        [line.dxf.handle],
        params,
        closed=False,
    )

    generated = list(doc.modelspace().query('*[layer=="GENERATED_CIRCLES"]'))
    assert len(circle_handles) == 2
    assert ray_handles == []
    assert sum(1 for entity in generated if entity.dxftype() == "CIRCLE") == 2
    assert sum(1 for entity in generated if entity.dxftype() == "LINE") == 2
    assert sum(1 for entity in generated if entity.dxftype() == "ARC") == 2
    copied_chain = [entity for entity in generated if entity.dxftype() == "LWPOLYLINE"]
    assert len(copied_chain) == 1
    assert min(point[0] for point in copied_chain[0].get_points()) < 0


def test_capsule_axis_gap_skips_capsules_but_keeps_circles_in_preview_and_export():
    doc = make_rect_doc()
    handles = [e.dxf.handle for e in doc.modelspace()]
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=2,
        circle_spacing=5.0,
        ray_offset=10.0,
        capsule_start_distance=1.0,
        capsule_axis_gap_above_distance=1000.0,
        capsule_axis_gap_below_distance=1000.0,
        ray_count=6,
        ray_direction="outward",
        top_gap_distance=0.0,
    )

    preview = circle_generator.compute_preview_geometry(
        doc,
        handles,
        params,
        closed=True,
        bounds={"min": [0, 0], "max": [100, 80]},
        scale=1.0,
    )

    assert len(preview["circles"]) > 0
    assert preview["capsules"] == []
    assert preview["capsule_gap_guide"] is not None

    circle_handles, _ = circle_generator.generate_circles(
        doc,
        handles,
        params,
        closed=True,
    )
    generated = list(doc.modelspace().query('*[layer=="GENERATED_CIRCLES"]'))

    assert len(circle_handles) > 0
    assert sum(1 for entity in generated if entity.dxftype() == "CIRCLE") == len(circle_handles)
    assert sum(1 for entity in generated if entity.dxftype() == "LINE") == 0
    assert sum(1 for entity in generated if entity.dxftype() == "ARC") == 0


def test_capsule_axis_gap_guide_can_use_different_above_and_below_distances():
    doc = make_rect_doc()
    handles = [e.dxf.handle for e in doc.modelspace()]
    params = CircleParams(
        capsule_axis_gap_above_distance=10.0,
        capsule_axis_gap_below_distance=30.0,
        top_gap_distance=0.0,
    )

    preview = circle_generator.compute_preview_geometry(
        doc,
        handles,
        params,
        closed=True,
        bounds={"min": [0, 0], "max": [100, 80]},
        scale=2.0,
    )

    guide = preview["capsule_gap_guide"]
    axis_y = preview["symmetry_axes"]["horizontal"]["y1"]

    assert guide["upper"]["y1"] == axis_y - 20.0
    assert guide["lower"]["y1"] == axis_y + 60.0


def test_legacy_capsule_axis_gap_applies_to_both_sides():
    params = CircleParams.from_dict({"capsule_axis_gap_distance": 12.5})

    assert params.capsule_axis_gap_above_distance == 12.5
    assert params.capsule_axis_gap_below_distance == 12.5


def test_capsule_start_distance_is_clamped_to_first_circle():
    params = CircleParams.from_dict({
        "ray_offset": 12.0,
        "capsule_start_distance": 50.0,
    })

    assert params.capsule_start_distance == 12.0

    params = CircleParams.from_dict({
        "ray_offset": 12.0,
        "capsule_start_distance": 0.0,
    })

    assert params.capsule_start_distance == 0.1


def test_capsule_start_stays_parameter_controlled_when_inner_circle_removed():
    placement = {
        "point": Vec2(0, 0),
        "normal": Vec2(0, 1),
        "centers": [Vec2(0, 10), Vec2(0, 20), Vec2(0, 30)],
    }
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=3,
        circle_spacing=10.0,
        ray_offset=10.0,
        capsule_start_distance=10.0,
        top_gap_distance=0.0,
    )
    kept_items = [
        {"circle_index": 1, "center": Vec2(0, 20)},
        {"circle_index": 2, "center": Vec2(0, 30)},
    ]

    capsule = circle_generator._capsule_for_placement(
        placement,
        params,
        kept_items=kept_items,
    )

    assert capsule is not None
    assert capsule["near"].isclose(Vec2(0, 10))
    assert capsule["far"].isclose(Vec2(0, 30))


def test_open_chain_normals_do_not_flip_sides():
    doc = ezdxf.new("R2010")
    samples = [
        SimpleNamespace(normal=Vec2(0, 1)),
        SimpleNamespace(normal=Vec2(0, -1)),
        SimpleNamespace(normal=Vec2(0, 1)),
    ]
    params = CircleParams(ray_direction="inward", top_gap_distance=0.0)

    normals = circle_generator._oriented_normals(doc, [], samples, params, closed=False)

    for previous, current in zip(normals, normals[1:]):
        assert previous.x * current.x + previous.y * current.y >= 0


def test_closed_dedupe_removes_duplicate_source_points():
    placements = [
        {"point": Vec2(0, 0), "centers": [Vec2(0, 1)]},
        {"point": Vec2(10, 0), "centers": [Vec2(10, 1)]},
        {"point": Vec2(0, 0), "centers": [Vec2(0, -1)]},
    ]

    unique = circle_generator._dedupe_placements_by_source(placements)

    assert len(unique) == 2
    assert unique[0]["centers"] == [Vec2(0, 1)]


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


def test_preview_includes_air_duct_templates():
    doc = make_rect_doc()
    handles = [entity.dxf.handle for entity in doc.modelspace()]
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=2,
        circle_spacing=12.0,
        ray_offset=12.0,
        ray_count=12,
        top_gap_distance=0.0,
        air_duct_enabled=True,
        air_duct_inlet_distance=10.0,
    )
    base = svg_exporter.doc_to_base_svg(doc, dark=True)

    preview = circle_generator.compute_preview_geometry(
        doc,
        handles,
        params,
        closed=True,
        bounds=base.bounds,
        scale=base.scale,
    )

    assert preview["air_ducts"]
    assert preview["air_duct_base_plates"]
    assert all(duct["d"].startswith("M ") and duct["d"].endswith("Z") for duct in preview["air_ducts"])
    assert all(
        plate["d"].startswith("M ") and plate["d"].endswith("Z")
        for plate in preview["air_duct_base_plates"]
    )
    assert len(preview["air_ducts"]) == len(
        {(duct["region"], duct.get("role")) for duct in preview["air_ducts"]}
    )
    assert preview["air_duct_template_offset"]["x"] > 0


def test_air_duct_record_uses_kept_circles_after_overlap_pruning():
    placement = {
        "point": Vec2(0, 0),
        "normal": Vec2(1, 0),
        "centers": [Vec2(10, 0), Vec2(20, 0), Vec2(30, 0)],
        "source_distance": 0.0,
    }
    kept_items = [
        {
            "center": Vec2(30, 0),
            "placement_index": 0,
            "circle_index": 2,
        }
    ]

    record = circle_generator._air_duct_record(placement, 2.0, kept_items)

    assert (record["near"] - Vec2(28, 0)).magnitude < 1e-9
    assert (record["far"] - Vec2(32, 0)).magnitude < 1e-9
    assert record["circle_centers"] == [Vec2(30, 0)]


def test_air_duct_contours_use_full_ray_row_to_avoid_pruned_hole_dents():
    placements = [
        {
            "point": Vec2(0, 0),
            "normal": Vec2(1, 0),
            "centers": [Vec2(10, 0), Vec2(20, 0), Vec2(30, 0)],
            "source_distance": 0.0,
        },
        {
            "point": Vec2(0, 20),
            "normal": Vec2(1, 0),
            "centers": [Vec2(10, 20), Vec2(20, 20), Vec2(30, 20)],
            "source_distance": 20.0,
        },
    ]
    kept_items = [
        {"center": Vec2(30, 0), "placement_index": 0, "circle_index": 2},
        {"center": Vec2(10, 20), "placement_index": 1, "circle_index": 0},
    ]
    params = CircleParams(circle_radius=2.0)

    records = []
    kept_by_placement = circle_generator._items_by_placement(kept_items)
    for index, placement in enumerate(placements):
        assert kept_by_placement[index]
        records.append(circle_generator._air_duct_record(placement, params.circle_radius, None))

    assert records[0]["near"].isclose(Vec2(8, 0))
    assert records[0]["far"].isclose(Vec2(32, 0))
    assert records[1]["near"].isclose(Vec2(8, 20))
    assert records[1]["far"].isclose(Vec2(32, 20))


def test_air_duct_contours_cover_kept_circles_after_pruning():
    doc = make_rect_doc()
    handles = [entity.dxf.handle for entity in doc.modelspace()]
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=3,
        circle_spacing=12.0,
        ray_offset=12.0,
        ray_count=18,
        top_gap_distance=0.0,
        air_duct_enabled=True,
    )
    placements = circle_generator.compute_placements(doc, handles, params, closed=True)
    kept_items, removed_items = circle_generator._overlap_pruned_circle_items(
        doc,
        handles,
        params,
        placements,
    )

    assert kept_items
    assert removed_items
    contours = circle_generator._air_duct_contours(
        doc,
        handles,
        params,
        placements,
        kept_items,
    )
    axis = circle_generator._chain_axis(doc, handles)
    expected_regions = {
        circle_generator._air_duct_region_key(
            placements[item["placement_index"]],
            axis,
            params,
        )
        for item in kept_items
    }
    generated_regions = {contour["region"] for contour in contours}

    assert expected_regions <= generated_regions
    assert all(len(contour["points"]) >= 3 for contour in contours)


def test_air_duct_default_split_keeps_upper_and_lower_regions_separate():
    doc = make_rect_doc()
    handles = [entity.dxf.handle for entity in doc.modelspace()]
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=2,
        circle_spacing=12.0,
        ray_offset=12.0,
        ray_count=24,
        top_gap_distance=0.0,
        capsule_axis_gap_above_distance=0.0,
        capsule_axis_gap_below_distance=0.0,
        air_duct_enabled=True,
    )
    placements = circle_generator.compute_placements(doc, handles, params, closed=True)
    kept_items, _ = circle_generator._overlap_pruned_circle_items(
        doc,
        handles,
        params,
        placements,
    )

    contours = circle_generator._air_duct_contours(
        doc,
        handles,
        params,
        placements,
        kept_items,
    )
    regions = {contour["region"] for contour in contours}

    assert regions == {"upper", "lower"}
    assert all(contour["role"].startswith("outline") for contour in contours)


def test_air_duct_inlet_is_integrated_into_region_outline():
    records = [
        {
            "near": Vec2(0, 10),
            "far": Vec2(0, 30),
            "width": 20.0,
            "source_distance": 0.0,
            "source_point": Vec2(0, 0),
        },
        {
            "near": Vec2(100, 10),
            "far": Vec2(100, 30),
            "width": 20.0,
            "source_distance": 100.0,
            "source_point": Vec2(100, 0),
        },
    ]
    params = CircleParams(circle_radius=2.0, air_duct_inlet_distance=5.0)

    contours = circle_generator._air_duct_region_contours(
        records,
        total_length=200.0,
        params=params,
        region="upper",
    )

    assert len(contours) == 1
    points = contours[0]["points"]
    assert any(abs(point.y - 15.0) < 1e-9 for point in points)
    assert any(abs(point.y - 30.0) < 1e-9 for point in points)


def test_air_duct_inlet_edges_align_to_curve_endpoints_without_diagonal_bridges():
    records = [
        {
            "near": Vec2(10, 10),
            "far": Vec2(0, 30),
            "width": 20.0,
            "source_distance": 0.0,
            "source_point": Vec2(0, 0),
        },
        {
            "near": Vec2(50, 20),
            "far": Vec2(50, 40),
            "width": 20.0,
            "source_distance": 50.0,
            "source_point": Vec2(50, 0),
        },
        {
            "near": Vec2(90, 10),
            "far": Vec2(100, 30),
            "width": 20.0,
            "source_distance": 100.0,
            "source_point": Vec2(100, 0),
        },
    ]
    params = CircleParams(circle_radius=2.0, air_duct_inlet_distance=5.0)

    contours = circle_generator._air_duct_region_contours(
        records,
        total_length=200.0,
        params=params,
        region="upper",
    )

    assert len(contours) == 1
    points = contours[0]["points"]
    assert max(point.y for point in points) >= 35.0
    assert min(point.y for point in points) <= 10.0
    assert max(point.y for point in points) > 35.0


def test_air_duct_outline_orients_reversed_records_before_adding_inlet():
    records = [
        {
            "near": Vec2(100, 10),
            "far": Vec2(100, 30),
            "width": 20.0,
            "source_distance": 100.0,
            "source_point": Vec2(100, 0),
        },
        {
            "near": Vec2(0, 10),
            "far": Vec2(0, 30),
            "width": 20.0,
            "source_distance": 0.0,
            "source_point": Vec2(0, 0),
        },
    ]
    params = CircleParams(circle_radius=2.0, air_duct_inlet_distance=5.0)

    contours = circle_generator._air_duct_region_contours(
        records,
        total_length=200.0,
        params=params,
        region="upper",
    )

    assert len(contours) == 1
    points = contours[0]["points"]
    assert points[0].x <= points[1].x
    assert any(abs(point.y - 15.0) < 1e-9 for point in points)


def test_air_duct_inlet_clamps_to_sloped_outer_boundary_without_tabs():
    records = [
        {
            "near": Vec2(10, 10),
            "far": Vec2(0, 30),
            "width": 20.0,
            "source_distance": 0.0,
            "source_point": Vec2(0, 0),
        },
        {
            "near": Vec2(50, 20),
            "far": Vec2(50, 40),
            "width": 20.0,
            "source_distance": 50.0,
            "source_point": Vec2(50, 0),
        },
        {
            "near": Vec2(90, 10),
            "far": Vec2(100, 30),
            "width": 20.0,
            "source_distance": 100.0,
            "source_point": Vec2(100, 0),
        },
    ]
    params = CircleParams(circle_radius=2.0, air_duct_inlet_distance=5.0)
    ordered = circle_generator._ordered_air_duct_records(records, 200.0)
    polygon = circle_generator._air_duct_component_polygon(ordered)

    inlet = circle_generator._air_duct_inlet_points(ordered, params, "upper", [polygon])

    assert inlet[0].x > min(point.x for record in records for point in (record["near"], record["far"]))
    assert inlet[2].x < max(point.x for record in records for point in (record["near"], record["far"]))


def test_air_duct_inner_region_does_not_bridge_disconnected_side_tops():
    records = [
        {
            "near": Vec2(0, 0),
            "far": Vec2(10, 0),
            "width": 10.0,
            "source_distance": 0.0,
            "source_point": Vec2(0, 0),
        },
        {
            "near": Vec2(0, 100),
            "far": Vec2(10, 100),
            "width": 10.0,
            "source_distance": 10.0,
            "source_point": Vec2(0, 100),
        },
        {
            "near": Vec2(100, 0),
            "far": Vec2(110, 0),
            "width": 10.0,
            "source_distance": 1000.0,
            "source_point": Vec2(100, 0),
        },
        {
            "near": Vec2(100, 100),
            "far": Vec2(110, 100),
            "width": 10.0,
            "source_distance": 1010.0,
            "source_point": Vec2(100, 100),
        },
    ]
    params = CircleParams(circle_radius=2.0, air_duct_inlet_distance=10.0)

    contours = circle_generator._air_duct_region_contours(
        records,
        total_length=2000.0,
        params=params,
        region="upper_inner",
    )

    assert contours
    for contour in contours:
        points = contour["points"]
        for index, point in enumerate(points):
            next_point = points[(index + 1) % len(points)]
            if abs(point.y - 100.0) < 1e-9 and abs(next_point.y - 100.0) < 1e-9:
                assert abs(point.x - next_point.x) <= 20.0


def test_air_duct_inner_region_keeps_same_side_connected_across_chain_wrap():
    records = []
    for source_distance, x, y in [
        (20.0, 100.0, 0.0),
        (100.0, 100.0, 20.0),
        (6600.0, 100.0, 40.0),
        (7200.0, 100.0, 60.0),
        (2000.0, 0.0, 0.0),
        (2200.0, 0.0, 20.0),
        (2400.0, 0.0, 40.0),
    ]:
        records.append({
            "near": Vec2(x, y),
            "far": Vec2(x + 10.0, y),
            "width": 10.0,
            "source_distance": source_distance,
            "source_point": Vec2(x, y),
        })

    components = circle_generator._split_air_duct_components(
        records,
        total_length=7300.0,
        split_disconnected=True,
    )

    assert sorted(len(component) for component in components) == [3, 4]
    assert any(
        len(component) == 4
        and {record["source_point"].x for record in component} == {100.0}
        for component in components
    )


def test_air_duct_inlet_tangent_to_side_ducts_unions_as_one_outline():
    records = []
    for source_distance, near, far in [
        (3180.14, (1851.76, -2458.14), (1893.75, -2457.60)),
        (3218.30, (1851.27, -2419.98), (1893.26, -2419.44)),
        (3256.47, (1850.78, -2381.81), (1892.78, -2381.27)),
        (3294.64, (1850.29, -2343.65), (1892.29, -2343.11)),
        (3332.81, (1849.80, -2305.48), (1891.80, -2304.95)),
        (6771.53, (2595.74, -2305.22), (2553.75, -2304.68)),
        (6809.70, (2595.25, -2343.38), (2553.26, -2342.84)),
        (6847.86, (2594.76, -2381.55), (2552.77, -2381.01)),
        (6886.03, (2594.28, -2419.71), (2552.28, -2419.17)),
        (6924.20, (2593.79, -2457.87), (2551.79, -2457.34)),
    ]:
        near_point = Vec2(*near)
        far_point = Vec2(*far)
        records.append({
            "near": near_point,
            "far": far_point,
            "width": (far_point - near_point).magnitude,
            "source_distance": source_distance,
            "source_point": near_point,
        })
    params = CircleParams(circle_radius=3.5, air_duct_inlet_distance=75.5)

    contours = circle_generator._air_duct_region_contours(
        records,
        total_length=7675.0,
        params=params,
        region="upper_inner",
    )

    assert len(contours) == 1
    points = contours[0]["points"]
    assert min(point.x for point in points) < 1900
    assert max(point.x for point in points) > 2550
    raw_min_x = min(point.x for record in records for point in (record["near"], record["far"]))
    raw_max_x = max(point.x for record in records for point in (record["near"], record["far"]))
    assert min(point.x for point in points) >= raw_min_x - 0.1
    assert max(point.x for point in points) <= raw_max_x + 0.1


def test_air_duct_outline_contains_all_circle_extent_points():
    records = [
        {
            "near": Vec2(0, -100),
            "far": Vec2(10, -100),
            "width": 10.0,
            "source_distance": 0.0,
            "source_point": Vec2(0, -100),
        },
        {
            "near": Vec2(50, -130),
            "far": Vec2(60, -130),
            "width": 10.0,
            "source_distance": 50.0,
            "source_point": Vec2(50, -130),
        },
        {
            "near": Vec2(100, -100),
            "far": Vec2(110, -100),
            "width": 10.0,
            "source_distance": 100.0,
            "source_point": Vec2(100, -100),
        },
    ]
    params = CircleParams(circle_radius=2.0, air_duct_inlet_distance=10.0)

    contours = circle_generator._air_duct_region_contours(
        records,
        total_length=200.0,
        params=params,
        region="lower",
    )

    def inside_or_on(point, polygon):
        return circle_generator._point_in_polygon(point, polygon) or any(
            circle_generator._point_on_segment(
                point,
                polygon[index],
                polygon[(index + 1) % len(polygon)],
            )
            for index in range(len(polygon))
        )

    extent_points = [
        point
        for record in records
        for point in (record["near"], record["far"])
    ]
    assert all(
        any(inside_or_on(point, contour["points"]) for contour in contours)
        for point in extent_points
    )


def test_air_duct_curve_removes_local_hairpin_at_rounded_foot():
    points = [
        Vec2(343.328, 122.094),
        Vec2(332.651, 124.912),
        Vec2(338.770, 121.356),
        Vec2(332.629, 128.808),
        Vec2(322.354, 146.829),
    ]

    cleaned = circle_generator._remove_hairpin_points(points)

    assert len(cleaned) == 4
    for previous, current, next_point in zip(cleaned, cleaned[1:], cleaned[2:]):
        incoming = current - previous
        outgoing = next_point - current
        assert incoming.normalize().dot(outgoing.normalize()) >= -0.82


def test_air_duct_offset_smoothing_removes_local_dent_without_losing_cover():
    normals = [Vec2(0, 1)] * 5
    points = [
        Vec2(0, 0),
        Vec2(10, 0),
        Vec2(20, -12),
        Vec2(30, 0),
        Vec2(40, 0),
    ]
    radius = 2.0
    required = radius + circle_generator._air_duct_envelope_margin(radius)
    records = [
        {
            "near_center": point - normal * required,
            "radius": radius,
        }
        for point, normal in zip(points, normals)
    ]

    smoothed = circle_generator._smooth_air_duct_offset_points(
        records,
        "near_center",
        points,
        normals,
    )

    assert smoothed[2].y > points[2].y + 1.0
    assert all(
        (point - record["near_center"]).dot(normal) + 1e-9 >= required
        for point, record, normal in zip(smoothed, records, normals)
    )


def test_air_duct_component_extends_endpoints_to_cover_end_hole_radius():
    records = [
        {
            "near": Vec2(0, 0),
            "far": Vec2(0, 40),
            "width": 40.0,
            "source_distance": 0.0,
            "source_point": Vec2(0, 0),
        },
        {
            "near": Vec2(100, 0),
            "far": Vec2(100, 40),
            "width": 40.0,
            "source_distance": 100.0,
            "source_point": Vec2(100, 0),
        },
    ]

    polygon = circle_generator._air_duct_component_polygon(records, endpoint_margin=5.0)
    xs = [point.x for point in polygon]

    assert min(xs) <= -5.0 + 1e-6
    assert max(xs) >= 105.0 - 1e-6


def test_air_duct_base_plate_ignores_inlet_and_has_flat_ends():
    records = []
    for index, (x, near_y, far_y) in enumerate([
        (0.0, 0.0, 30.0),
        (30.0, 6.0, 36.0),
        (60.0, 4.0, 34.0),
        (90.0, 0.0, 30.0),
    ]):
        near = Vec2(x, near_y)
        far = Vec2(x, far_y)
        records.append({
            "near": near,
            "far": far,
            "near_center": near,
            "far_center": far,
            "circle_centers": [near + (far - near) * 0.5],
            "radius": 2.0,
            "width": (far - near).magnitude,
            "source_distance": float(index * 10),
            "source_point": near,
        })

    params = CircleParams(
        circle_radius=2.0,
        air_duct_inlet_distance=4.0,
        air_duct_base_plate_margin=8.0,
    )
    shifted_params = CircleParams(
        circle_radius=2.0,
        air_duct_inlet_distance=24.0,
        air_duct_base_plate_margin=8.0,
    )

    contours = circle_generator._air_duct_base_plate_region_contours(
        records,
        total_length=120.0,
        params=params,
        region="upper",
    )
    shifted_contours = circle_generator._air_duct_base_plate_region_contours(
        records,
        total_length=120.0,
        params=shifted_params,
        region="upper",
    )

    assert len(contours) == 1
    assert len(shifted_contours) == 1
    points = contours[0]["points"]
    shifted_points = shifted_contours[0]["points"]
    assert len(points) == len(shifted_points)
    assert all(
        point.isclose(shifted)
        for point, shifted in zip(points, shifted_points)
    )

    component_polygons = circle_generator._air_duct_component_polygons_for_region(
        records,
        total_length=120.0,
        params=params,
        region="upper",
    )
    component_points = [point for polygon in component_polygons for point in polygon]
    min_y = min(point.y for point in points)
    max_y = max(point.y for point in points)

    assert min_y < min(point.y for point in component_points)
    assert max_y > max(point.y for point in component_points)
    assert all(
        air_duct_point_inside_or_on(point, points)
        for point in component_points
    )


def test_air_duct_base_plates_share_axis_gap_split_edges_without_overlap():
    doc = make_rect_doc()
    handles = [entity.dxf.handle for entity in doc.modelspace()]
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=2,
        circle_spacing=12.0,
        ray_offset=12.0,
        ray_count=36,
        top_gap_distance=0.0,
        capsule_axis_gap_above_distance=18.0,
        capsule_axis_gap_below_distance=18.0,
        air_duct_enabled=True,
        air_duct_base_plate_margin=8.0,
    )
    placements = circle_generator.compute_placements(doc, handles, params, closed=True)
    kept_items, _ = circle_generator._overlap_pruned_circle_items(
        doc,
        handles,
        params,
        placements,
    )
    grouped, total_length = circle_generator._air_duct_group_records(
        doc,
        handles,
        params,
        placements,
        kept_items,
    )
    region_data = circle_generator._air_duct_base_plate_region_data(
        grouped,
        total_length,
        params,
    )
    flat_bounds = circle_generator._air_duct_base_plate_flat_bounds_from_regions(region_data)

    contours = circle_generator._air_duct_base_plate_contours(
        doc,
        handles,
        params,
        placements,
        kept_items,
    )
    by_region = {contour["region"]: contour["points"] for contour in contours}

    assert {"upper_outer", "upper_inner", "lower_inner", "lower_outer"} <= set(by_region)
    ordered_regions = sorted(
        region_data,
        key=lambda region: region_data[region]["center_y"],
        reverse=True,
    )
    for upper_region, lower_region in zip(ordered_regions, ordered_regions[1:]):
        expected_split = (
            region_data[upper_region]["min_y"]
            + region_data[lower_region]["max_y"]
        ) * 0.5

        assert abs(flat_bounds[upper_region][0] - expected_split) < 1e-6
        assert abs(flat_bounds[lower_region][1] - expected_split) < 1e-6
        assert abs(min(point.y for point in by_region[upper_region]) - expected_split) < 1e-6
        assert abs(max(point.y for point in by_region[lower_region]) - expected_split) < 1e-6

        upper_split_points = [
            point
            for point in by_region[upper_region]
            if abs(point.y - expected_split) < 1e-6
        ]
        lower_split_points = [
            point
            for point in by_region[lower_region]
            if abs(point.y - expected_split) < 1e-6
        ]
        assert len(upper_split_points) >= 2
        assert len(lower_split_points) >= 2
        assert abs(min(point.x for point in upper_split_points) - min(point.x for point in lower_split_points)) < 1e-6
        assert abs(max(point.x for point in upper_split_points) - max(point.x for point in lower_split_points)) < 1e-6


def test_air_duct_base_plate_end_cap_stays_near_real_tip_width():
    component = [
        Vec2(-5.0, 0.0),
        Vec2(-42.0, 45.0),
        Vec2(0.0, 100.0),
        Vec2(42.0, 45.0),
        Vec2(5.0, 0.0),
    ]

    plate = circle_generator._air_duct_base_plate_polygon(
        [component],
        margin=10.0,
        radius=3.0,
    )
    top_y = max(point.y for point in plate)
    bottom_y = min(point.y for point in plate)
    top_points = [point for point in plate if abs(point.y - top_y) < 1e-6]
    bottom_points = [point for point in plate if abs(point.y - bottom_y) < 1e-6]

    assert 1 <= len(top_points) <= 2
    assert 1 <= len(bottom_points) <= 2
    assert all(
        air_duct_point_inside_or_on(point, plate)
        for point in component
    )
    if len(top_points) == 2:
        assert max(point.x for point in top_points) - min(point.x for point in top_points) <= 20.0
    if len(bottom_points) == 2:
        assert max(point.x for point in bottom_points) - min(point.x for point in bottom_points) <= 20.0


def test_air_duct_base_plate_tip_does_not_create_artificial_square_tab():
    component = [
        Vec2(-32.0, 0.0),
        Vec2(-24.0, 35.0),
        Vec2(-8.0, 72.0),
        Vec2(0.0, 84.0),
        Vec2(8.0, 72.0),
        Vec2(24.0, 35.0),
        Vec2(32.0, 0.0),
    ]

    plate = circle_generator._air_duct_base_plate_polygon(
        [component],
        margin=18.0,
        radius=3.5,
    )

    top_y = max(point.y for point in plate)
    top_points = [point for point in plate if abs(point.y - top_y) < 1e-6]

    assert 1 <= len(top_points) <= 2
    if len(top_points) == 2:
        assert max(point.x for point in top_points) - min(point.x for point in top_points) <= 1e-3


def test_air_duct_end_gap_bridges_top_gap_smoothly():
    records = []
    for index, (x, y) in enumerate([
        (-18.0, 82.0),
        (-42.0, 54.0),
        (-50.0, 12.0),
        (50.0, 12.0),
        (42.0, 54.0),
        (18.0, 82.0),
    ]):
        near = Vec2(x, y)
        far = Vec2(x * 0.55, y - 28.0)
        records.append({
            "near": near,
            "far": far,
            "near_center": near,
            "far_center": far,
            "circle_centers": [near, far],
            "radius": 2.0,
            "width": (far - near).magnitude,
            "source_distance": float(index * 20),
            "source_point": near,
        })

    params = CircleParams(circle_radius=2.0, top_gap_distance=80.0)
    bridged = circle_generator._bridge_air_duct_end_gap_records(
        records,
        "upper",
        params,
    )
    polygon = circle_generator._air_duct_component_polygon(bridged)
    bridge_points = [
        record["source_point"]
        for record in bridged[len(records):]
    ]

    assert len(bridged) > len(records)
    assert any(abs(point.x) <= 2.0 for point in bridge_points)
    assert max(point.y for point in bridge_points) > max(record["source_point"].y for record in records)
    assert max(point.y for point in polygon) > 82.0


def test_air_duct_base_plate_samples_are_symmetric_for_tip_gaps():
    component = [
        Vec2(-70.0, 0.0),
        Vec2(-52.0, 48.0),
        Vec2(-18.0, 96.0),
        Vec2(16.0, 94.0),
        Vec2(45.0, 45.0),
        Vec2(62.0, 0.0),
    ]

    plate = circle_generator._air_duct_base_plate_polygon(
        [component],
        margin=12.0,
        radius=3.5,
        extent_polygons=[component],
    )

    assert plate
    min_x = min(point.x for point in plate)
    max_x = max(point.x for point in plate)
    center_x = (min(point.x for point in component) + max(point.x for point in component)) * 0.5
    assert abs(((min_x + max_x) * 0.5) - center_x) < 0.1


def test_air_duct_base_plate_end_cap_does_not_fold_inward():
    component = [
        Vec2(400.0, 0.0),
        Vec2(290.0, 10.0),
        Vec2(250.0, 40.0),
        Vec2(630.0, 40.0),
        Vec2(590.0, 10.0),
        Vec2(480.0, 0.0),
    ]

    plate = circle_generator._air_duct_base_plate_polygon(
        [component],
        margin=20.0,
        radius=3.5,
    )

    assert len(plate) >= 4
    bottom_y = min(point.y for point in plate)
    bottom_points = [point for point in plate if abs(point.y - bottom_y) < 1e-6]
    assert len(bottom_points) == 2

    bottom_left = bottom_points[0]
    bottom_right = bottom_points[1]
    assert plate[1].x < bottom_left.x - 1e-6
    assert plate[-2].x > bottom_right.x + 1e-6


def test_dense_air_duct_region_outputs_single_merged_slot_outline():
    records = []
    for index in range(48):
        x = float(index * 5)
        near = Vec2(x, 10.0 + math.sin(index / 8.0) * 3.0)
        far = Vec2(x, 42.0 + math.sin(index / 8.0) * 3.0)
        records.append({
            "near": near,
            "far": far,
            "near_center": near,
            "far_center": far,
            "circle_centers": [near + (far - near) * 0.5],
            "radius": 2.0,
            "width": (far - near).magnitude,
            "source_distance": float(index * 5),
            "source_point": Vec2(x, 0.0),
        })

    params = CircleParams(circle_radius=2.0, air_duct_inlet_distance=8.0)
    contours = circle_generator._air_duct_region_contours(
        records,
        total_length=300.0,
        params=params,
        region="upper",
    )

    assert len(contours) == 1
    assert contours[0]["role"] == "outline_0"
    assert len(contours[0]["points"]) > len(records)


def test_air_duct_end_cap_integrates_inlet_without_standalone_rectangle():
    records = []
    for index in range(41):
        t = index / 40.0
        x = -100.0 + t * 200.0
        y = 40.0 + (1.0 - abs(t - 0.5) * 2.0) * 90.0
        near = Vec2(x, y)
        far = Vec2(x * 0.72, y - 32.0)
        records.append({
            "near": near,
            "far": far,
            "near_center": near,
            "far_center": far,
            "circle_centers": [near, near + (far - near) * 0.5, far],
            "radius": 2.0,
            "width": (far - near).magnitude,
            "source_distance": float(index * 5),
            "source_point": near,
        })

    params = CircleParams(circle_radius=2.0, air_duct_inlet_distance=8.0)
    contours = circle_generator._air_duct_region_contours(
        records,
        total_length=260.0,
        params=params,
        region="upper_outer",
    )

    assert len(contours) == 2
    assert all(contour["role"].startswith("outline") for contour in contours)
    assert {
        1 if circle_generator._polygon_signed_area(contour["points"]) > 0 else -1
        for contour in contours
    } == {-1, 1}
    assert any(
        min(point.y for point in contour["points"]) <= 41.0
        and max(point.y for point in contour["points"]) >= 130.0
        for contour in contours
    )
    assert all(len(contour["points"]) > 8 for contour in contours)
    assert not any(
        len(contour["points"]) <= 5
        and 10.0 <= min(point.y for point in contour["points"]) <= 25.0
        and 45.0 <= max(point.y for point in contour["points"]) <= 60.0
        for contour in contours
    )


def test_air_duct_axis_gap_splits_into_four_independent_regions():
    doc = make_rect_doc()
    handles = [entity.dxf.handle for entity in doc.modelspace()]
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=2,
        circle_spacing=12.0,
        ray_offset=12.0,
        ray_count=36,
        top_gap_distance=0.0,
        capsule_axis_gap_above_distance=18.0,
        capsule_axis_gap_below_distance=18.0,
        air_duct_enabled=True,
    )
    placements = circle_generator.compute_placements(doc, handles, params, closed=True)
    kept_items, _ = circle_generator._overlap_pruned_circle_items(
        doc,
        handles,
        params,
        placements,
    )

    contours = circle_generator._air_duct_contours(
        doc,
        handles,
        params,
        placements,
        kept_items,
    )
    by_region = {}
    for contour in contours:
        by_region.setdefault(contour["region"], []).append(contour)

    assert set(by_region) == {"upper_outer", "upper_inner", "lower_inner", "lower_outer"}
    assert all(by_region[region] for region in by_region)


def test_air_duct_simple_mode_uses_one_unpartitioned_region():
    doc = make_rect_doc()
    handles = [entity.dxf.handle for entity in doc.modelspace()]
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=2,
        circle_spacing=12.0,
        ray_offset=12.0,
        ray_count=36,
        top_gap_distance=0.0,
        capsule_axis_gap_above_distance=18.0,
        capsule_axis_gap_below_distance=18.0,
        air_duct_enabled=True,
        air_duct_simple_mode=True,
    )
    placements = circle_generator.compute_placements(doc, handles, params, closed=True)
    kept_items, _ = circle_generator._overlap_pruned_circle_items(
        doc,
        handles,
        params,
        placements,
    )

    contours = circle_generator._air_duct_contours(
        doc,
        handles,
        params,
        placements,
        kept_items,
    )
    base_plates = circle_generator._air_duct_base_plate_contours(
        doc,
        handles,
        params,
        placements,
        kept_items,
    )

    assert contours
    assert base_plates
    assert {contour["region"] for contour in contours} == {"simple"}
    assert {contour["region"] for contour in base_plates} == {"simple"}


def test_dense_split_air_duct_region_bridges_sides_as_single_outline():
    records = []
    for side_x, distance_base in [(0.0, 0.0), (120.0, 1000.0)]:
        for index in range(24):
            y = float(index * 5)
            near = Vec2(side_x, y)
            far = Vec2(side_x + 18.0, y)
            records.append({
                "near": near,
                "far": far,
                "near_center": near,
                "far_center": far,
                "circle_centers": [near + (far - near) * 0.5],
                "radius": 2.0,
                "width": (far - near).magnitude,
                "source_distance": distance_base + index * 5.0,
                "source_point": near,
            })

    params = CircleParams(circle_radius=2.0, air_duct_inlet_distance=12.0)
    contours = circle_generator._air_duct_region_contours(
        records,
        total_length=2000.0,
        params=params,
        region="upper_inner",
    )

    assert len(contours) == 1
    assert len(contours[0]["points"]) > 24
    xs = {round(point.x, 3) for point in contours[0]["points"]}
    ys = {round(point.y, 3) for point in contours[0]["points"]}
    assert len(xs) > 4
    assert len(ys) > 4


def test_generate_circles_exports_air_duct_layer():
    doc = make_rect_doc()
    handles = [entity.dxf.handle for entity in doc.modelspace()]
    params = CircleParams(
        circle_radius=2.0,
        circles_per_ray=2,
        circle_spacing=12.0,
        ray_offset=12.0,
        ray_count=12,
        top_gap_distance=0.0,
        air_duct_enabled=True,
    )

    circle_generator.generate_circles(doc, handles, params, closed=True)

    air_duct_entities = [
        entity
        for entity in doc.modelspace()
        if entity.dxf.layer == AIR_DUCT_LAYER
    ]
    assert air_duct_entities
    assert all(entity.dxftype() == "LWPOLYLINE" and entity.closed for entity in air_duct_entities)

    base_plate_entities = [
        entity
        for entity in doc.modelspace()
        if entity.dxf.layer == AIR_DUCT_BASE_PLATE_LAYER
    ]
    assert base_plate_entities
    assert all(
        entity.dxftype() == "LWPOLYLINE" and entity.closed
        for entity in base_plate_entities
    )
