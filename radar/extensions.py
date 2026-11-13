"""Track 1 extensions: what the six radars can and cannot see, and where radars should go.

All on the 4000 x 4000 DEM (16 M cells, 120 km), GDAL viewshed, 40 km range, the shared six sites.

  minalt   lowest detectable altitude: for every cell, the lowest height above ground at which an
           aircraft is seen by at least one radar (GDAL 3.4 has no direct mode, so a sweep over target
           heights; the result is exact at the sweep levels).  Also: cost and error of coarser sweeps.
  siting   greedy radar placement: from every ridge-top candidate (same rule as common/sites.py, without
           the 22 km spacing), pick radars one at a time to maximise the area where an aircraft 150 m
           above ground is seen.  Compared with the six shared sites (chosen by height only).
  detect   detection probability instead of line of sight: the per-km detection model of Track 3
           (corridor/radarfield.py, p(d) = p_max / (1 + (d / d50)^4)), combined over radars.
  mc       DEM uncertainty: Monte Carlo with correlated DEM noise (as Track 2, flight/uncertainty.py);
           which coverage is reliable and which depends on a few metres of DEM error.
  mast     mast height 10..100 m: coverage gained (E3 benchmarked the cost only).
  figs     figures from the JSON results.

Outputs: <results>/radar_ext/*.json, *.tif, fig_*.png
Run:     python3 -m radar.extensions [minalt siting detect mc mast figs]
"""
import json
import sys
import time

import numpy as np
from osgeo import gdal
from scipy.ndimage import maximum_filter

from common.config import RESULTS, RADAR_HEIGHT, TARGET_AIRCRAFT, VISIBLE, dem_path
from common.dem_utils import DEM, write_raster
from common.sites import load_sites
from flight.uncertainty import correlated_noise
from radar.viewshed import gdal_viewshed

OUT = RESULTS / "radar_ext"
RANGE = 40000.0
LEVELS = [0, 10, 25, 50, 75, 100, 150, 200, 300, 400, 500, 750, 1000, 1500, 2000]
P_MAX, D50 = 0.5, 20000.0           # same as corridor/radarfield.py
NOT_SEEN = 65535


def _dump(name, obj):
    json.dump(obj, open(OUT / f"{name}.json", "w"), indent=1, allow_nan=False)


def _vis(dem, x, y, th, mast=RADAR_HEIGHT):
    return gdal_viewshed(dem, x, y, mast, th, RANGE) == VISIBLE


# ------------------------------------------------------------------------------------------- minalt
def minalt(dem, sites):
    t0 = time.perf_counter()
    ma = np.full(dem.shape, NOT_SEEN, np.uint16)
    per = []
    for x, y, p in sites:
        t = time.perf_counter()
        for h in reversed(LEVELS):                  # descending: the last level that sees a cell wins
            v = _vis(dem, x, y, float(h))
            ma[v] = np.minimum(ma[v], h)
        per.append(time.perf_counter() - t)
    total = time.perf_counter() - t0
    write_raster(OUT / "min_detectable_alt_m.tif", ma, dem.gt, dem.proj, gdal.GDT_UInt16, nodata=NOT_SEEN)
    a = dem.cell ** 2 / 1e6
    seen = ma != NOT_SEEN
    res = {"levels_m": LEVELS, "seconds_total": total, "seconds_per_viewshed": total / (len(sites) * len(LEVELS)),
           "area_seen_at_or_below_km2": {str(h): float(((ma <= h) & seen).sum() * a) for h in LEVELS},
           "area_total_km2": float(ma.size * a), "median_min_alt_m_where_seen": float(np.median(ma[seen]))}
    # coarser sweeps: a cell's altitude is rounded up to the next coarse level -> over-estimate
    coarse = {}
    for name, lv in (("5 levels", [0, 100, 300, 750, 2000]), ("8 levels", [0, 50, 100, 200, 400, 750, 1500, 2000]),
                     ("15 levels (reference)", LEVELS)):
        lv = np.array(lv)
        m = ma[seen].astype(np.int64)
        up = lv[np.searchsorted(lv, m)]
        coarse[name] = {"viewsheds": len(lv) * len(sites), "seconds_est": len(lv) * len(sites) * res["seconds_per_viewshed"],
                        "mean_overestimate_m": float((up - m).mean()), "max_overestimate_m": float((up - m).max())}
    res["sweep_resolution"] = coarse
    _dump("minalt", res)
    print("minalt", {k: round(v) for k, v in res["area_seen_at_or_below_km2"].items()}, f"{total:.1f} s")


# ------------------------------------------------------------------------------------------- siting
def candidates(dem, zmin=1500.0, zmax=3200.0, margin=10000.0):
    z = np.nan_to_num(dem.z, nan=-1)
    pk = (z == maximum_filter(z, size=101)) & (z >= zmin) & (z <= zmax)
    m = int(margin / dem.cell)
    pk[:m] = pk[-m:] = False; pk[:, :m] = pk[:, -m:] = False
    rr, cc = np.nonzero(pk)
    return [(*dem.to_world(c, r), float(z[r, c])) for r, c in zip(rr, cc)]


def _coarse(v, f=4):
    """visible mask -> 120 m grid of booleans (a coarse cell counts when most of it is visible)"""
    n = v.shape[0] // f
    return v[:n * f, :n * f].reshape(n, f, n, f).mean(axis=(1, 3)) >= 0.5


def siting(dem, sites, k_max=10):
    cand = candidates(dem)
    t0 = time.perf_counter()
    cov = np.stack([_coarse(_vis(dem, x, y, TARGET_AIRCRAFT)) for x, y, _ in cand])     # (C, 1000, 1000) bool
    t_cov = time.perf_counter() - t0
    a = (dem.cell * 4) ** 2 / 1e6
    union = np.zeros(cov.shape[1:], bool); chosen, curve = [], []
    t1 = time.perf_counter()
    for _ in range(k_max):
        gain = (cov & ~union).sum(axis=(1, 2))
        gain[chosen] = -1
        i = int(gain.argmax()); chosen.append(i); union |= cov[i]
        curve.append(float(union.sum() * a))
    t_greedy = time.perf_counter() - t1
    # the six shared sites on the same 120 m grid
    sh = np.zeros_like(union); shared_curve = []
    for x, y, _ in sites:
        sh |= _coarse(_vis(dem, x, y, TARGET_AIRCRAFT)); shared_curve.append(float(sh.sum() * a))
    # exact check of the greedy six at 30 m
    ex = np.zeros(dem.shape, bool); exs = np.zeros(dem.shape, bool)
    for i in chosen[:6]:
        ex |= _vis(dem, cand[i][0], cand[i][1], TARGET_AIRCRAFT)
    for x, y, _ in sites:
        exs |= _vis(dem, x, y, TARGET_AIRCRAFT)
    a30 = dem.cell ** 2 / 1e6
    gsites = [{"x": cand[i][0], "y": cand[i][1], "ground_m": cand[i][2]} for i in chosen]
    sep = min(np.hypot(p["x"] - q["x"], p["y"] - q["y"]) for j, p in enumerate(gsites[:6]) for q in gsites[j + 1:6])
    res = {"candidates": len(cand), "seconds_coverage": t_cov, "seconds_greedy": t_greedy,
           "greedy_curve_km2": curve, "shared_curve_km2": shared_curve,
           "greedy6_exact_km2": float(ex.sum() * a30), "shared6_exact_km2": float(exs.sum() * a30),
           "greedy6_min_separation_km": sep / 1000, "greedy_sites": gsites,
           "radars_needed_to_match_shared6": int(np.searchsorted(curve, shared_curve[-1]) + 1),
           "area_total_km2": float(dem.z.size * a30)}
    _dump("siting", res)
    np.save(OUT / "siting_greedy6.npy", ex); np.save(OUT / "siting_shared6.npy", exs)
    print("siting", len(cand), "candidates; greedy6", round(res["greedy6_exact_km2"]), "km2 vs shared6", round(res["shared6_exact_km2"]),
          "| match with", res["radars_needed_to_match_shared6"], "radars")


# ------------------------------------------------------------------------------------------- detect
def detect(dem, sites):
    H = np.zeros(dem.shape, np.float64)          # sum over radars of -ln(1 - p_r)
    los = np.zeros(dem.shape, bool)
    rr, cc = np.mgrid[0:dem.shape[0], 0:dem.shape[1]]
    X = dem.gt[0] + (cc + 0.5) * dem.cell; Y = dem.gt[3] - (rr + 0.5) * dem.cell
    del rr, cc
    for x, y, _ in sites:
        v = _vis(dem, x, y, TARGET_AIRCRAFT)
        d = np.hypot(X[v] - x, Y[v] - y)
        p = P_MAX / (1 + (d / D50) ** 4)
        H[v] += -np.log1p(-p); los |= v
    P1 = 1 - np.exp(-H)                           # probability of detection per km flown
    P5 = 1 - np.exp(-5 * H)                       # ... over 5 km flown inside that cell's coverage
    a = dem.cell ** 2 / 1e6
    res = {"model": {"p_max_per_km": P_MAX, "d50_m": D50, "target_agl_m": TARGET_AIRCRAFT},
           "los_km2": float(los.sum() * a),
           "p1km_ge_0.5_km2": float((P1 >= 0.5).sum() * a), "p1km_ge_0.1_km2": float((P1 >= 0.1).sum() * a),
           "p5km_ge_0.9_km2": float((P5 >= 0.9).sum() * a), "p5km_ge_0.5_km2": float((P5 >= 0.5).sum() * a),
           "mean_p1km_where_los": float(P1[los].mean())}
    write_raster(OUT / "detect_p_per_km.tif", P1.astype(np.float32), dem.gt, dem.proj, gdal.GDT_Float32)
    _dump("detect", res)
    print("detect", {k: round(v) for k, v in res.items() if k.endswith("km2")})


# ----------------------------------------------------------------------------------------------- mc
def mc(dem, sites, runs=20, sigma_z=4.0, corr_m=300.0, seed=0):
    rng = np.random.default_rng(seed)
    out = {}
    a = dem.cell ** 2 / 1e6
    for label, th in (("ground", 0.0), ("air150", TARGET_AIRCRAFT)):
        nom = np.zeros(dem.shape, bool)
        for x, y, _ in sites:
            nom |= _vis(dem, x, y, th)
        out[label] = {"nom": nom, "hits": np.zeros(dem.shape, np.uint16), "km2": []}
    t0 = time.perf_counter()
    z0 = dem.z.copy()
    for k in range(runs):
        dem.z[:] = z0 + correlated_noise(dem.shape, sigma_z, corr_m / dem.cell, rng)
        dem._ds = None                            # rebuild the GDAL view (it copies when the DEM has no-data)
        for label, th in (("ground", 0.0), ("air150", TARGET_AIRCRAFT)):
            u = np.zeros(dem.shape, bool)
            for x, y, _ in sites:
                u |= _vis(dem, x, y, th)
            out[label]["hits"] += u; out[label]["km2"].append(float(u.sum() * a))
        print(f"  mc run {k + 1}/{runs}", flush=True)
    dem.z[:] = z0; dem._ds = None
    res = {"runs": runs, "sigma_z_m": sigma_z, "corr_m": corr_m, "seconds": time.perf_counter() - t0}
    for label, o in out.items():
        p = o["hits"] / runs; km2 = np.array(o["km2"])
        res[label] = {"nominal_km2": float(o["nom"].sum() * a), "mean_km2": float(km2.mean()), "std_km2": float(km2.std()),
                      "reliable_km2": float((p >= 0.95).sum() * a), "uncertain_km2": float(((p > 0.05) & (p < 0.95)).sum() * a),
                      "nominal_seen_but_unreliable_km2": float((o["nom"] & (p < 0.95)).sum() * a)}
        write_raster(OUT / f"mc_p_seen_{label}.tif", p.astype(np.float32), dem.gt, dem.proj, gdal.GDT_Float32)
    _dump("mc", res)
    print("mc", {l: {k: round(v) for k, v in res[l].items()} for l in ("ground", "air150")})


# --------------------------------------------------------------------------------------------- mast
def mast(dem, sites, heights=(10, 30, 60, 100)):
    a = dem.cell ** 2 / 1e6
    rows = []
    for h in heights:
        t = time.perf_counter()
        g = np.zeros(dem.shape, bool); ai = np.zeros(dem.shape, bool)
        for x, y, _ in sites:
            g |= _vis(dem, x, y, 0.0, float(h)); ai |= _vis(dem, x, y, TARGET_AIRCRAFT, float(h))
        rows.append({"mast_m": h, "ground_km2": float(g.sum() * a), "air150_km2": float(ai.sum() * a),
                     "seconds": time.perf_counter() - t})
        print("mast", rows[-1])
    _dump("mast", {"rows": rows, "area_total_km2": float(dem.z.size * a)})


# --------------------------------------------------------------------------------------------- figs
def figs(dem, sites):
    from common.plots import plt, save, base_map, km
    from matplotlib.colors import ListedColormap, BoundaryNorm
    J = lambda n: json.load(open(OUT / f"{n}.json"))

    ma = gdal.Open(str(OUT / "min_detectable_alt_m.tif")).ReadAsArray()
    m = J("minalt")
    fig, axs = plt.subplots(1, 2, figsize=(12.5, 5.2), gridspec_kw={"width_ratios": [1.15, 1]})
    ext = base_map(axs[0], dem, 4000, elev_tint=False)
    bounds = [0, 25, 75, 150, 300, 500, 1000, 2001]
    cm = ListedColormap(["#7f0000", "#d7301f", "#fc8d59", "#fdcc8a", "#c6dbef", "#6baed6", "#2171b5"])
    im = axs[0].imshow(np.ma.masked_equal(ma, NOT_SEEN), cmap=cm, norm=BoundaryNorm(bounds, cm.N), extent=ext, alpha=0.85)
    for x, y, p in sites:
        axs[0].plot(km(x), km(y), "^", c="w", mec="k", ms=7)
    axs[0].set_xlim(ext[0], ext[1]); axs[0].set_ylim(ext[2], ext[3])
    cb = fig.colorbar(im, ax=axs[0], shrink=0.75); cb.set_label("lowest detectable height above ground (m)")
    axs[0].set_title("Lowest altitude at which the six radars see an aircraft\n(uncoloured: not seen even at 2,000 m)", fontsize=9)
    hs = [int(h) for h in m["levels_m"]]
    axs[1].plot(hs, [m["area_seen_at_or_below_km2"][str(h)] / m["area_total_km2"] * 100 for h in hs], "o-", c="#b4472e")
    axs[1].axvline(TARGET_AIRCRAFT, c="0.6", ls="--", lw=0.8); axs[1].text(TARGET_AIRCRAFT * 1.08, 22, "150 m\n(Track 3)", fontsize=8, color="0.4")
    axs[1].set_xscale("symlog", linthresh=10); axs[1].set_xlim(0, 2200); axs[1].set_xlabel("aircraft height above ground (m)")
    axs[1].set_ylabel("% of the 120 x 120 km area where it is seen"); axs[1].grid(alpha=0.3)
    axs[1].set_title("Coverage against flying height", fontsize=9)
    save(fig, OUT / "fig_minalt.png")

    s = J("siting")
    fig, axs = plt.subplots(1, 2, figsize=(12.5, 5.2), gridspec_kw={"width_ratios": [1.15, 1]})
    ext = base_map(axs[0], dem, 4000, elev_tint=False)
    g6 = np.load(OUT / "siting_greedy6.npy"); s6 = np.load(OUT / "siting_shared6.npy")
    ov = np.zeros(g6.shape + (4,), np.float32)
    ov[s6 & ~g6] = (0.55, 0.55, 0.55, 0.6); ov[g6 & ~s6] = (0.12, 0.48, 0.44, 0.75); ov[g6 & s6] = (0.95, 0.65, 0.25, 0.65)
    axs[0].imshow(ov[::2, ::2], extent=ext)
    for x, y, _ in sites:
        axs[0].plot(km(x), km(y), "^", c="0.5", mec="k", ms=8)
    for p in s["greedy_sites"][:6]:
        axs[0].plot(km(p["x"]), km(p["y"]), "*", c="#1f7a6f", mec="k", ms=13)
    axs[0].set_xlim(ext[0], ext[1]); axs[0].set_ylim(ext[2], ext[3])
    axs[0].set_title("Aircraft at 150 m: shared six (grey ▲) vs greedy six (green ★)\norange both, green greedy only, grey shared only", fontsize=9)
    k = np.arange(1, len(s["greedy_curve_km2"]) + 1)
    axs[1].plot(k, s["greedy_curve_km2"], "o-", c="#1f7a6f", label="greedy placement")
    axs[1].plot(np.arange(1, 7), s["shared_curve_km2"], "^-", c="0.5", label="shared sites (highest first)")
    axs[1].set_xlabel("number of radars"); axs[1].set_ylabel("area where an aircraft at 150 m is seen (km²)")
    axs[1].legend(frameon=False); axs[1].grid(alpha=0.3); axs[1].set_title(f"{s['candidates']} ridge-top candidates", fontsize=9)
    save(fig, OUT / "fig_siting.png")

    mcr = J("mc"); d = J("detect"); ms = J("mast")
    fig, axs = plt.subplots(1, 3, figsize=(15.5, 4.6)); fig.subplots_adjust(wspace=0.5)
    p = gdal.Open(str(OUT / "mc_p_seen_air150.tif")).ReadAsArray()
    ext = base_map(axs[0], dem, 4000, elev_tint=False)
    n = p.shape[0] // 4
    blk = lambda m: m[:n * 4, :n * 4].reshape(n, 4, n, 4).any(axis=(1, 3))      # keep thin features when thinning
    rel, unc = blk(p >= 0.95), blk((p > 0.05) & (p < 0.95))
    ov = np.zeros(rel.shape + (4,), np.float32); ov[rel] = (0.96, 0.64, 0.38, 0.55); ov[unc] = (0.85, 0.1, 0.55, 0.95)
    axs[0].imshow(ov, extent=ext)
    axs[0].set_xlim(ext[0], ext[1]); axs[0].set_ylim(ext[2], ext[3])
    u = mcr["air150"]
    axs[0].set_title(f"DEM error ±{mcr['sigma_z_m']:.0f} m, {mcr['runs']} runs, aircraft 150 m\norange reliable {u['reliable_km2']:.0f} km², "
                     f"pink uncertain {u['uncertain_km2']:.0f} km²", fontsize=9)
    labels = ["line of sight", "P/km ≥ 0.1", "P/km ≥ 0.5", "P (5 km) ≥ 0.9"]
    vals = [d["los_km2"], d["p1km_ge_0.1_km2"], d["p1km_ge_0.5_km2"], d["p5km_ge_0.9_km2"]]
    axs[1].barh(labels[::-1], vals[::-1], color=["#2f5d7c", "#2f5d7c", "#2f5d7c", "#b4472e"])
    for i, v in enumerate(vals[::-1]):
        axs[1].text(v, i, f" {v:,.0f}", va="center", fontsize=8)
    axs[1].set_xlabel("km² (aircraft at 150 m)"); axs[1].set_title("Seen is not detected (Track 3 detection model)", fontsize=9)
    hs = [r["mast_m"] for r in ms["rows"]]
    axs[2].plot(hs, [r["ground_km2"] for r in ms["rows"]], "o-", c="#b4472e", label="ground")
    axs[2].plot(hs, [r["air150_km2"] for r in ms["rows"]], "s-", c="#2f5d7c", label="aircraft 150 m")
    axs[2].set_xlabel("mast height (m)"); axs[2].set_ylabel("km² seen by the six radars"); axs[2].legend(frameon=False)
    axs[2].grid(alpha=0.3); axs[2].set_title("Taller masts", fontsize=9)
    save(fig, OUT / "fig_detect_mc_mast.png")


STEPS = {"minalt": minalt, "siting": siting, "detect": detect, "mc": mc, "mast": mast, "figs": figs}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    dem = DEM(dem_path(4000)); sites = load_sites()
    for st in (sys.argv[1:] or list(STEPS)):
        t = time.perf_counter(); STEPS[st](dem, sites); print(f"== {st} {time.perf_counter() - t:.1f} s", flush=True)
