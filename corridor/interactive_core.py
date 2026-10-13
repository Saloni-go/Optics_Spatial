"""Track 3 - interactive corridor planning: what to precompute, what to compute on the fly.

The Planner keeps every structure needed to answer user actions fast, and says for each action
which strategy it used and how long it took:

  Level 0  no precompute          C Dijkstra / A* for every request
  Level 1  landmarks (ALT)        precompute once per cost surface; any start and goal (~0.4 s / 16 M nodes)
  Level 2  cost-to-go field       one backward search per goal; route from ANY start by lookup (microseconds)
  Level 3  multi-resolution        coarse cost grids; zoomed out -> coarse route, zoomed in -> refine only
           pyramid                 inside the visible window
  on change:
    - radar moved / added / removed  -> threat surface updated per radar window (RadarField),
                                        cost-to-go field repaired (CostToGo.repair) and/or D* Lite update
    - alpha changed                   -> every precompute is invalid: anytime weighted A* answers at once,
                                        then the field is rebuilt (in the GUI on a background thread)
"""
import math
import time
import numpy as np

from common.config import dem_path
from common.dem_utils import DEM
from corridor.exposure import blocked_mask
from corridor.optimizer import Problem, evaluate
from corridor.prep import sites_for, endpoints
from corridor.radarfield import RadarField
from corridor import cgrid


def scenario_endpoints(dem, size, blocked):
    """Devprayag -> Joshimath (the Track 2 endpoints) on the 4000 DEM, else the diagonal."""
    if size == 4000:
        try:
            from flight.route import load_route
            v = load_route()
            pts = []
            for x, y in (v[0], v[-1]):
                c, r = dem.to_pixel(x, y)
                pts.append((int(round(r)), int(round(c))))
            if not any(blocked[r, c] for r, c in pts):
                return pts[0], pts[1]
        except Exception:
            pass
    return endpoints(blocked)


# ------------------------------------------------------------------ anytime search
def anytime(p, start, goal, weights=(3.0, 2.0, 1.5, 1.25, 1.1, 1.0), lm=None):
    """Restarting weighted A* (Richter et al. 2010): solve with a large heuristic weight first
    (cost <= w x optimum), then smaller weights down to w = 1 (optimal).  Yields one result per weight
    with the elapsed time since the call."""
    t0 = time.perf_counter()
    for w in weights:
        r = cgrid.alt_c(p, start, goal, lm, w) if lm is not None else cgrid.astar_c(p, start, goal, w)
        r.update({"weight": w, "elapsed_s": time.perf_counter() - t0, "stage": f"weighted A* w={w:g}"})
        yield r


def progressive(pyr, start, goal, levels=(16, 4), corridor_cells=4, exact=True):
    """Coarse-to-fine anytime search: exact routes on ever finer pyramid levels, then a full-resolution
    search restricted to a corridor around two coarse routes (block-mean and block-minimum exposure:
    the mean keeps costs honest, the minimum keeps narrow hidden valleys that averaging blurs away),
    then the exact full search.  Every stage is drawn as soon as it is ready; costs are measured on
    the full-resolution grid."""
    p, t0 = pyr.p, time.perf_counter()
    paths = {}
    for k in levels:
        pts, info = pyr.coarse_route(k, start, goal)
        if pts is None:
            continue
        path = pyr.upsample(pts)
        paths[k] = info["path"]
        yield {"stage": f"coarse x{k}", "path": path, "cost": evaluate(p, path)["cost"],
               "elapsed_s": time.perf_counter() - t0, "level": k}
    k = levels[-1]
    if k in paths:
        cps = [(k, paths[k])]
        if k in pyr.mins:
            _, info = pyr.coarse_route(k, start, goal, pyr.mins[k])
            if info["path"] is not None:
                cps.append((k, info["path"]))
        r = pyr.corridor_route(cps, start, goal, corridor_cells)
        if r["path"] is not None:
            yield {**r, "stage": f"full-res corridor (+/-{corridor_cells * k * p.cell / 1000:.1f} km of 2 x{k} routes)",
                   "elapsed_s": time.perf_counter() - t0, "level": 1}
    if exact:
        r = cgrid.dijkstra_c(p, start, goal)
        yield {**r, "stage": "exact", "elapsed_s": time.perf_counter() - t0, "level": 1}


# ------------------------------------------------------------------ Level 3: multi-resolution pyramid
def _bresenham(r0, c0, r1, c1):
    pts = []
    dr, dc = abs(r1 - r0), abs(c1 - c0)
    sr, sc = (1 if r1 > r0 else -1), (1 if c1 > c0 else -1)
    err = dc - dr
    r, c = r0, c0
    while True:
        pts.append((r, c))
        if r == r1 and c == c1:
            return pts
        e2 = 2 * err
        if e2 > -dr:
            err -= dr; c += sc
        if e2 < dc:
            err += dc; r += sr


class Pyramid:
    """Coarse copies of the cost grid (mean exposure and height; blocked if most of the block is).
    They depend on the exposure surface but not on alpha / beta, so changing the weights keeps them.

    route(start, goal, view): the whole route is always solved on a coarse level small enough to be
    instant (<= glob_px cells across); the visible window is then re-solved at the level whose cells
    are about one screen pixel (full resolution when zoomed in), between the points where the
    coarse route enters and leaves the window.  Work is bounded by the screen, not by the map."""

    def __init__(self, p, factors=(2, 4, 8, 16, 32), min_factors=(4,)):
        """A coarse cell is blocked only if all its fine cells are (keeps the coarse graph connected)."""
        t = time.perf_counter()
        self.p, self.levels, self.mins = p, {1: p}, {}
        for k in factors:
            H2, W2 = p.H // k, p.W // k
            blk = lambda a, fn=np.mean: fn(a[:H2 * k, :W2 * k].reshape(H2, k, W2, k), axis=(1, 3))
            z, b = blk(p.z), blk(p.blocked.astype(np.float32)) > 0.999
            self.levels[k] = Problem(z, blk(p.E), b, p.cell * k, p.alpha, p.beta)
            if k in min_factors:
                self.mins[k] = Problem(z, blk(p.E, np.min), b.copy(), p.cell * k, p.alpha, p.beta)
        self.pre_s = time.perf_counter() - t
        qs = [q for k, q in self.levels.items() if k > 1] + list(self.mins.values())
        self.mem_mb = sum(q.z.nbytes + q.E.nbytes + q.blocked.nbytes for q in qs) / 2 ** 20

    def update_exposure(self, changed):
        """Radar edit: recompute the coarse exposure only over the changed box."""
        t = time.perf_counter()
        rows, cols = np.nonzero(changed.any(axis=1))[0], np.nonzero(changed.any(axis=0))[0]
        if len(rows):
            for k, q in self.levels.items():
                if k == 1:
                    continue
                a0, a1 = rows[0] // k, min(rows[-1] // k + 1, q.H)
                b0, b1 = cols[0] // k, min(cols[-1] // k + 1, q.W)
                blk = self.p.E[a0 * k:a1 * k, b0 * k:b1 * k].reshape(a1 - a0, k, b1 - b0, k)
                q.E[a0:a1, b0:b1] = blk.mean(axis=(1, 3))          # in place: the C views stay valid
                if k in self.mins:
                    self.mins[k].E[a0:a1, b0:b1] = blk.min(axis=(1, 3))
        return time.perf_counter() - t

    def set_weights(self, alpha, beta):
        for q in list(self.levels.values()) + list(self.mins.values()):
            q.alpha, q.beta = float(alpha), float(beta)

    def level_for(self, view_cells, screen_px=800):
        k = max(1, view_cells // screen_px)
        return max([f for f in self.levels if f <= k], default=1)

    def _cell(self, k, rc):
        q = self.levels[k]
        return (min(rc[0] // k, q.H - 1), min(rc[1] // k, q.W - 1))

    def coarse_route(self, k, start, goal, q=None):
        """Exact route on level k, returned as fine-grid points (cell centres) and the raw result."""
        q = q or self.levels[k]
        if k == 1:
            r = cgrid.dijkstra_c(q, start, goal)
            return ([divmod(i, q.W) for i in r["path"]] if r["path"] else None), r
        s, g = self._cell(k, start), self._cell(k, goal)
        q.blocked[s] = q.blocked[g] = False
        r = cgrid.dijkstra_c(q, s, g)
        if r["path"] is None:
            return None, r
        rc = [divmod(i, q.W) for i in r["path"]]
        fine = [(min(a * k + k // 2, self.p.H - 1), min(b * k + k // 2, self.p.W - 1)) for a, b in rc]
        fine[0], fine[-1] = start, goal
        return fine, r

    def upsample(self, fine_pts):
        """Polyline of fine-grid points -> connected fine path of cell indices."""
        out = []
        for (a, b), (c, d) in zip(fine_pts[:-1], fine_pts[1:]):
            seg = _bresenham(a, b, c, d)
            out += seg if not out else seg[1:]
        return [r * self.p.W + c for r, c in out]

    def corridor_route(self, coarse_paths, start, goal, b=4):
        """Full-resolution search allowed only within b coarse cells of the given (k, coarse path) routes."""
        from scipy.ndimage import binary_dilation
        p = self.p
        fine = np.zeros((p.H, p.W), bool)
        for k, cpath in coarse_paths:
            q = self.levels[k]
            m = np.zeros((q.H, q.W), bool)
            m.flat[cpath] = True
            m = binary_dilation(m, iterations=b)
            fine[:q.H * k, :q.W * k] |= np.repeat(np.repeat(m, k, 0), k, 1)
        sub = Problem(p.z, p.E, p.blocked | ~fine, p.cell, p.alpha, p.beta)
        sub.blocked[start] = sub.blocked[goal] = False
        r = cgrid.dijkstra_c(sub, start, goal)
        r["corridor_frac"] = float(fine.mean())
        return r

    def route(self, start, goal, view=None, screen_px=800, glob_px=500, margin=0.1):
        """view = (r0, r1, c0, c1) visible window in fine cells (None = whole map)."""
        t = time.perf_counter()
        p = self.p
        r0, r1, c0, c1 = view or (0, p.H, 0, p.W)
        kg = min([f for f in self.levels if max(p.H, p.W) // f <= glob_px], default=max(self.levels))
        kv = self.level_for(max(r1 - r0, c1 - c0), screen_px)
        kg = max(kg, kv)
        pts, _ = self.coarse_route(kg, start, goal)
        out = {"level": kg, "view_level": kv, "coarse": pts, "refined": None, "coarse_s": time.perf_counter() - t}
        if pts is None or kv == kg:
            out["total_s"] = time.perf_counter() - t
            return out
        # re-solve the visible part (plus a margin) at the level of detail of the view
        m = int(margin * max(r1 - r0, c1 - c0))
        R0, R1, C0, C1 = max(r0 - m, 0), min(r1 + m, p.H), max(c0 - m, 0), min(c1 + m, p.W)
        inside = [i for i, (r, c) in enumerate(pts) if R0 <= r < R1 and C0 <= c < C1]
        if len(inside) >= 2:
            a, b = pts[inside[0]], pts[inside[-1]]
            q = self.levels[kv]
            w0r, w1r, w0c, w1c = R0 // kv, min(R1 // kv, q.H), C0 // kv, min(C1 // kv, q.W)
            sub = Problem(q.z[w0r:w1r, w0c:w1c], q.E[w0r:w1r, w0c:w1c], q.blocked[w0r:w1r, w0c:w1c].copy(),
                          q.cell, p.alpha, p.beta)
            sa = (min(a[0] // kv - w0r, sub.H - 1), min(a[1] // kv - w0c, sub.W - 1))
            sb = (min(b[0] // kv - w0r, sub.H - 1), min(b[1] // kv - w0c, sub.W - 1))
            sub.blocked[sa] = sub.blocked[sb] = False
            rr = cgrid.dijkstra_c(sub, sa, sb)
            if rr["path"] is not None:
                out["refined"] = [((i // sub.W + w0r) * kv + kv // 2, (i % sub.W + w0c) * kv + kv // 2) for i in rr["path"]]
                out["refine_window"] = (R0, R1, C0, C1)
                out["refine_cells"] = sub.H * sub.W
        out["total_s"] = time.perf_counter() - t
        return out


# ------------------------------------------------------------------ the planner
class Planner:
    def __init__(self, size=4000, mode="exposure", alpha=10.0, beta=2.0, n_radars=6, landmarks=4):
        t = time.perf_counter()
        self.size, self.mode = size, mode
        self.dem = DEM(dem_path(size))
        self.field = RadarField(self.dem, sites_for(self.dem, size, n_radars), mode)
        self.p = Problem(self.dem.z, self.field.E.copy(), blocked_mask(self.dem), self.dem.cell, alpha, beta)
        self.start, self.goal = scenario_endpoints(self.dem, size, self.p.blocked)
        self.n_landmarks = landmarks
        self.ctg = self.lm = self.dstar = self.pyr = None
        self.events = []
        self.log("load", time.perf_counter() - t, "DEM + radar threat surface")

    def log(self, action, seconds, how, **extra):
        e = {"action": action, "ms": 1000 * seconds, "how": how, **extra}
        self.events.append(e)
        return e

    # -------------------------------------------------------------- precompute
    def precompute(self, level2=True, landmarks=True, pyramid=True):
        if level2:
            self.ctg = cgrid.CostToGo(self.p, self.goal)
            self.log("precompute", self.ctg.pre_s, "Level 2 cost-to-go field (one backward C Dijkstra)", mem_mb=self.ctg.mem_mb)
        if landmarks:
            self.lm = cgrid.CLandmarks(self.p, self.n_landmarks)
            self.log("precompute", self.lm.pre_s, f"Level 1 landmarks ({self.n_landmarks}, C, 8 threads)", mem_mb=self.lm.mem_mb)
        if pyramid:
            self.pyr = Pyramid(self.p)
            self.log("precompute", self.pyr.pre_s, "Level 3 pyramid (coarse grids x2..x32)", mem_mb=self.pyr.mem_mb)

    # -------------------------------------------------------------- Level 2 field upkeep
    def rebuild_field(self, background=False, done=None):
        """Recompute the cost-to-go field for the current goal and weights.  In the background the C
        search runs on a worker thread (ctypes releases the GIL), so the GUI keeps answering with
        coarse-to-fine routes until the field is ready; a newer edit makes an older rebuild obsolete."""
        self._gen = getattr(self, "_gen", 0) + 1
        gen, self.ctg = self._gen, None

        def work():
            c = cgrid.CostToGo(self.p, self.goal)
            if gen == self._gen:
                self.ctg = c
                self.log("field ready", c.pre_s, "Level 2 field rebuilt" + (" (background thread)" if background else ""))
                if done:
                    done()
        if background:
            import threading
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    def _quick(self, start, goal):
        """Best route available without the field: landmarks if valid, else coarse-to-fine (no exact stage)."""
        if self.lm is not None:
            r = cgrid.alt_c(self.p, start, goal, self.lm)
            return r["path"], r["cost"], "Level 1 landmark A* (C)"
        if self.pyr is None:
            self.pyr = Pyramid(self.p)
        self.pyr.set_weights(self.p.alpha, self.p.beta)
        r = None
        for r in progressive(self.pyr, start, goal, exact=False):
            pass
        return r["path"], r["cost"], "coarse-to-fine, " + r["stage"]

    # -------------------------------------------------------------- user actions
    def set_start(self, start):
        """Click: new start.  Level 2 lookup if the field is valid (exact, microseconds)."""
        self.start = start
        t = time.perf_counter()
        ctg = self.ctg
        if ctg is not None:
            self.path, self.cost = ctg.route(start)
            how = "Level 2 lookup (no search)"
        else:
            self.path, self.cost, how = self._quick(start, self.goal)
            how += " (field not ready)"
        return self.log("set start", time.perf_counter() - t, how, cost=self.cost)

    def set_goal(self, goal, background=False, done=None):
        """Right-click: new goal.  The field belongs to the old goal: answer with landmarks or
        coarse-to-fine at once, then rebuild the field for the new goal."""
        self.goal = goal
        t = time.perf_counter()
        self.path, self.cost, how = self._quick(self.start, goal)
        e = self.log("set goal (first answer)", time.perf_counter() - t, how, cost=self.cost)
        self.rebuild_field(background, done)
        return e

    def edit_radar(self, kind, i=None, x=None, y=None, repair=True, use_dstar=False, background=False, done=None):
        """Move / add / remove a radar: update the threat surface for that radar only, then repair."""
        t = time.perf_counter()
        if kind == "move":
            changed, tf = self.field.move(i, x, y)
        elif kind == "add":
            changed, tf = self.field.add(x, y)
        else:
            changed, tf = self.field.remove(i)
        cgrid.set_exposure(self.p, self.field.E)
        self.lm = None                                         # landmark distances are now stale
        out = {"field_ms": 1000 * tf, "changed_cells": int((changed > 0).sum())}
        if self.pyr is not None:
            out["pyramid_ms"] = 1000 * self.pyr.update_exposure(changed)
        if use_dstar and self.dstar is not None:
            info = self.dstar.update(changed); self.path, self.cost = self.dstar.route()
            out.update({"dstar_ms": 1000 * info["replan_s"], "dstar_expanded": info["expanded"]})
            how = "threat window + D* Lite repair"
        elif repair and self.ctg is not None:
            info = self.ctg.repair(changed); self.path, self.cost = self.ctg.route(self.start)
            out.update({"repair_ms": 1000 * info["repair_s"], "affected": info["affected"]})
            how = "threat window + Level 2 field repair (exact)"
        else:
            self.path, self.cost, how = self._quick(self.start, self.goal)
            how = "threat window + " + how
            self.rebuild_field(background, done)
        return self.log(f"{kind} radar", time.perf_counter() - t, how, cost=self.cost, **out)

    def set_alpha(self, alpha, on_route=None, background=False, done=None):
        """Change the exposure weight.  The cost-to-go field and the landmarks are invalid, but the
        pyramid is not (it stores exposure and height, not costs).  Coarse-to-fine search draws a route
        within milliseconds and improves it (on_route is called at every stage); the rebuilt Level 2
        field is the last, exact stage."""
        self.p.alpha = float(alpha)
        self.lm = None
        self._gen = getattr(self, "_gen", 0) + 1                # any rebuild in flight is now stale
        self.ctg = None
        if self.pyr is None:
            self.pyr = Pyramid(self.p)
        self.pyr.set_weights(self.p.alpha, self.p.beta)
        t = time.perf_counter()
        drawing = 0.0                                          # time spent in on_route is not planning time
        for i, r in enumerate(progressive(self.pyr, self.start, self.goal, exact=False)):
            self.path, self.cost = r["path"], r["cost"]
            r["elapsed_s"] -= drawing
            self.log("set alpha (%s)" % ("first route" if i == 0 else "improved"), r["elapsed_s"],
                     "coarse-to-fine: " + r["stage"], cost=r["cost"])
            if on_route:
                t1 = time.perf_counter(); on_route(r); drawing += time.perf_counter() - t1

        def finished():
            self.path, self.cost = self.ctg.route(self.start)
            r = {"stage": "exact (Level 2 field rebuilt)", "path": self.path, "cost": self.cost,
                 "elapsed_s": time.perf_counter() - t - drawing, "level": 1}
            self.log("set alpha (exact)", r["elapsed_s"], "Level 2 field rebuilt: exact, lookups valid again", cost=self.cost)
            if on_route:
                on_route(r)
            if done:
                done()
        self.rebuild_field(background, finished)
        return self.events[-1]

    def view(self, r0, r1, c0, c1, screen_px=800):
        """Pan / zoom never searches: a route is one global object, so the view draws the best route
        already known (exact from the Level 2 field, or the latest anytime stage while the field is
        rebuilt), decimated to about one point per screen pixel.  Re-solving the visible window on the
        pyramid was measured (E4) and rejected: slower and often in a different valley."""
        t = time.perf_counter()
        if not getattr(self, "path", None):
            if self.pyr is None:
                self.pyr = Pyramid(self.p)
            self.pyr.set_weights(self.p.alpha, self.p.beta)
            out = self.pyr.route(self.start, self.goal, (r0, r1, c0, c1), screen_px)
            self.lod = out
            return self.log("pan/zoom", out["total_s"], f"no route yet: pyramid preview at x{out['level']}")
        step = max(1, max(r1 - r0, c1 - c0) // screen_px)
        rc = np.array([divmod(i, self.p.W) for i in self.path])
        m = (rc[:, 0] >= r0) & (rc[:, 0] < r1) & (rc[:, 1] >= c0) & (rc[:, 1] < c1)
        self.lod = {"level": 1, "view_level": step, "coarse": None, "refined": [tuple(q) for q in rc[m][::step]],
                    "total_s": time.perf_counter() - t}
        src = "exact route (field)" if self.ctg is not None else "best anytime route so far"
        return self.log("pan/zoom", self.lod["total_s"], f"draw {src}, every {step} point(s); no search")

    def risk_budget(self, p_max, alphas=None, tol=0.01):
        """Shortest route whose detection probability is at most p_max (detection model).
        -ln P(undetected) is additive, so this is a resource-constrained shortest path; it is solved
        by Lagrangian relaxation: bisection on the price alpha of risk (each step one exact C search).
        Returns the cheapest-in-length feasible route found and the search trace."""
        assert self.mode == "detection"
        lo, hi = 0.0, 1.0
        trace, best = [], None
        q = Problem.__new__(Problem); q.__dict__.update(self.p.__dict__)
        q.__dict__.pop("_c_arrays", None)

        def solve(a):
            q.alpha = a
            r = cgrid.dijkstra_c(q, self.start, self.goal)
            pd = self.field.detection_probability(r["path"], q.W, q.cell)
            ev = evaluate(q, r["path"])
            trace.append({"alpha": a, "p_detect": pd, "length_km": ev["length_km"], "solve_s": r["solve_s"]})
            r["alpha"] = a
            return r, pd, ev
        t = time.perf_counter()
        r, pd, ev = solve(0.0)
        if pd <= p_max:
            best = (r, pd, ev)
        else:
            while True:                                        # grow the price until the budget is met
                r, pd, ev = solve(hi)
                if pd <= p_max or hi > 1e4:
                    break
                lo, hi = hi, hi * 4
            best = (r, pd, ev) if pd <= p_max else None
            for _ in range(12):                                # then bisect (geometric) on the price
                if best is None or hi / max(lo, 1e-9) < 1 + tol * 10:
                    break
                mid = math.sqrt(max(lo, hi / 64) * hi)
                r, pd, ev = solve(mid)
                if pd <= p_max:
                    hi = mid
                    if ev["length_km"] < best[2]["length_km"]:
                        best = (r, pd, ev)
                else:
                    lo = mid
        dt = time.perf_counter() - t
        if best is not None:
            self.path, self.cost = best[0]["path"], best[0]["cost"]
        return {"p_max": p_max, "found": best is not None, "p_detect": best[1] if best else None,
                "length_km": best[2]["length_km"] if best else None, "alpha": best[0]["alpha"] if best else None,
                "solves": len(trace), "seconds": dt, "trace": trace}

    def detection_probability(self, path=None):
        return self.field.detection_probability(path or self.path, self.p.W, self.p.cell) if self.mode == "detection" else None
