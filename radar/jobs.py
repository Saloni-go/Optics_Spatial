"""Track 1 benchmark jobs. Each runs in its own process (see common/bench.py).

    python -m radar.jobs '{"job": "viewshed", "dem_id": 4000, "algorithm": "gdal", ...}'
"""
import time
import numpy as np
from osgeo import gdal

from common.bench import child_main
from common.config import dem_path, RADAR_HEIGHT, VISIBLE, OUT_OF_RANGE, CELL
from common.dem_utils import DEM
from radar.viewshed import ALGORITHMS, window_for


def _xy_center(size):
    p = dem_path(size)
    ds = gdal.Open(str(p)); gt = ds.GetGeoTransform()
    return gt[0] + gt[1] * size / 2, gt[3] + gt[5] * size / 2


def job_viewshed(j):
    """One radar. Options: windowed (read only the range window), resample (coarser cells)."""
    size = int(j["dem_id"]); alg = j.get("impl", j["algorithm"])
    h = float(j.get("radar_h", RADAR_HEIGHT)); rng = float(j.get("range_m", 0)); th = float(j.get("target_h", 0))
    x, y = j.get("x"), j.get("y")
    if x is None:
        x, y = _xy_center(size)
    t0 = time.perf_counter()
    if j.get("resample", 1) > 1:
        f = int(j["resample"])
        mem = gdal.Warp("", str(dem_path(size)), format="MEM", xRes=CELL * f, yRes=CELL * f, resampleAlg="average")
        tmp = "/vsimem/coarse.tif"; gdal.Translate(tmp, mem)
        dem = DEM(tmp)
    elif j.get("windowed") and rng > 0:
        dem = DEM(dem_path(size), window=window_for(dem_path(size), x, y, rng))
    else:
        dem = DEM(dem_path(size))
    t1 = time.perf_counter()
    v = ALGORITHMS[alg](dem, x, y, h, th, rng, True)
    t2 = time.perf_counter()
    m = v != OUT_OF_RANGE
    return {"compute_s": t2 - t1, "io_s": t1 - t0, "visible_frac": float((v[m] == VISIBLE).mean()),
            "cells_processed": int(dem.z.size), "visible_km2": float((v == VISIBLE).sum() * dem.cell ** 2 / 1e6)}


def _one(args):
    size, x, y, h, rng, windowed = args
    p = dem_path(size)
    dem = DEM(p, window=window_for(p, x, y, rng)) if windowed else DEM(p)
    v = ALGORITHMS["gdal"](dem, x, y, h, 0.0, rng, True)
    import os
    from common.bench import peak_kb
    return dem.gt, (v == VISIBLE), os.getpid(), peak_kb()


def job_multi(j):
    """k radars spread on a grid; sequential vs process-pool parallel; union coverage."""
    size = int(j["dem_id"]); k = int(j["radar_count"]); rng = float(j.get("range_m", 30000))
    h = float(j.get("radar_h", RADAR_HEIGHT)); mode = j["algorithm"]
    ds = gdal.Open(str(dem_path(size))); gt = ds.GetGeoTransform()
    g = int(np.ceil(np.sqrt(k)))
    pts = []
    for i in range(k):
        cx = (i % g + 0.5) / g; cy = (i // g + 0.5) / g
        pts.append((gt[0] + gt[1] * size * cx, gt[3] + gt[5] * size * cy))
    args = [(size, x, y, h, rng, True) for x, y in pts]
    t1 = time.perf_counter()
    if mode.startswith("threads"):
        # GDAL releases the GIL inside ViewshedGenerate, so threads run truly in parallel without
        # the cost of starting processes (about 0.9 s each on Windows) or pickling results back
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(int(j.get("workers", 12)), k)) as ex:
            res = list(ex.map(_one, args))
    elif mode.startswith("parallel"):
        from concurrent.futures import ProcessPoolExecutor
        workers = int(j.get("workers", 8))
        with ProcessPoolExecutor(max_workers=min(workers, k)) as ex:
            res = list(ex.map(_one, args))
    else:
        res = [_one(a) for a in args]
    union = np.zeros((size, size), bool)
    workers_peak = {}
    for wgt, vis, pid, pk in res:
        workers_peak[pid] = max(workers_peak.get(pid, 0), pk)
        c0 = int(round((wgt[0] - gt[0]) / gt[1])); r0 = int(round((wgt[3] - gt[3]) / gt[5]))
        union[r0:r0 + vis.shape[0], c0:c0 + vis.shape[1]] |= vis
    t2 = time.perf_counter()
    wsum = sum(workers_peak.values()) if mode.startswith("parallel") else 0   # threads share the process
    return {"compute_s": t2 - t1, "union_visible_frac": float(union.mean()), "workers_peak_kb_sum": wsum,
            "n_workers": len(workers_peak)}


if __name__ == "__main__":
    child_main({"viewshed": job_viewshed, "multi": job_multi})
