"""Track 2 benchmarks.  Raw rows -> results/flight/benchmark_raw.csv

  F1 size       DEM 500..4000, straight route through the centre (0.8 x width), 1 km spacing,
                unlimited radius: work grows with cells per viewshed AND number of positions
  F1b size_fix  DEM 500..4000, the same 12 km route and 20 km radius for every DEM size
  F2 spacing    DEM 4000, Alaknanda route, spacing 250..4000 m (waypoint count)
  F3 altitude   DEM 4000, Alaknanda route, 100..3000 m AGL
  F4 radius     DEM 4000, Alaknanda route, radius 5..40 km
  F5 length     DEM 4000, Alaknanda route truncated to 25..150 km
  F6 optimise   DEM 4000, Alaknanda route, 500 m spacing, 20 km radius:
                baseline / cached / window / parallel (8 processes) / threads (12) /
                adaptive (similarity, tau 0.85) / adaptive_gain (new-ground criterion, eps 0.05)
Accuracy of the optimisations (adaptive vs dense) is computed in flight/analysis.py.
Run:  run.bat -m flight.benchmark [F1 ...] [--repeats 5]
"""
import argparse
import json

from common.bench import run_series, machine_info
from common.config import RESULTS, CELL

OUT = RESULTS / "flight"
CSV = OUT / "benchmark_raw.csv"


def base(size, **kw):
    d = {"track": "flight", "job": "route", "dem_id": size, "width": size, "height": size, "cell_size_m": CELL,
         "algorithm": "window"}
    d.update(kw)
    return d


def f1(r):
    return [base(s, experiment="F1_size", param_name="cells", param_value=s * s, radius_m=0, spacing_m=1000,
                 route_frac=0.8, _repeats=3 if s == 4000 else r) for s in (500, 1000, 2000, 4000)]


def f1b(r):
    # a 12 km route = 0.8 of the 500-cell DEM (15 km); same physical route for all sizes
    return [base(s, experiment="F1b_size_fixed_route", param_name="cells", param_value=s * s, radius_m=20000,
                 spacing_m=1000, route_frac=0.8 * 500 / s) for s in (500, 1000, 2000, 4000)]


def f2(r):
    return [base(4000, experiment="F2_spacing", route="alaknanda", param_name="spacing_m", param_value=sp,
                 spacing_m=sp, radius_m=20000, save_union=str(OUT / f"union_F2_{sp}.npy"))
            for sp in (250, 500, 1000, 2000, 4000)]


def f3(r):
    return [base(4000, experiment="F3_altitude", route="alaknanda", param_name="agl_m", param_value=a, agl=a,
                 spacing_m=1000, radius_m=20000) for a in (100, 300, 1000, 3000)]


def f4(r):
    return [base(4000, experiment="F4_radius", route="alaknanda", param_name="radius_km", param_value=k,
                 spacing_m=1000, radius_m=k * 1000) for k in (5, 10, 20, 40)]


def f5(r):
    return [base(4000, experiment="F5_length", route="alaknanda", param_name="route_km", param_value=L,
                 route_km=L, spacing_m=1000, radius_m=20000) for L in (25, 50, 100, 150)]


def f6(r):
    jobs = []
    for impl in ("baseline", "cached", "window", "parallel", "threads", "adaptive", "adaptive_gain"):
        jobs.append(base(4000, experiment="F6_optimise", route="alaknanda", algorithm=impl, param_name="mode",
                         param_value=impl, spacing_m=500, radius_m=20000, workers=12 if impl == "threads" else 8,
                         save_union=str(OUT / f"union_F6_{impl}.npy"), _repeats=3 if impl == "baseline" else r))
    return jobs


EXPS = {"F1": f1, "F1b": f1b, "F2": f2, "F3": f3, "F4": f4, "F5": f5, "F6": f6}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("exps", nargs="*", default=list(EXPS))
    ap.add_argument("--repeats", type=int, default=5)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(machine_info(), open(OUT / "machine.json", "w"), indent=1)
    for e in a.exps:
        print("==", e, flush=True)
        run_series("flight.jobs", EXPS[e](a.repeats), CSV, repeats=a.repeats)
