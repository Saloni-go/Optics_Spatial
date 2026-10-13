"""Track 3 - scenario: Devprayag -> Joshimath (same endpoints as the Track 2 route) on the
4000 x 4000 DEM, avoiding the six shared radars, aircraft 150 m above ground, ceiling 5000 m.

Routes for alpha in {0 (shortest, beta=0), 1, 3, 10, 30, 100} with beta = 2, plus the Track 2
valley route evaluated with the same metrics.
Outputs (results/corridor/): exposure.tif, blocked.tif, routes.geojson, stats.json, fig_*.png
Run:  run.bat -m corridor.run_corridor
"""
import json
import numpy as np
from osgeo import gdal

from common.config import RESULTS, dem_path
from common.dem_utils import DEM, write_raster, write_lines_geojson
from common.plots import plt, base_map, km, save, C_RADAR
from common.sites import load_sites
from corridor.exposure import exposure, blocked_mask, CEILING
from corridor.optimizer import Problem, dijkstra_csgraph, astar_py, evaluate
from flight.route import ALAKNANDA, lonlat_to_utm, resample, load_route

OUT = RESULTS / "corridor"
ALPHAS = [0, 1, 3, 10, 30, 100]
BETA = 2.0


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dem = DEM(dem_path(4000))
    sites = load_sites()
    E, cnt = exposure(dem, sites)
    blk = blocked_mask(dem)
    write_raster(OUT / "exposure.tif", E, dem.gt, dem.proj, gdal.GDT_Float32)
    write_raster(OUT / "blocked.tif", blk.astype(np.uint8), dem.gt, dem.proj, gdal.GDT_Byte, nodata=0)
    verts = lonlat_to_utm(ALAKNANDA)
    (sx, sy), (gx, gy) = verts[0], verts[-1]
    sc, sr = dem.to_pixel(sx, sy); gc, gr = dem.to_pixel(gx, gy)
    start, goal = (int(round(sr)), int(round(sc))), (int(round(gr)), int(round(gc)))
    routes, props, stats = [], [], {"start": start, "goal": goal, "ceiling_m": CEILING, "beta": BETA,
                                    "exposed_frac_of_dem": float((E > 0).mean()), "blocked_frac": float(blk.mean()),
                                    "routes": {}}
    for a in ALPHAS:
        b = 0.0 if a == 0 else BETA
        p = Problem(dem.z, E, blk, dem.cell, a, b)
        r = dijkstra_csgraph(p, start, goal)
        ev = evaluate(Problem(dem.z, E, blk, dem.cell, 10.0, BETA), r["path"])   # report on a common scale
        ev.update({"alpha": a, "beta": b, "solve_s": r["solve_s"], "build_s": r["build_s"]})
        name = "shortest" if a == 0 else f"alpha_{a}"
        stats["routes"][name] = ev
        xy = [dem.to_world(*divmod(i, dem.shape[1])[::-1]) for i in r["path"]]
        routes.append(xy); props.append({"name": name, **{k: v for k, v in ev.items() if isinstance(v, (int, float))}})
        print(name, {k: round(v, 3) if isinstance(v, float) else v for k, v in ev.items()})
    # A* on alpha=10 must return the same cost as Dijkstra
    p10 = Problem(dem.z, E, blk, dem.cell, 10, BETA)
    ra = astar_py(p10, start, goal)
    stats["astar_check_alpha10"] = {"astar_cost": ra["cost"], "dijkstra_cost": stats["routes"]["alpha_10"]["cost"],
                                    "astar_expanded": ra["expanded"], "astar_s": ra["solve_s"]}
    print("A* check", stats["astar_check_alpha10"])
    # landmark (ALT) heuristic: same optimum, far fewer expansions
    from corridor.optimizer import Landmarks, astar_alt
    lm = Landmarks(p10, k=4)
    rl = astar_alt(p10, start, goal, lm)
    stats["alt_check_alpha10"] = {"alt_cost": rl["cost"], "alt_expanded": rl["expanded"], "alt_s": rl["solve_s"],
                                  "heuristic_s": rl["build_s"], "landmark_pre_s": rl["pre_s"], "landmark_mb": rl["pre_mb"]}
    print("ALT check", stats["alt_check_alpha10"])
    # Track 2 valley route under the same metrics
    verts = load_route()
    vr = resample(verts, 30.0)
    c, rr = dem.to_pixel(vr[:, 0], vr[:, 1])
    idx = [int(round(y)) * dem.shape[1] + int(round(x)) for x, y in zip(c, rr)]
    idx = [i for k, i in enumerate(idx) if k == 0 or i != idx[k - 1]]
    stats["routes"]["track2_valley_route"] = evaluate(p10, idx)
    write_lines_geojson(OUT / "routes.geojson", routes, props)
    json.dump(stats, open(OUT / "stats.json", "w"), indent=1)
    figures(dem, E, blk, sites, routes, stats, verts)


def figures(dem, E, blk, sites, routes, stats, verts):
    fig, ax = plt.subplots(figsize=(8, 7.4))
    ext = base_map(ax, dem, 4000, elev_tint=False)
    ax.imshow(np.ma.masked_equal(E, 0), cmap="Reds", extent=ext, alpha=0.6, vmin=0, vmax=max(E.max(), 1))
    ax.imshow(np.ma.masked_equal(blk.astype(np.uint8), 0), cmap="Greys", vmin=0, vmax=1.3, extent=ext, alpha=0.55)
    cols = {"shortest": "#1d3557", "alpha_3": "#457b9d", "alpha_10": "#2a9d8f", "alpha_100": "#8338ec"}
    for xy, (name, ev) in zip(routes, stats["routes"].items()):
        if name not in cols:
            continue
        a = np.array(xy)
        ax.plot(km(a[:, 0]), km(a[:, 1]), c=cols[name], lw=1.8,
                label=f"{name}: {ev['length_km']:.0f} km, exposed {ev['exposed_frac'] * 100:.0f}%")
    v = np.array(verts)
    ax.plot(km(v[:, 0]), km(v[:, 1]), c="k", ls=":", lw=1.2, label="Track 2 valley route")
    for x, y, p in sites:
        ax.plot(km(x), km(y), "^", c=C_RADAR, mec="k", ms=8)
    ax.legend(fontsize=7.5, loc="lower right", framealpha=0.9)
    ax.set_title("Radar exposure (red) of an aircraft 150 m above ground, blocked terrain (grey)\n"
                 "and least-exposure routes Devprayag -> Joshimath", fontsize=9)
    save(fig, OUT / "fig_routes.png")

    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    rs = [(n, e) for n, e in stats["routes"].items() if n.startswith(("shortest", "alpha"))]
    L = [e["length_km"] for _, e in rs]; X = [e["exposure_km"] for _, e in rs]
    ax.plot(L, X, "o-", c="#2a9d8f")
    for (n, e), l, x in zip(rs, L, X):
        ax.annotate(n.replace("alpha_", "a="), (l, x), textcoords="offset points", xytext=(4, 4), fontsize=7.5)
    t2 = stats["routes"]["track2_valley_route"]
    ax.plot(t2["length_km"], t2["exposure_km"], "s", c="k"); ax.annotate("Track 2 route", (t2["length_km"], t2["exposure_km"]),
                                                                       textcoords="offset points", xytext=(4, -10), fontsize=7.5)
    ax.set_xlabel("route length (km)"); ax.set_ylabel("exposure integral (km, weighted)")
    ax.set_title("Distance vs radar exposure trade-off", fontsize=9)
    save(fig, OUT / "fig_tradeoff.png")


if __name__ == "__main__":
    main()
