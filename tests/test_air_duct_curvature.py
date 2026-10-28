"""The no-slot bands must retain the curved sides of the duct template."""
import pytest
from ezdxf.math import Vec2
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from backend.dxf_engine import circle_generator as generator
from backend.state import CircleParams


@pytest.mark.parametrize("region,sign", [("upper_inner", 1), ("lower_inner", -1)])
@pytest.mark.parametrize("count", [9, 24])
def test_no_slot_band_preserves_curved_sides_outside_inlet(region, sign, count):
    records = []
    for side in (0, 1):
        for index in range(count):
            y = index * 120.0 / (count - 1)
            x = 0.002 * y * y if side == 0 else 240.0 - 0.002 * y * y
            direction = Vec2(1 if side == 0 else -1, 0)
            near = Vec2(x, sign * y)
            far = near + direction * 18.0
            records.append({
                "near": near, "far": far, "width": 18.0,
                "near_center": near + direction * 2.0,
                "far_center": far - direction * 2.0,
                "radius": 2.0,
                "source_distance": side * 1000.0 + index * 5.0,
                "source_point": near,
            })
    params = CircleParams(circle_radius=2, air_duct_inlet_distance=50)
    components = generator._split_air_duct_components(records, 2000, True)
    margin = params.circle_radius + generator._air_duct_envelope_margin(params.circle_radius)
    sides = [generator._air_duct_component_polygon(c, margin) for c in components]
    inlet = generator._air_duct_inlet_points(records, params, region, sides)
    slot_min_y = min(p.y for p in inlet)
    slot_max_y = max(p.y for p in inlet)
    contours = generator._air_duct_region_contours(records, 2000, params, region)

    assert len(contours) == 1
    actual = Polygon(contours[0]["points"])
    assert actual.is_valid
    sides = generator._expand_air_duct_loops_to_cover_records(sides, records, params.circle_radius)
    expected_sides = unary_union([Polygon(p) for p in sides])
    inlet_band = box(-1000, slot_min_y, 1000, slot_max_y).buffer(1e-6)
    difference = actual.symmetric_difference(expected_sides).difference(inlet_band)
    assert difference.area < 1e-6


@pytest.mark.parametrize("above,below", [(150, 0), (0, 100), (150, 100)])
def test_gap_parameters_preserve_curves_in_preview_and_dxf(above, below):
    import ezdxf
    from backend.config import AIR_DUCT_LAYER

    doc = ezdxf.new()
    entity = doc.modelspace().add_ellipse((0, 0), major_axis=(0, 400), ratio=0.3)
    chain = [entity.dxf.handle]
    params = CircleParams(
        circle_radius=2, ray_offset=20, circle_spacing=10, circles_per_ray=3,
        ray_count=160, top_gap_distance=0, air_duct_inlet_distance=20,
        capsule_axis_gap_above_distance=above,
        capsule_axis_gap_below_distance=below,
    )
    placements, _, blocked, _ = generator._prepare_generation(doc, chain, params, True, None, True)
    assert not blocked
    kept, _ = generator._overlap_pruned_circle_items(doc, chain, params, placements)
    contours = generator._air_duct_contours(doc, chain, params, placements, kept)
    regions = {c["region"] for c in contours}
    if above:
        assert "upper_inner" in regions
    if below:
        assert "lower_inner" in regions
    for contour in contours:
        if contour["region"].endswith("_inner"):
            assert Polygon(contour["points"]).is_valid
            # Genuine curved sides contain many distinct X coordinates, in
            # contrast to the four X values in the bounding-box fallback.
            assert len({round(p.x, 5) for p in contour["points"]}) > 12

    bounds = {"min": [-150, -450], "max": [150, 450]}
    preview = generator.compute_preview_geometry(
        doc, chain, params, True, bounds, 2, require_closed_outline=True,
    )
    assert [p["d"] for p in preview["air_ducts"]] == [
        generator._contour_svg_path(c["points"], bounds, 2) for c in contours
    ]
    generator.generate_circles(doc, chain, params, True, require_closed_outline=True)
    exported = list(doc.modelspace().query(f'LWPOLYLINE[layer=="{AIR_DUCT_LAYER}"]'))
    assert len(exported) == len(contours)
    for entity, contour in zip(exported, contours):
        assert entity.closed
        assert [(p[0], p[1]) for p in entity.get_points()] == [
            (p.x, p.y) for p in contour["points"]
        ]
