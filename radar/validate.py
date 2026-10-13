"""Track 1 - correctness checks.

1. Synthetic terrains with known answers (flat, valley: everything visible; ridge: everything
   behind a 200 m wall hidden; cone: compared to the exact naive LOS).
2. Real DEM (500 x 500 and 1000 x 1000 with 10 km range): R2 and GDAL against the exact naive
   line-of-sight reference.
Writes results/radar/validation.json and a figure.
"""
import json
import time
import numpy as np

from common.config import DATA, RESULTS, RADAR_HEIGHT, VISIBLE, INVISIBLE, OUT_OF_RANGE, dem_path
from common.dem_utils import DEM
from radar.viewshed import ALGORITHMS, agreement

OUT = RESULTS / "radar"


def synthetic():
    res = {}
    for name in ("flat", "valley", "ridge", "cone"):
        dem = DEM(DATA / "synthetic" / f"{name}.tif")
        n = dem.shape[0]
        # observer: centre for flat/valley/ridge; on the west flank of the cone
        oc, orow = (n // 2 - 70, n // 2) if name == "cone" else (n // 2 - (0 if name != "ridge" else 0), n // 2)
        x, y = dem.to_world(oc, orow)
        res[name] = {}
        outs = {}
        for alg, fn in ALGORITHMS.items():
            t = time.perf_counter()
            v = fn(dem, x, y, RADAR_HEIGHT, 0.0, 0.0, True)
            outs[alg] = v
            m = v != OUT_OF_RANGE
            entry = {"seconds": time.perf_counter() - t, "visible_frac": float((v[m] == VISIBLE).mean())}
            if name in ("flat", "valley"):
                entry["expected"] = "all visible"
                entry["correct_frac"] = float((v[m] == VISIBLE).mean())
            elif name == "ridge":
                west = v[:, :259]; east = v[:, 262:]
                entry["expected"] = "west of wall visible, east of wall hidden"
                ok = np.concatenate([(west[west != OUT_OF_RANGE] == VISIBLE), (east[east != OUT_OF_RANGE] == INVISIBLE)])
                entry["correct_frac"] = float(ok.mean())
            res[name][alg] = entry
        if name == "cone":
            for alg in ("r2", "gdal"):
                res[name][alg].update({"vs_naive": agreement(outs["naive"], outs[alg])})
        np.save(OUT / f"synthetic_{name}_r2.npy", outs["r2"])
    return res


def real():
    res = {}
    for size, rng in ((500, 0.0), (1000, 10000.0)):
        dem = DEM(dem_path(size))
        x, y = dem.to_world(size // 2, size // 2)
        outs = {}
        for alg, fn in ALGORITHMS.items():
            t = time.perf_counter()
            outs[alg] = fn(dem, x, y, RADAR_HEIGHT, 0.0, rng, True)
            print(size, alg, f"{time.perf_counter() - t:.2f}s", flush=True)
        res[f"dem_{size}_range_{int(rng)}"] = {alg: agreement(outs["naive"], outs[alg]) for alg in ("r2", "gdal")}
        np.save(OUT / f"val_{size}_naive.npy", outs["naive"]); np.save(OUT / f"val_{size}_r2.npy", outs["r2"])
        np.save(OUT / f"val_{size}_gdal.npy", outs["gdal"])
    return res


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    s = synthetic()
    for k, v in s.items():
        print(k, {a: round(e.get("correct_frac", e.get("visible_frac")), 4) for a, e in v.items()})
    r = real()
    for k, v in r.items():
        print(k, {a: (round(e["agreement"], 4), round(e["kappa"], 4)) for a, e in v.items()})
    json.dump({"synthetic": s, "real": r}, open(OUT / "validation.json", "w"), indent=1)
