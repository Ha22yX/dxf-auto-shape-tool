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
    "circle_radius": 5.0,
    "circles_per_ray": 3,
    "circle_spacing": 15.0,
    "ray_offset": 5.0,
    "ray_count": 10,
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
