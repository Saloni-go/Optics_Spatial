"""Track 2 - idea 1 analysis: figures for F7-F9 and the complexity model F10.

F10 model.  One GDAL viewshed sweeps every cell of its disc once (Wang et al. reference planes), so a
route of W positions with radius r on a map of N cells should cost
        T  =  a * W * A  +  b * W,        A = min(pi r^2 / cell^2, N)   (A = N for unlimited radius)
a = seconds per cell swept, b = fixed cost per position (window copy, GDAL set-up, accumulation).
It is fitted to every median of F1-F5 (window mode) with relative-error weights, then checked on
how well it predicts each experiment.  Big-O: T = O(W * min(r^2, N)).

Run:  python3 -m flight.idea1_analysis
"""
import json
import math

import numpy as np

from common.analysis import load, medians
from common.config import RESULTS, CELL
from common.plots import plt, save

OUT = RESULTS / "flight"


def jacc(a, b):
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 1.0


def f7(rows, S):
    m = medians(rows, "F7_shared")
    order = ["window", "cached", "threads", "shared", "shared_threads"]
    d = [(a, m[a][0]) for a in order if a in m]
    S["F7"] = [{"mode": a, "compute_s": p["compute"], "peak_mb": p["peak_mb"]} for a, p in d]
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
    cols = ["#adb5bd", "#8ecae6", "#2a9d8f", "#f4a261", "#e76f51"]
    label = {"window": "window copy", "cached": "whole DEM\n(1 copy)", "threads": "window copy\n+12 threads",
             "shared": "shared view", "shared_threads": "shared view\n+12 threads"}
    names = [label[a] for a, _ in d]
    b = axs[0].bar(names, [p["compute"] for _, p in d], color=cols)
    for bb, (_, p) in zip(b, d):
        axs[0].text(bb.get_x() + bb.get_width() / 2, bb.get_height(), f"{p['compute']:.2f}s", ha="center", va="bottom", fontsize=8)
    axs[0].set_ylabel("compute time (s)"); axs[0].set_title("Copying the DEM per position vs a shared zero-copy view", fontsize=9)
    axs[1].bar(names, [p["peak_mb"] for _, p in d], color=cols)
    axs[1].set_ylabel("peak memory (MB)"); axs[1].set_title("Peak process memory", fontsize=9)
    for ax in axs:
        ax.tick_params(axis="x", labelsize=7.5)
    save(fig, OUT / "fig_idea1_shared.png")


def f8(rows, S):
    U = OUT / "idea1_unions"
    S["F8"] = {}
    fig, axs = plt.subplots(1, 2, figsize=(10.5, 3.8), sharey=True)
    for ax, prof in zip(axs, ("valley", "cruise")):
        m = medians(rows, f"F8_multires_{prof}")
        ref = np.load(U / f"{prof}_ref.npy")
        tref = m["shared_threads"][0]["compute"]
        out = [{"k": 1, "r_near_km": None, "compute_s": tref, "jaccard": 1.0}]
        for alg, pts in m.items():
            if not alg.startswith("multires"):
                continue
            rn = int(alg.split("rn")[1])
            for p in pts:
                u = np.load(U / f"{prof}_k{int(p['param'])}_rn{rn * 1000}.npy")
                out.append({"k": int(p["param"]), "r_near_km": rn, "compute_s": p["compute"], "jaccard": jacc(ref, u),
                            "missed_km2": float((ref & ~u).sum() * CELL ** 2 / 1e6),
                            "extra_km2": float((u & ~ref).sum() * CELL ** 2 / 1e6)})
        S["F8"][prof] = out
        mk = {2: "o", 5: "s", 10: "^"}
        cl = {2: "#2a9d8f", 3: "#e76f51", 4: "#6d597a"}
        for o in out[1:]:
            ax.scatter(o["compute_s"], 100 * o["jaccard"], marker=mk[o["r_near_km"]], c=cl[o["k"]], s=40)
        ax.scatter(tref, 100, marker="*", c="k", s=120, label="exact (shared + threads)")
        for k, c in cl.items():
            ax.scatter([], [], c=c, label=f"far field {int(30 * k)} m (k={k})")
        for rn, mm in mk.items():
            ax.scatter([], [], marker=mm, c="0.5", label=f"exact within {rn} km")
        ax.set_xlabel("compute time (s), 333 positions"); ax.set_title(f"{prof}: fine near, coarse far", fontsize=9)
    axs[0].set_ylabel("coverage overlap with exact (%)"); axs[1].legend(fontsize=7, frameon=False, loc="lower right")
    save(fig, OUT / "fig_idea1_multires.png")


def f9(rows, S):
    S["F9"] = {}
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
    for ax, exp, ttl in ((axs[0], "F9_memory", "route grows with the map, unlimited radius"),
                         (axs[1], "F9_memory_fixed_route", "same 12 km route, 20 km radius")):
        m = medians(rows, exp)
        S["F9"][exp] = {}
        for alg, c in (("full", "#457b9d"), ("tiled", "#e76f51")):
            pts = m.get(alg, [])
            x = [p["param"] for p in pts]
            ax.loglog(x, [p["peak_mb"] for p in pts], "o-", c=c, label=f"{alg}: process peak")
            ax.loglog(x, [p.get("acc_mb", 0) for p in pts], "s--", c=c, alpha=0.7, label=f"{alg}: accumulator only")
            S["F9"][exp][alg] = [{"cells": p["param"], "peak_mb": p["peak_mb"], "acc_mb": p.get("acc_mb"),
                                  "compute_s": p["compute"]} for p in pts]
        ax.set_xlabel("DEM cells"); ax.set_ylabel("MB"); ax.set_title(ttl, fontsize=9); ax.legend(fontsize=7, frameon=False)
    save(fig, OUT / "fig_idea1_memory.png")


def f10(S):
    rows = load(OUT / "benchmark_raw.csv")
    pts = []
    exps = {"F1_size": None, "F1b_size_fixed_route": 20000, "F2_spacing": 20000, "F3_altitude": 20000,
            "F4_radius": "param", "F5_length": 20000}
    for exp, rad in exps.items():
        for p in medians(rows, exp).get("window", []):
            N = (p["param"] if exp.startswith("F1") else 16e6)
            r = p["param"] * 1000 if rad == "param" else rad
            A = N if r is None else min(math.pi * (r / CELL) ** 2, N)
            pts.append({"exp": exp, "W": p["waypoints"], "A": A, "t": p["compute"]})
    W = np.array([q["W"] for q in pts]); A = np.array([q["A"] for q in pts]); t = np.array([q["t"] for q in pts])
    X = np.column_stack([W * A, W]) / t[:, None]                   # relative-error weighting
    (a, b), *_ = np.linalg.lstsq(X, np.ones_like(t), rcond=None)
    pred = a * W * A + b * W
    err = np.abs(pred - t) / t
    r2 = 1 - ((np.log(t) - np.log(pred)) ** 2).sum() / ((np.log(t) - np.log(t).mean()) ** 2).sum()
    S["F10"] = {"model": "T = a*W*min(pi r^2/cell^2, N) + b*W", "a_ns_per_cell": a * 1e9, "b_ms_per_position": b * 1e3,
                "r2_log": float(r2), "mean_abs_err_pct": float(100 * err.mean()), "max_abs_err_pct": float(100 * err.max()),
                "points": [{**q, "pred": float(pr)} for q, pr in zip(pts, pred)]}
    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    cmap = dict(zip(exps, ["#e63946", "#2a9d8f", "#457b9d", "#f4a261", "#6d597a", "#8ecae6"]))
    for q, pr in zip(pts, pred):
        ax.scatter(q["t"], pr, c=cmap[q["exp"]], s=30)
    for e, c in cmap.items():
        ax.scatter([], [], c=c, label=e)
    lo, hi = t.min() * 0.7, t.max() * 1.4
    ax.loglog([lo, hi], [lo, hi], "k:", lw=0.8)
    ax.set_xlabel("measured compute (s)"); ax.set_ylabel("model prediction (s)")
    ax.set_title(f"T = a*W*A + b*W:  a = {a * 1e9:.2f} ns/cell, b = {b * 1e3:.2f} ms/position\n"
                 f"mean error {100 * err.mean():.0f}%, R^2 (log) = {r2:.3f}", fontsize=8.5)
    ax.legend(fontsize=7, frameon=False)
    save(fig, OUT / "fig_idea1_complexity.png")


def main():
    rows = load(OUT / "idea1_raw.csv")
    S = {}
    f7(rows, S); f8(rows, S); f9(rows, S); f10(S)
    json.dump(S, open(OUT / "idea1_summary.json", "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in S.items() if k != "F10"}, indent=1, default=float)[:4000])
    print({k: v for k, v in S["F10"].items() if k != "points"})


if __name__ == "__main__":
    main()
