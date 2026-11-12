"""Static configuration for the BurdaSaxla backend."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OSM_RAW = Path(os.environ.get("BURDASAXLA_OSM", DATA_DIR / "osm_raw.json"))
DB_PATH = Path(os.environ.get("BURDASAXLA_DB", DATA_DIR / "burdasaxla.sqlite3"))

# Metric CRS for all distance maths: UTM zone 39N covers Baku.
METRIC_CRS = "EPSG:32639"

ADMIN_TOKEN = os.environ.get("BURDASAXLA_ADMIN_TOKEN", "burdasaxla-admin")

# Roads that get curb segments (both sides modelled).
CURB_HIGHWAYS = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
    "unclassified", "residential", "living_street",
}
# Roads cars may route over (superset of curb roads).
DRIVE_HIGHWAYS = CURB_HIGHWAYS | {"service"}
EXCLUDED_SERVICE = {"parking_aisle", "driveway", "drive-through", "emergency_access"}
# Roads pedestrians may walk along.
NO_WALK_HIGHWAYS = {"motorway", "motorway_link", "trunk_link", "construction", "proposed", "raceway"}

# Default carriageway widths (m) when OSM has no width/lanes tags.
DEFAULT_WIDTH = {
    "motorway": 22, "trunk": 18, "primary": 15, "secondary": 12, "tertiary": 10,
    "unclassified": 7, "residential": 7, "living_street": 5, "service": 5,
}
LANE_WIDTH = 3.25

# Urban speeds (km/h) used for driving-time estimates.
SPEED_KMH = {
    "motorway": 60, "trunk": 45, "primary": 35, "secondary": 30, "tertiary": 28,
    "unclassified": 22, "residential": 20, "living_street": 10, "service": 10,
}

MIN_STOP_LENGTH_M = 7.0  # a car needs ~5 m + margins to pull in and out
