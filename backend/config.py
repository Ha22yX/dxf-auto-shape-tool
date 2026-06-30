import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# SVG export settings
SVG_WIDTH = 1200
SVG_HEIGHT = 800
SVG_MARGIN = 20

# Default circle generation parameters
DEFAULT_PARAMS = {
    "circle_radius": 3.5,
    "circles_per_ray": 3,
    "circle_spacing": 17.5,
    "ray_offset": 75.0,
    "capsule_start_distance": 10.0,
    "capsule_clearance_distance": 2.0,
    "capsule_axis_gap_above_distance": 0.0,
    "capsule_axis_gap_below_distance": 0.0,
    "top_gap_distance": 40.0,
    "ray_count": 200,
    "ray_direction": "inward",  # "inward" or "outward"
    "dedupe_closed_rays": True,
}

# Selection / geometry tolerances
POINT_TOLERANCE = 1e-4
CLICK_TOLERANCE_PIXELS = 8
MIN_ENTITY_LENGTH = 1e-6

# Generated circles layer
GENERATED_LAYER = "GENERATED_CIRCLES"
RAY_LAYER = "GENERATED_RAYS"
SELECTED_HIGHLIGHT_COLOR = "#00BFFF"
