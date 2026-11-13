"""Integrated pipeline: all three tracks, every algorithm and benchmark, on the same dataset and machine.

    run.bat -m integration.pipeline                     # everything (about 2-3 h on a 12-core desktop)
    run.bat -m integration.pipeline --list              # the steps
    run.bat -m integration.pipeline --from flight.run_flight
    run.bat -m integration.pipeline --only integration.cross_track
    run.bat -m integration.pipeline --quick             # benchmarks with 1 repeat (smoke test)

Every track runs on the same Copernicus GLO-30 DEMs (500-4000 cells, EPSG:32644, 30 m), the same six shared
radar sites (common/sites.py) and the same visibility model (common/config.py).  Steps run one at a time in
fresh processes, so benchmarks never overlap; the benchmark CSVs are cleared first so every number in
results/ comes from this machine and this commit.  results/integration/run_manifest.json records the git
commit, the machine and each step's exit code and duration; each step's output is in
results/integration/logs/<step>.txt.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "integration"
LOGS = OUT / "logs"


def py(*args):
    return [sys.executable, *args]


# (step id, command, benchmark CSV cleared before the step, benchmark?)
STEPS = [
    ("data.check", py("-c", "from common.config import SIZES, dem_path; missing = [s for s in SIZES if not dem_path(s).exists()]; "
                            "assert not missing, f'missing DEMs {missing}: run run.bat scripts\\\\prepare_data.py'; print('DEMs', SIZES, 'present')"), None, False),
    ("radar.validate", py("-m", "radar.validate"), None, False),
    ("radar.run_radar", py("-m", "radar.run_radar"), None, False),
    ("radar.benchmark", py("-m", "radar.benchmark"), "radar", True),
    ("radar.analysis", py("-m", "radar.analysis"), None, False),
    ("flight.run_flight", py("-m", "flight.run_flight"), None, False),
    ("flight.benchmark", py("-m", "flight.benchmark"), "flight", True),
    ("flight.spacing_study", py("-m", "flight.spacing_study"), None, True),
    ("flight.analysis", py("-m", "flight.analysis"), None, False),
    ("corridor.run_corridor", py("-m", "corridor.run_corridor"), None, False),
    ("corridor.benchmark", py("-m", "corridor.benchmark"), "corridor", True),
    ("corridor.analysis", py("-m", "corridor.analysis"), None, False),
    ("corridor.interactive_bench", py("-m", "corridor.interactive_bench"), None, True),
    ("corridor.extensions_bench", py("-m", "corridor.extensions_bench"), None, True),
    ("corridor.efficiency_bench", py("-m", "corridor.efficiency_bench"), None, True),
    ("corridor.panzoom_bench", py("-m", "corridor.panzoom_bench"), None, True),
    ("integration.cross_track", py("-m", "integration.cross_track"), None, False),
    ("qgis.build_project", [str(ROOT / "run_qgis.bat"), str(ROOT / "qgis" / "build_project.py")], None, False),
    ("qgis.render_bench", [str(ROOT / "run_qgis.bat"), str(ROOT / "qgis" / "render_bench.py")], None, True),
]


def git(*args):
    import shutil
    exe = shutil.which("git") or next((p for p in (r"C:\Program Files\Git\cmd\git.exe", r"C:\Program Files\Gitin\git.exe")
                                       if Path(p).exists()), "git")
    try:
        return subprocess.run([exe, *args], cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=None)
    ap.add_argument("--only", nargs="+", default=None)
    ap.add_argument("--quick", action="store_true", help="benchmarks with one repeat")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    ids = [s[0] for s in STEPS]
    if a.list:
        print("\n".join(ids)); return
    steps = STEPS
    if a.only:
        bad = set(a.only) - set(ids)
        assert not bad, f"unknown steps {bad}"
        steps = [s for s in STEPS if s[0] in a.only]
    elif a.start:
        steps = STEPS[ids.index(a.start):]
    OUT.mkdir(parents=True, exist_ok=True); LOGS.mkdir(exist_ok=True)
    from common.bench import machine_info
    mf = OUT / "run_manifest.json"
    manifest = json.load(open(mf)) if mf.exists() and (a.only or a.start) else {}
    manifest.update({"commit": git("rev-parse", "--short", "HEAD"), "dirty": bool(git("status", "--porcelain")),
                     "machine": machine_info(), "quick": a.quick})
    manifest.setdefault("steps", {})
    log = open(OUT / "pipeline_log.txt", "a", encoding="utf-8")
    t_all = time.time()
    for sid, cmd, clear, bench in steps:
        if clear:
            (ROOT / "results" / clear / "benchmark_raw.csv").unlink(missing_ok=True)
        if bench and a.quick and "--repeats" not in cmd and sid.endswith(".benchmark"):
            cmd = cmd + ["--repeats", "1"]
        stamp = time.strftime("%H:%M:%S")
        print(f"[{stamp}] START {sid}", flush=True); log.write(f"[{stamp}] START {sid}\n"); log.flush()
        t = time.time()
        with open(LOGS / f"{sid}.txt", "w", encoding="utf-8") as f:
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
            rc = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, env=env).returncode
        dt = time.time() - t
        manifest["steps"][sid] = {"exit": rc, "seconds": round(dt, 1), "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
                                  "benchmark": bench}
        if rc == 3221225477 and sid.startswith("qgis."):          # standalone QGIS often crashes in exitQgis()
            manifest["steps"][sid]["note"] = "QGIS crashed on exit (0xC0000005); check that the outputs were written"
        json.dump(manifest, open(mf, "w"), indent=1)
        stamp = time.strftime("%H:%M:%S")
        msg = f"[{stamp}] END   {sid}  exit {rc}  {dt / 60:.1f} min"
        print(msg, flush=True); log.write(msg + "\n"); log.flush()
    if a.only or a.start:                        # partial run: keep the full run's total, add this run's time
        manifest["partial_runs_minutes"] = manifest.get("partial_runs_minutes", []) + [round((time.time() - t_all) / 60, 1)]
    else:
        manifest["total_minutes"] = round((time.time() - t_all) / 60, 1)
    json.dump(manifest, open(mf, "w"), indent=1)
    failed = [s for s, v in manifest["steps"].items() if v["exit"]]
    print("PIPELINE DONE", f"{manifest.get('total_minutes')} min", "failed: " + ", ".join(failed) if failed else "all steps ok")


if __name__ == "__main__":
    main()
