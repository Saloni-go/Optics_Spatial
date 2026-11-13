"""Track 2 - scale test: does the complexity model fitted on 0.25-16 M cells predict a 64 M-cell map?

  predict   BEFORE any 64 M run: write predictions (time and peak memory) for every experiment below to
            <results>/flight/scale/predictions.json, with a timestamp.  Two time models, both fitted only on
            the F1-F5 medians of this machine (window mode):
              v1  T = a*W*min(pi r^2/cell^2, N) + b*W          (the published F10 model)
              v2  T = a*W*mean(A_i) + b*W, A_i = cells of the radius disc that lie inside the map at
                  position i (exact clipping; v1 overestimates near map edges and for large radii)
            Memory: peak MB = c0 + c1*N, fitted on F1 (route grows with the map).
  run       S1  F1 workload on 8000 x 8000 (straight route 0.8 x width, 1 km spacing, unlimited radius):
                window (the fitted mode) and shared_threads (idea 1)
            S2  F1b: the same 12 km route, 20 km radius, on 8000 x 8000
            S3  Alaknanda route, 1 km spacing, radius 20 / 40 / 60 / 80 km on 8000 x 8000 (the fit only saw
                radii up to 40 km), and 60 / 80 km on 4000 x 4000 (disc clipped by the map edge)
  analyse   predicted vs measured, figures, summary
Run:  python3 -m flight.scale_bench predict ; python3 -m flight.scale_bench run ; python3 -m flight.scale_bench analyse
"""
import argparse
import json
import math
import time

import numpy as np

from common.analysis import load, medians
from common.bench import run_series, machine_info
from common.config import RESULTS, CELL, dem_path
from common.plots import plt, save

OUT = RESULTS / "flight" / "scale"
CSV = OUT / "scale_raw.csv"
FIT_CSV = RESULTS / "flight" / "benchmark_raw.csv"


def disc_cells_in_map(rc, cc, R, H, W):
    """Exact number of cells within R cells of (rc, cc) that lie inside an H x W map (row by row)."""
    if R <= 0:
        return H * W
    r0, r1 = max(0, int(math.floor(rc - R))), min(H - 1, int(math.ceil(rc + R)))
    tot = 0
    for r in range(r0, r1 + 1):
        dy = r - rc
        if abs(dy) > R:
            continue
        hw = math.sqrt(R * R - dy * dy)
        c0, c1 = max(0, math.ceil(cc - hw)), min(W - 1, math.floor(cc + hw))
        if c1 >= c0:
            tot += c1 - c0 + 1
    return tot


def workload(size, route, spacing, radius, route_frac=0.8):
    """W positions and the exact mean disc area (cells) for one experiment, from the DEM header only."""
    from osgeo import gdal
    from flight.route import resample, straight_route, load_route
    ds = gdal.Open(str(dem_path(size))); gt = ds.GetGeoTransform(); H, Wd = ds.RasterYSize, ds.RasterXSize

    class _D:                                            # just enough of DEM for straight_route
        shape = (H, Wd); cell = gt[1]
        def to_world(self, c, r):
            return gt[0] + (c + 0.5) * gt[1], gt[3] + (r + 0.5) * gt[5]
    verts = load_route() if route == "alaknanda" else straight_route(_D(), route_frac)
    pts = resample(verts, spacing)
    R = radius / CELL if radius > 0 else 0
    A = []
    for x, y, _ in pts:
        cc, rc = (x - gt[0]) / gt[1] - 0.5, (y - gt[3]) / gt[5] - 0.5
        A.append(disc_cells_in_map(rc, cc, R, H, Wd))
    return len(pts), float(np.mean(A)), H * Wd


def fit_points():
    rows = load(FIT_CSV)
    exps = {"F1_size": ("straight", 1000, 0, None), "F1b_size_fixed_route": ("straight", 1000, 20000, "fixed"),
            "F2_spacing": ("alaknanda", "param", 20000, None), "F3_altitude": ("alaknanda", 1000, 20000, None),
            "F4_radius": ("alaknanda", 1000, "param", None), "F5_length": ("alaknanda", 1000, 20000, "length")}
    pts = []
    for exp, (route, sp, rad, kind) in exps.items():
        for p in medians(rows, exp).get("window", []):
            size = int(math.sqrt(p["param"])) if exp.startswith("F1") else 4000
            spacing = p["param"] if sp == "param" else sp
            radius = p["param"] * 1000 if rad == "param" else rad
            frac = 0.8 * 500 / size if kind == "fixed" else 0.8
            W, Aex, N = workload(size, route, spacing, radius, frac)
            if kind == "length":                         # truncated route: positions are what was measured
                W = p["waypoints"]
            Av1 = N if radius <= 0 else min(math.pi * (radius / CELL) ** 2, N)
            pts.append({"exp": exp, "size": size, "W": W, "A_v1": Av1, "A_v2": Aex, "t": p["compute"], "peak_mb": p["peak_mb"]})
    return pts


def fit(pts, key):
    W = np.array([q["W"] for q in pts], float); A = np.array([q[key] for q in pts], float); t = np.array([q["t"] for q in pts])
    X = np.column_stack([W * A, W]) / t[:, None]
    (a, b), *_ = np.linalg.lstsq(X, np.ones_like(t), rcond=None)
    pred = a * W * A + b * W
    return float(a), float(b), float(100 * np.mean(np.abs(pred - t) / t))


EXPERIMENTS = [  # id, size, route, spacing, radius_m, mode, route_frac
    ("S1_F1_window", 8000, "straight", 1000, 0, "window", 0.8),
    ("S1_F1_shared_threads", 8000, "straight", 1000, 0, "shared_threads", 0.8),
    ("S2_F1b_window", 8000, "straight", 1000, 20000, "window", 0.8 * 500 / 8000),
] + [(f"S3_r{r}_8000", 8000, "alaknanda", 1000, r * 1000, "window", 0.8) for r in (20, 40, 60, 80)] \
  + [(f"S3_r{r}_4000", 4000, "alaknanda", 1000, r * 1000, "window", 0.8) for r in (60, 80)]


def predict():
    OUT.mkdir(parents=True, exist_ok=True)
    pts = fit_points()
    a1, b1, e1 = fit(pts, "A_v1"); a2, b2, e2 = fit(pts, "A_v2")
    f1 = [q for q in pts if q["exp"] == "F1_size"]
    N = np.array([q["size"] ** 2 for q in f1], float); M = np.array([q["peak_mb"] for q in f1])
    c1, c0 = np.polyfit(N, M, 1)
    out = {"made_at": time.strftime("%Y-%m-%d %H:%M:%S"), "fit_on": "F1-F5 window-mode medians, results/linux/flight/benchmark_raw.csv",
           "v1": {"a_ns": a1 * 1e9, "b_ms": b1 * 1e3, "fit_err_pct": e1}, "v2": {"a_ns": a2 * 1e9, "b_ms": b2 * 1e3, "fit_err_pct": e2},
           "memory": {"c0_mb": float(c0), "c1_mb_per_Mcell": float(c1 * 1e6), "fit_sizes": N.tolist(), "fit_peak_mb": M.tolist()},
           "fit_points": pts, "experiments": []}
    for eid, size, route, sp, rad, mode, frac in EXPERIMENTS:
        W, Aex, N = workload(size, route, sp, rad, frac)
        Av1 = N if rad <= 0 else min(math.pi * (rad / CELL) ** 2, N)
        out["experiments"].append({"id": eid, "size": size, "cells": N, "mode": mode, "W": W, "A_v1": Av1, "A_v2": Aex,
                                   "pred_v1_s": a1 * W * Av1 + b1 * W, "pred_v2_s": a2 * W * Aex + b2 * W,
                                   "pred_peak_mb": float(c0 + c1 * N) if eid.startswith("S1_F1_window") else None})
    json.dump(out, open(OUT / "predictions.json", "w"), indent=1)
    for e in out["experiments"]:
        print(e["id"], f"W={e['W']}", f"v1 {e['pred_v1_s']:.2f} s", f"v2 {e['pred_v2_s']:.2f} s",
              f"mem {e['pred_peak_mb']:.0f} MB" if e["pred_peak_mb"] else "")
    print({k: out[k] for k in ("v1", "v2", "memory")})


def run(repeats):
    json.dump(machine_info(), open(OUT / "machine.json", "w"), indent=1)
    jobs = []
    for eid, size, route, sp, rad, mode, frac in EXPERIMENTS:
        j = {"track": "flight", "dem_id": size, "width": size, "height": size, "cell_size_m": CELL, "experiment": eid,
             "param_name": "cells", "param_value": size * size, "route": route, "route_frac": frac, "spacing_m": sp,
             "radius_m": rad, "_repeats": 2 if eid == "S1_F1_window" else repeats}
        if mode == "window":
            j.update({"job": "route", "algorithm": "window"}); mod = "flight.jobs"
        else:
            j.update({"job": "fast", "algorithm": mode}); mod = "flight.jobs_fast"
        print("==", eid, flush=True)
        run_series(mod, [j], CSV, repeats=repeats)


def analyse():
    P = json.load(open(OUT / "predictions.json"))
    rows = load(CSV)
    res = []
    for e in P["experiments"]:
        m = medians(rows, e["id"])
        if not m:
            continue
        p = list(m.values())[0][0]
        r = {**e, "measured_s": p["compute"], "measured_peak_mb": p["peak_mb"], "runs": p["n"],
             "err_v1_pct": 100 * (e["pred_v1_s"] - p["compute"]) / p["compute"],
             "err_v2_pct": 100 * (e["pred_v2_s"] - p["compute"]) / p["compute"]}
        if e.get("pred_peak_mb"):
            r["err_mem_pct"] = 100 * (e["pred_peak_mb"] - p["peak_mb"]) / p["peak_mb"]
        res.append(r)
    json.dump({"predictions_made_at": P["made_at"], "models": {k: P[k] for k in ("v1", "v2", "memory")}, "results": res},
              open(OUT / "scale_summary.json", "w"), indent=1)
    for r in res:
        print(f"{r['id']:24s} measured {r['measured_s']:8.2f} s | v1 {r['pred_v1_s']:8.2f} ({r['err_v1_pct']:+.0f}%) | "
              f"v2 {r['pred_v2_s']:8.2f} ({r['err_v2_pct']:+.0f}%) | peak {r['measured_peak_mb']:.0f} MB"
              + (f" (pred {r['pred_peak_mb']:.0f}, {r['err_mem_pct']:+.0f}%)" if r.get("pred_peak_mb") else ""))
    # figures
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
    ax = axs[0]
    fp = P["fit_points"]
    a2, b2 = P["v2"]["a_ns"] * 1e-9, P["v2"]["b_ms"] * 1e-3
    ax.scatter([q["t"] for q in fp], [a2 * q["W"] * q["A_v2"] + b2 * q["W"] for q in fp], c="0.6", s=22, label="F1-F5 (fitted)")
    win = [r for r in res if r["mode"] == "window"]
    ax.scatter([r["measured_s"] for r in win], [r["pred_v2_s"] for r in win], c="#e63946", s=55, marker="D", label="new runs (predicted)")
    for r in win:
        ax.annotate(r["id"].replace("S3_", "").replace("_window", ""), (r["measured_s"], r["pred_v2_s"]), textcoords="offset points",
                    xytext=(5, -9), fontsize=7)
    lo = min([q["t"] for q in fp] + [r["measured_s"] for r in win]) * 0.6
    hi = max([q["t"] for q in fp] + [r["measured_s"] for r in win]) * 1.6
    ax.loglog([lo, hi], [lo, hi], "k:", lw=0.8); ax.loglog([lo, hi], [lo * 1.2, hi * 1.2], c="0.85", lw=0.6); ax.loglog([lo, hi], [lo / 1.2, hi / 1.2], c="0.85", lw=0.6)
    ax.set_xlabel("measured compute (s)"); ax.set_ylabel("predicted (s)"); ax.legend(fontsize=8, frameon=False)
    ax.set_title("Model v2 (exact disc area), fitted on <= 16 M cells\npredicting 64 M cells and radii up to 80 km (band: +/-20%)", fontsize=9)
    ax = axs[1]
    f1 = [q for q in fp if q["exp"] == "F1_size"]
    s1 = [r for r in res if r["id"] == "S1_F1_window"]
    xs = [q["size"] ** 2 for q in f1] + [r["cells"] for r in s1]
    ax.loglog([q["size"] ** 2 for q in f1], [q["t"] for q in f1], "o-", c="#457b9d", label="F1 measured (fit)")
    if s1:
        ax.loglog([s1[0]["cells"]], [s1[0]["measured_s"]], "D", c="#e63946", ms=8, label="64 M measured")
        ax.loglog([s1[0]["cells"]], [s1[0]["pred_v2_s"]], "x", c="k", ms=9, label="64 M predicted")
    sh = [r for r in res if r["id"] == "S1_F1_shared_threads"]
    if sh:
        ax.loglog([sh[0]["cells"]], [sh[0]["measured_s"]], "s", c="#2a9d8f", ms=8, label="64 M, shared + 12 threads")
    ax.set_xlabel("DEM cells (route grows with the map)"); ax.set_ylabel("compute (s)"); ax.legend(fontsize=8, frameon=False)
    ax.set_title("F1 workload extended to 8000 x 8000", fontsize=9)
    save(fig, OUT / "fig_scale_prediction.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["predict", "run", "analyse"])
    ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    {"predict": predict, "run": lambda: run(a.repeats), "analyse": analyse}[a.step]()
