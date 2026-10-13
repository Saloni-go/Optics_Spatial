"""Track 3 - Python interface to the compiled grid search (corridor/c/gridsearch.c).

    dijkstra_c(p, s, g)        Dijkstra in C on the implicit grid (no explicit graph)
    astar_c(p, s, g, w=1)      A* with straight-line + climb heuristic
    alt_c(p, s, g, lm)         landmark A* (ALT); lm = CLandmarks(p)
    CLandmarks(p, k, threads)  landmark preprocessing in C: one forward and one backward one-to-all
                               search per landmark, run on threads (ctypes releases the GIL)

Results have the same form as corridor/optimizer.py, so the C solvers drop into the benchmarks.
The DLL is compiled on first use if it is missing (needs gcc on PATH, e.g. MinGW-w64).
"""
import ctypes as ct
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent / "c"
SRC, DLL = HERE / "gridsearch.c", HERE / "gridsearch.dll"
INCS = [HERE / "dstar.inc", HERE / "parallel.inc", HERE / "csp.inc", HERE / "tiles.inc", HERE / "layers.inc"]


def build(force=False):
    if DLL.exists() and not force and DLL.stat().st_mtime >= max(f.stat().st_mtime for f in [SRC] + INCS):
        return DLL
    import os
    gcc = os.environ.get("GCC") or shutil.which("gcc")
    if not gcc:
        raise RuntimeError("gcc not found: install MinGW-w64 or build corridor/c/gridsearch.dll by hand")
    # -static: OpenMP and pthread runtimes linked in, so the DLL loads without MinGW on PATH
    subprocess.run([gcc, "-O3", "-fopenmp", "-shared", "-static", "-o", str(DLL), str(SRC)], check=True)
    return DLL


_lib = None
_lock = __import__("threading").Lock()
PAR_LOCK = __import__("threading").Lock()     # one parallel search at a time: its threads spin at barriers
THREADS = min(12, __import__("os").cpu_count() or 1)


def lib():
    """Load the DLL once; fully configured before it becomes visible to other threads."""
    global _lib
    if _lib is None:
        with _lock:
            if _lib is None:
                L = ct.CDLL(str(build()))
                P = np.ctypeslib.ndpointer
                f64, f32, u8, i32 = (P(dtype=t, flags="C_CONTIGUOUS") for t in (np.float64, np.float32, np.uint8, np.int32))
                L.grid_search.restype = ct.c_int64
                L.grid_search.argtypes = [ct.c_int32, ct.c_int32, f64, f64, u8, ct.c_double, ct.c_double, ct.c_double,
                                          ct.c_int32, ct.c_int32, ct.c_int32, ct.c_double, ct.c_int32, ct.c_void_p, ct.c_void_p,
                                          ct.POINTER(ct.c_double), ct.POINTER(ct.c_int64), i32, ct.c_int64]
                L.grid_sssp.restype = ct.c_int64
                L.grid_sssp.argtypes = [ct.c_int32, ct.c_int32, f64, f64, u8, ct.c_double, ct.c_double, ct.c_double,
                                        ct.c_int32, ct.c_int32, f32]
                L.grid_costtogo.restype = ct.c_int64
                L.grid_costtogo.argtypes = [ct.c_int32, ct.c_int32, f64, f64, u8, ct.c_double, ct.c_double, ct.c_double,
                                            ct.c_int32, f64, i32]
                L.grid_repair.restype = ct.c_int64
                L.grid_repair.argtypes = [ct.c_int32, ct.c_int32, f64, f64, u8, ct.c_double, ct.c_double, ct.c_double,
                                          ct.c_int32, u8, f64, i32, ct.POINTER(ct.c_int64)]
                L.grid_follow.restype = ct.c_int64
                L.grid_follow.argtypes = [i32, ct.c_int32, ct.c_int32, i32, ct.c_int64]
                L.dstar_new.restype = ct.c_void_p
                L.dstar_new.argtypes = [ct.c_int32, ct.c_int32, f64, f64, u8, ct.c_double, ct.c_double, ct.c_double,
                                        ct.c_int32, ct.c_int32]
                L.dstar_plan.restype = ct.c_int64
                L.dstar_plan.argtypes = [ct.c_void_p, ct.c_int32]
                L.dstar_update.restype = ct.c_int64
                L.dstar_update.argtypes = [ct.c_void_p, f64, u8]
                L.dstar_cost.restype = ct.c_double
                L.dstar_cost.argtypes = [ct.c_void_p]
                L.dstar_path.restype = ct.c_int64
                L.dstar_path.argtypes = [ct.c_void_p, i32, ct.c_int64]
                L.grid_costtogo_par.restype = ct.c_int64
                L.grid_costtogo_par.argtypes = [ct.c_int32, ct.c_int32, f64, f64, u8, ct.c_double, ct.c_double, ct.c_double,
                                                ct.c_int32, ct.c_double, ct.c_int32, f64, i32, ct.POINTER(ct.c_int64)]
                L.grid_costtogo_w.restype = ct.c_int64
                L.grid_costtogo_w.argtypes = [ct.c_int32, ct.c_int32, f64, f64, u8, ct.c_double, ct.c_double, ct.c_double,
                                              ct.c_double, ct.c_double, ct.c_int32, f64]
                L.csp_label.restype = ct.c_int64
                L.csp_label.argtypes = [ct.c_int32, ct.c_int32, f64, f64, u8, ct.c_double, ct.c_double, ct.c_int32, ct.c_int32,
                                        ct.c_double, ct.c_double, f64, f64, ct.c_double, ct.c_void_p, ct.c_double, ct.c_int64,
                                        ct.POINTER(ct.c_double),
                                        ct.POINTER(ct.c_double), ct.POINTER(ct.c_int64), i32, ct.c_int64]
                L.window_multi.restype = ct.c_int64
                L.window_multi.argtypes = [ct.c_int32, ct.c_int32, f64, f64, u8, ct.c_double, ct.c_double, ct.c_double,
                                           ct.c_int32, ct.c_int32, ct.c_int32, ct.c_int32, ct.c_int32, ct.c_void_p,
                                           ct.c_int32, ct.c_void_p, ct.c_int32, ct.c_void_p]
                L.overlay_query.restype = ct.c_int32
                L.overlay_query.argtypes = [ct.c_int32, ct.c_void_p, ct.c_void_p, ct.c_void_p, ct.c_int32, ct.c_void_p,
                                            ct.c_void_p, ct.c_int32, ct.c_void_p, ct.c_void_p, ct.POINTER(ct.c_double),
                                            ct.c_void_p]
                V = ct.c_void_p
                L.grid3_costtogo.restype = ct.c_int64
                L.grid3_costtogo.argtypes = [ct.c_int32, ct.c_int32, ct.c_int32, V, V, V, V, V, ct.c_double, ct.c_double,
                                             ct.c_double, ct.c_double, ct.c_int32, V, V]
                L.dstar_free.restype = None
                L.dstar_free.argtypes = [ct.c_void_p]
                _lib = L
    return _lib


def _arrays(p):
    """Contiguous views the C code reads (cached on the problem object)."""
    if not hasattr(p, "_c_arrays"):
        p._c_arrays = (np.ascontiguousarray(p.z, np.float64).ravel(), np.ascontiguousarray(p.E, np.float64).ravel(),
                       np.ascontiguousarray(p.blocked, np.uint8).ravel())
    return p._c_arrays


def set_exposure(p, E):
    """Replace the exposure surface of problem p (and drop the cached C views)."""
    p.E = np.ascontiguousarray(E, np.float64)
    if hasattr(p, "_c_arrays"):
        z, _, blk = p._c_arrays
        p._c_arrays = (z, p.E.ravel(), blk)


class CostToGo:
    """Level 2: the cost of the best route from EVERY cell to one goal, plus the next step.
    compute() is one backward Dijkstra in C; route() then needs no search at all;
    repair() updates the field after the exposure changed in a region (incremental)."""

    def __init__(self, p, goal, threads=None, delta=None):
        self.p, self.goal = p, (p.idx(goal) if isinstance(goal, tuple) else int(goal))
        N = p.H * p.W
        self.dist = np.empty(N, np.float64)
        self.next = np.empty(N, np.int32)
        if threads:                                   # delta-stepping on `threads` cores
            self.compute_parallel(threads, delta)
            self.mem_mb = (self.dist.nbytes + self.next.nbytes) / 2 ** 20
        else:
            self.compute()

    def compute(self):
        p = self.p
        z, E, blk = _arrays(p)
        t = time.perf_counter()
        self.settled = lib().grid_costtogo(p.H, p.W, z, E, blk, p.cell, p.alpha, p.beta, self.goal, self.dist, self.next)
        self.pre_s = time.perf_counter() - t
        self.mem_mb = (self.dist.nbytes + self.next.nbytes) / 2 ** 20
        return self.pre_s

    def compute_parallel(self, threads=THREADS, delta=None):
        """Same field with delta-stepping on several cores (exact; corridor/c/parallel.inc)."""
        p = self.p
        z, E, blk = _arrays(p)
        # bucket width ~16 typical edge costs (scales with alpha, so large risk prices stay cheap)
        delta = delta or 16 * p.cell * (1.0 + p.alpha * float(E.mean()))
        rel = ct.c_int64()
        with PAR_LOCK:
            t = time.perf_counter()
            phases = lib().grid_costtogo_par(p.H, p.W, z, E, blk, p.cell, p.alpha, p.beta, self.goal, delta, threads,
                                             self.dist, self.next, ct.byref(rel))
            self.pre_s = time.perf_counter() - t
        if phases < 0:
            raise MemoryError("grid_costtogo_par: allocation failed")
        self.phases, self.relaxations = int(phases), int(rel.value)
        return self.pre_s

    def route(self, start):
        """Best route start -> goal by following the stored next steps."""
        s = self.p.idx(start) if isinstance(start, tuple) else int(start)
        cap = 40 * (self.p.H + self.p.W)
        while True:
            path = np.empty(cap, np.int32)
            n = lib().grid_follow(self.next, s, self.goal, path, cap)
            if n >= 0:
                return (path[:n].tolist() if n > 0 else None), float(self.dist[s])
            cap = -n

    def repair(self, changed):
        """Repair after p.E changed on the cells marked True in `changed` (bool, H x W or N)."""
        p = self.p
        z, E, blk = _arrays(p)
        ch = np.ascontiguousarray(changed, np.uint8).ravel()
        settled = ct.c_int64()
        t = time.perf_counter()
        naff = lib().grid_repair(p.H, p.W, z, E, blk, p.cell, p.alpha, p.beta, self.goal, ch, self.dist, self.next,
                                 ct.byref(settled))
        dt = time.perf_counter() - t
        if naff < 0:
            raise MemoryError("grid_repair: allocation failed")
        return {"repair_s": dt, "affected": int(naff), "settled": int(settled.value)}


def _search(p, start, goal, hmode, w=1.0, lm=None):
    z, E, blk = _arrays(p)
    s, g = p.idx(start), p.idx(goal)
    cost, exp = ct.c_double(), ct.c_int64()
    cap = 40 * (p.H + p.W)
    K, fwd, bwd = (len(lm.nodes), lm.fwd.ctypes.data, lm.bwd.ctypes.data) if lm is not None else (0, None, None)
    while True:
        path = np.empty(cap, np.int32)
        t = time.perf_counter()
        n = lib().grid_search(p.H, p.W, z, E, blk, p.cell, p.alpha, p.beta, s, g, hmode, w, K, fwd, bwd,
                              ct.byref(cost), ct.byref(exp), path, cap)
        dt = time.perf_counter() - t
        if n >= -1 or -n <= cap:
            break
        cap = -n                                         # path longer than the buffer: retry once, bigger
    if n == -1:
        raise MemoryError("grid_search: allocation failed")
    return {"path": path[:n].tolist() if n > 0 else None, "cost": float(cost.value), "expanded": int(exp.value),
            "solve_s": dt, "build_s": 0.0}


def dijkstra_c(p, start, goal):
    return _search(p, start, goal, 0)


def astar_c(p, start, goal, w=1.0):
    return _search(p, start, goal, 1, w)


def alt_c(p, start, goal, lm, w=1.0):
    r = _search(p, start, goal, 2, w, lm)
    r.update({"pre_s": lm.pre_s, "pre_mb": lm.mem_mb})
    return r


class CLandmarks:
    """Same landmarks as optimizer.Landmarks (corners), distances computed by grid_sssp in C."""

    def __init__(self, p, k=4, threads=8):
        lib()                                              # load before the worker threads start
        z, E, blk = _arrays(p)
        free = np.argwhere(~p.blocked)
        corners = [(0, 0), (0, p.W - 1), (p.H - 1, 0), (p.H - 1, p.W - 1),
                   (0, p.W // 2), (p.H - 1, p.W // 2), (p.H // 2, 0), (p.H // 2, p.W - 1)][:k]
        self.nodes = []
        for r, c in corners:
            i = int(np.argmin(np.abs(free[:, 0] - r) + np.abs(free[:, 1] - c)))
            self.nodes.append(int(free[i, 0]) * p.W + int(free[i, 1]))
        N = p.H * p.W
        self.fwd = np.empty((k, N), np.float32)            # d(L, v)
        self.bwd = np.empty((k, N), np.float32)            # d(v, L)
        jobs = [(self.fwd, i, 0) for i in range(k)] + [(self.bwd, i, 1) for i in range(k)]

        def run(job):
            out, i, rev = job
            row = np.empty(N, np.float32)
            lib().grid_sssp(p.H, p.W, z, E, blk, p.cell, p.alpha, p.beta, self.nodes[i], rev, row)
            out[i] = row

        t = time.perf_counter()
        if threads > 1:
            with ThreadPoolExecutor(max_workers=min(threads, len(jobs))) as ex:
                list(ex.map(run, jobs))
        else:
            for j in jobs:
                run(j)
        self.pre_s = time.perf_counter() - t
        self.build_s = 0.0
        self.mem_mb = (self.fwd.nbytes + self.bwd.nbytes) / 2 ** 20


class DStar:
    """D* Lite incremental replanner (C) for one route whose start may move and whose costs may change.
    plan(start) replans after the start moved; update(changed) after p.E changed on some cells."""

    def __init__(self, p, start, goal):
        self.p = p
        self._keep = _arrays(p)                    # the C object points into these arrays
        z, E, blk = self._keep
        self.goal = p.idx(goal)
        self.h = lib().dstar_new(p.H, p.W, z, E, blk, p.cell, p.alpha, p.beta, p.idx(start), self.goal)
        if not self.h:
            raise MemoryError("dstar_new failed")
        self.plan(start)

    def plan(self, start):
        t = time.perf_counter()
        n = lib().dstar_plan(self.h, self.p.idx(start) if isinstance(start, tuple) else int(start))
        return {"replan_s": time.perf_counter() - t, "expanded": int(n)}

    def update(self, changed):
        z, E, blk = _arrays(self.p)
        self._keep = (z, E, blk)
        ch = np.ascontiguousarray(changed, np.uint8).ravel()
        t = time.perf_counter()
        n = lib().dstar_update(self.h, E, ch)
        return {"replan_s": time.perf_counter() - t, "expanded": int(n)}

    def route(self):
        cap = 40 * (self.p.H + self.p.W)
        while True:
            path = np.empty(cap, np.int32)
            n = lib().dstar_path(self.h, path, cap)
            if n >= 0:
                return (path[:n].tolist() if n > 0 else None), float(lib().dstar_cost(self.h))
            cap *= 2

    def __del__(self):
        if getattr(self, "h", None):
            lib().dstar_free(self.h); self.h = None
