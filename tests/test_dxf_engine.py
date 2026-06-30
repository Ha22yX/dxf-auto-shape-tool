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
from backend.app import upload_dxf, download_dxf, _apply_selection
from backend.config import DEFAULT_PARAMS
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
