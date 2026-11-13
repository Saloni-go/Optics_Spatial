"""Track 2 idea-1 benchmark jobs (one process per run, see common/bench.py)."""
import time

import numpy as np

from common.bench import child_main
from common.config import dem_path, FLIGHT_AGL
from common.dem_utils import DEM
from flight.fast import run_route_fast
from flight.jobs import _route
from flight.route import resample, length
from flight.visibility import AltitudeModel, run_route


def job_fast(j):
    size = int(j["dem_id"])
    t0 = time.perf_counter()
    dem = DEM(dem_path(size))
    t1 = time.perf_counter()
    verts = _route(dem, j)
    am = AltitudeModel(dem, verts, j.get("alt_mode", "agl"), float(j.get("agl", FLIGHT_AGL)), j.get("msl"))
    pts = resample(verts, float(j.get("spacing_m", 500)))
    radius = float(j.get("radius_m", 20000))
    mode = j.get("impl", j["algorithm"])
    tiled = bool(j.get("tiled", False))
    if mode in ("window", "threads", "cached"):          # existing modes, for the same-process comparison
        acc, t = run_route(dem, pts, am, radius, mode=mode, workers=int(j.get("workers", 12)))
    else:
        acc, t = run_route_fast(dem, pts, am, radius, mode=mode, workers=int(j.get("workers", 12)),
                                k=int(j.get("k", 3)), r_near=float(j.get("r_near", 5000)), tiled=tiled)
    seen = acc.count > 0
    res = {"compute_s": t["compute_s"], "io_s": t1 - t0, "waypoints": len(pts), "route_km": length(verts) / 1000,
           "seen_km2": float(seen.sum() * dem.cell ** 2 / 1e6)}
    if tiled:
        res["acc_mb"] = acc.mem_mb(); res["tiles"] = len(acc.tiles)
    else:
        res["acc_mb"] = (acc.count.nbytes + acc.first.nbytes) / 2 ** 20
    if t.get("coarse_build_s"):
        res["coarse_build_s"] = t["coarse_build_s"]
    if j.get("save_union"):
        np.save(j["save_union"], seen)
    return res


if __name__ == "__main__":
    child_main({"fast": job_fast})
