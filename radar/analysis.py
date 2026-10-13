"""Track 1 - benchmark figures, empirical complexity and accuracy of the optimisations.
Run after radar.benchmark:  run.bat -m radar.analysis
"""
import json
import numpy as np
from osgeo import gdal

from common.analysis import load, medians, power_fit
from common.config import RESULTS, CELL, RADAR_HEIGHT, dem_path
from common.dem_utils import DEM
from common.plots import plt, save
from radar.viewshed import gdal_viewshed, agreement

OUT = RESULTS / "radar"
COL = {"naive": "#e63946", "r2": "#457b9d", "gdal": "#2a9d8f", "sequential": "#457b9d", "parallel8": "#e76f51",
       "threads12": "#2a9d8f"}


def resample_accuracy():
    dem = DEM(dem_path(4000)); x, y = dem.to_world(2000, 2000)
    ref = gdal_viewshed(dem, x, y, RADAR_HEIGHT, 0, 0)
    res = {"30": {"agreement": 1.0, "kappa": 1.0, "visible_frac": float((ref == 1).mean())}}
    for f in (2, 3, 4):
        mem = gdal.Warp("", str(dem_path(4000)), format="MEM", xRes=CELL * f, yRes=CELL * f, resampleAlg="average")
        gdal.Translate("/vsimem/c.tif", mem)
        dc = DEM("/vsimem/c.tif")
        v = gdal_viewshed(dc, x, y, RADAR_HEIGHT, 0, 0)
        src = gdal.GetDriverByName("MEM").Create("", v.shape[1], v.shape[0], 1, gdal.GDT_Byte)
        src.SetGeoTransform(dc.gt); src.SetProjection(dc.proj); src.GetRasterBand(1).WriteArray(v)
        up = gdal.Warp("", src, format="MEM", outputBounds=(dem.gt[0], dem.gt[3] - 4000 * CELL, dem.gt[0] + 4000 * CELL, dem.gt[3]),
                       xRes=CELL, yRes=CELL, resampleAlg="near").ReadAsArray()
        res[str(int(CELL * f))] = {**agreement(ref, up), "visible_frac": float((v == 1).mean())}
    return res


def main():
    rows = load(OUT / "benchmark_raw.csv")
    summary = {}

    # E1: size scaling
    m = medians(rows, "E1_size")
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.8))
    summary["E1"] = {}
    for alg, pts in m.items():
        x = [p["param"] for p in pts]; t = [p["compute"] for p in pts]; mem = [p["peak_mb"] for p in pts]
        b, _ = power_fit(x, t)
        axs[0].loglog(x, t, "o-", c=COL.get(alg), label=f"{alg} (slope {b:.2f})" if b else alg)
        axs[1].loglog(x, mem, "o-", c=COL.get(alg), label=alg)
        summary["E1"][alg] = {"cells": x, "compute_s": t, "runtime_s": [p["runtime"] for p in pts], "peak_mb": mem,
                              "exponent": b}
    # project the naive algorithm to 16M cells using its fitted exponent
    if "naive" in summary["E1"]:
        b = summary["E1"]["naive"]["exponent"]; x0, t0 = summary["E1"]["naive"]["cells"][-1], summary["E1"]["naive"]["compute_s"][-1]
        summary["E1"]["naive"]["projected_16M_s"] = t0 * (16e6 / x0) ** b
        axs[0].loglog([x0, 16e6], [t0, t0 * (16e6 / x0) ** b], ":", c=COL["naive"], label="naive (projected)")
    axs[0].set_xlabel("DEM cells"); axs[0].set_ylabel("compute time (s)"); axs[0].legend(fontsize=8, frameon=False)
    axs[1].set_xlabel("DEM cells"); axs[1].set_ylabel("peak memory (MB)"); axs[1].legend(fontsize=8, frameon=False)
    axs[0].set_title("Runtime vs DEM size (radar at centre, unlimited range)", fontsize=9)
    axs[1].set_title("Peak process memory vs DEM size", fontsize=9)
    save(fig, OUT / "fig_bench_size.png")

    # E2: range
    m = medians(rows, "E2_range")
    fig, ax = plt.subplots(figsize=(5, 3.6)); summary["E2"] = {}
    for alg, pts in m.items():
        x = [p["param"] for p in pts]; t = [p["compute"] for p in pts]
        b, _ = power_fit(x[:4], t[:4])
        ax.loglog(x, t, "o-", c=COL.get(alg), label=f"{alg} (slope {b:.2f})")
        summary["E2"][alg] = {"range_km": x, "compute_s": t, "exponent_vs_range": b}
    ax.set_xlabel("radar range (km)"); ax.set_ylabel("compute time (s)"); ax.legend(fontsize=8, frameon=False)
    ax.set_title("Runtime vs radar range (DEM 4000)", fontsize=9)
    save(fig, OUT / "fig_bench_range.png")

    # E3: height -> coverage, runtime
    m = medians(rows, "E3_height")["gdal"]
    summary["E3"] = [{"radar_h_m": p["param"], "compute_s": p["compute"], "visible_frac": p.get("visible_frac")} for p in m]
    fig, ax = plt.subplots(figsize=(5, 3.4))
    ax.semilogx([p["param"] for p in m], [p["visible_frac"] * 100 for p in m], "o-", c="#2a9d8f")
    ax.set_xlabel("radar mast height (m)"); ax.set_ylabel("ground visible within 30 km (%)")
    ax2 = ax.twinx(); ax2.semilogx([p["param"] for p in m], [p["compute"] * 1000 for p in m], "s--", c="0.5")
    ax2.set_ylabel("compute (ms)", color="0.4"); ax2.set_ylim(0, None)
    ax.set_title("Coverage vs radar height (runtime unchanged)", fontsize=9)
    save(fig, OUT / "fig_bench_height.png")

    # E4: number of radars, sequential vs parallel
    m = medians(rows, "E4_radars")
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6)); summary["E4"] = {}
    for alg, pts in m.items():
        x = [p["param"] for p in pts]
        axs[0].plot(x, [p["compute"] for p in pts], "o-", c=COL.get(alg), label=alg)
        tot = [p["peak_mb"] + p.get("workers_peak_kb_sum", 0) / 1024 for p in pts]
        axs[1].plot(x, tot, "o-", c=COL.get(alg), label=alg + (" (parent + workers)" if "parallel" in alg else ""))
        summary["E4"][alg] = {"radars": x, "compute_s": [p["compute"] for p in pts], "total_peak_mb": tot,
                              "union_frac": [p.get("union_visible_frac") for p in pts]}
    if "sequential" in summary["E4"] and "parallel8" in summary["E4"]:
        summary["E4"]["speedup"] = [s / p for s, p in zip(summary["E4"]["sequential"]["compute_s"], summary["E4"]["parallel8"]["compute_s"])]
    if "threads12" in summary["E4"]:
        summary["E4"]["speedup_threads"] = [s / p for s, p in zip(summary["E4"]["sequential"]["compute_s"], summary["E4"]["threads12"]["compute_s"])]
    axs[0].set_xlabel("number of radars (30 km range)"); axs[0].set_ylabel("compute time (s)"); axs[0].legend(fontsize=8, frameon=False)
    axs[1].set_xlabel("number of radars"); axs[1].set_ylabel("peak memory (MB)"); axs[1].legend(fontsize=8, frameon=False)
    axs[0].set_title("Multiple radars: sequential vs 8 processes vs 12 threads", fontsize=9); axs[1].set_title("Memory cost of parallelism", fontsize=9)
    save(fig, OUT / "fig_bench_radars.png")

    # E5: clipping
    m = medians(rows, "E5_clipping")
    summary["E5"] = {alg: [{"range_km": p["param"], "runtime_s": p["runtime"], "compute_s": p["compute"], "peak_mb": p["peak_mb"]}
                           for p in pts] for alg, pts in m.items()}
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
    for alg, pts in m.items():
        ls = "-" if alg.endswith("window") else "--"
        c = COL["gdal"] if alg.startswith("gdal") else COL["r2"]
        axs[0].plot([p["param"] for p in pts], [p["runtime"] for p in pts], "o" + ls, c=c, label=alg)
        axs[1].plot([p["param"] for p in pts], [p["peak_mb"] for p in pts], "o" + ls, c=c, label=alg)
    axs[0].set_ylabel("total runtime incl. reading DEM (s)"); axs[1].set_ylabel("peak memory (MB)")
    for ax in axs:
        ax.set_xlabel("radar range (km)"); ax.legend(fontsize=7.5, frameon=False)
    axs[0].set_title("Region clipping: read only the range window", fontsize=9)
    save(fig, OUT / "fig_bench_clipping.png")

    # E6: resolution
    m = medians(rows, "E6_resample")["gdal"]
    acc = resample_accuracy()
    summary["E6"] = [{"cell_m": p["param"], "runtime_s": p["runtime"], "compute_s": p["compute"], "peak_mb": p["peak_mb"],
                      **{k: acc[str(int(p['param']))][k] for k in ("agreement", "kappa")}} for p in m]
    fig, ax = plt.subplots(figsize=(5, 3.6))
    ax.plot([p["cell_m"] for p in summary["E6"]], [p["compute_s"] for p in summary["E6"]], "o-", c="#2a9d8f")
    ax.set_xlabel("cell size (m)"); ax.set_ylabel("compute time (s)")
    ax2 = ax.twinx(); ax2.plot([p["cell_m"] for p in summary["E6"]], [p["agreement"] * 100 for p in summary["E6"]], "s--", c="#e63946")
    ax2.set_ylabel("agreement with 30 m result (%)", color="#e63946")
    ax.set_title("Coarser DEM: faster but less accurate", fontsize=9)
    save(fig, OUT / "fig_bench_resolution.png")

    summary["validation"] = json.load(open(OUT / "validation.json"))
    json.dump(summary, open(OUT / "benchmark_summary.json", "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in summary.items() if k in ("E1", "E2")}, indent=1, default=float)[:3000])


if __name__ == "__main__":
    main()
