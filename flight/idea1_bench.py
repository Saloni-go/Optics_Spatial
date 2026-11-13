"""Track 2 - idea 1 benchmarks (cheaper computation).  Raw rows -> <results>/flight/idea1_raw.csv

  F7 shared     DEM 4000, Alaknanda route, 500 m spacing, 20 km radius:
                window (copy per position) / cached / threads (copy, 12 threads) /
                shared (zero-copy, serial) / shared_threads (zero-copy, 12 threads) - all exact
  F8 multires   same route, valley 300 m AGL and cruise 5500 m MSL: fine 30 m within r_near,
                k-times coarser beyond; k in 2, 3, 4 and r_near in 2, 5, 10 km (accuracy in idea1_analysis)
  F9 memory     DEM 500..4000, F1 workload (route through the centre) and the fixed 12 km route:
                full-map accumulator vs tiled accumulator (peak memory and accumulator MB)
The complexity model (F10) is fitted in flight/idea1_analysis.py from F1-F5 and these runs.
Run:  python3 -m flight.idea1_bench [F7 F8 F9] [--repeats 5]
"""
import argparse
import json

from common.bench import run_series, machine_info
from common.config import RESULTS, CELL

OUT = RESULTS / "flight"
CSV = OUT / "idea1_raw.csv"
UNIONS = OUT / "idea1_unions"


def base(size, **kw):
    d = {"track": "flight", "job": "fast", "dem_id": size, "width": size, "height": size, "cell_size_m": CELL,
         "route": "alaknanda", "spacing_m": 500, "radius_m": 20000}
    d.update(kw)
    return d


def f7(r):
    return [base(4000, experiment="F7_shared", algorithm=m, param_name="mode", param_value=i, workers=12)
            for i, m in enumerate(("window", "cached", "threads", "shared", "shared_threads"))]


def f8(r):
    jobs = []
    for prof, kw in (("valley", {}), ("cruise", {"alt_mode": "msl", "msl": 5500.0})):
        jobs.append(base(4000, experiment=f"F8_multires_{prof}", algorithm="shared_threads", param_name="k",
                         param_value=1, save_union=str(UNIONS / f"{prof}_ref.npy"), **kw))
        for k in (2, 3, 4):
            for rn in (2000, 5000, 10000):
                jobs.append(base(4000, experiment=f"F8_multires_{prof}", algorithm=f"multires_rn{rn // 1000}",
                                 impl="multires_threads", param_name="k", param_value=k, k=k, r_near=rn,
                                 save_union=str(UNIONS / f"{prof}_k{k}_rn{rn}.npy"), **kw))
    return jobs


def f9(r):
    jobs = []
    for s in (500, 1000, 2000, 4000):
        for tiled in (False, True):
            name = "tiled" if tiled else "full"
            jobs.append(base(s, experiment="F9_memory", algorithm=name, impl="shared_threads", route="straight",
                             route_frac=0.8, spacing_m=1000, radius_m=0, tiled=tiled, param_name="cells",
                             param_value=s * s))
            jobs.append(base(s, experiment="F9_memory_fixed_route", algorithm=name, impl="shared_threads",
                             route="straight", route_frac=0.8 * 500 / s, spacing_m=1000, tiled=tiled,
                             param_name="cells", param_value=s * s))
    return jobs


EXPS = {"F7": f7, "F8": f8, "F9": f9}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("exps", nargs="*", default=list(EXPS))
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--fresh", action="store_true", help="delete earlier rows first (one machine per CSV)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True); UNIONS.mkdir(exist_ok=True)
    if a.fresh:
        CSV.unlink(missing_ok=True)
    json.dump(machine_info(), open(OUT / "machine.json", "w"), indent=1)
    for e in a.exps:
        print("==", e, flush=True)
        run_series("flight.jobs_fast", EXPS[e](a.repeats), CSV, repeats=a.repeats)
