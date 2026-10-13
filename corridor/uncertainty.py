"""Track 3 - routing when the radar positions are only known approximately.

Each radar's true position is uncertain (Gaussian, sigma metres around the reported site).  Sampling S
position scenarios gives S hazard surfaces H_s.  Because the log-survival -ln P(undetected) is additive
along a route, three planners stay ordinary shortest-path problems:

  nominal     plan on the reported positions only (what we did so far);
  expected    plan on the mean hazard  mean_s H_s   (minimises the expected log-survival);
  envelope    plan on a high per-cell quantile of H_s (q = 0.9): pessimistic about where each radar is.

All three are judged on fresh test scenarios (not the ones used for planning): mean, 90th percentile and
worst-case probability of detection, and route length.
"""
import math

import numpy as np

from corridor import cgrid
from corridor.optimizer import Problem, evaluate
from corridor.radarfield import RadarField


def sample_sites(sites, sigma, rng, dem):
    H, W = dem.shape
    out = []
    for x, y in sites:
        for _ in range(20):
            nx, ny = x + rng.normal(0, sigma), y + rng.normal(0, sigma)
            c, r = dem.to_pixel(nx, ny)
            if 0 <= c < W and 0 <= r < H:
                break
        out.append((nx, ny))
    return out


def hazard(dem, sites):
    return RadarField(dem, sites, "detection").E


def p_detect(H, path, W, cell):
    rc = np.array([divmod(i, W) for i in path])
    h = H[rc[:, 0], rc[:, 1]]
    seg = np.hypot(*np.diff(rc, axis=0).T) * cell / 1000
    return 1 - math.exp(-(seg * 0.5 * (h[1:] + h[:-1])).sum())


def plan(dem, blocked, H, start, goal, alpha=10.0, beta=2.0):
    p = Problem(dem.z, H, blocked, dem.cell, alpha, beta)
    f = cgrid.CostToGo(p, goal, threads=cgrid.THREADS)
    path, cost = f.route(start)
    return path, evaluate(p, path)["length_km"]
