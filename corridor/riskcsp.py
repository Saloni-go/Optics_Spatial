"""Track 3 - shortest route under a detection-risk budget, with a certificate.

    minimise  L(route) = length + beta x climb
    subject to P(detected) <= p_max   <=>   R(route) = sum(length x hazard) <= B = -1000 ln(1 - p_max)

(R in metre-hazard units, so the planner's exposure weight alpha is exactly the Lagrange multiplier.)

1. LARAC (Juttner et al. 2001): Lagrangian relaxation that moves the price of risk lambda straight to the
   best value (a few exact searches; each is one parallel cost-to-go field).  Gives a feasible route and a
   LOWER BOUND on the best possible length: LB = min_route(L + lambda R) - lambda B.
2. The gap between them comes from routes inside the convex hull of the length/risk trade-off, which no
   price can reach.  csp_label (C) closes it: an exact label-setting search for the constrained problem,
   restricted to a corridor around the LARAC routes and pruned with exact bounds (least remaining length
   and least remaining risk from every cell, two backward searches).
The answer is reported with its certified distance from the optimum: (L - LB) / LB.
"""
import copy
import ctypes as ct
import math
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from corridor import cgrid
from corridor.optimizer import evaluate


def budget_units(p_max):
    return -1000.0 * math.log(1.0 - p_max)


def p_of(R):
    return 1.0 - math.exp(-R / 1000.0)


class RiskCSP:
    def __init__(self, p, goal, threads=cgrid.THREADS):
        """p: problem whose E is the per-km detection hazard H (RadarField mode='detection')."""
        self.p, self.goal, self.threads = p, goal, threads
        self.hL = self.hR = None
        self.fields = {}

    # ------------------------------------------------------------ pieces
    def LR(self, path):
        q = copy.copy(self.p); q.alpha = 0.0
        ev = evaluate(q, path)
        return ev["cost"], 1000.0 * ev["exposure_km"]

    def solve(self, lam, start):
        q = copy.copy(self.p); q.alpha = float(lam)
        f = cgrid.CostToGo(q, self.goal, threads=self.threads)
        path, _ = f.route(start)
        L, R = self.LR(path)
        self.fields[float(lam)] = f.dist                    # kept for the Lagrangian pruning bound
        return {"lam": lam, "path": path, "L": L, "R": R, "s": f.pre_s}

    def bounds(self):
        """hL, hR: least remaining length / risk to the goal from every cell (two C searches in parallel)."""
        if self.hL is not None:
            return 0.0
        p = self.p
        z, E, blk = cgrid._arrays(p)
        N = p.H * p.W
        g = p.idx(self.goal)

        def run(w):
            d = np.empty(N, np.float64)
            cgrid.lib().grid_costtogo_w(p.H, p.W, z, E, blk, p.cell, p.beta, w[0], w[1], w[2], g, d)
            return d
        t = time.perf_counter()
        with ThreadPoolExecutor(2) as ex:
            self.hL, self.hR = ex.map(run, [(1.0, 0.0, 1.0), (0.0, 1.0, 0.0)])
        self.bounds_s = time.perf_counter() - t
        return self.bounds_s

    # ------------------------------------------------------------ 1. LARAC
    def larac(self, start, p_max, eps=1e-9, max_iter=30):
        B = budget_units(p_max)
        self.fields = {}
        t = time.perf_counter()
        trace = []
        pc = self.solve(0.0, start); trace.append(pc)
        if pc["R"] <= B:
            return {"status": "shortest route already feasible", "best": pc, "LB": pc["L"], "trace": trace,
                    "solves": 1, "s": time.perf_counter() - t, "B": B}
        lam = 1.0
        while True:                                   # a price high enough to be feasible
            pd = self.solve(lam, start); trace.append(pd)
            if pd["R"] <= B or lam > 1e7:
                break
            lam *= 10
        if pd["R"] > B:
            return {"status": "infeasible", "best": None, "LB": math.inf, "trace": trace, "solves": len(trace),
                    "s": time.perf_counter() - t, "B": B}
        LB = -math.inf
        for _ in range(max_iter):
            lam = (pc["L"] - pd["L"]) / (pd["R"] - pc["R"])
            r = self.solve(lam, start); trace.append(r)
            c_r, c_pc = r["L"] + lam * r["R"], pc["L"] + lam * pc["R"]
            LB = max(LB, c_r - lam * B)
            if abs(c_r - c_pc) <= eps * max(1.0, abs(c_pc)) or c_r >= c_pc:
                break
            if r["R"] <= B:
                pd = r
            else:
                pc = r
        self.lam_best = max(((lam_ + 0.0, d) for lam_, d in self.fields.items()),
                            key=lambda t: self._lb(t[0], t[1], start, B))
        return {"status": "ok", "best": pd, "LB": LB, "lam": lam, "trace": trace, "solves": len(trace),
                "s": time.perf_counter() - t, "B": B}

    def _lb(self, lam, dist, start, B):
        return dist[self.p.idx(start)] - lam * B

    # ------------------------------------------------------------ 2. exact search in a corridor
    def exact(self, start, B, ub, paths, width_cells=40, max_labels=20_000_000, resolution=1e-3):
        """resolution: labels whose risk differs by less than resolution x B are merged (0 = exact)."""
        from scipy.ndimage import maximum_filter
        p = self.p
        tb = self.bounds()
        t = time.perf_counter()
        m = np.zeros((p.H, p.W), bool)
        for path in paths:
            if path:
                m.flat[path] = True
        allowed = maximum_filter(m, size=2 * width_cells + 1) & ~p.blocked
        allowed = np.ascontiguousarray(allowed, np.uint8).ravel()
        z, E, _ = cgrid._arrays(p)
        Lo, Ro, nl = ct.c_double(), ct.c_double(), ct.c_int64()
        cap = 40 * (p.H + p.W)
        path = np.empty(cap, np.int32)
        lam, dlam = getattr(self, "lam_best", (0.0, None))
        n = cgrid.lib().csp_label(p.H, p.W, z, E, allowed, p.cell, p.beta, p.idx(start), p.idx(self.goal), B,
                                  ub * (1 + 1e-12), self.hL, self.hR, lam,
                                  dlam.ctypes.data if dlam is not None else None, resolution * B, max_labels,
                                  ct.byref(Lo), ct.byref(Ro),
                                  ct.byref(nl), path, cap)
        out = {"labels": int(nl.value), "corridor_frac": float(allowed.mean()), "s": time.perf_counter() - t,
               "resolution": resolution,
               "bounds_s": tb}
        if n > 0:
            out.update({"status": "ok", "path": path[:n].tolist(), "L": Lo.value, "R": Ro.value})
        else:
            out.update({"status": {0: "no better route in corridor", -2: "label cap hit"}.get(n, f"error {n}")})
        return out

    # ------------------------------------------------------------ both
    def query(self, start, p_max, width_cells=40, exact=True, resolution=1e-3, max_labels=20_000_000):
        lr = self.larac(start, p_max)
        res = {"p_max": p_max, "status": lr["status"], "larac_s": lr["s"], "solves": lr["solves"], "LB": lr["LB"]}
        if lr["best"] is None:
            return res
        b = lr["best"]
        res.update({"larac_L": b["L"], "larac_p": p_of(b["R"]), "larac_gap_pct": 100 * (b["L"] / lr["LB"] - 1),
                    "path": b["path"], "L": b["L"], "p_detect": p_of(b["R"])})
        if exact and lr["status"] == "ok" and b["L"] > lr["LB"] * (1 + 1e-9):
            ex = self.exact(start, lr["B"], b["L"], [r["path"] for r in lr["trace"]], width_cells,
                            max_labels=max_labels, resolution=resolution)
            if ex["status"] == "label cap hit":
                # fall back to splicing: exact search on the union of the LARAC routes only (2 cells wide)
                sp = self.exact(start, lr["B"], b["L"], [r["path"] for r in lr["trace"]], 2,
                                max_labels=max_labels, resolution=resolution)
                sp["status"] = "splice: " + sp["status"]
                sp["s"] += ex["s"]
                ex = sp
            res.update({"exact_status": ex["status"], "exact_s": ex["s"], "bounds_s": ex["bounds_s"],
                        "labels": ex["labels"], "corridor_frac": ex["corridor_frac"]})
            if ex["status"].endswith("ok") and ex["L"] < b["L"]:
                res.update({"path": ex["path"], "L": ex["L"], "p_detect": p_of(ex["R"])})
        res["gap_pct"] = 100 * (res["L"] / lr["LB"] - 1)
        res["length_km"] = evaluate(self.p, res["path"])["length_km"]
        return res
