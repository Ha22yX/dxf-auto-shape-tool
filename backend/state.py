from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    capsule_start_distance: float = DEFAULT_PARAMS["capsule_start_distance"]
    capsule_axis_gap_distance: float = DEFAULT_PARAMS["capsule_axis_gap_distance"]
    top_gap_distance: float = DEFAULT_PARAMS["top_gap_distance"]
    ray_count: int = DEFAULT_PARAMS["ray_count"]
    ray_direction: str = DEFAULT_PARAMS["ray_direction"]
    dedupe_closed_rays: bool = DEFAULT_PARAMS["dedupe_closed_rays"]

    @classmethod
    def from_dict(cls, data: dict) -> "CircleParams":
        ray_offset = float(data.get("ray_offset", DEFAULT_PARAMS["ray_offset"]))
        capsule_start_distance = float(data.get(
            "capsule_start_distance",
            DEFAULT_PARAMS["capsule_start_distance"],
        ))
        capsule_start_distance = max(0.1, min(capsule_start_distance, max(0.1, ray_offset)))
        return cls(
            circle_radius=float(data.get("circle_radius", DEFAULT_PARAMS["circle_radius"])),
            circles_per_ray=int(data.get("circles_per_ray", DEFAULT_PARAMS["circles_per_ray"])),
            circle_spacing=float(data.get("circle_spacing", DEFAULT_PARAMS["circle_spacing"])),
            ray_offset=ray_offset,
            capsule_start_distance=capsule_start_distance,
            capsule_axis_gap_distance=max(0.0, float(data.get(
                "capsule_axis_gap_distance",
                DEFAULT_PARAMS["capsule_axis_gap_distance"],
            ))),
            top_gap_distance=float(data.get("top_gap_distance", DEFAULT_PARAMS["top_gap_distance"])),
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
            "capsule_start_distance": self.capsule_start_distance,
            "capsule_axis_gap_distance": self.capsule_axis_gap_distance,
            "top_gap_distance": self.top_gap_distance,
            "ray_count": self.ray_count,
            "ray_direction": self.ray_direction,
            "dedupe_closed_rays": self.dedupe_closed_rays,
        }


@dataclass
class SessionState:
    session_id: str
    original_doc: ezdxf.document.Drawing
    working_doc: ezdxf.document.Drawing
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    selected_handles: list[str] = field(default_factory=list)
    selected_chain: list[str] = field(default_factory=list)
    manual_apex_distance: Optional[float] = None
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
    state = SESSION_STORE.get(session_id)
    if state:
        state.last_accessed_at = datetime.now(timezone.utc)
    return state


def create_session(session_id: str, state: SessionState) -> None:
    SESSION_STORE[session_id] = state


def delete_session(session_id: str) -> None:
    SESSION_STORE.pop(session_id, None)


def delete_other_sessions(active_session_id: str) -> list[str]:
    removed = []
    for session_id in list(SESSION_STORE.keys()):
        if session_id == active_session_id:
            continue
        SESSION_STORE.pop(session_id, None)
        removed.append(session_id)
    return removed


def prune_sessions(max_age_seconds: int) -> list[str]:
    now = datetime.now(timezone.utc)
    removed = []
    for session_id, state in list(SESSION_STORE.items()):
        age = (now - state.last_accessed_at).total_seconds()
        if age > max_age_seconds:
            SESSION_STORE.pop(session_id, None)
            removed.append(session_id)
    return removed
