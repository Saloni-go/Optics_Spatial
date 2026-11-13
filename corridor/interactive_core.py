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


# ------------------------------------------------------------------ A1: precomputed fields for a ladder of alphas
def cost_at(p, path, alpha):
    """Route cost under a different exposure weight (same surface)."""
    import copy
    q = copy.copy(p); q.alpha = float(alpha)
    return evaluate(q, path)["cost"] if path else math.inf


class AlphaBank:
    """Next-step fields to one goal for a ladder of alpha values (only the int32 next pointers are kept:
    64 MB per alpha on 16 M cells).  Moving the alpha slider then needs no search: the route for the
    nearest banked alpha is followed at once (exact when alpha is on the ladder), while the exact field
    for the new alpha is rebuilt in the background.  Built with one C search per alpha on parallel threads."""

    def __init__(self, p, goal, alphas=(2.0, 5.0, 10.0, 20.0, 50.0), threads=None, compact=False):
        """compact: keep 1-byte direction codes instead of int32 next pointers (16 MB instead of 64 MB per
        alpha on 16 M cells; the same routes, see corridor/memory_bench.py)."""
        self.p, self.goal_rc = p, goal
        self.goal = p.idx(goal)
        self.alphas = sorted(float(a) for a in alphas)
        self.threads = threads
        self.compact = compact
        self.next, self.valid = {}, False
        self.build()

    def build(self):
        """threads=None: one field after another, each with the parallel delta-stepping search (fastest);
        threads=k: k serial Dijkstra searches side by side (one per alpha)."""
        from concurrent.futures import ThreadPoolExecutor
        import copy
        p = self.p
        L = cgrid.lib()
        z, E, blk = cgrid._arrays(p)
        N = p.H * p.W

        def one(a):
            d = np.empty(N, np.float64); nx = np.empty(N, np.int32)
            L.grid_costtogo(p.H, p.W, z, E, blk, p.cell, a, p.beta, self.goal, d, nx)
            return a, nx

        def one_par(a):
            q = copy.copy(p); q.alpha = float(a)
            return a, cgrid.CostToGo(q, self.goal_rc, threads=cgrid.THREADS).next
        t = time.perf_counter()
        if self.threads is None:
            nexts = dict(one_par(a) for a in self.alphas)
        else:
            with ThreadPoolExecutor(max_workers=min(self.threads, len(self.alphas))) as ex:
                nexts = dict(ex.map(one, self.alphas))
        if getattr(self, "compact", False):
            nexts = {a: cgrid.to_dirs(nx, p.W) for a, nx in nexts.items()}
        self.next, self.valid = nexts, True
        self.pre_s = time.perf_counter() - t
        self.mem_mb = sum(v.nbytes for v in nexts.values()) / 2 ** 20
        return self.pre_s

    def nearest(self, alpha):
        if alpha <= 0:
            return self.alphas[0]
        return min(self.alphas, key=lambda a: abs(math.log(a) - math.log(alpha)))

    def route(self, start, alpha):
        """(path, cost at the requested alpha, banked alpha used)."""
        a = self.nearest(alpha)
        s = self.p.idx(start) if isinstance(start, tuple) else int(start)
        path = cgrid.follow(self.next[a], s, self.goal, self.p.W)
        return path, cost_at(self.p, path, alpha), a


# ------------------------------------------------------------------ the planner
class Planner:
    def __init__(self, size=4000, mode="exposure", alpha=10.0, beta=2.0, n_radars=6, landmarks=4, threads=cgrid.THREADS,
                 dem=None, sites=None, ends=None):
        """threads: cores for field (re)builds (delta-stepping); None = serial Dijkstra.
        Any DEM (a DEM object or a path to a projected GeoTIFF) instead of the project's size-`size` DEM;
        sites = radar positions [(x, y)] in its CRS (default: n_radars ridge-top sites);
        ends = ((x, y), (x, y)) start and goal in its CRS (default: the project scenario / the DEM diagonal)."""
        t = time.perf_counter()
        self.threads = threads
        self.mode = mode
        self.dem = DEM(dem_path(size)) if dem is None else dem if isinstance(dem, DEM) else DEM(dem)
        self.size = size if dem is None else max(self.dem.shape)
        self.field = RadarField(self.dem, sites if sites is not None else sites_for(self.dem, self.size, n_radars), mode)
        self.p = Problem(self.dem.z, self.field.E.copy(), blocked_mask(self.dem), self.dem.cell, alpha, beta)
        if ends is not None:
            self.start, self.goal = (self.snap(*self.dem.to_pixel(x, y)[::-1]) for x, y in ends)
        else:
            self.start, self.goal = scenario_endpoints(self.dem, self.size, self.p.blocked)
        self.n_landmarks = landmarks
        self.ctg = self.lm = self.dstar = self.pyr = self.bank = None
        self.events = []
        self.log("load", time.perf_counter() - t, "DEM + radar threat surface")

    def snap(self, r, c, radius=50):
        """Nearest unblocked cell to the (fractional) cell r, c, clipped to the grid."""
        H, W = self.p.H, self.p.W
        r, c = int(min(max(round(r), 0), H - 1)), int(min(max(round(c), 0), W - 1))
        if not self.p.blocked[r, c]:
            return r, c
        r0, c0 = max(r - radius, 0), max(c - radius, 0)
        free = np.argwhere(~self.p.blocked[r0:r + radius + 1, c0:c + radius + 1])
        if not len(free):
            raise ValueError("no unblocked cell near the requested point")
        k = int(np.argmin(np.hypot(free[:, 0] + r0 - r, free[:, 1] + c0 - c)))
        return int(free[k, 0] + r0), int(free[k, 1] + c0)

    def log(self, action, seconds, how, **extra):
        e = {"action": action, "ms": 1000 * seconds, "how": how, **extra}
        self.events.append(e)
        return e

    # -------------------------------------------------------------- precompute
    def precompute(self, level2=True, landmarks=True, pyramid=True, bank=None):
        if level2:
            self.ctg = cgrid.CostToGo(self.p, self.goal, threads=self.threads)
            how = f"parallel delta-stepping, {self.threads} threads" if self.threads else "one backward C Dijkstra"
            self.log("precompute", self.ctg.pre_s, f"Level 2 cost-to-go field ({how})", mem_mb=self.ctg.mem_mb)
        if landmarks:
            self.lm = cgrid.CLandmarks(self.p, self.n_landmarks)
            self.log("precompute", self.lm.pre_s, f"Level 1 landmarks ({self.n_landmarks}, C, 8 threads)", mem_mb=self.lm.mem_mb)
        if pyramid:
            self.pyr = Pyramid(self.p)
            self.log("precompute", self.pyr.pre_s, "Level 3 pyramid (coarse grids x2..x32)", mem_mb=self.pyr.mem_mb)
        if bank:
            self.bank = AlphaBank(self.p, self.goal, bank, compact=True)   # 1-byte directions: same routes, 4x less memory
            self.log("precompute", self.bank.pre_s, f"alpha bank {self.bank.alphas} (parallel C)", mem_mb=self.bank.mem_mb)

    def _bank_ok(self):
        b = self.bank
        return b is not None and b.valid and b.goal == self.p.idx(self.goal)

    def rebuild_bank(self, background=True):
        """The bank is stale after a radar edit or a new goal: rebuild all ladder fields (parallel threads)."""
        if self.bank is None:
            return
        self.bank.valid = False
        self._bgen = getattr(self, "_bgen", 0) + 1
        gen, alphas, threads = self._bgen, self.bank.alphas, self.bank.threads

        def work():
            nb = AlphaBank.__new__(AlphaBank)
            nb.__dict__.update({"p": self.p, "goal_rc": self.goal, "goal": self.p.idx(self.goal),
                                "alphas": alphas, "threads": threads, "next": {}, "valid": False,
                                "compact": getattr(self.bank, "compact", False)})
            nb.build()
            if gen == self._bgen:
                self.bank = nb
                self.log("alpha bank ready", nb.pre_s, f"{len(nb.alphas)} ladder fields rebuilt" + (" (background)" if background else ""))
        if background:
            import threading
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    # -------------------------------------------------------------- Level 2 field upkeep
    def rebuild_field(self, background=False, done=None):
        """Recompute the cost-to-go field for the current goal and weights.  In the background the C
        search runs on a worker thread (ctypes releases the GIL), so the GUI keeps answering with
        coarse-to-fine routes until the field is ready; a newer edit makes an older rebuild obsolete."""
        self._gen = getattr(self, "_gen", 0) + 1
        gen, self.ctg = self._gen, None

        def work():
            c = cgrid.CostToGo(self.p, self.goal, threads=self.threads)
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
        elif self._bank_ok():
            self.path, self.cost, a = self.bank.route(start, self.p.alpha)
            how = f"alpha-bank lookup (alpha={a:g}" + (")" if a == self.p.alpha else ", nearest; exact field rebuilding)")
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
        self.rebuild_bank(background)
        return e

    def edit_radar(self, kind, i=None, x=None, y=None, repair=None, use_dstar=False, background=False, done=None):
        """Move / add / remove a radar: update the threat surface for that radar only, then fix the field.
        repair=None: with several cores rebuild the field in parallel (faster than repairing it, E8), else repair."""
        if repair is None:
            repair = not self.threads
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
        elif self.threads:                                     # 0.3-0.4 s: exact at once, no background needed
            self.ctg = cgrid.CostToGo(self.p, self.goal, threads=self.threads)
            self.path, self.cost = self.ctg.route(self.start)
            out["rebuild_ms"] = 1000 * self.ctg.pre_s
            how = f"threat window + parallel field rebuild, {self.threads} threads (exact)"
        else:
            self.path, self.cost, how = self._quick(self.start, self.goal)
            how = "threat window + " + how
            self.rebuild_field(background, done)
        e = self.log(f"{kind} radar", time.perf_counter() - t, how, cost=self.cost, **out)
        if self.bank is not None:
            self.rebuild_bank(background)                      # the alpha ladder is stale too (not counted above)
        return e

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
        stages = progressive(self.pyr, self.start, self.goal, exact=False)
        if self._bank_ok():
            path, cost, a = self.bank.route(self.start, self.p.alpha)
            r = {"stage": f"alpha bank (alpha={a:g})", "path": path, "cost": cost, "level": 1,
                 "elapsed_s": time.perf_counter() - t}
            self.path, self.cost = path, cost
            self.log("set alpha (first route)", r["elapsed_s"], f"alpha-bank lookup, nearest alpha={a:g}" +
                     (" (exact)" if a == self.p.alpha else ""), cost=cost)
            if on_route:
                t1 = time.perf_counter(); on_route(r); drawing += time.perf_counter() - t1
            if a == self.p.alpha:
                stages = []                                    # already exact: skip coarse-to-fine
            else:
                stages = (st for st in stages if st["level"] == 1)   # only full-res stages can beat it
        for i, r in enumerate(stages):
            if self._bank_ok() and r["cost"] >= self.cost:
                continue                                       # keep the better bank route on screen
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

    def risk_budget(self, p_max, exact=True):
        """Shortest route whose detection probability is at most p_max (detection model): LARAC on parallel
        fields, then an exact label search in a corridor (corridor/riskcsp.py).  Reports the certified gap
        to the best possible length."""
        assert self.mode == "detection"
        from corridor.riskcsp import RiskCSP
        t = time.perf_counter()
        C = RiskCSP(self.p, self.goal, threads=self.threads or cgrid.THREADS)
        r = C.query(self.start, p_max, width_cells=15, resolution=1e-2, max_labels=4_000_000, exact=exact)
        found = r.get("path") is not None
        if found:
            self.path = r["path"]
            self.cost = cost_at(self.p, self.path, self.p.alpha)
        return {"p_max": p_max, "found": found, "p_detect": r.get("p_detect"), "length_km": r.get("length_km"),
                "gap_pct": r.get("gap_pct"), "solves": r["solves"], "seconds": time.perf_counter() - t,
                "status": r["status"], "exact_status": r.get("exact_status")}

    def detection_probability(self, path=None):
        path = path if path is not None else getattr(self, "path", None)
        return self.field.detection_probability(path, self.p.W, self.p.cell) if self.mode == "detection" else None
