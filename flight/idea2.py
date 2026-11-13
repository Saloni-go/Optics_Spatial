"""Track 2 - idea 2 experiments: realistic sensor and uncertainty.

  sensors   F11  valley (300 m AGL) and cruise (5500 m MSL), 500 m spacing, 20 km radius, five sensors
                 (omni, omni + 3 m resolution limit, forward camera, side-looking pair, nadir camera):
                 area observed, dwell time at 60 m/s, rasters; runtime / memory in fresh processes
  gsd       F11b area observed vs required ground resolution (0.5 .. 30 m) for the omni camera
  mc        F12  Monte Carlo: DEM error, position error, both; 20 runs each, both profiles;
                 P(seen) rasters and reliable / uncertain area
  figs      figures + idea2_summary.json
Run:  python3 -m flight.idea2 [sensors gsd mc figs] [--repeats 3] [--runs 20]
"""
import argparse
import dataclasses
import json
import math

import numpy as np
from osgeo import gdal

from common.bench import run_series, machine_info
from common.config import RESULTS, CELL, dem_path
from common.dem_utils import DEM, write_raster
from common.plots import plt, save, base_map, km
from flight.route import load_route, resample
from flight.sensor import SENSORS, run_sensor, headings, dwell_seconds, CAM_IFOV
from flight.uncertainty import monte_carlo
from flight.visibility import AltitudeModel

OUT = RESULTS / "flight" / "idea2"
SPACING, RADIUS, SPEED = 500.0, 20000.0, 60.0
PROFILES = {"valley": {"label": "Terrain following, 300 m AGL"},
            "cruise": {"label": "Cruise, 5500 m MSL", "alt_mode": "msl", "msl": 5500.0}}


def _setup():
    dem = DEM(dem_path(4000)); v = load_route(); pts = resample(v, SPACING)
    ams = {"valley": AltitudeModel(dem, v), "cruise": AltitudeModel(dem, v, "msl", 300.0, 5500.0)}
    return dem, v, pts, ams


def sensors(repeats):
    dem, v, pts, ams = _setup()
    a = dem.cell ** 2 / 1e6
    res = {}
    for prof, am in ams.items():
        alts, hd = am(pts[:, 2]), headings(pts)
        res[prof] = {}
        for name, s in SENSORS.items():
            acc, t = run_sensor(dem, pts[:, 0], pts[:, 1], alts, hd, RADIUS, s)
            dwell = dwell_seconds(acc.count, SPACING, SPEED)
            seen = acc.count > 0
            res[prof][name] = {"sensor": s.describe(), "observed_km2": float(seen.sum() * a),
                               "dwell_s_mean": float(dwell[seen].mean()) if seen.any() else 0.0,
                               "dwell_s_median": float(np.median(dwell[seen])) if seen.any() else 0.0,
                               "observed_ge_30s_km2": float((dwell >= 30).sum() * a),
                               "compute_s_inprocess": t["compute_s"]}
            write_raster(OUT / f"dwell_{prof}_{name}.tif", dwell, dem.gt, dem.proj, gdal.GDT_Float32, nodata=0)
            print(prof, name, {k: (round(x, 2) if isinstance(x, float) else x) for k, x in res[prof][name].items() if k != "sensor"}, flush=True)
    json.dump(res, open(OUT / "sensors.json", "w"), indent=1)
    # timing and peak memory in fresh processes
    jobs = []
    for prof, kw in PROFILES.items():
        kw = {k: x for k, x in kw.items() if k != "label"}
        for name in SENSORS:
            jobs.append({"track": "flight", "job": "sensor", "experiment": f"F11_sensor_{prof}", "algorithm": name,
                         "dem_id": 4000, "width": 4000, "height": 4000, "cell_size_m": CELL, "route": "alaknanda",
                         "spacing_m": SPACING, "radius_m": RADIUS, "param_name": "sensor", "param_value": 0, **kw})
    run_series("flight.jobs_fast", jobs, OUT / "idea2_raw.csv", repeats=repeats)


def gsd():
    dem, v, pts, ams = _setup()
    res = {}
    for prof, am in ams.items():
        alts, hd = am(pts[:, 2]), headings(pts)
        res[prof] = []
        for g in (0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0, math.inf):
            s = dataclasses.replace(SENSORS["omni"], name=f"gsd{g}", ifov=CAM_IFOV if math.isfinite(g) else 0.0, gsd_max=g)
            acc, t = run_sensor(dem, pts[:, 0], pts[:, 1], alts, hd, RADIUS, s)
            res[prof].append({"gsd_max_m": g, "observed_km2": float((acc.count > 0).sum() * dem.cell ** 2 / 1e6),
                              "compute_s": t["compute_s"]})
            print(prof, res[prof][-1], flush=True)
    json.dump(res, open(OUT / "gsd.json", "w"), indent=1, default=str)


def mc(runs):
    dem, v, pts, ams = _setup()
    res = {}
    for prof, am in ams.items():
        res[prof] = {}
        for src in ("dem", "position", "both"):
            p, st = monte_carlo(dem, pts, am, RADIUS, src, runs=runs, seed={"dem": 1, "position": 2, "both": 3}[src])
            res[prof][src] = st
            print(prof, src, {k: (round(x, 3) if isinstance(x, float) else x) for k, x in st.items() if k != "params"}, flush=True)
            if src == "both":
                write_raster(OUT / f"p_seen_{prof}.tif", p.astype(np.float32), dem.gt, dem.proj, gdal.GDT_Float32, nodata=0)
                np.save(OUT / f"p_seen_{prof}.npy", p.astype(np.float32))
    json.dump(res, open(OUT / "mc.json", "w"), indent=1)


def figs():
    from common.analysis import load, medians
    S = {"sensors": json.load(open(OUT / "sensors.json")), "gsd": json.load(open(OUT / "gsd.json")),
         "mc": json.load(open(OUT / "mc.json")), "timing": {}}
    rows = load(OUT / "idea2_raw.csv")
    for prof in PROFILES:
        m = medians(rows, f"F11_sensor_{prof}")
        S["timing"][prof] = {a: {"compute_s": p[0]["compute"], "peak_mb": p[0]["peak_mb"]} for a, p in m.items()}
    names = list(SENSORS)
    # 1. observed area and runtime per sensor
    fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
    w = 0.38
    for j, (prof, c) in enumerate((("valley", "#2a9d8f"), ("cruise", "#e76f51"))):
        x = np.arange(len(names)) + (j - 0.5) * w
        axs[0].bar(x, [S["sensors"][prof][n]["observed_km2"] for n in names], w, color=c, label=PROFILES[prof]["label"])
        axs[1].bar(x, [S["timing"][prof][n]["compute_s"] for n in names], w, color=c, label=PROFILES[prof]["label"])
    for ax, yl in zip(axs, ("area observed (km$^2$)", "compute time (s), 333 positions")):
        ax.set_xticks(range(len(names))); ax.set_xticklabels([n.replace("_gsd3", "\n<= 3 m") for n in names], fontsize=8)
        ax.set_ylabel(yl); ax.legend(fontsize=7.5, frameon=False)
    axs[0].set_title("What a real sensor observes (3 m resolution limit except plain omni)", fontsize=9)
    axs[1].set_title("Cost of the sensor model", fontsize=9)
    save(fig, OUT / "fig_idea2_sensors.png")
    # 2. resolution requirement
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    for prof, c in (("valley", "#2a9d8f"), ("cruise", "#e76f51")):
        d = [r for r in S["gsd"][prof] if r["gsd_max_m"] not in ("inf", math.inf)]
        inf = [r for r in S["gsd"][prof] if r["gsd_max_m"] in ("inf", math.inf)][0]["observed_km2"]
        ax.semilogx([r["gsd_max_m"] for r in d], [100 * r["observed_km2"] / inf for r in d], "o-", c=c, label=PROFILES[prof]["label"])
    ax.set_xlabel("required ground resolution (m per pixel)"); ax.set_ylabel("% of line-of-sight area observed")
    ax.set_title("Seeing is not resolving (6000 px, 60 deg camera)", fontsize=9); ax.legend(fontsize=7.5, frameon=False)
    save(fig, OUT / "fig_idea2_gsd.png")
    # 3. dwell maps for the forward camera
    dem, v, pts, ams = _setup()
    va = np.asarray(v)
    fig, axs = plt.subplots(1, 2, figsize=(11, 5.2))
    for ax, prof in zip(axs, ("valley", "cruise")):
        ext = base_map(ax, dem, 4000, elev_tint=False)
        dw = gdal.Open(str(OUT / f"dwell_{prof}_forward.tif")).ReadAsArray()
        im = ax.imshow(np.ma.masked_equal(dw, 0), cmap="viridis", extent=ext, vmax=np.percentile(dw[dw > 0], 99))
        ax.plot(km(va[:, 0]), km(va[:, 1]), c="w", lw=0.8)
        st = S["sensors"][prof]["forward"]
        ax.set_title(f"{PROFILES[prof]['label']}, forward camera\nobserved {st['observed_km2']:,.0f} km$^2$, "
                     f"median dwell {st['dwell_s_median']:.0f} s", fontsize=9)
        fig.colorbar(im, ax=ax, shrink=0.7, label="seconds observed (60 m/s)")
    save(fig, OUT / "fig_idea2_dwell.png")
    # 4. Monte Carlo
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.6), gridspec_kw={"width_ratios": [1, 1, 0.9]})
    for ax, prof in zip(axs[:2], ("valley", "cruise")):
        ext = base_map(ax, dem, 4000, elev_tint=False)
        p = np.load(OUT / f"p_seen_{prof}.npy")
        im = ax.imshow(np.ma.masked_equal(p, 0), cmap="RdYlGn", vmin=0, vmax=1, extent=ext)
        st = S["mc"][prof]["both"]
        ax.set_title(f"{PROFILES[prof]['label']}: P(seen), DEM + position error\n"
                     f"reliable {st['reliable_km2']:,.0f} km$^2$, uncertain {st['uncertain_km2']:,.0f} km$^2$", fontsize=9)
        fig.colorbar(im, ax=ax, shrink=0.7)
    srcs = ("dem", "position", "both")
    x = np.arange(3)
    for j, (prof, c) in enumerate((("valley", "#2a9d8f"), ("cruise", "#e76f51"))):
        nom = S["mc"][prof]["both"]["nominal_km2"]
        axs[2].bar(x + (j - 0.5) * 0.38, [100 * S["mc"][prof][s]["uncertain_km2"] / nom for s in srcs], 0.38, color=c,
                   label=PROFILES[prof]["label"])
    axs[2].set_xticks(x); axs[2].set_xticklabels(["DEM error\n4 m", "position error\n10 m / 15 m", "both"])
    axs[2].set_ylabel("uncertain area, % of nominal seen area"); axs[2].legend(fontsize=7.5, frameon=False)
    axs[2].set_title("Which error matters", fontsize=9)
    save(fig, OUT / "fig_idea2_uncertainty.png")
    json.dump(S, open(OUT / "idea2_summary.json", "w"), indent=1, default=str)
    print(json.dumps(S["timing"], indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("steps", nargs="*", default=["sensors", "gsd", "mc", "figs"])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--runs", type=int, default=20)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(machine_info(), open(OUT / "machine.json", "w"), indent=1)
    for st in a.steps:
        print("==", st, flush=True)
        {"sensors": lambda: sensors(a.repeats), "gsd": gsd, "mc": lambda: mc(a.runs), "figs": figs}[st]()
