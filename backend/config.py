import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# A one-file EXE extracts resources to a temporary directory. Keep runtime
# files outside that directory so logs survive closing the application.
RUNTIME_DIR = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "DXFAutoShapeTool"
    if getattr(sys, "frozen", False) else BASE_DIR
)
TEMP_DIR = RUNTIME_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

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
    "air_duct_enabled": True,
    "air_duct_inlet_distance": 20.0,
    "top_gap_distance": 40.0,
    "ray_count": 200,
    "ray_direction": "inward",  # "inward" or "outward"
    "dedupe_closed_rays": True,
}

# Selection / geometry tolerances
POINT_TOLERANCE = 1e-4
CURVE_TOLERANCE = 0.01  # maximum curve flattening error, in drawing units
CLICK_TOLERANCE_PIXELS = 8
MIN_ENTITY_LENGTH = 1e-6

# Generated circles layer
GENERATED_LAYER = "GENERATED_CIRCLES"
RAY_LAYER = "GENERATED_RAYS"
AIR_DUCT_LAYER = "GENERATED_AIR_DUCTS"
SELECTED_HIGHLIGHT_COLOR = "#00BFFF"

# Automatically extend nearby open outline fragments and add explicit closure edges.
AUTO_JOIN_GAP = 5.0
AUTO_JOIN_RATIO = 0.02
REPAIRED_OUTLINE_LAYER = "AUTO_CLOSED_OUTLINE"
