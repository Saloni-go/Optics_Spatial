"""Re-run the R2 timings after the R2 fix (each cell takes the ray closest to its centre).

E1 (size, 0.25-64 M cells): R2 only.  The old-rule R2 rows are moved to benchmark_raw_r2_old.csv first,
so analysis sees only the fixed R2 and the old numbers stay for comparison.
E2 (range) and E5 (clipping): R2 and GDAL, so both are on the same machine.

Run:  OPTICS_RESULTS=results/linux64 OPTICS_BENCH_SIZES=500,1000,2000,4000,8000 python3 -m radar.rerun_r2
"""
import csv

from common.bench import run_series
from radar.benchmark import CSV, OUT, e1, e2, e5


def move_old_r2():
    if not CSV.exists():
        return
    rows = list(csv.DictReader(open(CSV)))
    old = [r for r in rows if r["algorithm"] == "r2" and r["experiment"] == "E1_size"]
    if not old:
        return
    keep = [r for r in rows if r not in old]
    oldp = OUT / "benchmark_raw_r2_old.csv"
    for path, rs in ((oldp, old), (CSV, keep)):
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rs)
    print(f"moved {len(old)} old R2 rows to {oldp.name}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    move_old_r2()
    jobs = [j for j in e1(5) if j["algorithm"] == "r2"] + e2(5) + e5(5)
    for j in jobs:
        if "algorithm_impl" in j:
            j["impl"] = j.pop("algorithm_impl")
    run_series("radar.jobs", jobs, CSV, repeats=5)
