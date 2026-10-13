"""Track 2 - benchmark figures, complexity fits and accuracy of cheaper sampling.
Run after flight.benchmark:  run.bat -m flight.analysis
"""
import json
import numpy as np

from common.analysis import load, medians, power_fit
from common.config import RESULTS
from common.plots import plt, save

OUT = RESULTS / "flight"


def jacc(a, b):
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 1.0


def main():
    rows = load(OUT / "benchmark_raw.csv")
    S = {}

    # F1 / F1b: DEM size
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.8))
    for exp, c, lab in (("F1_size", "#e76f51", "route grows with DEM, unlimited radius"),
                        ("F1b_size_fixed_route", "#2a9d8f", "fixed 12 km route, 20 km radius")):
        pts = medians(rows, exp)["window"]
        x = [p["param"] for p in pts]; t = [p["compute"] for p in pts]
        b, _ = power_fit(x, t)
        axs[0].loglog(x, t, "o-", c=c, label=f"{lab} (slope {b:.2f})")
        axs[1].loglog(x, [p["peak_mb"] for p in pts], "o-", c=c, label=lab)
        S[exp] = {"cells": x, "compute_s": t, "peak_mb": [p["peak_mb"] for p in pts], "exponent": b,
                  "waypoints": [p.get("waypoints") for p in pts]}
    for ax, yl in zip(axs, ("compute time (s)", "peak memory (MB)")):
        ax.set_xlabel("DEM cells"); ax.set_ylabel(yl); ax.legend(fontsize=7.5, frameon=False)
    axs[0].set_title("Flight visibility runtime vs DEM size", fontsize=9)
    save(fig, OUT / "fig_bench_size.png")

    # F2: spacing / waypoint count + accuracy against the densest sampling
    pts = medians(rows, "F2_spacing")["window"]
    ref = np.load(OUT / "union_F2_250.npy")
    acc = {}
    for p in pts:
        u = np.load(OUT / f"union_F2_{int(p['param'])}.npy")
        acc[p["param"]] = {"jaccard_vs_250m": jacc(ref, u), "missed_km2": float((ref & ~u).sum() * 900 / 1e6)}
    S["F2"] = [{"spacing_m": p["param"], "waypoints": p.get("waypoints"), "compute_s": p["compute"], "peak_mb": p["peak_mb"],
                **acc[p["param"]]} for p in pts]
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
    w = [d["waypoints"] for d in S["F2"]]; t = [d["compute_s"] for d in S["F2"]]
    b, _ = power_fit(w, t)
    axs[0].loglog(w, t, "o-", c="#457b9d", label=f"slope {b:.2f}")
    axs[0].set_xlabel("number of sampled positions"); axs[0].set_ylabel("compute time (s)"); axs[0].legend(frameon=False, fontsize=8)
    axs[0].set_title("Runtime is linear in the number of positions", fontsize=9)
    axs[1].plot([d["spacing_m"] for d in S["F2"]], [d["jaccard_vs_250m"] * 100 for d in S["F2"]], "o-", c="#e63946")
    axs[1].set_xlabel("spacing between positions (m)"); axs[1].set_ylabel("coverage overlap with 250 m run (%)")
    axs[1].set_title("Sparser sampling misses terrain", fontsize=9)
    save(fig, OUT / "fig_bench_spacing.png")
    S["F2_exponent_vs_waypoints"] = b

    # F3 altitude, F4 radius, F5 length
    fig, axs = plt.subplots(1, 3, figsize=(13, 3.4))
    for ax, exp, xl in ((axs[0], "F3_altitude", "flight height above ground (m)"), (axs[1], "F4_radius", "visibility radius (km)"),
                        (axs[2], "F5_length", "route length (km)")):
        pts = medians(rows, exp)["window"]
        x = [p["param"] for p in pts]
        ax.plot(x, [p["compute"] for p in pts], "o-", c="#457b9d", label="compute (s)")
        ax2 = ax.twinx(); ax2.plot(x, [p.get("seen_km2", 0) for p in pts], "s--", c="#e76f51")
        ax2.set_ylabel("area seen (km$^2$)", color="#e76f51")
        ax.set_xlabel(xl); ax.set_ylabel("compute time (s)")
        if exp != "F5_length":
            ax.set_xscale("log")
        b, _ = power_fit(x, [p["compute"] for p in pts])
        S[exp] = [{"param": p["param"], "compute_s": p["compute"], "seen_km2": p.get("seen_km2"), "peak_mb": p["peak_mb"]} for p in pts]
        S[exp + "_exponent"] = b
        ax.set_title(f"{exp.split('_')[1]}: time slope {b:.2f}", fontsize=9)
    save(fig, OUT / "fig_bench_params.png")

    # F6: optimisations
    m = medians(rows, "F6_optimise")
    ref = np.load(OUT / "union_F6_window.npy")
    S["F6"] = []
    for alg in ("baseline", "cached", "window", "parallel", "threads", "adaptive", "adaptive_gain"):
        if alg not in m:
            continue
        p = m[alg][0]
        u = np.load(OUT / f"union_F6_{alg}.npy")
        S["F6"].append({"mode": alg, "runtime_s": p["runtime"], "compute_s": p["compute"], "peak_mb": p["peak_mb"],
                        "waypoints": p.get("waypoints"), "jaccard_vs_dense": jacc(ref, u)})
    fig, ax = plt.subplots(figsize=(8.5, 3.6))
    names = [d["mode"].replace("adaptive_gain", "adaptive\n(new ground)").replace("adaptive", "adaptive", 1) for d in S["F6"]]
    t = [d["compute_s"] for d in S["F6"]]
    bars = ax.bar(names, t, color=["#adb5bd", "#8ecae6", "#219ebc", "#e76f51", "#2a9d8f", "#f4a261", "#e9c46a"][:len(names)])
    for bb, d in zip(bars, S["F6"]):
        ax.text(bb.get_x() + bb.get_width() / 2, bb.get_height(), f"{d['compute_s']:.2f}s\n{int(d['waypoints'])} pos\nJ={d['jaccard_vs_dense']:.3f}",
                ha="center", va="bottom", fontsize=7)
    ax.set_ylabel("compute time (s)"); ax.set_ylim(0, max(t) * 1.35)
    ax.set_title("Optimisations, 166 km valley route, 500 m spacing, 20 km radius", fontsize=9)
    save(fig, OUT / "fig_bench_optimise.png")

    json.dump(S, open(OUT / "benchmark_summary.json", "w"), indent=1, default=float)
    print(json.dumps(S, indent=1, default=float)[:2500])


if __name__ == "__main__":
    main()
