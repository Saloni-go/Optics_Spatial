"""Track 3 - pan and zoom on the fly: radar coverage for the visible window at screen resolution.

    run.bat -m corridor.panzoom_bench

Canvas 1600 x 1000 px, 4000 x 4000 DEM (16 M cells), the six shared radars, aircraft 150 m AGL, 40 km range.
P1  zoom / pan sweep: 10 zoom levels (view 4000 .. 125 cells wide) x 8 random view centres each.
    Per view: level of detail chosen, ms, cells processed, agreement with the exact full-resolution coverage
    (Track 1 coverage_air150_count.tif) cell by cell, for the radar count and for covered / not covered.
    Two densities: 1 computed cell per screen pixel (default) and 2 (sharper).
    Baseline: recompute the full DEM at full resolution on every pan / zoom.
P2  radar count: 6 .. 48 radars (random sites): full recompute vs live view (full extent, and a 500-cell view).
P3  radar moved: redraw the current view vs recompute the whole coverage.
Outputs: results/corridor/panzoom/panzoom.json, fig_panzoom.png, fig_panzoom_radars.png, fig_panzoom_views.png
"""
import json
import time

import numpy as np
from osgeo import gdal

from common.config import RESULTS, dem_path
from common.dem_utils import DEM
from common.plots import plt, save, hillshade_for
from common.sites import load_sites
from corridor.liveview import LiveCoverage, upsample

OUT = RESULTS / "corridor" / "panzoom"
PX = (1600, 1000)
WIDTHS = (4000, 2828, 2000, 1414, 1000, 707, 500, 354, 250, 125)


def timed(f, n=3):
    best, out = [], None
    for _ in range(n):
        out = f(); best.append(out["ms"])
    out["ms"] = float(np.median(best))
    return out


def view_at(H, W, w, cr, cc):
    h = int(round(w * PX[1] / PX[0]))
    r0 = int(np.clip(cr - h // 2, 0, max(0, H - h))); c0 = int(np.clip(cc - w // 2, 0, max(0, W - w)))
    return (r0, min(H, r0 + h), c0, min(W, c0 + w))


def agreement(out, ref):
    b, k = out["box"], out["level"]
    rr = ref[b[0]:b[1], b[2]:b[3]]
    up = upsample(out["count"], k, rr.shape)
    return float((up == rr).mean()), float(((up > 0) == (rr > 0)).mean())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(5)
    dem = DEM(dem_path(4000)); H, W = dem.shape
    sites = [(x, y) for x, y, _ in load_sites()]
    L = LiveCoverage(dem)
    res = {"canvas_px": list(PX), "grid": [H, W], "radars": len(sites), "threads": L.threads,
           "pyramid": {"levels": sorted(L.levels), "build_s": round(L.pyramid_s, 3), "extra_mb": round(L.pyramid_mb, 1)}}

    # ---------------------------------------------------------------- exact reference + full-recompute baseline
    full = timed(lambda: L.compute(sites, (0, H, 0, W), PX, level=1))
    ref = full["count"]
    t1 = RESULTS / "radar" / "coverage_air150_count.tif"
    if t1.exists():
        res["reference_matches_track1"] = float((gdal.Open(str(t1)).ReadAsArray() == ref).mean())
    res["full_recompute_ms"] = round(full["ms"], 1)
    print("full recompute", res["full_recompute_ms"], "ms; matches Track 1:", res.get("reference_matches_track1"), flush=True)

    # ---------------------------------------------------------------- P1 zoom / pan sweep
    rows = []
    for w in WIDTHS:
        for j in range(8):
            cr, cc = (H // 2, W // 2) if w == W else (int(rng.integers(0, H)), int(rng.integers(0, W)))
            v = view_at(H, W, w, cr, cc)
            for dens in (1.0, 2.0):
                o = timed(lambda: L.compute(sites, v, PX, density=dens))
                a_count, a_cov = agreement(o, ref)
                rows.append({"width": w, "view": v, "density": dens, "level": o["level"], "cell_m": dem.cell * o["level"],
                             "ms": round(o["ms"], 2), "cells": o["cells"], "radars_used": o["radars"],
                             "out_px": list(o["count"].shape), "agree_count": round(a_count, 5), "agree_covered": round(a_cov, 5)})
            if w == W:
                break                                   # one full-extent view
        r = [x for x in rows if x["width"] == w and x["density"] == 1]
        print(f"view {w:5d} cells  level {r[0]['level']:2d}  {np.median([x['ms'] for x in r]):6.1f} ms  "
              f"agree {np.median([x['agree_count'] for x in r]):.4f} / {np.median([x['agree_covered'] for x in r]):.4f}", flush=True)
    res["P1_rows"] = rows
    summ = []
    for w in WIDTHS:
        for dens in (1.0, 2.0):
            r = [x for x in rows if x["width"] == w and x["density"] == dens]
            summ.append({"width": w, "density": dens, "level": r[0]["level"], "cell_m": r[0]["cell_m"],
                         "ms_median": round(float(np.median([x["ms"] for x in r])), 2),
                         "ms_max": round(float(np.max([x["ms"] for x in r])), 2),
                         "cells_median": int(np.median([x["cells"] for x in r])),
                         "agree_count_median": round(float(np.median([x["agree_count"] for x in r])), 4),
                         "agree_covered_median": round(float(np.median([x["agree_covered"] for x in r])), 4)})
    res["P1_summary"] = summ
    d1 = [x for x in rows if x["density"] == 1]
    res["P1_overall"] = {"views": len(d1), "ms_median": round(float(np.median([x["ms"] for x in d1])), 1),
                         "ms_p95": round(float(np.percentile([x["ms"] for x in d1], 95)), 1),
                         "ms_max": round(float(np.max([x["ms"] for x in d1])), 1),
                         "exact_views": sum(x["agree_count"] == 1.0 for x in d1),
                         "level1_views": sum(x["level"] == 1 for x in d1)}
    print("P1", res["P1_overall"], flush=True)

    # ---------------------------------------------------------------- P2 radar count
    m = int(10000 / dem.cell)
    p2 = []
    for n in (6, 12, 24, 48):
        S = sites + [dem.to_world(int(c), int(r)) for r, c in zip(rng.integers(m, H - m, n - 6), rng.integers(m, W - m, n - 6))]
        f = timed(lambda: L.compute(S, (0, H, 0, W), PX, level=1))
        lv = timed(lambda: L.compute(S, (0, H, 0, W), PX))
        zv = view_at(H, W, 500, H // 2, W // 2)
        zz = timed(lambda: L.compute(S, zv, PX))
        p2.append({"radars": n, "full_recompute_ms": round(f["ms"], 1), "live_full_extent_ms": round(lv["ms"], 1),
                   "live_full_extent_level": lv["level"], "live_zoom500_ms": round(zz["ms"], 1),
                   "live_zoom500_radars_used": zz["radars"]})
        print("P2", p2[-1], flush=True)
    res["P2_radars"] = p2

    # ---------------------------------------------------------------- P3 radar moved
    moved = list(sites); x, y = moved[2]; moved[2] = (x + 3000.0, y - 2000.0)
    p3 = {}
    for w in (4000, 1000, 250):
        v = view_at(H, W, w, H // 2, W // 2)
        p3[f"view_{w}"] = round(timed(lambda: L.compute(moved, v, PX))["ms"], 1)
    p3["full_recompute_ms"] = round(timed(lambda: L.compute(moved, (0, H, 0, W), PX, level=1))["ms"], 1)
    res["P3_radar_moved"] = p3
    print("P3", p3, flush=True)
    L.close()
    json.dump(res, open(OUT / "panzoom.json", "w"), indent=1)
    figures(res, dem, sites, ref)


def figures(res, dem, sites, ref):
    s = res["P1_summary"]
    fig, axs = plt.subplots(1, 2, figsize=(9.5, 3.4))
    for dens, col, lab in ((1.0, "#2a9d8f", "live view, 1 cell / pixel"), (2.0, "#e76f51", "live view, 2 cells / pixel")):
        r = [x for x in s if x["density"] == dens]
        axs[0].plot([x["width"] for x in r], [x["ms_median"] for x in r], "o-", color=col, label=lab, ms=4)
        axs[1].plot([x["width"] for x in r], [100 * x["agree_count_median"] for x in r], "o-", color=col, label=lab, ms=4)
    axs[0].axhline(res["full_recompute_ms"], color="#888", ls="--", label="recompute whole DEM, full res")
    for ax in axs:
        ax.set_xscale("log"); ax.invert_xaxis(); ax.set_xlabel("view width (cells; right = zoomed in)")
    axs[0].set_ylabel("ms per pan / zoom"); axs[0].set_title("Coverage for the visible window", fontsize=9)
    axs[0].legend(fontsize=7, frameon=False)
    axs[1].set_ylabel("% cells with the exact radar count"); axs[1].set_ylim(85, 100.5)
    axs[1].set_title("Agreement with full-resolution coverage", fontsize=9)
    r1 = [x for x in s if x["density"] == 1.0]
    for x in r1:
        axs[1].annotate(f"{x['cell_m']:.0f} m", (x["width"], 100 * x["agree_count_median"]), fontsize=6,
                        textcoords="offset points", xytext=(0, -10), ha="center")
    fig.tight_layout(); save(fig, OUT / "fig_panzoom.png")

    p2 = res["P2_radars"]
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    n = [x["radars"] for x in p2]
    ax.plot(n, [x["full_recompute_ms"] for x in p2], "o--", color="#888", label="recompute whole DEM")
    ax.plot(n, [x["live_full_extent_ms"] for x in p2], "o-", color="#2a9d8f", label="live view, full extent")
    ax.plot(n, [x["live_zoom500_ms"] for x in p2], "o-", color="#1d3557", label="live view, zoomed (500 cells)")
    ax.set_xlabel("radars"); ax.set_ylabel("ms per pan / zoom"); ax.legend(fontsize=7, frameon=False)
    ax.set_title("Cost follows the screen, not the DEM", fontsize=9)
    fig.tight_layout(); save(fig, OUT / "fig_panzoom_radars.png")

    # three views as the user would see them
    H, W = dem.shape
    L = LiveCoverage(dem)
    hs = hillshade_for(dem, 4000)
    cmap = plt.get_cmap("YlOrRd", 6)
    fig, axs = plt.subplots(1, 3, figsize=(10.5, 3.5))
    for ax, w in zip(axs, (4000, 1000, 250)):
        v = view_at(H, W, w, int(H * 0.45), int(W * 0.55))
        o = L.compute(sites, v, PX)
        b = o["box"]
        ext = (b[2], b[3], b[1], b[0])
        ax.imshow(hs[v[0]:v[1], v[2]:v[3]], cmap="gray", extent=(v[2], v[3], v[1], v[0]), interpolation="nearest")
        c = np.ma.masked_equal(o["count"], 0)
        ax.imshow(c, cmap=cmap, vmin=0.5, vmax=6.5, alpha=0.6, extent=ext, interpolation="nearest")
        ax.set_xlim(v[2], v[3]); ax.set_ylim(v[1], v[0]); ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(f"view {w} cells: level {o['level']} ({30 * o['level']} m), {o['ms']:.0f} ms", fontsize=8.5)
    L.close()
    fig.tight_layout(); save(fig, OUT / "fig_panzoom_views.png")


if __name__ == "__main__":
    main()
