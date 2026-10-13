"""Track 1 benchmarks.  Raw rows -> results/radar/benchmark_raw.csv (5 repeats, median reported).

  E1 size      DEM 500..4000, unlimited range, radar at centre: naive / r2 / gdal
  E2 range     DEM 4000, range 5..60 km: r2 / gdal (full DEM loaded)
  E3 height    DEM 4000, range 30 km, radar 10..300 m: gdal (coverage changes, cost should not)
  E4 radars    DEM 4000, range 30 km, 1..16 radars: sequential vs 8 processes vs 12 threads
  E5 clipping  DEM 4000, range 10/20/40 km: full DEM read vs window read (region clipping)
  E6 resample  DEM 4000, unlimited range, 30/60/90/120 m cells: gdal (accuracy in analysis.py)

Run:  run.bat -m radar.benchmark [E1 E2 ...] [--repeats 5]
"""
import argparse
import json

from common.bench import run_series, machine_info
from common.config import RESULTS, CELL

OUT = RESULTS / "radar"
CSV = OUT / "benchmark_raw.csv"
SIZES = [500, 1000, 2000, 4000]


def base(size):
    return {"track": "radar", "dem_id": size, "width": size, "height": size, "cell_size_m": CELL}


def e1(rep):
    jobs = []
    for s in SIZES:
        for alg in ("gdal", "r2"):
            jobs.append({**base(s), "job": "viewshed", "experiment": "E1_size", "algorithm": alg,
                         "param_name": "cells", "param_value": s * s, "radar_count": 1, "range_m": 0})
        if s <= 1000:
            jobs.append({**base(s), "job": "viewshed", "experiment": "E1_size", "algorithm": "naive",
                         "param_name": "cells", "param_value": s * s, "radar_count": 1, "range_m": 0,
                         "_repeats": 3})
    return jobs


def e2(rep):
    return [{**base(4000), "job": "viewshed", "experiment": "E2_range", "algorithm": alg, "param_name": "range_km",
             "param_value": r, "range_m": r * 1000, "radar_count": 1}
            for r in (5, 10, 20, 40, 60) for alg in ("gdal", "r2")]


def e3(rep):
    return [{**base(4000), "job": "viewshed", "experiment": "E3_height", "algorithm": "gdal", "param_name": "radar_h_m",
             "param_value": h, "radar_h": h, "range_m": 30000, "radar_count": 1} for h in (10, 30, 100, 300)]


def e4(rep):
    jobs = []
    for k in (1, 2, 4, 8, 16):
        for mode in ("sequential", "parallel8", "threads12"):
            jobs.append({**base(4000), "job": "multi", "experiment": "E4_radars", "algorithm": mode,
                         "param_name": "radar_count", "param_value": k, "radar_count": k, "range_m": 30000,
                         "workers": 12 if mode == "threads12" else 8, "_repeats": 3})
    return jobs


def e5(rep):
    jobs = []
    for r in (10, 20, 40):
        for alg in ("gdal", "r2"):
            for win in (False, True):
                jobs.append({**base(4000), "job": "viewshed", "experiment": "E5_clipping",
                             "algorithm": f"{alg}_{'window' if win else 'full'}", "param_name": "range_km",
                             "param_value": r, "range_m": r * 1000, "windowed": win, "radar_count": 1,
                             "_alg": alg})
    for j in jobs:
        j["algorithm_impl"] = j.pop("_alg")
    return jobs


def e6(rep):
    return [{**base(4000), "job": "viewshed", "experiment": "E6_resample", "algorithm": "gdal",
             "param_name": "cell_m", "param_value": CELL * f, "resample": f, "range_m": 0, "radar_count": 1,
             "cell_size_m": CELL * f} for f in (1, 2, 3, 4)]


EXPS = {"E1": e1, "E2": e2, "E3": e3, "E4": e4, "E5": e5, "E6": e6}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("exps", nargs="*", default=list(EXPS))
    ap.add_argument("--repeats", type=int, default=5)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(machine_info(), open(OUT / "machine.json", "w"), indent=1)
    for e in a.exps:
        print("==", e, flush=True)
        jobs = EXPS[e](a.repeats)
        for j in jobs:  # E5 stores the real algorithm under algorithm_impl
            if "algorithm_impl" in j:
                j["impl"] = j.pop("algorithm_impl")
        run_series("radar.jobs", jobs, CSV, repeats=a.repeats)
