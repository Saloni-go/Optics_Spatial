"""Track 3 - radar placement game: where should a defender put K radars, if the attacker then flies the
least-risk route?

Defender: picks K sites from candidate peaks.  Attacker: knows the radars, chooses the safest of several
entry points and flies the route minimising length + alpha x risk to the goal (detection model).
Defender's score = the attacker's probability of being detected on that route (higher is better).

The inner problem (attacker's best response) is one cost-to-go field from the goal (parallel C, ~0.1 s at
2000 x 2000), which serves every entry point at once, so a greedy defender can afford hundreds of
evaluations.  Baselines: the scenario's hand-placed radars, random placements, and the classic coverage
placement (maximise the area seen, ignoring routes).
"""
import math
import time

import numpy as np

from corridor import cgrid
from corridor.optimizer import Problem
from corridor.radarfield import RadarField


def candidate_peaks(dem, n=40, min_sep_m=4000.0, margin=0.03):
    """Highest cells, at least min_sep_m apart (non-maximum suppression), away from the map edge."""
    z = np.nan_to_num(dem.z.astype(np.float64), nan=-1e9)
    H, W = z.shape
    k = int(min_sep_m / dem.cell)
    order = np.argsort(z, axis=None)[::-1]
    taken = []
    for i in order:
        r, c = divmod(int(i), W)
        if not (margin * H < r < (1 - margin) * H and margin * W < c < (1 - margin) * W):
            continue
        if all(abs(r - a) > k or abs(c - b) > k for a, b in taken):
            taken.append((r, c))
            if len(taken) == n:
                break
    return taken


class Game:
    def __init__(self, dem, blocked, entries, goal, candidates, alpha=10.0, beta=2.0):
        t = time.perf_counter()
        self.dem, self.blocked, self.entries, self.goal = dem, blocked, entries, goal
        self.alpha, self.beta = alpha, beta
        self.cands = candidates
        rf = RadarField(dem, [], "detection")
        self.contrib = [rf._contribution(*dem.to_world(c, r)) for r, c in candidates]
        self.coverage = [int((cb[2] > 0).sum()) for cb in self.contrib]
        self.prep_s = time.perf_counter() - t
        self.evals = 0

    def surface(self, sel):
        E = np.zeros(self.dem.shape, np.float64)
        for i in sel:
            r0, c0, a = self.contrib[i]
            E[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] += a
        return E

    def attacker(self, sel):
        """Attacker's best response: (P(detect) of the safest entry's route, entry index, path)."""
        E = self.surface(sel)
        p = Problem(self.dem.z, E, self.blocked, self.dem.cell, self.alpha, self.beta)
        f = cgrid.CostToGo(p, self.goal, threads=cgrid.THREADS)
        self.evals += 1
        best = (math.inf, None, None)
        for k, s in enumerate(self.entries):
            path, cost = f.route(s)
            if path is None:
                continue
            rc = np.array([divmod(i, p.W) for i in path])
            h = E[rc[:, 0], rc[:, 1]]
            seg = np.hypot(*np.diff(rc, axis=0).T) * p.cell / 1000
            pd = 1 - math.exp(-(seg * 0.5 * (h[1:] + h[:-1])).sum())
            if pd < best[0]:
                best = (pd, k, path)
        return best

    def greedy(self, K):
        sel, trace = [], []
        t = time.perf_counter()
        for _ in range(K):
            scores = [(self.attacker(sel + [i])[0], i) for i in range(len(self.cands)) if i not in sel]
            pd, i = max(scores)
            sel.append(i); trace.append(pd)
        return sel, trace, time.perf_counter() - t

    def coverage_greedy(self, K):
        """Classic placement: maximise the number of cells seen by at least one radar (no routing)."""
        seen = np.zeros(self.dem.shape, bool)
        sel = []
        for _ in range(K):
            best, bi = -1, None
            for i in range(len(self.cands)):
                if i in sel:
                    continue
                r0, c0, a = self.contrib[i]
                gain = int(((a > 0) & ~seen[r0:r0 + a.shape[0], c0:c0 + a.shape[1]]).sum())
                if gain > best:
                    best, bi = gain, i
            sel.append(bi)
            r0, c0, a = self.contrib[bi]
            seen[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] |= a > 0
        return sel
