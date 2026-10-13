"""Track 2 benchmark jobs (one process per run, see common/bench.py)."""
import time
import numpy as np

from common.bench import child_main
from common.config import dem_path, FLIGHT_AGL, FLIGHT_RADIUS
from common.dem_utils import DEM
from flight.route import load_route, resample, straight_route, length
from flight.visibility import AltitudeModel, run_route, run_adaptive


def _route(dem, j):
    kind = j.get("route", "straight")
    if kind == "alaknanda":
        v = load_route()
        if j.get("route_km"):                       # truncate to the first route_km kilometres
            p = resample(v, 100.0)
            p = p[p[:, 2] <= j["route_km"] * 1000]
            v = [tuple(q[:2]) for q in p]
        return v
    return straight_route(dem, float(j.get("route_frac", 0.8)))


def job_route(j):
    size = int(j["dem_id"])
    t0 = time.perf_counter()
    dem = DEM(dem_path(size))
    t1 = time.perf_counter()
    verts = _route(dem, j)
    radius = float(j.get("radius_m", FLIGHT_RADIUS))
    am = AltitudeModel(dem, verts, j.get("alt_mode", "agl"), float(j.get("agl", FLIGHT_AGL)), j.get("msl"))
    mode = j.get("impl", j["algorithm"])
    if mode.startswith("adaptive"):
        acc, pts, t = run_adaptive(dem, verts, am, radius, coarse=float(j.get("coarse", 4000)),
                                   finest=float(j.get("finest", 250)), tau=float(j.get("tau", 0.85)),
                                   criterion="gain" if mode == "adaptive_gain" else "similarity",
                                   eps=float(j.get("eps", 0.05)))
    else:
        pts = resample(verts, float(j.get("spacing_m", 1000)))
        acc, t = run_route(dem, pts, am, radius, mode=mode, workers=int(j.get("workers", 8)))
    seen = acc.count > 0
    res = {"compute_s": t["compute_s"], "io_s": t1 - t0, "waypoints": t["viewsheds"],
           "route_km": length(verts) / 1000, "seen_km2": float(seen.sum() * dem.cell ** 2 / 1e6)}
    if j.get("save_union"):
        np.save(j["save_union"], seen)
    return res


if __name__ == "__main__":
    child_main({"route": job_route})
