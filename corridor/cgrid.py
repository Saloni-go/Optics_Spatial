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


def build(force=False):
    if DLL.exists() and not force and DLL.stat().st_mtime >= SRC.stat().st_mtime:
        return DLL
    import os
    gcc = os.environ.get("GCC") or shutil.which("gcc")
    if not gcc:
        raise RuntimeError("gcc not found: install MinGW-w64 or build corridor/c/gridsearch.dll by hand")
    subprocess.run([gcc, "-O3", "-shared", "-o", str(DLL), str(SRC)], check=True)
    return DLL


_lib = None
_lock = __import__("threading").Lock()


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
                _lib = L
    return _lib


def _arrays(p):
    """Contiguous views the C code reads (cached on the problem object)."""
    if not hasattr(p, "_c_arrays"):
        p._c_arrays = (np.ascontiguousarray(p.z, np.float64).ravel(), np.ascontiguousarray(p.E, np.float64).ravel(),
                       np.ascontiguousarray(p.blocked, np.uint8).ravel())
    return p._c_arrays


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
