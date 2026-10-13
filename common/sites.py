"""Radar sites shared by Track 1 (coverage maps) and Track 3 (exposure cost).

Deterministic rule so every track can rebuild them without depending on another track's output:
ridge-top local maxima (highest cell in a 3 km window) between 1500 and 3200 m (reachable, below
the snow line), picked highest-first with at least 22 km between sites, inside the 4000 DEM with a
10 km margin.  Saved to results/shared/radars.geojson.
"""
import json
import numpy as np
from scipy.ndimage import maximum_filter

from common.config import RESULTS, dem_path, RADAR_HEIGHT
from common.dem_utils import DEM, write_points_geojson

SITES_FILE = RESULTS / "shared" / "radars.geojson"


def choose_sites(n=6, zmin=1500.0, zmax=3200.0, min_sep=22000.0, margin=10000.0):
    dem = DEM(dem_path(4000))
    z = np.nan_to_num(dem.z, nan=-1)
    peaks = (z == maximum_filter(z, size=101)) & (z >= zmin) & (z <= zmax)
    m = int(margin / dem.cell)
    peaks[:m] = peaks[-m:] = False; peaks[:, :m] = peaks[:, -m:] = False
    rr, cc = np.nonzero(peaks)
    order = np.argsort(-z[rr, cc])
    chosen = []
    for k in order:
        x, y = dem.to_world(cc[k], rr[k])
        if all(np.hypot(x - a, y - b) >= min_sep for a, b, _ in chosen):
            chosen.append((x, y, float(z[rr[k], cc[k]])))
        if len(chosen) == n:
            break
    return chosen


def load_sites():
    if not SITES_FILE.exists():
        SITES_FILE.parent.mkdir(parents=True, exist_ok=True)
        s = choose_sites()
        write_points_geojson(SITES_FILE, [(x, y) for x, y, _ in s],
                             [{"id": f"R{i + 1}", "ground_m": z, "mast_m": RADAR_HEIGHT} for i, (x, y, z) in enumerate(s)])
    fc = json.load(open(SITES_FILE))
    return [(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1], f["properties"]) for f in fc["features"]]


if __name__ == "__main__":
    for s in load_sites():
        print(s)
