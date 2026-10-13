"""Track 1 - scenario run on the 4000 x 4000 DEM with the six shared radar sites.

Outputs (results/radar/):
  viewshed_R<i>.tif           ground visibility from each radar (1 visible, 0 blocked, 255 out of range)
  coverage_ground_count.tif   number of radars that see each ground cell
  coverage_air150_count.tif   number of radars that see an aircraft 150 m above each cell
  range_rings.geojson         radar range circles
  stats.json, fig_*.png
Run:  run.bat -m radar.run_radar
"""
import json
import numpy as np
from osgeo import gdal

from common.config import RESULTS, RADAR_HEIGHT, TARGET_AIRCRAFT, VISIBLE, OUT_OF_RANGE, dem_path
from common.dem_utils import DEM, write_raster, write_lines_geojson
from common.plots import plt, base_map, km, save, C_RADAR
from common.sites import load_sites
from radar.viewshed import gdal_viewshed, agreement

OUT = RESULTS / "radar"
RANGE = 40000.0


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dem = DEM(dem_path(4000))
    sites = load_sites()
    a = dem.cell ** 2 / 1e6
    ground = np.zeros(dem.shape, np.uint8); air = np.zeros(dem.shape, np.uint8)
    stats = {"range_km": RANGE / 1000, "radar_h_m": RADAR_HEIGHT, "aircraft_agl_m": TARGET_AIRCRAFT, "radars": []}
    rings = []
    for i, (x, y, p) in enumerate(sites):
        v = gdal_viewshed(dem, x, y, RADAR_HEIGHT, 0.0, RANGE)
        va = gdal_viewshed(dem, x, y, RADAR_HEIGHT, TARGET_AIRCRAFT, RANGE)
        write_raster(OUT / f"viewshed_{p['id']}.tif", v, dem.gt, dem.proj, gdal.GDT_Byte, nodata=OUT_OF_RANGE)
        inr = v != OUT_OF_RANGE
        ground += (v == VISIBLE); air += (va == VISIBLE)
        stats["radars"].append({"id": p["id"], "x": x, "y": y, "ground_m": p["ground_m"],
                                "area_in_range_km2": float(inr.sum() * a),
                                "ground_visible_km2": float((v == VISIBLE).sum() * a),
                                "ground_visible_frac": float((v[inr] == VISIBLE).mean()),
                                "air150_visible_frac": float((va[va != OUT_OF_RANGE] == VISIBLE).mean())})
        t = np.linspace(0, 2 * np.pi, 121)
        rings.append(list(zip(x + RANGE * np.cos(t), y + RANGE * np.sin(t))))
        print(stats["radars"][-1])
    write_raster(OUT / "coverage_ground_count.tif", ground, dem.gt, dem.proj, gdal.GDT_Byte, nodata=0)
    write_raster(OUT / "coverage_air150_count.tif", air, dem.gt, dem.proj, gdal.GDT_Byte, nodata=0)
    write_lines_geojson(OUT / "range_rings.geojson", rings, [{"id": s[2]["id"]} for s in sites])
    stats["union_ground_frac_of_dem"] = float((ground > 0).mean())
    stats["union_air150_frac_of_dem"] = float((air > 0).mean())
    stats["multi_covered_ground_frac"] = float((ground > 1).mean())
    json.dump(stats, open(OUT / "stats.json", "w"), indent=1)
    figures(dem, sites, ground, air, stats)


def figures(dem, sites, ground, air, stats):
    from matplotlib.colors import ListedColormap, BoundaryNorm
    cm = ListedColormap(["#ffd166", "#f8961e", "#f3722c", "#e63946", "#9d0208", "#370617"])
    norm = BoundaryNorm(np.arange(0.5, 7.5), cm.N)
    fig, axs = plt.subplots(1, 2, figsize=(11.5, 5.4))
    for ax, arr, ttl in ((axs[0], ground, "Ground cells visible (radar mast 30 m)"),
                         (axs[1], air, f"Aircraft {int(TARGET_AIRCRAFT)} m above ground detectable")):
        ext = base_map(ax, dem, 4000, elev_tint=False)
        im = ax.imshow(np.ma.masked_equal(arr, 0), cmap=cm, norm=norm, extent=ext, alpha=0.9)
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3])
        for x, y, p in sites:
            ax.add_patch(plt.Circle((km(x), km(y)), RANGE / 1000, fill=False, ls="--", lw=0.7, ec="k"))
            ax.plot(km(x), km(y), "^", c=C_RADAR, mec="k", ms=7)
            ax.text(km(x) + 1.5, km(y) + 1.5, p["id"], fontsize=8, weight="bold")
        frac = (arr > 0).mean() * 100
        ax.set_title(f"{ttl}\nunion: {frac:.1f}% of the 120 x 120 km area", fontsize=9)
    cb = fig.colorbar(im, ax=axs, shrink=0.7, ticks=range(1, 7)); cb.set_label("number of radars")
    save(fig, OUT / "fig_coverage_six_radars.png")

    # single radar close-up: visible vs blocked inside the range circle
    x, y, p = sites[0]
    v = gdal_viewshed(dem, x, y, RADAR_HEIGHT, 0.0, RANGE)
    k = int(RANGE / dem.cell) + 20
    c, r = dem.to_pixel(x, y); c, r = int(c), int(r)
    r0, r1, c0, c1 = max(r - k, 0), min(r + k, dem.shape[0]), max(c - k, 0), min(c + k, dem.shape[1])
    sub = v[r0:r1, c0:c1]
    from osgeo import gdal as g
    hs = g.Open(str(dem_path(4000)).replace("dem_4000", "hillshade_4000")).ReadAsArray()[r0:r1, c0:c1]
    ext = [km(dem.gt[0] + c0 * dem.cell), km(dem.gt[0] + c1 * dem.cell), km(dem.gt[3] - r1 * dem.cell), km(dem.gt[3] - r0 * dem.cell)]
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(hs, cmap="gray", extent=ext)
    ov = np.full(sub.shape + (4,), 0.0)
    ov[sub == 1] = (0.95, 0.65, 0.25, 0.65); ov[sub == 0] = (0.15, 0.2, 0.45, 0.45)
    ax.imshow(ov, extent=ext)
    ax.plot(km(x), km(y), "^", c=C_RADAR, mec="k", ms=10)
    s = stats["radars"][0]
    ax.set_title(f"Radar {p['id']} ({p['ground_m']:.0f} m): orange visible, blue blocked\n"
                 f"{s['ground_visible_frac'] * 100:.1f}% of ground within {RANGE / 1000:.0f} km is visible", fontsize=9)
    ax.set_xlabel("Easting (km)"); ax.set_ylabel("Northing (km)")
    save(fig, OUT / "fig_single_radar.png")

    # algorithm comparison on the 500 x 500 validation run
    try:
        n = np.load(OUT / "val_500_naive.npy"); r2 = np.load(OUT / "val_500_r2.npy"); gd = np.load(OUT / "val_500_gdal.npy")
    except FileNotFoundError:
        return
    d500 = DEM(dem_path(500))
    hs = g.Open(str(dem_path(500)).replace("dem_500", "hillshade_500")).ReadAsArray()
    fig, axs = plt.subplots(1, 4, figsize=(14, 3.8))
    for ax, arr, t in ((axs[0], n, "Naive LOS (exact reference)"), (axs[1], r2, "R2 ray casting"), (axs[2], gd, "GDAL viewshed")):
        ax.imshow(hs, cmap="gray"); ov = np.zeros(arr.shape + (4,)); ov[arr == 1] = (0.95, 0.65, 0.25, 0.7)
        ax.imshow(ov); ax.set_title(t, fontsize=9); ax.set_xticks([]); ax.set_yticks([])
    diff = np.zeros(n.shape + (4,))
    diff[(n == 1) & (gd == 0)] = (0.1, 0.3, 0.9, 1); diff[(n == 0) & (gd == 1)] = (0.9, 0.1, 0.1, 1)
    axs[3].imshow(hs, cmap="gray", alpha=0.6); axs[3].imshow(diff); axs[3].set_xticks([]); axs[3].set_yticks([])
    ag = agreement(n, gd)
    axs[3].set_title(f"GDAL vs exact: {ag['agreement'] * 100:.2f}% agree\nred false visible, blue false hidden", fontsize=9)
    save(fig, OUT / "fig_algorithm_comparison.png")


if __name__ == "__main__":
    main()
