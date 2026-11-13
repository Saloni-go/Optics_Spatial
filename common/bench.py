"""Benchmark harness shared by all tracks.

Each measured run executes in a *fresh Python process* so that peak memory is not polluted by
earlier runs.  The child process reports:
  runtime_s   wall-clock time of the job function (includes the job's own raster I/O)
  compute_s   time of the core algorithm only, when the job reports it
  peak_rss_kb peak working set of the process (psutil peak_wset on Windows = max RSS)
  base_rss_kb working set after imports, before the job (interpreter + numpy + GDAL)
Rows are appended to a CSV that follows the shared results schema in context.md.
"""
import csv
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

import psutil

FIELDS = ["track", "experiment", "algorithm", "dem_id", "width", "height", "cell_size_m", "scenario_id",
          "param_name", "param_value", "waypoints", "radar_count", "graph_nodes", "repeat",
          "runtime_s", "compute_s", "peak_rss_kb", "base_rss_kb", "render_time_s",
          "accuracy_or_quality", "notes", "timestamp"]


def peak_kb():
    """Peak resident memory of this process in KB: peak_wset on Windows, VmHWM on Linux, ru_maxrss on macOS
    (psutil has no peak there; falling back to rss would report the memory in use at the END)."""
    mi = psutil.Process().memory_info()
    if hasattr(mi, "peak_wset"):
        return int(mi.peak_wset / 1024)
    try:                                  # Linux: high-water mark of THIS process image (fresh after exec)
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1])
    except OSError:
        pass
    # macOS / fallback.  Note: on Linux ru_maxrss survives exec, so a child started by a large
    # parent would report the parent's peak - that is why /proc is preferred above.
    import resource, sys
    m = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(m / 1024) if sys.platform == "darwin" else int(m)


def current_kb():
    return int(psutil.Process().memory_info().rss / 1024)


# ------------------------------------------------------------------ child side
def child_main(registry):
    """Entry point of a job process:  python -m <track>.jobs '<json>'"""
    job = json.loads(sys.argv[1])
    fn = registry[job["job"]]
    base = current_kb()
    t0 = time.perf_counter()
    out = fn(job) or {}
    runtime = time.perf_counter() - t0
    out.update({"runtime_s": runtime, "peak_rss_kb": peak_kb(), "base_rss_kb": base})
    print("RESULT:" + json.dumps(out), flush=True)


# ----------------------------------------------------------------- parent side
def run_job(module, job, timeout=3600):
    cmd = [sys.executable, "-m", module, json.dumps(job)]
    env = dict(os.environ)
    root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=root, env=env)
    for line in p.stdout.splitlines()[::-1]:
        if line.startswith("RESULT:"):
            return json.loads(line[7:])
    raise RuntimeError(f"job failed: {job}\nSTDOUT:{p.stdout[-2000:]}\nSTDERR:{p.stderr[-4000:]}")


def run_series(module, jobs, csv_path, repeats=5, row_base=None, verbose=True):
    """Run every job `repeats` times, append raw rows to csv_path, return list of median rows."""
    csv_path = Path(csv_path)
    new = not csv_path.exists()
    medians = []
    with open(csv_path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        for job in jobs:
            reps = job.pop("_repeats", repeats)
            rows = []
            for r in range(reps):
                res = run_job(module, dict(job))
                row = dict(row_base or {})
                row.update({k: v for k, v in job.items() if k in FIELDS})
                row.update({k: v for k, v in res.items() if k in FIELDS})
                row["repeat"] = r
                row["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                extra = {k: v for k, v in res.items() if k not in FIELDS}
                if extra:
                    row["notes"] = json.dumps(extra)
                w.writerow(row); fh.flush()
                rows.append(row)
            med = dict(rows[0])
            for k in ("runtime_s", "compute_s", "peak_rss_kb", "base_rss_kb"):
                vals = [float(x[k]) for x in rows if x.get(k) not in (None, "")]
                if vals:
                    med[k] = statistics.median(vals)
            medians.append(med)
            if verbose:
                print(f"  {job.get('experiment')}/{job.get('algorithm')} {job.get('param_name')}={job.get('param_value')}"
                      f" dem={job.get('dem_id')}: median {med['runtime_s']:.3f}s, peak {med['peak_rss_kb'] / 1024:.0f} MB"
                      f" (n={reps})", flush=True)
    return medians


def machine_info():
    from osgeo import gdal
    import numpy, scipy
    vm = psutil.virtual_memory()
    return {"cpu": platform.processor(), "cores_logical": psutil.cpu_count(), "cores_physical": psutil.cpu_count(False),
            "ram_gb": round(vm.total / 2 ** 30, 1), "os": platform.platform(), "python": platform.python_version(),
            "numpy": numpy.__version__, "scipy": scipy.__version__, "gdal": gdal.__version__}
