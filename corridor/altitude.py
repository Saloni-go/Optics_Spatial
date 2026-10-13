"""Track 3 - 3-D corridor: the planner also chooses the flight height.

Until now the aircraft flew at a fixed 150 m above ground.  Here it may use several flight levels
(75 / 150 / 300 / 600 m above ground) and change between them:
  - each level has its own radar threat surface: a viewshed depends on the target height, so lower
    flight hides behind more terrain;
  - each level has its own ceiling mask (terrain + height above the 5000 m ceiling is blocked);
  - flying low costs extra per metre (gamma: terrain-following risk / fuel), climbing costs beta per
    metre, every height change costs vcost per metre.
The search is a backward Dijkstra over levels x cells in C (corridor/c/layers.inc).
"""
import ctypes as ct
import math
import time

import numpy as np

from corridor import cgrid
from corridor.exposure import blocked_mask, CEILING
from corridor.radarfield import RadarField

LEVELS = (75.0, 150.0, 300.0, 600.0)
GAMMA = (0.30, 0.15, 0.05, 0.0)          # extra cost per metre flown at that height (x gamma_scale)


class Layered:
    def __init__(self, dem, sites, mode="detection", levels=LEVELS, gamma=GAMMA, alpha=10.0, beta=2.0, vcost=0.5):
        t = time.perf_counter()
        self.dem, self.levels, self.gamma = dem, tuple(levels), tuple(gamma)
        self.alpha, self.beta, self.vcost, self.mode = alpha, beta, vcost, mode
        H, W = dem.shape
        self.H, self.W, self.N = H, W, H * W
        z = np.nan_to_num(dem.z.astype(np.float64), nan=0.0)
        self.z = np.ascontiguousarray(z)
        base = blocked_mask(dem)
        self.E = np.empty((len(levels), H, W), np.float64)
        self.blocked = np.empty((len(levels), H, W), np.uint8)
        for l, a in enumerate(levels):
            self.E[l] = RadarField(dem, sites, mode, target_h=a).E
            self.blocked[l] = base | (z + a > CEILING)
        self.prep_s = time.perf_counter() - t

    def field(self, goal, gamma_scale=1.0, only=None):
        """Backward field over all levels (or only the level indices in `only`, others blocked)."""
        blk = self.blocked
        if only is not None:
            blk = blk.copy()
            for l in range(len(self.levels)):
                if l not in only:
                    blk[l] = 1
        M = len(self.levels) * self.N
        dist = np.empty(M, np.float64); nxt = np.empty(M, np.int32)
        g = np.ascontiguousarray([x * gamma_scale for x in self.gamma], np.float64)
        agl = np.ascontiguousarray(self.levels, np.float64)
        blk = np.ascontiguousarray(blk)
        V = ct.c_void_p
        t = time.perf_counter()
        n = cgrid.lib().grid3_costtogo(self.H, self.W, len(self.levels), self.z.ctypes.data_as(V), self.E.ctypes.data_as(V),
                                       blk.ctypes.data_as(V), agl.ctypes.data_as(V), g.ctypes.data_as(V), self.dem.cell,
                                       self.alpha, self.beta, self.vcost, goal[0] * self.W + goal[1],
                                       dist.ctypes.data_as(V), nxt.ctypes.data_as(V))
        if n < 0:
            raise MemoryError("grid3_costtogo failed")
        return {"dist": dist, "next": nxt, "s": time.perf_counter() - t, "mem_mb": (dist.nbytes + nxt.nbytes) / 2 ** 20}

    def route(self, f, start, level=None):
        """Follow the field from start (at the best level, or at a given level index)."""
        c = start[0] * self.W + start[1]
        nodes = [l * self.N + c for l in range(len(self.levels))] if level is None else [level * self.N + c]
        u = min(nodes, key=lambda v: f["dist"][v])
        if not math.isfinite(f["dist"][u]):
            return None, math.inf
        cost, path = float(f["dist"][u]), [u]
        nxt = f["next"]
        while nxt[u] >= 0:
            u = int(nxt[u]); path.append(u)
        return path, cost

    def describe(self, path):
        """Length per level, height changes, P(detect) (detection mode) along a 3-D path."""
        N, W, cell = self.N, self.W, self.dem.cell
        lv = np.array([v // N for v in path]); cc = np.array([v % N for v in path])
        r, c = cc // W, cc % W
        horiz = lv[1:] == lv[:-1]
        seg = np.hypot(np.diff(r), np.diff(c)) * cell
        seg = np.where(horiz, seg, 0.0)
        h = self.E[lv, r, c]
        risk = (seg / 1000.0 * 0.5 * (h[1:] + h[:-1])).sum()
        per_level = {f"{int(a)} m": float(seg[lv[:-1] == l].sum() / 1000) for l, a in enumerate(self.levels)}
        return {"length_km": float(seg.sum() / 1000), "per_level_km": per_level,
                "level_changes": int((~horiz).sum()),
                "mean_agl_m": float(np.average([self.levels[l] for l in lv[:-1]], weights=seg) if seg.sum() else 0),
                "p_detect": float(1 - math.exp(-risk)) if self.mode == "detection" else None,
                "exposure_km": float(risk) if self.mode != "detection" else None}
