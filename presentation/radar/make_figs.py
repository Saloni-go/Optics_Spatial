"""Concept and validation figures for the radar slide deck (presentation/radar/figs/).

  fig_los_concept.png           line of sight along a real terrain profile from radar R1
  fig_synthetic_validation.png  the four synthetic terrains with their viewsheds
Run:  run.bat presentation\\radar\\make_figs.py
"""
from pathlib import Path

import numpy as np

from common.config import DATA, RADAR_HEIGHT, EARTH_R, CURV_COEFF, dem_path
from common.dem_utils import DEM, bilinear
from common.plots import plt
from common.sites import load_sites
from radar.viewshed import gdal_viewshed

OUT = Path(__file__).resolve().parent / "figs"; OUT.mkdir(parents=True, exist_ok=True)
VIS, BLK, RAD = "#f2a541", "#1d3557", "#e63946"


def los_concept():
    dem = DEM(dem_path(4000))
    x, y, p = load_sites()[0]
    c0, r0 = dem.to_pixel(x, y); c0, r0 = int(round(c0)), int(round(r0))
    n = int(30000 / dem.cell)                                   # 30 km profile heading west
    cc = c0 - np.arange(n + 1.0); rr = np.full(n + 1, float(r0))
    d = np.arange(n + 1) * dem.cell
    z = bilinear(dem.z, cc, rr) - CURV_COEFF * d ** 2 / (2 * EARTH_R)
    zo = z[0] + RADAR_HEIGHT
    slope = np.full(n + 1, -np.inf); slope[1:] = (z[1:] - zo) / d[1:]
    horizon = np.maximum.accumulate(np.concatenate([[-np.inf], slope[:-1]]))
    vis = slope >= horizon; vis[0] = True
    fig, ax = plt.subplots(figsize=(11, 3.9))
    ax.fill_between(d / 1000, z, z.min() - 150, color="#d9d4c7", zorder=1)
    ax.plot(d / 1000, z, c="#6b6558", lw=0.8, zorder=2)
    zv = np.where(vis, z, np.nan); zb = np.where(~vis, z, np.nan)
    ax.plot(d / 1000, zb, c=BLK, lw=3.2, zorder=3, label="blocked ground")
    ax.plot(d / 1000, zv, c=VIS, lw=3.2, zorder=4, label="visible ground")
    # one visible and one blocked sight line
    iv = np.nonzero(vis & (d > 18600) & (d < 19300))[0]; ib = np.nonzero(~vis & (d > 20500) & (d < 23000))[0]
    for i, col, ls in ((iv[len(iv) // 2], "#b86e00", "-"), (ib[np.argmin(z[ib])], BLK, "--")):
        ax.plot([0, d[i] / 1000], [zo, z[i]], c=col, lw=1.3, ls=ls, zorder=5)
        ax.plot(d[i] / 1000, z[i], "o", c=col, ms=6, zorder=6)
    ax.plot(0, zo, "^", c=RAD, mec="k", ms=11, zorder=7)
    ax.annotate("radar R1\n(30 m mast)", (0, zo), (0.9, zo + 190), fontsize=10, arrowprops=dict(arrowstyle="-", lw=0.6))
    ax.set_xlabel("distance from radar (km)"); ax.set_ylabel("elevation after curvature drop (m)")
    ax.set_xlim(-0.6, 30.3); ax.set_ylim(z.min() - 150, max(z.max(), zo) + 420)
    ax.legend(loc="upper right", frameon=False, fontsize=10, ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(OUT / "fig_los_concept.png", dpi=200, bbox_inches="tight"); plt.close(fig)
    print("visible share of profile", float(vis.mean()))


def synthetic():
    from matplotlib.colors import ListedColormap
    fig, axs = plt.subplots(2, 4, figsize=(11, 5.6), gridspec_kw={"height_ratios": [1, 1]})
    for k, (name, want) in enumerate((("flat", "all visible"), ("valley", "all visible"),
                                      ("ridge", "hidden behind the wall"), ("cone", "back of hill hidden"))):
        dem = DEM(DATA / "synthetic" / f"{name}.tif"); n = dem.shape[0]
        oc, orow = (n // 2 - 70, n // 2) if name == "cone" else (n // 2, n // 2)
        x, y = dem.to_world(oc, orow)
        v = gdal_viewshed(dem, x, y, RADAR_HEIGHT)
        a = axs[0, k]; im = a.imshow(dem.z, cmap="terrain", vmin=950, vmax=1900 if name == "valley" else 1320)
        a.set_title(f"{name}\nelevation {dem.z.min():.0f}-{dem.z.max():.0f} m", fontsize=10)
        b = axs[1, k]; b.imshow(v, cmap=ListedColormap([BLK, VIS]), vmin=0, vmax=1)
        b.set_title(f"viewshed: {want}\n{(v == 1).mean() * 100:.1f}% visible", fontsize=10)
        for ax in (a, b):
            ax.plot(oc, orow, "^", c=RAD, mec="k", ms=8); ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout(h_pad=1.6)
    fig.savefig(OUT / "fig_synthetic_validation.png", dpi=200, bbox_inches="tight"); plt.close(fig)


if __name__ == "__main__":
    los_concept()
    synthetic()
