"""Track 3 - memory efficiency and on-the-fly operations (4000 x 4000 DEM, detection model).

    run.bat -m corridor.efficiency_bench

M1  alpha bank: int32 next pointers vs 1-byte direction codes (memory, build time, route time, identical routes)
M2  Level 2 field: float64 cost + int32 next (12 B/cell) vs float32 cost + 1-byte direction (5 B/cell):
    same routes? cost error?
M3  bank snapshots on disk: zlib on the direction codes (ratio, compress / restore time)
O1  hover preview: route + P(detect) from the cursor cell for 2000 random cells (Level 2 lookup)
O2  alpha slider: bank lookups for 200 slider positions; exact field after release
Outputs: results/corridor/efficiency/efficiency.json, fig_memory.png, fig_onthefly.png
"""
import json
import time
import zlib

import numpy as np

from common.config import RESULTS
from common.plots import plt, save
from corridor import cgrid
from corridor.interactive_core import AlphaBank, Planner

OUT = RESULTS / "corridor" / "efficiency"
ALPHAS = (2.5, 5, 10, 20, 40, 80)
MB = 2 ** 20


def ms(f, *a):
    t = time.perf_counter(); r = f(*a); return r, 1000 * (time.perf_counter() - t)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(11)
    P = Planner(4000, "detection")
    P.precompute(landmarks=False, pyramid=False)
    p, W = P.p, P.p.W
    free = np.argwhere(~p.blocked)
    starts = [tuple(int(v) for v in free[i]) for i in rng.integers(len(free), size=500)]
    res = {"grid": [p.H, p.W], "cells": p.H * p.W}

    # ---------------------------------------------------------------- M1 alpha bank
    A = AlphaBank(p, P.goal, ALPHAS)
    B = AlphaBank(p, P.goal, ALPHAS, compact=True)
    ta, tb, same = [], [], 0
    for k, s in enumerate(starts):
        a = ALPHAS[k % len(ALPHAS)]
        (pa, _, _), da = ms(A.route, s, a); (pb, _, _), db = ms(B.route, s, a)
        ta.append(da); tb.append(db); same += pa == pb
    res["M1_bank"] = {"alphas": list(ALPHAS), "int32_mb": round(A.mem_mb, 1), "dir8_mb": round(B.mem_mb, 1),
                      "ratio": round(A.mem_mb / B.mem_mb, 2), "build_s_int32": round(A.pre_s, 2), "build_s_dir8": round(B.pre_s, 2),
                      "route_ms_median_int32": round(float(np.median(ta)), 3), "route_ms_median_dir8": round(float(np.median(tb)), 3),
                      "identical_routes": f"{same}/{len(starts)}"}
    print("M1", res["M1_bank"], flush=True)

    # ---------------------------------------------------------------- M2 Level 2 field
    ctg = P.ctg
    dirs = cgrid.to_dirs(ctg.next, W)
    d32 = ctg.dist.astype(np.float32)
    same, err = 0, []
    for s in starts:
        i = p.idx(s)
        pa, _ = ctg.route(s)
        pb = cgrid.follow(dirs, i, ctg.goal, W)
        same += pa == pb
        if np.isfinite(ctg.dist[i]) and ctg.dist[i] > 0:
            err.append(abs(float(d32[i]) - ctg.dist[i]) / ctg.dist[i])
    full = ctg.dist.nbytes + ctg.next.nbytes
    compact = d32.nbytes + dirs.nbytes
    res["M2_field"] = {"float64_int32_mb": round(full / MB, 1), "float32_dir8_mb": round(compact / MB, 1),
                       "ratio": round(full / compact, 2), "identical_routes": f"{same}/{len(starts)}",
                       "cost_rel_error_max": float(max(err)), "cost_rel_error_median": float(np.median(err))}
    print("M2", res["M2_field"], flush=True)

    # ---------------------------------------------------------------- M3 snapshots
    comp = {}
    for a, d in B.next.items():
        z, tc = ms(zlib.compress, d.tobytes(), 6)
        back, td = ms(zlib.decompress, z)
        assert back == d.tobytes()
        comp[a] = (len(z), tc, td)
    sizes = [v[0] for v in comp.values()]
    res["M3_snapshot"] = {"dir8_mb_per_alpha": round(B.mem_mb / len(ALPHAS), 1), "zlib_mb_per_alpha": round(np.mean(sizes) / MB, 2),
                          "ratio_vs_dir8": round(B.mem_mb / len(ALPHAS) / (np.mean(sizes) / MB), 1),
                          "ratio_vs_int32": round(A.mem_mb / len(ALPHAS) / (np.mean(sizes) / MB), 1),
                          "compress_ms": round(float(np.mean([v[1] for v in comp.values()])), 1),
                          "restore_ms": round(float(np.mean([v[2] for v in comp.values()])), 1)}
    print("M3", res["M3_snapshot"], flush=True)

    # ---------------------------------------------------------------- O1 hover preview
    look, pdt = [], []
    for i in rng.integers(len(free), size=2000):
        s = tuple(int(v) for v in free[i])
        (path, _), d1 = ms(ctg.route, s)
        if not path:
            continue                                   # cell not connected to the goal below the ceiling
        _, d2 = ms(P.detection_probability, path)
        look.append(d1); pdt.append(d1 + d2)
    res["O1_hover"] = {"n": 2000, "route_ms_median": round(float(np.median(look)), 3), "route_ms_p99": round(float(np.percentile(look, 99)), 3),
                       "route_plus_pdetect_ms_median": round(float(np.median(pdt)), 2),
                       "route_plus_pdetect_ms_p99": round(float(np.percentile(pdt, 99)), 2)}
    print("O1", res["O1_hover"], flush=True)

    # ---------------------------------------------------------------- O2 alpha slider
    slide = []
    for v in np.linspace(0, 1, 200):
        alpha = 0.25 * 2 ** (v * np.log2(160 / 0.25))
        _, d = ms(B.route, P.start, alpha); slide.append(d)
    t = time.perf_counter()
    import copy
    q = copy.copy(p); q.alpha = 33.0
    cgrid.CostToGo(q, P.goal, threads=cgrid.THREADS)
    res["O2_slider"] = {"positions": 200, "bank_lookup_ms_median": round(float(np.median(slide)), 3),
                        "bank_lookup_ms_max": round(float(np.max(slide)), 3),
                        "exact_on_release_s": round(time.perf_counter() - t, 3)}
    print("O2", res["O2_slider"], flush=True)
    json.dump(res, open(OUT / "efficiency.json", "w"), indent=1)
    figures(res, look, pdt, slide)


def figures(res, look, pdt, slide):
    m1, m2, m3 = res["M1_bank"], res["M2_field"], res["M3_snapshot"]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    labels = ["alpha bank\nint32 next", "alpha bank\n1-byte dirs", "bank snapshot\nzlib", "Level 2 field\nf64 + int32",
              "Level 2 field\nf32 + 1-byte"]
    vals = [m1["int32_mb"], m1["dir8_mb"], m3["zlib_mb_per_alpha"] * len(m1["alphas"]), m2["float64_int32_mb"], m2["float32_dir8_mb"]]
    bars = ax.bar(labels, vals, color=["#bbb", "#2a9d8f", "#1d3557", "#bbb", "#2a9d8f"], edgecolor="k")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 4, f"{v:.0f} MB", ha="center", fontsize=8)
    ax.set_ylabel("memory (MB)")
    ax.set_title(f"16 M cells: same routes ({m1['identical_routes']} bank, {m2['identical_routes']} field) with less memory", fontsize=9)
    ax.tick_params(axis="x", labelsize=7.5)
    save(fig, OUT / "fig_memory.png")
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.2))
    axs[0].hist(look, bins=40, color="#2a9d8f", alpha=0.8, label="route lookup")
    axs[0].hist(pdt, bins=40, color="#e76f51", alpha=0.6, label="+ P(detect)")
    axs[0].set_xlabel("ms per mouse move"); axs[0].set_title("Hover preview (2000 cursor cells)", fontsize=9); axs[0].legend(fontsize=7.5)
    axs[1].plot(slide, color="#1d3557"); axs[1].set_xlabel("slider position"); axs[1].set_ylabel("ms")
    axs[1].set_title(f"alpha slider: bank lookup, exact field on release {res['O2_slider']['exact_on_release_s']:.2f} s", fontsize=9)
    fig.tight_layout(); save(fig, OUT / "fig_onthefly.png")


if __name__ == "__main__":
    main()
