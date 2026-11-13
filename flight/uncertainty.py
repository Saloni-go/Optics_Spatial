"""Track 2 - idea 2: how sure are we that a cell was seen?

The nominal answer assumes a perfect DEM and a perfectly flown route.  Monte Carlo over the error
sources, each run re-computes the whole route coverage:

  dem        DEM height error: Gaussian, sigma_z metres, spatially correlated over corr_m metres
             (Copernicus GLO-30 quotes about 2-4 m absolute vertical error; a DSM also has
             tree / building heights that come and go, which this does not model)
  position   aircraft horizontal error sigma_xy and altitude error sigma_alt per position
             (GNSS + autopilot holding error, independent per position)
  both       the two together

Per cell the result is P(seen) = share of runs in which it was seen.  Reported: seen area per run
(mean / spread), area seen in >= 95% of runs ("reliable"), area seen in 5-95% ("uncertain"), and the
overlap (Jaccard) of each run with the nominal one.
"""
import copy
import time

import numpy as np
from scipy.ndimage import gaussian_filter

from flight.sensor import run_sensor, SENSORS, headings


def correlated_noise(shape, sigma, corr_cells, rng):
    """Gaussian field with standard deviation sigma and correlation length ~corr_cells (float32)."""
    n = rng.standard_normal(shape).astype(np.float32)
    f = gaussian_filter(n, corr_cells, mode="wrap")
    f *= sigma / max(float(f.std()), 1e-12)
    return f


def monte_carlo(dem, pts, alt_fn, radius, source="both", runs=20, sigma_z=4.0, corr_m=300.0, sigma_xy=10.0,
                sigma_alt=15.0, sensor=SENSORS["omni"], seed=0, workers=12):
    rng = np.random.default_rng(seed)
    alts = alt_fn(pts[:, 2]); hd = headings(pts)
    nominal, _ = run_sensor(dem, pts[:, 0], pts[:, 1], alts, hd, radius, sensor, workers)
    nom = nominal.count > 0
    hits = np.zeros(dem.shape, np.uint16)
    per_run = []
    t0 = time.perf_counter()
    for k in range(runs):
        d, xs, ys, al = dem, pts[:, 0], pts[:, 1], alts
        if source in ("dem", "both"):
            d = copy.copy(dem)
            d.z = dem.z + correlated_noise(dem.shape, sigma_z, corr_m / dem.cell, rng)
        if source in ("position", "both"):
            xs = xs + rng.normal(0, sigma_xy, len(xs)); ys = ys + rng.normal(0, sigma_xy, len(ys))
            al = al + rng.normal(0, sigma_alt, len(al))
        acc, _ = run_sensor(d, xs, ys, al, hd, radius, sensor, workers)
        seen = acc.count > 0
        hits += seen
        per_run.append({"seen_km2": float(seen.sum() * dem.cell ** 2 / 1e6),
                        "jaccard_vs_nominal": float((seen & nom).sum() / max((seen | nom).sum(), 1))})
    p = hits / runs
    a = dem.cell ** 2 / 1e6
    km2 = np.array([r["seen_km2"] for r in per_run]); J = np.array([r["jaccard_vs_nominal"] for r in per_run])
    return p, {"source": source, "runs": runs, "seconds": time.perf_counter() - t0,
               "nominal_km2": float(nom.sum() * a),
               "seen_km2_mean": float(km2.mean()), "seen_km2_std": float(km2.std()),
               "seen_km2_p5": float(np.percentile(km2, 5)), "seen_km2_p95": float(np.percentile(km2, 95)),
               "jaccard_mean": float(J.mean()), "jaccard_min": float(J.min()),
               "reliable_km2": float((p >= 0.95).sum() * a), "uncertain_km2": float(((p > 0.05) & (p < 0.95)).sum() * a),
               "nominal_seen_but_unreliable_km2": float((nom & (p < 0.95)).sum() * a),
               "params": {"sigma_z": sigma_z, "corr_m": corr_m, "sigma_xy": sigma_xy, "sigma_alt": sigma_alt}}
