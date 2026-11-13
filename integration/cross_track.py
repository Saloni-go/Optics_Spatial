"""Cross-track integration on the shared dataset (4000 x 4000 Copernicus DEM, six shared radars).

    run.bat -m integration.cross_track          (after radar.run_radar, flight.run_flight, corridor.run_corridor)

1. Coverage vs detection (Track 1 x Track 3): the cumulative radar viewshed for an aircraft 150 m above ground
   (Track 1, coverage_air150_count.tif) against the cells where the Track 3 detection hazard is non-zero.
   A route that stays outside the cumulative viewshed must have P(detect) = 0; checked cell by cell, on every
   named route, on 5000 random paths and on the best fully hidden route.
2. Named routes scored by all three tracks: Track 2 valley route, Track 3 least-exposure routes (alpha 1-100),
   Track 3 risk-budget route (P(detect) <= 50 %) and the hidden route: length, covered length, P(detect),
   which radar detects first, and what the aircraft itself sees along the route (Track 2 engine, 150 m AGL).
3. One machine for all benchmarks: E1 / F1 / C1 runtime vs DEM size and empirical exponents.
Outputs: results/integration/cross_track.json, fig_*.png
"""
import csv
import json
import time

import numpy as np

from common.config import RESULTS, dem_path, FLIGHT_RADIUS, OUT_OF_RANGE
from common.dem_utils import DEM, write_lines_geojson, write_raster
from common.plots import plt, base_map, km, save, C_RADAR
from common.sites import load_sites
from corridor import cgrid
from corridor.exposure import blocked_mask
from corridor.optimizer import Problem
from corridor.radarfield import RadarField

OUT = RESULTS / "integration"
SEED = 7
N_RANDOM = 5000


def read(path):
    from osgeo import gdal
    return gdal.Open(str(path)).ReadAsArray()


def lines(path):
    fc = json.load(open(path))
    return [(f["properties"], f["geometry"]["coordinates"]) for f in fc["features"]]


def to_cells(dem, xy, step=15.0):
    """Polyline in world coordinates -> sequence of distinct cell indices (sampled every `step` m)."""
    from flight.route import resample
    pts = resample(np.asarray(xy, float), step)
    c, r = dem.to_pixel(pts[:, 0], pts[:, 1])
    r = np.clip(np.round(r).astype(int), 0, dem.shape[0] - 1); c = np.clip(np.round(c).astype(int), 0, dem.shape[1] - 1)
    idx = r * dem.shape[1] + c
    keep = np.r_[True, idx[1:] != idx[:-1]]
    return idx[keep]


def seg_hazard(h, rc, cell):
    """Integrated hazard along a cell path (same trapezoid rule as RadarField.detection_probability)."""
    seg_km = np.hypot(*np.diff(rc, axis=0).T) * cell / 1000.0
    return float((seg_km * 0.5 * (h[1:] + h[:-1])).sum()), seg_km


def score(dem, F, covered, idx, per_radar):
    """Route metrics under the shared detection model."""
    W = dem.shape[1]
    rc = np.column_stack(np.divmod(np.asarray(idx), W))
    H, seg_km = seg_hazard(F.E[rc[:, 0], rc[:, 1]], rc, dem.cell)
    cov = covered[rc[:, 0], rc[:, 1]]
    seg_cov = 0.5 * (cov[1:].astype(float) + cov[:-1])
    # hazard of the uncovered part only: must be exactly 0
    h_out = np.where(cov, 0.0, F.E[rc[:, 0], rc[:, 1]])
    H_out, _ = seg_hazard(h_out, rc, dem.cell)
    cum = 1 - np.exp(-np.r_[0, np.cumsum(seg_km * 0.5 * (F.E[rc[1:, 0], rc[1:, 1]] + F.E[rc[:-1, 0], rc[:-1, 1]]))])
    dist = np.r_[0, np.cumsum(seg_km)]
    first = {}
    for q in (0.1, 0.5):
        k = np.argmax(cum >= q) if (cum >= q).any() else None
        first[f"km_to_p{int(q * 100)}"] = None if k is None else round(float(dist[k]), 1)
    rad = []
    for i, (r0, c0, a) in enumerate(per_radar):
        hi = np.zeros(len(rc))
        inside = (rc[:, 0] >= r0) & (rc[:, 0] < r0 + a.shape[0]) & (rc[:, 1] >= c0) & (rc[:, 1] < c0 + a.shape[1])
        hi[inside] = a[rc[inside, 0] - r0, rc[inside, 1] - c0]
        rad.append(1 - np.exp(-seg_hazard(hi, rc, dem.cell)[0]))
    return {"length_km": round(float(seg_km.sum()), 2), "covered_km": round(float((seg_km * seg_cov).sum()), 2),
            "covered_frac": round(float((seg_km * seg_cov).sum() / max(seg_km.sum(), 1e-9)), 4),
            "p_detect": float(1 - np.exp(-H)), "p_detect_outside_coverage": float(1 - np.exp(-H_out)),
            "p_per_radar": [round(float(p), 4) for p in rad], "worst_radar": f"R{int(np.argmax(rad)) + 1}" if max(rad) > 0 else None,
            **first, "_profile": (dist, cum, cov)}


def bresenham(r0, c0, r1, c1):
    n = int(max(abs(r1 - r0), abs(c1 - c0))) + 1
    rr = np.round(np.linspace(r0, r1, n)).astype(int); cc = np.round(np.linspace(c0, c1, n)).astype(int)
    return rr, cc


def aircraft_view(dem, xy, agl=150.0, spacing=1000.0):
    """Track 2 engine: area the aircraft itself sees along the route (radius 20 km, terrain following)."""
    from flight.route import resample
    from flight.visibility import AltitudeModel, run_route
    verts = [tuple(p) for p in np.asarray(xy, float)]
    pts = resample(np.asarray(verts), spacing)
    am = AltitudeModel(dem, verts, "agl", agl, None)
    acc, t = run_route(dem, pts, am, FLIGHT_RADIUS, mode="window")
    return {"seen_km2": round(float((acc.count > 0).sum() * dem.cell ** 2 / 1e6), 1), "waypoints": len(pts),
            "track2_compute_s": round(float(t["compute_s"]), 2)}


def bench_summary():
    from common.analysis import load, medians, power_fit
    out, curves = {}, {}
    for track, exp, label in (("radar", "E1_size", "Track 1 viewshed"), ("flight", "F1_size", "Track 2 route visibility"),
                              ("corridor", "C1_size", "Track 3 routing")):
        f = RESULTS / track / "benchmark_raw.csv"
        if not f.exists():
            continue
        m = medians(load(f), exp)
        mach = json.load(open(RESULTS / track / "machine.json")) if (RESULTS / track / "machine.json").exists() else {}
        out[track] = {"experiment": exp, "machine_cpu": mach.get("cpu"), "cores": mach.get("cores_logical"), "algorithms": {}}
        for alg, rows in m.items():
            x = [r["param"] for r in rows]; y = [r["runtime"] for r in rows]
            b, _ = power_fit(x, y)
            out[track]["algorithms"][alg] = {"cells": x, "runtime_s": [round(v, 4) for v in y],
                                             "peak_mb": [round(r["peak_mb"], 1) for r in rows], "exponent": b}
            curves[(label, alg)] = (x, y)
    return out, curves


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    dem = DEM(dem_path(4000))
    sites = [(x, y) for x, y, _ in load_sites()]
    W, H = dem.shape[1], dem.shape[0]
    res = {"dataset": {"dem": "Copernicus GLO-30, 4000 x 4000, 30 m, EPSG:32644", "radars": len(sites),
                       "aircraft_agl_m": 150, "radar_mast_m": 30, "range_km": 40}}

    # ---------------------------------------------------------------- 1. coverage vs detection, cell by cell
    cov_count = read(RESULTS / "radar" / "coverage_air150_count.tif")
    covered = (cov_count > 0) & (cov_count != OUT_OF_RANGE)
    F = RadarField(dem, sites, "detection")
    hazard = F.E > 0
    both, cov_only, haz_only = (covered & hazard).sum(), (covered & ~hazard).sum(), (~covered & hazard).sum()
    res["cells"] = {"covered_by_track1": int(covered.sum()), "hazard_track3": int(hazard.sum()), "both": int(both),
                    "covered_not_hazard": int(cov_only), "hazard_not_covered": int(haz_only),
                    "agreement": float(1 - (cov_only + haz_only) / covered.size),
                    "covered_frac_of_dem": float(covered.mean())}
    print("cells", res["cells"], flush=True)
    if haz_only:                      # where the models disagree: distance from the nearest radar
        rr, cc = np.nonzero(~covered & hazard)
        d = np.min([np.hypot(*(np.array(dem.to_world(cc, rr)) - np.array(s)[:, None])) for s in sites], axis=0)
        res["cells"]["hazard_not_covered_dist_km"] = [round(float(np.min(d)) / 1000, 2), round(float(np.max(d)) / 1000, 2)]

    # ---------------------------------------------------------------- 2. named routes
    stats3 = json.load(open(RESULTS / "corridor" / "stats.json"))
    start, goal = tuple(stats3["start"]), tuple(stats3["goal"])
    named = {}
    (p2, xy2), = lines(RESULTS / "flight" / "route.geojson")
    named["Track 2 valley route"] = xy2
    for props, xy in lines(RESULTS / "corridor" / "routes.geojson"):
        if props["name"] in ("shortest", "alpha_1", "alpha_10", "alpha_100"):
            named["Track 3 " + props["name"].replace("_", " = ").replace("alpha", "alpha")] = xy
    blk = blocked_mask(dem)
    zero = np.zeros(dem.shape)
    # risk budget route: shortest route with P(detect) <= 50 % (Track 3 LARAC)
    from corridor.riskcsp import RiskCSP
    p10 = Problem(dem.z, F.E, blk, dem.cell, 10.0, 2.0)
    t = time.perf_counter()
    rb = RiskCSP(p10, goal, threads=cgrid.THREADS).query(start, 0.5, width_cells=15, resolution=1e-2, max_labels=4_000_000)
    res["risk_budget_s"] = round(time.perf_counter() - t, 1)
    if rb.get("path"):
        named["Track 3 risk budget 50 %"] = [dem.to_world(i % W, i // W) for i in rb["path"]]
    # fully hidden route: aircraft never inside the cumulative viewshed (cells covered = blocked)
    hidden_blk = blk | covered
    hid = {"start_covered": bool(covered[start]), "goal_covered": bool(covered[goal])}
    ph = Problem(dem.z, zero, hidden_blk, dem.cell, 0.0, 0.0)
    r = cgrid.dijkstra_c(ph, start, goal) if not (hidden_blk[start] or hidden_blk[goal]) else {"path": None}
    hid["exists"] = bool(r.get("path"))
    # least covered length route: distance inside coverage costs 1000x
    pm = Problem(dem.z, covered.astype(float), blk, dem.cell, 1000.0, 0.0)
    rm = cgrid.dijkstra_c(pm, start, goal)
    if r.get("path"):
        named["Hidden route (outside cumulative viewshed)"] = [dem.to_world(i % W, i // W) for i in r["path"]]
    if rm.get("path"):
        named["Least covered length"] = [dem.to_world(i % W, i // W) for i in rm["path"]]
    res["hidden_route"] = hid
    routes, profiles = {}, {}
    for name, xy in named.items():
        s = score(dem, F, covered, to_cells(dem, xy), F.contrib)
        profiles[name] = s.pop("_profile")
        t = time.perf_counter()
        s["aircraft_sees"] = aircraft_view(dem, xy)
        routes[name] = s
        print(f"{name:42s} {s['length_km']:7.1f} km  covered {s['covered_km']:6.1f} km  P(detect) {100 * s['p_detect']:6.2f}%  "
              f"outside-coverage {s['p_detect_outside_coverage']:.2e}  sees {s['aircraft_sees']['seen_km2']:,.0f} km2 "
              f"({time.perf_counter() - t:.0f} s)", flush=True)
    res["routes"] = routes
    write_lines_geojson(OUT / "routes_scored.geojson", list(named.values()),
                        [{"name": n, "p_detect": v["p_detect"], "length_km": v["length_km"], "covered_km": v["covered_km"]}
                         for n, v in routes.items()])

    # ---------------------------------------------------------------- random paths
    rng = np.random.default_rng(SEED)
    free = np.argwhere(~blk)
    P, frac, viol = np.zeros(N_RANDOM), np.zeros(N_RANDOM), 0
    for k in range(N_RANDOM):
        (r0, c0), (r1, c1) = free[rng.integers(len(free), size=2)]
        rr, cc = bresenham(r0, c0, r1, c1)
        h = F.E[rr, cc]; cv = covered[rr, cc]
        rc = np.column_stack([rr, cc])
        Hh, sk = seg_hazard(h, rc, dem.cell)
        P[k] = 1 - np.exp(-Hh)
        frac[k] = float((sk * 0.5 * (cv[1:].astype(float) + cv[:-1])).sum() / max(sk.sum(), 1e-9))
        if seg_hazard(np.where(cv, 0.0, h), rc, dem.cell)[0] > 0:
            viol += 1
    out_paths = frac == 0
    res["random_paths"] = {"n": N_RANDOM, "fully_outside_coverage": int(out_paths.sum()),
                           "max_p_detect_fully_outside": float(P[out_paths].max()) if out_paths.any() else None,
                           "paths_with_hazard_outside_coverage": viol,
                           "p_detect_median_by_covered_frac": {f"{lo:.1f}-{lo + .2:.1f}": float(np.median(P[(frac >= lo) & (frac < lo + .2)]))
                                                               for lo in np.arange(0, 1, .2) if ((frac >= lo) & (frac < lo + .2)).any()}}
    print("random", res["random_paths"], flush=True)

    # ---------------------------------------------------------------- 3. benchmarks on one machine
    res["benchmarks"], curves = bench_summary()
    res["seconds"] = round(time.perf_counter() - t0, 1)
    json.dump(res, open(OUT / "cross_track.json", "w"), indent=1, default=float)
    figures(dem, sites, cov_count, covered, named, routes, profiles, frac, P, curves, res)
    print("done", res["seconds"], "s")


def figures(dem, sites, cov_count, covered, named, routes, profiles, frac, P, curves, res):
    from matplotlib.colors import ListedColormap
    colours = ["#1d3557", "#2a9d8f", "#e9c46a", "#f4a261", "#e76f51", "#8338ec", "#06d6a0", "#ff006e"]
    # integrated map
    fig, ax = plt.subplots(figsize=(8.6, 8))
    ext = base_map(ax, dem, 4000, elev_tint=False)
    cmap = ListedColormap(["#ffd6cc", "#ff9b85", "#f4512c", "#c1121f", "#780000", "#3d0000"])
    ax.imshow(np.ma.masked_where(~covered, np.minimum(cov_count, 6)), cmap=cmap, vmin=0.5, vmax=6.5, extent=ext, alpha=0.55,
              interpolation="nearest")
    for (name, xy), col in zip(named.items(), colours):
        a = np.asarray(xy)
        ax.plot(km(a[:, 0]), km(a[:, 1]), lw=1.8 if "Track 3" in name else 1.3, c=col,
                ls="--" if "valley" in name else "-",
                label=f"{name}: P(detect) {100 * routes[name]['p_detect']:.0f}%, {routes[name]['length_km']:.0f} km")
    for i, (x, y) in enumerate(sites):
        ax.plot(km(x), km(y), "^", c=C_RADAR, mec="white", ms=9)
        ax.text(km(x) + 1.2, km(y) + 1.2, f"R{i + 1}", fontsize=8, weight="bold")
    ax.legend(fontsize=6.6, loc="lower right", framealpha=0.92)
    ax.set_title("All three tracks on one dataset: radar coverage of a 150 m AGL aircraft (Track 1, red = number of radars),\n"
                 "Track 2 valley route and Track 3 routes scored with the same detection model", fontsize=8.5)
    save(fig, OUT / "fig_integrated_map.png")
    # coverage vs detection on random paths
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
    axs[0].scatter(frac, 100 * P, s=3, alpha=0.25, c="#555")
    for (name, s), col in zip(routes.items(), colours):
        axs[0].scatter(s["covered_frac"], 100 * s["p_detect"], s=60, c=col, edgecolors="k", label=name, zorder=5)
    axs[0].set_xlabel("fraction of path length inside the cumulative viewshed (Track 1)")
    axs[0].set_ylabel("P(detect) under the Track 3 model (%)")
    rp = res["random_paths"]
    axs[0].set_title(f"{rp['n']} random paths + named routes: {rp['fully_outside_coverage']} paths fully outside coverage,\n"
                     f"max P(detect) among them = {100 * (rp['max_p_detect_fully_outside'] or 0):.3g}%; "
                     f"paths with hazard outside coverage: {rp['paths_with_hazard_outside_coverage']}", fontsize=8)
    axs[0].legend(fontsize=6.3, loc="lower right")
    for (name, (d, cum, cov)), col in zip(profiles.items(), colours):
        axs[1].plot(d, 100 * cum, c=col, lw=1.4, label=name)
    axs[1].set_xlabel("distance along route (km)"); axs[1].set_ylabel("cumulative P(detect) (%)")
    axs[1].set_title("Detection accumulates only inside the cumulative viewshed", fontsize=9)
    fig.tight_layout(); save(fig, OUT / "fig_detection_vs_coverage.png")
    # benchmarks on one machine
    if curves:
        fig, ax = plt.subplots(figsize=(7.4, 4.6))
        for (label, alg), (x, y) in curves.items():
            ax.loglog(x, y, "o-", ms=3.5, lw=1.1, label=f"{label}: {alg}")
        ax.set_xlabel("DEM cells"); ax.set_ylabel("median runtime (s)")
        from common.bench import machine_info
        mi = machine_info()
        mach = (f"AMD Ryzen 9 7900X, {mi['cores_physical']} cores / {mi['cores_logical']} threads" if "AuthenticAMD" in (mi["cpu"] or "")
                and mi["cores_logical"] == 24 else mi["cpu"])
        ax.set_title(f"Runtime vs DEM size, all tracks on the same machine\n({mach})", fontsize=9)
        ax.legend(fontsize=6.5, ncol=2); ax.grid(alpha=0.3, which="both")
        save(fig, OUT / "fig_scaling_all_tracks.png")


if __name__ == "__main__":
    main()
