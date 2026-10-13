"""Track 3 - benchmark figures, complexity fits and solution quality.
Run after corridor.benchmark:  run.bat -m corridor.analysis
"""
import json

from common.analysis import load, medians, power_fit
from common.config import RESULTS
from common.plots import plt, save

OUT = RESULTS / "corridor"
COL = {"dijkstra_py": "#e63946", "astar_py": "#f4a261", "dijkstra_csgraph": "#2a9d8f", "multires": "#457b9d",
       "astar_alt": "#8338ec", "csgraph": "#2a9d8f", "alt": "#8338ec", "astar": "#f4a261"}


def main():
    rows = load(OUT / "benchmark_raw.csv")
    S = {}
    # C1 size
    m = medians(rows, "C1_size")
    opt = {p["param"]: p.get("route_cost") for p in m.get("dijkstra_csgraph", [])}
    fig, axs = plt.subplots(1, 3, figsize=(14, 3.8))
    S["C1"] = {}
    for alg, pts in m.items():
        x = [p["param"] for p in pts]; t = [p["compute"] for p in pts]
        b, _ = power_fit(x, t)
        axs[0].loglog(x, t, "o-", c=COL.get(alg), label=f"{alg} (slope {b:.2f})")
        axs[1].loglog(x, [p["peak_mb"] for p in pts], "o-", c=COL.get(alg), label=alg)
        gap = [100 * (p["route_cost"] / opt[p["param"]] - 1) if opt.get(p["param"]) else None for p in pts]
        axs[2].semilogx(x, gap, "o-", c=COL.get(alg), label=alg)
        S["C1"][alg] = {"nodes": x, "compute_s": t, "solve_s": [p.get("solve_s") for p in pts], "build_s": [p.get("build_s") for p in pts],
                        "peak_mb": [p["peak_mb"] for p in pts], "expanded": [p.get("expanded") for p in pts],
                        "cost_gap_pct": gap, "exponent": b, "route_km": [p.get("route_length_km") for p in pts]}
    axs[0].set_ylabel("compute time incl. graph build (s)"); axs[1].set_ylabel("peak memory (MB)"); axs[2].set_ylabel("cost above optimum (%)")
    for ax in axs:
        ax.set_xlabel("graph nodes (DEM cells)"); ax.legend(fontsize=7, frameon=False)
    axs[0].set_title("Route search time vs graph size", fontsize=9); axs[1].set_title("Memory vs graph size", fontsize=9)
    axs[2].set_title("Solution quality", fontsize=9)
    save(fig, OUT / "fig_bench_size.png")

    # C2 alpha
    m = medians(rows, "C2_alpha")
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6)); S["C2"] = {}
    for alg, pts in m.items():
        x = [max(p["param"], 0.3) for p in pts]
        axs[0].semilogx(x, [p.get("expanded") for p in pts], "o-", c=COL.get(alg), label=alg)
        S["C2"][alg] = [{"alpha": p["param"], "compute_s": p["compute"], "expanded": p.get("expanded"),
                         "length_km": p.get("route_length_km"), "exposure_km": p.get("route_exposure_km"),
                         "exposed_frac": p.get("route_exposed_frac")} for p in pts]
    cs = S["C2"].get("dijkstra_csgraph", [])
    axs[1].plot([d["length_km"] for d in cs], [d["exposure_km"] for d in cs], "o-", c="#2a9d8f")
    for d in cs:
        if d["alpha"] in (30, 100):
            continue
        axs[1].annotate(f"a={d['alpha']:g}", (d["length_km"], d["exposure_km"]), textcoords="offset points", xytext=(3, 3), fontsize=7)
    axs[0].set_xlabel("alpha (exposure weight; 0 plotted at 0.3)"); axs[0].set_ylabel("nodes expanded"); axs[0].legend(fontsize=8, frameon=False)
    axs[0].set_title("Plain A* loses its advantage; landmark A* (ALT) keeps it", fontsize=9)
    axs[1].set_xlabel("route length (km)"); axs[1].set_ylabel("exposure integral (km)"); axs[1].set_title("Trade-off (DEM 2000)", fontsize=9)
    save(fig, OUT / "fig_bench_alpha.png")

    # C3 multires
    pts = medians(rows, "C3_multires").get("multires", [])
    o4000 = opt.get(16e6)
    S["C3"] = [{"k": p["param"], "compute_s": p["compute"], "expanded": p.get("expanded"), "peak_mb": p["peak_mb"],
                "cost_gap_pct": 100 * (p["route_cost"] / o4000 - 1) if o4000 else None} for p in pts]
    # C4 distance
    m = medians(rows, "C4_distance")
    S["C4"] = {alg: [{"diag_frac": p["param"], "compute_s": p["compute"], "expanded": p.get("expanded")} for p in pts] for alg, pts in m.items()}
    # C5 exposure preprocessing
    pts = medians(rows, "C5_exposure").get("gdal_viewshed", [])
    S["C5"] = [{"radars": p["param"], "compute_s": p["compute"], "peak_mb": p["peak_mb"], "exposed_frac": p.get("exposed_frac")} for p in pts]
    b, _ = power_fit([d["radars"] for d in S["C5"]], [d["compute_s"] for d in S["C5"]])
    S["C5_exponent"] = b

    fig, axs = plt.subplots(1, 3, figsize=(15, 3.4)); fig.subplots_adjust(wspace=0.45)
    if S["C3"]:
        axs[0].plot([d["k"] for d in S["C3"]], [d["compute_s"] for d in S["C3"]], "o-", c="#457b9d")
        ax2 = axs[0].twinx(); ax2.plot([d["k"] for d in S["C3"]], [d["cost_gap_pct"] for d in S["C3"]], "s--", c="#e63946")
        ax2.set_ylabel("cost above optimum (%)", color="#e63946")
        axs[0].set_xlabel("coarsening factor k"); axs[0].set_ylabel("compute (s)"); axs[0].set_title("Multi-resolution (DEM 4000)", fontsize=9)
    for alg, pts in S["C4"].items():
        axs[1].plot([d["diag_frac"] for d in pts], [d["expanded"] for d in pts], "o-", c=COL.get(alg), label=alg)
    axs[1].set_xlabel("start-goal distance (fraction of diagonal)"); axs[1].set_ylabel("nodes expanded"); axs[1].legend(fontsize=8, frameon=False)
    axs[1].set_title("Search effort vs trip length (DEM 2000)", fontsize=9)
    axs[2].plot([d["radars"] for d in S["C5"]], [d["compute_s"] for d in S["C5"]], "o-", c="#2a9d8f")
    axs[2].set_xlabel("number of radars"); axs[2].set_ylabel("exposure preprocessing (s)")
    axs[2].set_title(f"Exposure surface cost (slope {b:.2f})" if b else "Exposure surface cost", fontsize=9)
    save(fig, OUT / "fig_bench_misc.png")

    # C6 many queries on one map
    m = medians(rows, "C6_multi_query")
    S["C6"] = {alg: [{"nodes": p["param"], "total_s": p["compute"], "pre_s": p.get("pre_s"), "per_query_s": p.get("per_query_s"),
                      "mean_expanded": p.get("mean_expanded"), "peak_mb": p["peak_mb"], "cost_sum": p.get("cost_sum")} for p in pts]
               for alg, pts in m.items()}
    if S["C6"]:
        fig, axs = plt.subplots(1, 3, figsize=(14, 3.6)); fig.subplots_adjust(wspace=0.35)
        for alg, pts in S["C6"].items():
            x = [d["nodes"] for d in pts]
            axs[0].loglog(x, [d["per_query_s"] for d in pts], "o-", c=COL.get(alg), label=alg)
            axs[1].loglog(x, [d["mean_expanded"] for d in pts], "o-", c=COL.get(alg), label=alg)
            axs[2].loglog(x, [d["peak_mb"] for d in pts], "o-", c=COL.get(alg), label=alg)
        for ax, yl, t in ((axs[0], "time per route (s)", "Per-query time (preprocessing excluded)"),
                          (axs[1], "nodes expanded per route", "Search effort"), (axs[2], "peak memory (MB)", "Memory")):
            ax.set_xlabel("graph nodes"); ax.set_ylabel(yl); ax.set_title(t, fontsize=9); ax.legend(fontsize=8, frameon=False)
        save(fig, OUT / "fig_bench_multiquery.png")
    json.dump(S, open(OUT / "benchmark_summary.json", "w"), indent=1, default=float)
    print(json.dumps(S, indent=1, default=float)[:3000])


if __name__ == "__main__":
    main()
