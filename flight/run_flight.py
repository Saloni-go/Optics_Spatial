"""Track 2 - scenario run: Alaknanda valley route over the 4000 x 4000 DEM.

Produces (results/flight/):
  route.geojson, waypoints.geojson               route and sampled positions (alt, visible km2)
  count_<case>.tif, first_seen_<case>.tif        cumulative visibility and first-seen index
  blind_<case>.tif                               corridor cells never seen
  stats.json, fig_*.png                          numbers and figures

Two flight profiles are compared: terrain-following at 300 m AGL (valley flying) and a constant
cruise at 5500 m MSL.
Run:  run.bat -m flight.run_flight
"""
import json
import numpy as np
from osgeo import gdal

from common.config import RESULTS, FLIGHT_AGL, FLIGHT_RADIUS, WAYPOINT_SPACING, dem_path
from common.dem_utils import DEM, write_raster, write_lines_geojson, write_points_geojson
from common.plots import plt, base_map, km, save, extent_km, C_ROUTE
from flight.route import ALAKNANDA, lonlat_to_utm, resample, length, valley_route

TOWN_NAMES = ["near Devprayag (start)", "Devprayag", "Srinagar", "Rudraprayag", "Karnaprayag", "Chamoli", "Joshimath (end)"]
from flight.visibility import AltitudeModel, run_route, corridor_mask

OUT = RESULTS / "flight"
CASES = {"agl300": {"mode": "agl", "agl": FLIGHT_AGL, "msl": None, "label": "Terrain following, 300 m AGL"},
         "msl5500": {"mode": "msl", "agl": FLIGHT_AGL, "msl": 5500.0, "label": "Cruise, 5500 m MSL"}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dem = DEM(dem_path(4000))
    towns = lonlat_to_utm(ALAKNANDA)
    verts = valley_route(dem, towns)
    write_lines_geojson(OUT / "route.geojson", [verts], [{"name": "Alaknanda valley route", "length_km": length(verts) / 1000}])
    write_points_geojson(OUT / "towns.geojson", towns, [{"name": n} for n in TOWN_NAMES])
    pts = resample(verts, WAYPOINT_SPACING)
    dense = resample(verts, 100.0)
    corr = corridor_mask(dem, dense, FLIGHT_RADIUS)
    a = dem.cell ** 2 / 1e6
    stats = {"route_km": length(verts) / 1000, "waypoints": len(pts), "spacing_m": WAYPOINT_SPACING,
             "radius_m": FLIGHT_RADIUS, "corridor_km2": float(corr.sum() * a), "cases": {}}
    accs = {}
    for name, c in CASES.items():
        am = AltitudeModel(dem, verts, c["mode"], c["agl"], c["msl"])
        acc, t = run_route(dem, pts, am, FLIGHT_RADIUS, mode="window")
        accs[name] = (acc, am)
        seen = acc.count > 0
        blind = corr & ~seen
        write_raster(OUT / f"count_{name}.tif", acc.count, dem.gt, dem.proj, gdal.GDT_UInt16, nodata=0)
        write_raster(OUT / f"first_seen_{name}.tif", acc.first, dem.gt, dem.proj, gdal.GDT_Int32, nodata=-1)
        write_raster(OUT / f"blind_{name}.tif", blind.astype(np.uint8), dem.gt, dem.proj, gdal.GDT_Byte, nodata=0)
        alts = am(pts[:, 2])
        per = np.array(acc.per_wp)
        stats["cases"][name] = {"label": c["label"], "compute_s": t["compute_s"],
                                "seen_km2": float(seen.sum() * a), "seen_in_corridor_frac": float((seen & corr).sum() / corr.sum()),
                                "blind_km2": float(blind.sum() * a), "mean_visible_km2_per_wp": float(per[:, 1].mean()),
                                "max_count": int(acc.count.max()), "alt_min": float(alts.min()), "alt_max": float(alts.max()),
                                "clearance_min": float((alts - dem.elev_at(pts[:, 0], pts[:, 1])).min())}
        write_points_geojson(OUT / f"waypoints_{name}.geojson", pts[:, :2],
                             [{"i": int(i), "dist_km": float(pts[i, 2] / 1000), "alt_msl": float(alts[i]),
                               "visible_km2": float(per[i, 1]), "new_km2": float(per[i, 2])} for i in range(len(pts))])
        print(name, json.dumps(stats["cases"][name]))
    json.dump(stats, open(OUT / "stats.json", "w"), indent=1)
    figures(dem, verts, pts, dense, corr, accs, stats)


def figures(dem, verts, pts, dense, corr, accs, stats):
    v = np.asarray(verts)
    # 1. cumulative visibility maps for both profiles
    fig, axs = plt.subplots(1, 2, figsize=(11, 5.4))
    for ax, (name, (acc, am)) in zip(axs, accs.items()):
        ext = base_map(ax, dem, 4000, elev_tint=False)
        cnt = np.ma.masked_equal(acc.count, 0)
        im = ax.imshow(cnt, cmap="magma_r", extent=ext, alpha=0.75, norm=matplotlib_lognorm(cnt.max()))
        blind = np.ma.masked_where(~(corr & (acc.count == 0)), np.ones(dem.shape))
        ax.imshow(blind, cmap="Blues", vmin=0, vmax=1.5, extent=ext, alpha=0.6)
        ax.plot(km(v[:, 0]), km(v[:, 1]), c=C_ROUTE, lw=1.6)
        ax.plot(km(pts[0, 0]), km(pts[0, 1]), "o", c="white", mec="k", ms=5)
        ax.plot(km(pts[-1, 0]), km(pts[-1, 1]), "s", c="white", mec="k", ms=5)
        s = stats["cases"][name]
        ax.set_title(f"{CASES[name]['label']}\nseen {s['seen_km2']:,.0f} km$^2$, blind in corridor {s['blind_km2']:,.0f} km$^2$", fontsize=9)
        fig.colorbar(im, ax=ax, shrink=0.7, label="number of positions that see the cell")
    save(fig, OUT / "fig_cumulative_visibility.png")

    # 2. altitude profile
    fig, ax = plt.subplots(figsize=(9, 3))
    g = dem.elev_at(dense[:, 0], dense[:, 1])
    ax.fill_between(dense[:, 2] / 1000, 0, g, color="#bfa98a", label="terrain under route")
    for name, (acc, am) in accs.items():
        ax.plot(dense[:, 2] / 1000, am(dense[:, 2]), lw=1.4, label=CASES[name]["label"])
    ax.set_ylim(0, None); ax.set_xlabel("distance along route (km)"); ax.set_ylabel("m above sea level")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    save(fig, OUT / "fig_altitude_profile.png")

    # 3. per-position visible and newly seen area + cumulative
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.2))
    for name, (acc, am) in accs.items():
        per = np.array(acc.per_wp)
        d = pts[:, 2] / 1000
        axs[0].plot(d, per[:, 1], lw=1.1, label=CASES[name]["label"])
        axs[1].plot(d, np.cumsum(per[:, 2]), lw=1.4, label=CASES[name]["label"])
    axs[0].set_ylabel("visible area at position (km$^2$)"); axs[1].set_ylabel("cumulative area seen (km$^2$)")
    for ax in axs:
        ax.set_xlabel("distance along route (km)")
    axs[0].legend(fontsize=8, frameon=False)
    save(fig, OUT / "fig_coverage_along_route.png")


def matplotlib_lognorm(vmax):
    from matplotlib.colors import LogNorm
    return LogNorm(vmin=1, vmax=max(int(vmax), 2))


if __name__ == "__main__":
    main()
