"""Shared conventions for all three tracks (Phase 0 decisions).

Every track imports from here so the DEMs, units and visibility assumptions are identical.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"

# ---- DEM -----------------------------------------------------------------
# Copernicus GLO-30 DSM (30 m), Garhwal Himalaya, Uttarakhand.
CRS_EPSG = 32644                 # WGS 84 / UTM zone 44N, metres
CELL = 30.0                      # metres, same for every size (coverage grows, resolution fixed)
CENTER_LONLAT = (78.98, 30.285)  # Rudraprayag; all subsets are centred here
SIZES = [500, 1000, 2000, 4000]  # cells per side -> 0.25M, 1M, 4M, 16M cells
NODATA = -9999.0
COP_TILES = [(29, 78), (29, 79), (30, 78), (30, 79)]  # (lat, lon) of 1x1 degree tiles


def dem_path(size):
    return DATA / f"dem_{size}.tif"


# ---- visibility model ------------------------------------------------------
# Observer/target heights are metres above ground. Earth curvature with standard
# atmospheric refraction: effective drop = d^2 / (2 R) * (1 - k), k = 0.13 (GDAL default
# curvature coefficient 0.85714 = 1 - 1/7 is the same convention).
EARTH_R = 6371000.0
REFRACTION_K = 1.0 / 7.0
CURV_COEFF = 1.0 - REFRACTION_K   # passed to gdal_viewshed as -cc

RADAR_HEIGHT = 30.0       # radar mast height above ground (m)
TARGET_GROUND = 0.0       # "terrain cell visible" means the ground surface itself is visible
TARGET_AIRCRAFT = 150.0   # low-flying aircraft height above ground used for radar exposure (Track 3)
RADAR_RANGE = 30000.0     # default radar range (m)

FLIGHT_AGL = 300.0        # default flight clearance above ground (Track 2)
FLIGHT_RADIUS = 20000.0   # default sensor/visibility radius from the aircraft (m)
WAYPOINT_SPACING = 1000.0 # default spacing between sampled flight positions (m)

# Visible-cell encoding in all output rasters
VISIBLE, INVISIBLE, OUT_OF_RANGE = 1, 0, 255
