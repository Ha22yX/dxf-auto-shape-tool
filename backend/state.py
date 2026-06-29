from dataclasses import dataclass, field
from typing import Optional
import ezdxf
from ezdxf.math import Matrix44

from backend.config import DEFAULT_PARAMS


@dataclass
class CircleParams:
    circle_radius: float = DEFAULT_PARAMS["circle_radius"]
    circles_per_ray: int = DEFAULT_PARAMS["circles_per_ray"]
    circle_spacing: float = DEFAULT_PARAMS["circle_spacing"]
    ray_offset: float = DEFAULT_PARAMS["ray_offset"]
    ray_count: int = DEFAULT_PARAMS["ray_count"]
    ray_direction: str = DEFAULT_PARAMS["ray_direction"]
    dedupe_closed_rays: bool = DEFAULT_PARAMS["dedupe_closed_rays"]

    @classmethod
    def from_dict(cls, data: dict) -> "CircleParams":
        return cls(
            circle_radius=float(data.get("circle_radius", DEFAULT_PARAMS["circle_radius"])),
            circles_per_ray=int(data.get("circles_per_ray", DEFAULT_PARAMS["circles_per_ray"])),
            circle_spacing=float(data.get("circle_spacing", DEFAULT_PARAMS["circle_spacing"])),
            ray_offset=float(data.get("ray_offset", DEFAULT_PARAMS["ray_offset"])),
            ray_count=int(data.get("ray_count", DEFAULT_PARAMS["ray_count"])),
            ray_direction=str(data.get("ray_direction", DEFAULT_PARAMS["ray_direction"])),
            dedupe_closed_rays=bool(data.get("dedupe_closed_rays", DEFAULT_PARAMS["dedupe_closed_rays"])),
        )

    def to_dict(self) -> dict:
        return {
            "circle_radius": self.circle_radius,
            "circles_per_ray": self.circles_per_ray,
            "circle_spacing": self.circle_spacing,
            "ray_offset": self.ray_offset,
            "ray_count": self.ray_count,
            "ray_direction": self.ray_direction,
            "dedupe_closed_rays": self.dedupe_closed_rays,
        }


@dataclass
class SessionState:
    session_id: str
    original_doc: ezdxf.document.Drawing
    working_doc: ezdxf.document.Drawing
    selected_handles: list[str] = field(default_factory=list)
    selected_chain: list[str] = field(default_factory=list)
    generated_handles: list[str] = field(default_factory=list)
    generated_ray_handles: list[str] = field(default_factory=list)
    entity_svg_transform: Matrix44 = field(default_factory=Matrix44)
    params: CircleParams = field(default_factory=CircleParams)
    original_bounds: dict = field(default_factory=dict)
    show_generated: bool = True
    svg_string_generated: str = ""
    svg_string_original: str = ""
    chain_info: dict = field(default_factory=dict)
    # New: accurate base SVG (from ezdxf.addons.drawing) and its WCS->SVG transform.
    base_svg_string: str = ""
    svg_bounds: dict = field(default_factory=dict)
    svg_scale: float = 1.0
    # New: lightweight overlay geometry for real-time preview (no DXF mutation).
    preview_geometry: dict = field(default_factory=dict)



# In-memory session store. For multi-user production, replace with Redis + disk.
SESSION_STORE: dict[str, SessionState] = {}


def get_session(session_id: str) -> Optional[SessionState]:
    return SESSION_STORE.get(session_id)


def create_session(session_id: str, state: SessionState) -> None:
    SESSION_STORE[session_id] = state


def delete_session(session_id: str) -> None:
    SESSION_STORE.pop(session_id, None)
