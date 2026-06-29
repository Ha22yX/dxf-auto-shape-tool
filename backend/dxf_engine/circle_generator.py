"""Generate circles and rays along normal directions from selected edge chain."""
from typing import List, Tuple
import ezdxf
from ezdxf.math import Vec2

from backend.state import CircleParams
from backend.config import GENERATED_LAYER, RAY_LAYER
from backend.dxf_engine import geometry_utils as geom


def generate_circles(doc: ezdxf.document.Drawing, chain: List[str], params: CircleParams, closed: bool = False) -> Tuple[List[str], List[str]]:
    """
    Generate circles and rays on rays perpendicular to the selected chain.
    Returns (circle_handles, ray_handles).
    """
    if not chain or params.ray_count <= 0 or params.circles_per_ray <= 0:
        return [], []

    msp = doc.modelspace()
    if GENERATED_LAYER not in doc.layers:
        doc.layers.add(GENERATED_LAYER)
    if RAY_LAYER not in doc.layers:
        doc.layers.add(RAY_LAYER)

    # Sample points evenly along the chain
    samples = geom.sample_chain(doc, chain, params.ray_count, closed=closed)

    if not samples:
        return [], []

    # Orient normals consistently along the chain.
    # For closed chains use signed-area based inward/outward.
    # For open chains the raw left-of-tangent normals already define a
    # consistent side along the traversal direction.
    # A single standalone ARC is special-cased: "inward" points toward the
    # arc center, while "outward" points away from it.
    if closed:
        oriented_normals = geom.orient_normals_for_closed_chain(
            samples,
            inward=(params.ray_direction == "inward"),
        )
    else:
        oriented_normals = [s.normal for s in samples]
        is_single_arc = (
            len(chain) == 1
            and doc.entitydb.get(chain[0])
            and doc.entitydb[chain[0]].dxftype() == "ARC"
        )
        if params.ray_direction == "inward":
            if is_single_arc:
                # Standalone ARC raw normals point outward; flip to inward.
                oriented_normals = [-n for n in oriented_normals]
        else:  # outward
            if not is_single_arc:
                oriented_normals = [-n for n in oriented_normals]

    circle_handles = []
    ray_handles = []

    for sample, normal in zip(samples, oriented_normals):
        # Ray start point = sample point + normal * ray_offset
        ray_start = sample.point + normal * params.ray_offset

        # Generate circles along the ray
        last_circle_center = None
        for k in range(params.circles_per_ray):
            center = ray_start + normal * (k * params.circle_spacing)
            circle = msp.add_circle(
                center=(center.x, center.y),
                radius=params.circle_radius,
                dxfattribs={"layer": GENERATED_LAYER},
            )
            circle_handles.append(circle.dxf.handle)
            last_circle_center = center

        # Draw ray line from start to farthest circle center
        if last_circle_center is not None:
            ray = msp.add_line(
                start=(ray_start.x, ray_start.y),
                end=(last_circle_center.x, last_circle_center.y),
                dxfattribs={"layer": RAY_LAYER},
            )
            ray_handles.append(ray.dxf.handle)

    return circle_handles, ray_handles
