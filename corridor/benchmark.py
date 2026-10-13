"""Track 3 benchmarks.  Raw rows -> results/corridor/benchmark_raw.csv

  C1 size      DEM 500..4000 (diagonal 10% -> 90%), alpha 10, beta 2:
               dijkstra_py, astar_py, dijkstra_csgraph, multires(k=4)
  C2 alpha     DEM 2000, alpha 0..100: astar_py and csgraph (runtime and route trade-off)
  C3 multires  DEM 4000, k = 2, 4, 8 (buffer 3 coarse cells): time vs cost gap
  C4 distance  DEM 2000, endpoints 25..100% of the diagonal: astar_py vs dijkstra_py
  C5 exposure  DEM 4000, 1..16 radars: exposure preprocessing cost
  C6 multi     8 routes on one map: landmark A* (Python) vs SciPy C Dijkstra vs plain A*
  C7 compiled  DEM 500..4000: our C Dijkstra / A* / landmark A* (corridor/c/gridsearch.c) vs Python landmark A*
  C8 multi_c   8 routes on one map with the C solvers (compare with C6)
Exposure surfaces are cached first (results/corridor/cache) so solve timings exclude them.
Run:  run.bat -m corridor.benchmark [C1 ...] [--repeats 5]
"""
import argparse
import json

from common.bench import run_series, machine_info
from common.config import RESULTS, CELL
from corridor.prep import exposure_for

OUT = RESULTS / "corridor"
CSV = OUT / "benchmark_raw.csv"


def base(size, **kw):
    d = {"track": "corridor", "job": "solve", "dem_id": size, "width": size, "height": size, "cell_size_m": CELL,
         "graph_nodes": size * size, "alpha": 10, "beta": 2}
    d.update(kw)
    return d


def c1(r):
    jobs = []
    for s in (500, 1000, 2000, 4000):
        for alg in ("dijkstra_csgraph", "astar_py", "multires", "dijkstra_py"):
            reps = r if s <= 1000 else (3 if s == 2000 else 1)
            jobs.append(base(s, experiment="C1_size", algorithm=alg, param_name="nodes", param_value=s * s, _repeats=reps))
    return jobs


def c2(r):
    return [base(2000, experiment="C2_alpha", algorithm=alg, param_name="alpha", param_value=a, alpha=a,
                 _repeats=3) for a in (0, 1, 3, 10, 30, 100) for alg in ("astar_py", "astar_alt", "dijkstra_csgraph")]


def c3(r):
    return [base(4000, experiment="C3_multires", algorithm="multires", param_name="k", param_value=k, k=k, buffer=3,
                 _repeats=3) for k in (2, 4, 8)]


def c4(r):
    jobs = []
    for f in (0.25, 0.5, 0.75, 1.0):
        f0, f1 = 0.5 - 0.4 * f, 0.5 + 0.4 * f
        for alg in ("astar_py", "dijkstra_py"):
            jobs.append(base(2000, experiment="C4_distance", algorithm=alg, param_name="diag_frac", param_value=f,
                             f0=f0, f1=f1, _repeats=3))
    return jobs


def c5(r):
    return [{"track": "corridor", "job": "exposure", "experiment": "C5_exposure", "algorithm": "gdal_viewshed",
             "dem_id": 4000, "width": 4000, "height": 4000, "cell_size_m": CELL, "param_name": "radar_count",
             "param_value": n, "radar_count": n} for n in (1, 2, 4, 8, 16)]


def c6(r):
    """Many routes on one map: landmark A* (ALT) vs C Dijkstra vs plain A*, 8 queries."""
    jobs = []
    for s in (1000, 2000, 4000):
        for alg in ("csgraph", "alt", "astar"):
            if alg == "astar" and s == 4000:
                continue                                   # ~8 x 55 s; projected from C1 instead
            jobs.append(base(s, job="multi_query", experiment="C6_multi_query", algorithm=alg, param_name="nodes",
                             param_value=s * s, queries=8, landmarks=4, _repeats=1 if s == 4000 else 3))
    return jobs


def c7(r):
    """Compiled solvers (corridor/c/gridsearch.c) against the Python and SciPy ones, all sizes, alpha 10.
    Query time is compute_s; landmark preprocessing is reported separately (pre_s)."""
    jobs = []
    for s in (500, 1000, 2000, 4000):
        for alg in ("dijkstra_c", "astar_c", "alt_c", "astar_alt"):
            reps = r if s <= 1000 else (3 if s == 2000 else (1 if alg == "astar_alt" else 3))
            jobs.append(base(s, experiment="C7_compiled", algorithm=alg, param_name="nodes", param_value=s * s,
                             landmarks=4, threads=8, _repeats=reps))
    return jobs


def c8(r):
    """Eight routes on one map with the compiled solvers (compare with C6)."""
    return [base(s, job="multi_query", experiment="C8_multi_query_c", algorithm=alg, param_name="nodes", param_value=s * s,
                 queries=8, landmarks=4, threads=8, _repeats=1 if s == 4000 else 3)
            for s in (1000, 2000, 4000) for alg in ("dijkstra_c", "alt_c")]


EXPS = {"C1": c1, "C2": c2, "C3": c3, "C4": c4, "C5": c5, "C6": c6, "C7": c7, "C8": c8}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("exps", nargs="*", default=list(EXPS))
    ap.add_argument("--repeats", type=int, default=5)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(machine_info(), open(OUT / "machine.json", "w"), indent=1)
    for s in (500, 1000, 2000, 4000):
        exposure_for(s)
    for e in a.exps:
        print("==", e, flush=True)
        run_series("corridor.jobs", EXPS[e](a.repeats), CSV, repeats=a.repeats)
