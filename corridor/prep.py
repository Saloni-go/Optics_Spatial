"""Track 3 - building a routing problem for a DEM size (exposure surface cached on disk).

For the 4000 DEM the six shared radar sites are used.  Smaller DEMs (different extents) get
`n` radars at fixed relative positions, each snapped to the highest cell within 1.5 km, so the
problem looks alike at every size.  Endpoints: 10% and 90% along the DEM diagonal (snapped to
unblocked cells).
"""
import time
import numpy as np

from common.config import RESULTS, dem_path
from common.dem_utils import DEM
from common.sites import load_sites
from corridor.exposure import exposure, blocked_mask
from corridor.optimizer import Problem

CACHE = RESULTS / "corridor" / "cache"
REL_SITES = [(0.25, 0.3), (0.75, 0.25), (0.5, 0.55), (0.2, 0.75), (0.8, 0.7), (0.55, 0.9)]


def sites_for(dem, size, n=6):
    if size == 4000 and n == 6:
        return [(x, y) for x, y, _ in load_sites()]
    out = []
    k = int(1500 / dem.cell)
    for i in range(n):
        fx, fy = REL_SITES[i % len(REL_SITES)]
        if i >= len(REL_SITES):                          # extra radars for the scaling test
            fx, fy = ((i * 0.37) % 0.8) + 0.1, ((i * 0.61) % 0.8) + 0.1
        c, r = int(fx * size), int(fy * size)
        r0, c0 = max(r - k, 0), max(c - k, 0)
        win = np.nan_to_num(dem.z[r0:r + k, c0:c + k], nan=-1)
        rr, cc = np.unravel_index(np.argmax(win), win.shape)
        out.append(dem.to_world(c0 + cc, r0 + rr))
    return out


def exposure_for(size, n=6, dem=None):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"E_{size}_{n}.npy"
    dem = dem or DEM(dem_path(size))
    if f.exists():
        return np.load(f), dem, 0.0
    t = time.perf_counter()
    E, _ = exposure(dem, sites_for(dem, size, n))
    dt = time.perf_counter() - t
    np.save(f, E)
    return E, dem, dt


def endpoints(blocked, f0=0.1, f1=0.9):
    H, W = blocked.shape
    def snap(r, c):
        free = np.argwhere(~blocked[max(r - 50, 0):r + 50, max(c - 50, 0):c + 50])
        d = np.hypot(free[:, 0] + max(r - 50, 0) - r, free[:, 1] + max(c - 50, 0) - c)
        k = np.argmin(d)
        return int(free[k, 0] + max(r - 50, 0)), int(free[k, 1] + max(c - 50, 0))
    return snap(int(f0 * H), int(f0 * W)), snap(int(f1 * H) - 1, int(f1 * W) - 1)


def problem(size, alpha=10.0, beta=2.0, n=6):
    E, dem, _ = exposure_for(size, n)
    blk = blocked_mask(dem)
    return Problem(dem.z, E, blk, dem.cell, alpha, beta), dem
