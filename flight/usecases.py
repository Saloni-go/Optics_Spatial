"""Track 2 - idea 3: six applications of flight-route visibility on the Alaknanda scenario.

  link       U1  radio link to ground stations: from which stretches of the route can at least one
                 town station (10 m mast, 60 km range) see the aircraft?  Outages, best station set.
  river      U2  covering a line target: how much of the valley floor (river / road) is seen, and where
                 are the gaps, for valley flying vs straight high flights.
  sar        U3  search and rescue: a 15 x 15 km search box, lawnmower patterns at several track
                 spacings and heights; area observed sharply enough to spot a person (0.5 m per pixel,
                 same 6000 px / 60 deg camera) vs flight time.
  altitude   U4  per position, the lowest height that still sees a required share (30..90%) of what the
                 highest level sees of the ground within 5 km; mean height vs coverage trade-off.
  fleet      U5  several aircraft on parallel routes: added area per aircraft and overlap.
  lookahead  U6  terrain look-ahead: if the aircraft held heading and altitude, how many seconds until
                 it hits terrain?  Share of the route with < 20 s warning.
  figs       figures + usecases_summary.json
Results: <results>/flight/usecases/.   Run:  python3 -m flight.usecases [link river ...]
"""
import argparse
import json
import math
import time

import numpy as np
from osgeo import gdal

from common.bench import machine_info
from common.config import RESULTS, EARTH_R, CURV_COEFF, dem_path
from common.dem_utils import DEM, bilinear, write_raster, write_lines_geojson, read_geojson_points
from common.plots import plt, save, base_map, km
from flight.route import load_route, resample, length
from flight.sensor import SENSORS, run_sensor, headings
from flight.visibility import AltitudeModel

OUT = RESULTS / "flight" / "usecases"
SPEED = 60.0           # m/s
RADIUS = 20000.0
SPACING = 500.0


def _dem():
    return DEM(dem_path(4000))


def coverage(dem, verts, am, sensor="omni", spacing=SPACING, radius=RADIUS, alts=None):
    pts = resample(verts, spacing)
    al = am(pts[:, 2]) if alts is None else alts
    acc, info = run_sensor(dem, pts[:, 0], pts[:, 1], al, headings(pts), radius, SENSORS[sensor])
    return acc, pts, info


# --------------------------------------------------------------------------- line of sight point -> points
def los_many(dem, a, pts, step=15.0):
    """Line of sight from a = (x, y, z_msl) to every row (x, y, z_msl) of pts (curvature + refraction)."""
    x0, y0, z0 = a
    out = np.zeros(len(pts), bool)
    for i, (x1, y1, z1) in enumerate(pts):
        d = math.hypot(x1 - x0, y1 - y0)
        n = max(int(d / step), 2)
        f = np.arange(1, n) / n
        xs, ys = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
        c, r = dem.to_pixel(xs, ys)
        ok = (c >= 0) & (c < dem.shape[1] - 1) & (r >= 0) & (r < dem.shape[0] - 1)
        # observer's frame: everything drops by curv * s^2 / 2R with distance s (as in the viewshed)
        drop = lambda s: CURV_COEFF * s ** 2 / (2 * EARTH_R)
        zt = bilinear(dem.z, c[ok], r[ok]) - drop(f[ok] * d)
        zl = z0 + ((z1 - drop(d)) - z0) * f[ok]                 # straight ray to the lowered target
        out[i] = bool(np.all(zl > zt))
    return out


# --------------------------------------------------------------------------- U1 radio link
def link(dem, v, profiles, mast=10.0, rng=60000.0):
    towns = read_geojson_points(RESULTS / "flight" / "towns.geojson")
    pts = resample(v, SPACING)
    res = {}
    for prof, am in profiles.items():
        al = am(pts[:, 2])
        P = np.column_stack([pts[:, 0], pts[:, 1], al])
        t0 = time.perf_counter()
        vis = []
        for x, y, p in towns:
            zg = float(dem.elev_at(x, y)[0]) + mast
            d = np.hypot(P[:, 0] - x, P[:, 1] - y)
            ok = d <= rng
            m = np.zeros(len(P), bool)
            m[ok] = los_many(dem, (x, y, zg), P[ok])
            vis.append(m)
        vis = np.array(vis)
        any_ = vis.any(axis=0)
        # outages: runs of consecutive positions without a link
        gaps, cur = [], None
        for i, okk in enumerate(any_):
            if not okk and cur is None:
                cur = i
            if okk and cur is not None:
                gaps.append((cur, i - 1)); cur = None
        if cur is not None:
            gaps.append((cur, len(any_) - 1))
        gl = [((b - a + 1) * SPACING / 1000, float(pts[a, 2] / 1000)) for a, b in gaps]
        # greedy: which stations are actually needed
        order, cov = [], np.zeros(len(P), bool)
        for _ in range(len(towns)):
            gain = [(int((vis[k] & ~cov).sum()), k) for k in range(len(towns)) if k not in order]
            g, k = max(gain)
            if g == 0:
                break
            order.append(k); cov |= vis[k]
        res[prof] = {"seconds": time.perf_counter() - t0, "positions": len(P),
                     "link_frac": float(any_.mean()), "outage_km": float((~any_).sum() * SPACING / 1000),
                     "longest_outage_km": max([g for g, _ in gl], default=0.0), "outages": gl,
                     "per_station_frac": {towns[k][2]["name"]: float(vis[k].mean()) for k in range(len(towns))},
                     "greedy_stations": [towns[k][2]["name"] for k in order],
                     "link_by_position": any_.astype(int).tolist()}
        print("link", prof, {k: x for k, x in res[prof].items() if k not in ("outages", "link_by_position")}, flush=True)
    return res


# --------------------------------------------------------------------------- U2 river / road coverage
def river(dem, v, profiles):
    """The valley-floor route is the river / road proxy (it was built as the least-elevation path)."""
    line = resample(v, 30.0)
    c, r = dem.to_pixel(line[:, 0], line[:, 1])
    rc = np.clip(np.rint(r).astype(int), 0, dem.shape[0] - 1); cc = np.clip(np.rint(c).astype(int), 0, dem.shape[1] - 1)
    straight = [tuple(v[0]), tuple(v[-1])]
    flights = {"valley 300 m AGL": (v, profiles["valley"]),
               "straight 5500 m MSL": (straight, AltitudeModel(dem, straight, "msl", 300.0, 5500.0)),
               "straight 7500 m MSL": (straight, AltitudeModel(dem, straight, "msl", 300.0, 7500.0)),
               "valley 5500 m MSL": (v, profiles["cruise"])}
    res = {}
    for name, (verts, am) in flights.items():
        for sensor in ("omni", "omni_gsd3"):
            acc, pts, info = coverage(dem, verts, am, sensor)
            seen = acc.count[rc, cc] > 0
            gaps, cur = [], None
            for i, s in enumerate(seen):
                if not s and cur is None:
                    cur = i
                if s and cur is not None:
                    gaps.append((i - cur) * 0.03); cur = None
            if cur is not None:
                gaps.append((len(seen) - cur) * 0.03)
            res[f"{name} | {sensor}"] = {"flight_km": length(verts) / 1000, "line_km": float(line[-1, 2] / 1000),
                                         "seen_frac": float(seen.mean()), "gaps": len(gaps),
                                         "longest_gap_km": max(gaps, default=0.0), "compute_s": info["compute_s"]}
            print("river", name, sensor, res[f"{name} | {sensor}"], flush=True)
    return res


# --------------------------------------------------------------------------- U3 search and rescue
def lawnmower(x0, y0, size, spacing):
    xs = np.arange(x0 + spacing / 2, x0 + size, spacing)
    v = []
    for i, x in enumerate(xs):
        ys = (y0, y0 + size) if i % 2 == 0 else (y0 + size, y0)
        v += [(x, ys[0]), (x, ys[1])]
    return v


def sar(dem, v, size=15000.0):
    mid = resample(v, 1000.0)
    cx, cy = mid[len(mid) // 2, :2]                  # search box centred on the route midpoint
    x0, y0 = cx - size / 2, cy - size / 2
    c0, r1 = dem.to_pixel(x0, y0); c1, r0 = dem.to_pixel(x0 + size, y0 + size)
    box = (slice(int(r0), int(r1)), slice(int(c0), int(c1)))
    box_km2 = (box[0].stop - box[0].start) * (box[1].stop - box[1].start) * dem.cell ** 2 / 1e6
    res = {"box": [x0, y0, size], "box_km2": box_km2, "runs": []}
    for agl in (150.0, 300.0, 600.0):
        for sp in (500.0, 1000.0, 2000.0, 4000.0):
            verts = lawnmower(x0, y0, size, sp)
            am = AltitudeModel(dem, verts, "agl", agl)
            acc, pts, info = coverage(dem, verts, am, "person", spacing=250.0, radius=8000.0)
            sub = acc.count[box] > 0
            # coverage as a function of flight time (positions are in flight order)
            first = acc.first[box]
            t = pts[:, 2] / SPEED / 60.0             # minutes
            curve = [(float(t[i]), float(((first >= 0) & (first <= i)).sum() * dem.cell ** 2 / 1e6))
                     for i in range(0, len(pts), max(1, len(pts) // 40))]
            r = {"agl": agl, "track_spacing_m": sp, "flight_km": length(verts) / 1000,
                 "flight_min": length(verts) / SPEED / 60, "covered_frac": float(sub.mean()),
                 "covered_km2": float(sub.sum() * dem.cell ** 2 / 1e6), "curve": curve, "compute_s": info["compute_s"]}
            res["runs"].append(r)
            print("sar", {k: x for k, x in r.items() if k != "curve"}, flush=True)
    return res


# --------------------------------------------------------------------------- U4 altitude optimisation
def altitude(dem, v, levels=(150.0, 300.0, 600.0, 1000.0, 2000.0), target=0.8, near=5000.0):
    """Within `near` metres the view saturates with height, so "lowest level seeing >= target of what the
    highest level sees" is a real trade-off (within 20 km, higher always sees much more)."""
    pts = resample(v, SPACING)
    hd = headings(pts)
    ams = {L: AltitudeModel(dem, v, "agl", L) for L in levels}
    per, unions, t0 = {}, {}, time.perf_counter()
    for L, am in ams.items():
        acc, _ = run_sensor(dem, pts[:, 0], pts[:, 1], am(pts[:, 2]), hd, near, SENSORS["omni"])
        per[L] = np.array([a for _, a, _ in sorted(acc.per_wp)])
        unions[L] = float((acc.count > 0).sum() * dem.cell ** 2 / 1e6)
    A = np.array([per[L] for L in levels])           # levels x positions
    best = A.max(axis=0)
    ground = dem.elev_at(pts[:, 0], pts[:, 1])
    res = {"levels": list(levels), "near_m": near, "seconds": 0.0,
           "constant": {str(int(L)): {"seen_km2": unions[L], "mean_agl": L,
                                      "climb_m": float(np.maximum(np.diff(ams[L](pts[:, 2])), 0).sum())} for L in levels},
           "sweep": []}
    for tg in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        choice = np.array([next(k for k in range(len(levels)) if A[k, i] >= tg * best[i]) for i in range(A.shape[1])])
        choice = np.array([choice[max(0, i - 1):i + 2].max() for i in range(len(choice))])   # no 1-position dips
        alts = np.array([ams[levels[k]](np.array([pts[i, 2]]))[0] for i, k in enumerate(choice)])
        acc, _ = run_sensor(dem, pts[:, 0], pts[:, 1], alts, hd, near, SENSORS["omni"])
        row = {"target": tg, "seen_km2": float((acc.count > 0).sum() * dem.cell ** 2 / 1e6),
               "mean_agl": float(np.mean([levels[k] for k in choice])),
               "share_per_level": {str(int(L)): float((choice == k).mean()) for k, L in enumerate(levels)},
               "climb_m": float(np.maximum(np.diff(alts), 0).sum())}
        res["sweep"].append(row)
        if abs(tg - target) < 1e-9 or tg == 0.6:
            res["profile" if tg == 0.6 else "_"] = {"target": tg, "dist_km": (pts[:, 2] / 1000).tolist(), "alt": alts.tolist(),
                                                      "ground": ground.tolist(), "level": [levels[k] for k in choice]}
    res.pop("_", None)
    res["optimised"] = next(r for r in res["sweep"] if r["target"] == 0.6)
    res["seconds"] = time.perf_counter() - t0
    print("altitude", {k: x for k, x in res.items() if k != "profile"}, flush=True)
    return res


# --------------------------------------------------------------------------- U5 several aircraft
def offset_route(dem, v, off):
    a = np.asarray(v, float)
    d = a[-1] - a[0]; n = np.array([-d[1], d[0]]) / np.hypot(*d)
    b = a + off * n
    H, W = dem.shape
    lo = np.array([dem.gt[0] + 2 * dem.cell, dem.gt[3] - (H - 2) * dem.cell])
    hi = np.array([dem.gt[0] + (W - 2) * dem.cell, dem.gt[3] - 2 * dem.cell])
    return [tuple(p) for p in np.clip(b, lo, hi)]


def fleet(dem, v, offsets=(0.0, -8000.0, 8000.0, -16000.0), agl=300.0):
    res = {"agl": agl, "aircraft": []}
    union = np.zeros(dem.shape, bool)
    a = dem.cell ** 2 / 1e6
    routes = []
    for k, off in enumerate(offsets):
        r = offset_route(dem, v, off) if off else v
        routes.append(r)
        acc, pts, info = coverage(dem, r, AltitudeModel(dem, r, "agl", agl))
        seen = acc.count > 0
        new = seen & ~union
        res["aircraft"].append({"offset_km": off / 1000, "own_km2": float(seen.sum() * a), "added_km2": float(new.sum() * a),
                                "overlap_with_earlier_frac": float((seen & union).sum() / max(seen.sum(), 1)),
                                "union_km2": float((union | seen).sum() * a), "compute_s": info["compute_s"]})
        union |= seen
        print("fleet", res["aircraft"][-1], flush=True)
    write_lines_geojson(OUT / "fleet_routes.geojson", routes, [{"offset_km": o / 1000} for o in offsets])
    write_raster(OUT / "fleet_union.tif", union.astype(np.uint8), dem.gt, dem.proj, gdal.GDT_Byte, nodata=0)
    return res


# --------------------------------------------------------------------------- U6 terrain look-ahead
def lookahead(dem, v, profiles, horizon=12000.0, step=30.0, warn_s=20.0):
    pts = resample(v, 100.0)
    hd = headings(pts)
    d = np.arange(step, horizon + step, step)
    res = {}
    for prof, am in profiles.items():
        al = am(pts[:, 2])
        tti = np.full(len(pts), np.inf)
        t0 = time.perf_counter()
        for i in range(len(pts)):
            xs = pts[i, 0] + d * np.sin(hd[i]); ys = pts[i, 1] + d * np.cos(hd[i])
            c, r = dem.to_pixel(xs, ys)
            ok = (c >= 0) & (c < dem.shape[1] - 1) & (r >= 0) & (r < dem.shape[0] - 1)
            z = np.full(len(d), -1e9); z[ok] = bilinear(dem.z, c[ok], r[ok])
            hit = np.nonzero(z >= al[i])[0]
            if len(hit):
                tti[i] = d[hit[0]] / SPEED
        warn = tti < warn_s
        res[prof] = {"seconds": time.perf_counter() - t0, "positions": len(pts),
                     "warn_frac": float(warn.mean()), "median_tti_s": float(np.median(np.minimum(tti, horizon / SPEED))),
                     "never_frac": float(np.isinf(tti).mean()),
                     "tti_s": np.minimum(tti, horizon / SPEED).tolist(), "dist_km": (pts[:, 2] / 1000).tolist()}
        print("lookahead", prof, {k: x for k, x in res[prof].items() if k not in ("tti_s", "dist_km")}, flush=True)
    return res


# --------------------------------------------------------------------------- figures
def figs():
    S = {k: json.load(open(OUT / f"{k}.json")) for k in ("link", "river", "sar", "altitude", "fleet", "lookahead")}
    dem = _dem(); v = np.asarray(load_route())
    fig, axs = plt.subplots(2, 3, figsize=(17, 9.5))
    # U1
    ax = axs[0, 0]
    for prof, c in (("valley", "#2a9d8f"), ("cruise", "#e76f51")):
        L = np.array(S["link"][prof]["link_by_position"])
        ax.fill_between(np.arange(len(L)) * SPACING / 1000, L * (1 if prof == "cruise" else 0.9), step="mid", alpha=0.5, color=c,
                        label=f"{prof}: link {100 * S['link'][prof]['link_frac']:.0f}% of route")
    ax.set_xlabel("distance along route (km)"); ax.set_yticks([]); ax.legend(fontsize=7.5, frameon=False, loc="lower left")
    ax.set_title("U1  Radio link to any town station (10 m mast, 60 km)", fontsize=9)
    # U2
    ax = axs[0, 1]
    names = list(S["river"])
    ax.barh(range(len(names)), [100 * S["river"][n]["seen_frac"] for n in names],
            color=["#2a9d8f" if "gsd3" not in n else "#e76f51" for n in names])
    ax.set_yticks(range(len(names))); ax.set_yticklabels([n.replace(" | omni_gsd3", "  (3 m camera)").replace(" | omni", "  (line of sight)") for n in names], fontsize=7)
    ax.set_xlabel("% of valley floor (river / road) seen"); ax.set_title("U2  Covering a line target", fontsize=9)
    # U3
    ax = axs[0, 2]
    for r in S["sar"]["runs"]:
        cc = np.array(r["curve"])
        ax.plot(cc[:, 0], 100 * cc[:, 1] / S["sar"]["box_km2"], {150: ":", 300: "-", 600: "--"}[int(r["agl"])],
                label=f"{int(r['agl'])} m AGL, tracks {r['track_spacing_m'] / 1000:g} km")
    ax.set_xlabel("flight time (min, 60 m/s)"); ax.set_ylabel("% of 15 x 15 km box seen at <= 0.5 m (person)")
    ax.legend(fontsize=6.5, frameon=False); ax.set_title("U3  Search and rescue: lawnmower patterns", fontsize=9)
    # U4
    ax = axs[1, 0]
    sw = S["altitude"]["sweep"]; c3 = S["altitude"]["constant"]
    ax.plot([r["mean_agl"] for r in sw], [r["seen_km2"] for r in sw], "o-", c="#e76f51", label="lowest height per position")
    for r in sw:
        ax.annotate(f"{int(100 * r['target'])}%", (r["mean_agl"], r["seen_km2"]), textcoords="offset points", xytext=(4, -9), fontsize=6.5)
    ax.plot([float(L) for L in c3], [d["seen_km2"] for d in c3.values()], "s--", c="#457b9d", label="constant height")
    ax.set_xscale("log"); ax.set_xlabel("mean height above ground (m)"); ax.set_ylabel("ground within 5 km seen (km$^2$)")
    ax.legend(fontsize=7.5, frameon=False)
    ax.set_title("U4  Height vs coverage (label: share of the best local view required)", fontsize=8.5)
    # U5
    ax = axs[1, 1]
    A = S["fleet"]["aircraft"]
    ax.bar(range(1, len(A) + 1), [a["union_km2"] for a in A], color="#457b9d")
    for i, a in enumerate(A):
        ax.text(i + 1, a["union_km2"], f"+{a['added_km2']:,.0f}\n{100 * a['overlap_with_earlier_frac']:.0f}% overlap", ha="center", va="bottom", fontsize=7)
    ax.set_xlabel("number of aircraft (parallel routes 8 km apart)"); ax.set_ylabel("area seen together (km$^2$)")
    ax.set_ylim(0, A[-1]["union_km2"] * 1.25); ax.set_title("U5  Several aircraft, 300 m AGL", fontsize=9)
    # U6
    ax = axs[1, 2]
    for prof, c in (("valley", "#2a9d8f"), ("cruise", "#e76f51")):
        L = S["lookahead"][prof]
        ax.plot(L["dist_km"], L["tti_s"], c=c, lw=0.7, label=f"{prof}: < 20 s on {100 * L['warn_frac']:.0f}% of route")
    ax.axhline(20, c="k", ls=":", lw=0.8)
    ax.set_xlabel("distance along route (km)"); ax.set_ylabel("seconds to terrain if heading held")
    ax.legend(fontsize=7.5, frameon=False); ax.set_title("U6  Terrain look-ahead", fontsize=9)
    save(fig, OUT / "fig_usecases.png")
    summary = {"link": {p: {k: x for k, x in d.items() if k != "link_by_position"} for p, d in S["link"].items()},
               "river": S["river"],
               "sar": [{k: x for k, x in r.items() if k != "curve"} for r in S["sar"]["runs"]],
               "altitude": {k: x for k, x in S["altitude"].items() if k != "profile"},
               "fleet": S["fleet"],
               "lookahead": {p: {k: x for k, x in d.items() if k not in ("tti_s", "dist_km")} for p, d in S["lookahead"].items()}}
    json.dump(summary, open(OUT / "usecases_summary.json", "w"), indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("steps", nargs="*", default=["link", "river", "sar", "altitude", "fleet", "lookahead", "figs"])
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(machine_info(), open(OUT / "machine.json", "w"), indent=1)
    dem, v = None, None
    for st in a.steps:
        print("==", st, flush=True)
        if st == "figs":
            figs(); continue
        if dem is None:
            dem, v = _dem(), load_route()
            profiles = {"valley": AltitudeModel(dem, v), "cruise": AltitudeModel(dem, v, "msl", 300.0, 5500.0)}
        fn = {"link": lambda: link(dem, v, profiles), "river": lambda: river(dem, v, profiles), "sar": lambda: sar(dem, v),
              "altitude": lambda: altitude(dem, v), "fleet": lambda: fleet(dem, v),
              "lookahead": lambda: lookahead(dem, v, profiles)}[st]
        json.dump(fn(), open(OUT / f"{st}.json", "w"), indent=1, default=float)
