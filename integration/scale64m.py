"""All three tracks at 0.25-64 M cells on one machine: runtime and memory against DEM size.

For every size-scaling benchmark (Track 1 E1, Track 2 F1 / F1b, Track 3 C1 / C7 / C8) it fits a power law
t = c * N^b on the four sizes up to 16 M cells, extrapolates it to 64 M, and compares with the 64 M run:
does the growth seen up to 16 M continue?  Memory is extrapolated with a straight line (fixed base +
bytes per cell), runtime with the power law.  Methods that cannot run at 64 M on this machine (skipped.json,
failures.json) are listed with the reason.

Inputs:  <results>/radar|flight|corridor/benchmark_raw.csv  (run with OPTICS_BENCH_SIZES=500,...,8000)
Outputs: <results>/integration/scale64m.json, fig_scale64m_runtime.png, fig_scale64m_memory.png
Run:     python3 -m integration.scale64m
"""
import json

import numpy as np

from common.analysis import load, medians, power_fit
from common.config import RESULTS
from common.plots import plt, save

OUT = RESULTS / "integration"
SERIES = [  # track, csv dir, experiment, algorithm, label, time key
    (1, "radar", "E1_size", "gdal", "T1 GDAL viewshed", "compute"),
    (1, "radar", "E1_size", "r2", "T1 R2 ray casting", "compute"),
    (1, "radar", "E1_size", "naive", "T1 naive LOS (exact)", "compute"),
    (2, "flight", "F1_size", "window", "T2 route grows with map", "compute"),
    (2, "flight", "F1b_size_fixed_route", "window", "T2 fixed 12 km route", "compute"),
    (3, "corridor", "C1_size", "dijkstra_csgraph", "T3 SciPy Dijkstra (graph)", "compute"),
    (3, "corridor", "C1_size", "dijkstra_py", "T3 Python Dijkstra", "compute"),
    (3, "corridor", "C1_size", "astar_py", "T3 Python A*", "compute"),
    (3, "corridor", "C1_size", "multires", "T3 multi-resolution", "compute"),
    (3, "corridor", "C7_compiled", "dijkstra_c", "T3 C Dijkstra", "compute"),
    (3, "corridor", "C7_compiled", "astar_c", "T3 C A*", "compute"),
    (3, "corridor", "C7_compiled", "alt_c", "T3 C landmark A* (query)", "compute"),
    (3, "corridor", "C8_multi_query_c", "dijkstra_c", "T3 8 routes, C Dijkstra", "compute"),
    (3, "corridor", "C8_multi_query_c", "alt_c", "T3 8 routes, C landmarks", "compute"),
]
BIG = 64e6


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = {d: load(RESULTS / d / "benchmark_raw.csv") for d in ("radar", "flight", "corridor")}
    res = []
    for track, d, exp, alg, label, key in SERIES:
        pts = medians(rows[d], exp).get(alg, [])
        if not pts:
            continue
        N = np.array([p["param"] for p in pts]); t = np.array([p[key] for p in pts]); m = np.array([p["peak_mb"] for p in pts])
        small = N <= 16e6
        b, c = power_fit(N[small], t[small])
        bm, _ = power_fit(N[small], m[small])
        # memory = fixed base (interpreter, libraries) + bytes per cell: a straight line, not a power law
        k1, k0 = np.polyfit(N[small], m[small], 1) if small.sum() >= 2 else (None, None)
        mem_lin = (lambda n: k0 + k1 * n) if k1 is not None else None
        r = {"track": track, "experiment": exp, "algorithm": alg, "label": label, "cells": N.tolist(), "time_s": t.tolist(),
             "peak_mb": m.tolist(), "exponent_to_16M": b, "mem_exponent_to_16M": bm,
             "mem_bytes_per_cell": k1 * 2 ** 20 if k1 is not None else None, "mem_base_mb": k0}
        if (N == BIG).any():
            tb = float(t[N == BIG][0]); mb = float(m[N == BIG][0])
            r.update({"t64_s": tb, "t64_pred_s": c * BIG ** b if b is not None else None,
                      "peak64_mb": mb, "peak64_pred_mb": mem_lin(BIG) if mem_lin else None,
                      "exponent_all": power_fit(N, t)[0], "step_16_to_64": tb / float(t[N == 16e6][0]) if (N == 16e6).any() else None})
            r["t64_err_pct"] = 100 * (r["t64_pred_s"] - tb) / tb if r["t64_pred_s"] else None
            r["mem64_err_pct"] = 100 * (r["peak64_pred_mb"] - mb) / mb if r["peak64_pred_mb"] else None
        elif len(N) and N.max() >= 16e6 and b is not None:
            r["t64_pred_s"] = c * BIG ** b; r["peak64_pred_mb"] = mem_lin(BIG) if mem_lin else None
            r["not_run_at_64M"] = True
        res.append(r)
    skipped = []
    for d in ("radar", "flight", "corridor"):
        for f in ("skipped.json", "failures.json"):
            p = RESULTS / d / f
            if p.exists():
                skipped += [{**x, "source": f"{d}/{f}"} for x in json.load(open(p))]
    json.dump({"series": res, "not_run": skipped}, open(OUT / "scale64m.json", "w"), indent=1, default=float)

    for r in res:
        if "t64_s" in r:
            print(f"{r['label']:30s} 16M->64M x{r['step_16_to_64']:.1f}  slope<=16M {r['exponent_to_16M']:.2f}  "
                  f"64M {r['t64_s']:8.2f} s (pred {r['t64_pred_s']:8.2f}, {r['t64_err_pct']:+.0f}%)  "
                  f"peak {r['peak64_mb']:.0f} MB (pred {r['peak64_pred_mb']:.0f}, {r['mem64_err_pct']:+.0f}%)")
        elif r.get("not_run_at_64M"):
            print(f"{r['label']:30s} not run at 64M; extrapolated {r['t64_pred_s']:.1f} s, {r.get('peak64_pred_mb') or 0:.0f} MB")
    for s in skipped:
        print("not run:", s.get("experiment"), s.get("algorithm"), s.get("size") or s.get("dem_id"), "-", (s.get("reason") or s.get("error", ""))[:90])

    cols = {1: "#b4472e", 2: "#1f7a6f", 3: "#2f5d7c"}
    styles = ["o-", "s-", "^-", "D-", "v-", "P-", "X-"]
    for kind, key, fname, ylab in (("runtime", "time_s", "fig_scale64m_runtime.png", "compute time (s)"),
                                   ("memory", "peak_mb", "fig_scale64m_memory.png", "peak memory (MB)")):
        fig, axs = plt.subplots(1, 3, figsize=(15, 4.4))
        for ax, track, ttl in zip(axs, (1, 2, 3), ("Track 1 radar (E1)", "Track 2 flight (F1, F1b)", "Track 3 corridor (C1, C7, C8)")):
            k = 0
            for r in res:
                if r["track"] != track:
                    continue
                ax.loglog(r["cells"], r[key], styles[k % len(styles)], c=cols[track], alpha=0.35 + 0.65 * (1 - k / 8), ms=4,
                          label=r["label"].split(" ", 1)[1])
                if kind == "runtime" and r.get("t64_pred_s"):
                    ax.loglog([16e6, BIG], [r["time_s"][r["cells"].index(16e6)] if 16e6 in r["cells"] else r["t64_pred_s"], r["t64_pred_s"]],
                              ":", c="0.5", lw=0.8)
                k += 1
            ax.axvline(16e6, c="0.8", lw=0.8, ls="--"); ax.text(17e6, ax.get_ylim()[0] * 1.3, "16 M: largest\nin team run", fontsize=7, color="0.5")
            if kind == "memory":
                ax.axhline(15.3 * 1024, c="#e63946", lw=0.8, ls="--"); ax.text(3e5, 15.3 * 1024 * 1.1, "laptop RAM 15.3 GB", fontsize=7, color="#e63946")
            ax.set_xlabel("DEM cells"); ax.set_ylabel(ylab); ax.set_title(ttl, fontsize=9.5); ax.legend(fontsize=6.5, frameon=False)
        fig.suptitle(f"{kind.capitalize()} from 0.25 M to 64 M cells on one machine (dotted: power law fitted up to 16 M, extrapolated)", fontsize=10)
        save(fig, OUT / fname)


if __name__ == "__main__":
    main()
