"""Track 3 - least-cost visibility-aware route on the 8-connected DEM grid.

Edge cost (see exposure.py):  c(u,v) = L_uv * (1 + alpha * (E_u + E_v)/2) + beta * max(0, z_v - z_u)

Solvers (all exact on the same graph except multires):
  dijkstra_py   textbook Dijkstra with a binary heap, pure Python, stops at the goal  O(E log V)
  astar_py      A* with h(u) = euclid(u, goal) + beta * max(0, z_goal - z_u)
                admissible and consistent because every metre costs >= 1 and any path must
                climb at least z_goal - z_u, so A* returns the same optimum with fewer expansions
  dijkstra_csgraph  SciPy's C Dijkstra on an explicit CSR graph (graph build timed separately)
  multires      coarse-to-fine: solve on a k-times coarser grid, then A* on the fine grid
                restricted to a buffer around the coarse route.  Approximate.
"""
import heapq
import math
import time
import numpy as np
from scipy import sparse
from scipy.ndimage import binary_dilation
from scipy.sparse.csgraph import dijkstra as cs_dijkstra

OFFS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


class Problem:
    def __init__(self, z, E, blocked, cell, alpha=10.0, beta=1.0):
        self.H, self.W = z.shape
        self.z = np.ascontiguousarray(np.nan_to_num(z, nan=0.0), dtype=np.float64)
        self.E = np.ascontiguousarray(E, dtype=np.float64)
        self.blocked = np.ascontiguousarray(blocked, dtype=bool)
        self.cell, self.alpha, self.beta = float(cell), float(alpha), float(beta)

    def idx(self, rc):
        return int(rc[0]) * self.W + int(rc[1])

    def rc(self, i):
        return divmod(int(i), self.W)


def _neighbours(W, H):
    """(dr, dc, index offset, length factor)"""
    return [(dr, dc, dr * W + dc, math.sqrt(2.0) if dr and dc else 1.0) for dr, dc in OFFS]


def geo_heuristic(p, goal):
    """Straight-line distance + beta * height still to climb, for every node (vectorised)."""
    gr, gc = goal
    rr, cc = np.ogrid[0:p.H, 0:p.W]
    h = np.hypot(rr - gr, cc - gc) * p.cell + p.beta * np.maximum(p.z[gr, gc] - p.z, 0)
    return h.ravel()


class Landmarks:
    """ALT preprocessing (Goldberg and Harrelson 2005): exact cost from every node to and from a
    few landmarks.  By the triangle inequality, for any goal g:
        d(u, g) >= d(u, L) - d(g, L)      and      d(u, g) >= d(L, g) - d(L, u)
    so the largest of these over the landmarks is an admissible and consistent heuristic that,
    unlike straight-line distance, already 'knows' about exposure detours.  Costs one forward and
    one backward Dijkstra per landmark (SciPy, C) and 2 x K x N floats of memory; it pays off when
    several routes are planned on the same cost surface."""

    def __init__(self, p, k=4, graph=None):
        t0 = time.perf_counter()
        G = graph if graph is not None else build_csr(p)
        self.build_s = time.perf_counter() - t0
        free = np.argwhere(~p.blocked)
        corners = [(0, 0), (0, p.W - 1), (p.H - 1, 0), (p.H - 1, p.W - 1),
                   (0, p.W // 2), (p.H - 1, p.W // 2), (p.H // 2, 0), (p.H // 2, p.W - 1)][:k]
        self.nodes = []
        for r, c in corners:                       # nearest unblocked cell to each corner / edge midpoint
            i = int(np.argmin(np.abs(free[:, 0] - r) + np.abs(free[:, 1] - c)))
            self.nodes.append(int(free[i, 0]) * p.W + int(free[i, 1]))
        t1 = time.perf_counter()
        self.fwd = cs_dijkstra(G, directed=True, indices=self.nodes).astype(np.float32)           # d(L, v)
        self.bwd = cs_dijkstra(G.T.tocsr(), directed=True, indices=self.nodes).astype(np.float32)  # d(v, L)
        self.pre_s = time.perf_counter() - t1
        self.mem_mb = (self.fwd.nbytes + self.bwd.nbytes) / 2 ** 20

    def heuristic(self, p, goal):
        g = p.idx(goal)
        h = geo_heuristic(p, goal)
        with np.errstate(invalid="ignore"):
            for k in range(len(self.nodes)):
                for t in (self.bwd[k] - self.bwd[k, g], self.fwd[k, g] - self.fwd[k]):
                    t = np.where(np.isnan(t), 0, t).astype(np.float64) - 1.0   # -1: float32 rounding margin
                    np.maximum(h, t, out=h)
        return h


def _search(p, start, goal, use_h, H=None, w=1.0):
    """Best-first search.  use_h=False: Dijkstra.  H: precomputed heuristic per node (default:
    straight-line + climb).  w > 1: weighted A*, cost at most w x optimum."""
    W, Hh, cell, a, b = p.W, p.H, p.cell, p.alpha, p.beta
    z = memoryview(p.z.ravel()); E = memoryview(p.E.ravel())
    blk = memoryview(p.blocked.ravel().view(np.uint8))
    n = W * Hh
    dist = np.full(n, np.inf); D = memoryview(dist)
    parent = np.full(n, -1, np.int64); PAR = memoryview(parent)
    closed = np.zeros(n, np.uint8); C = memoryview(closed)
    s, g = p.idx(start), p.idx(goal)
    nb = _neighbours(W, Hh)
    H = memoryview(np.ascontiguousarray((H if H is not None else geo_heuristic(p, goal)) * w if use_h else np.zeros(1)))
    h = (lambda i: H[i]) if use_h else (lambda i: 0.0)
    H_ = Hh

    D[s] = 0.0
    heap = [(h(s), 0.0, s)]
    pop, push = heapq.heappop, heapq.heappush
    expanded = 0
    while heap:
        f, du, u = pop(heap)
        if C[u]:
            continue
        C[u] = 1
        expanded += 1
        if u == g:
            break
        ur, uc = divmod(u, W)
        zu, eu = z[u], E[u]
        for dr, dc, off, lf in nb:
            vr = ur + dr; vc = uc + dc
            if vr < 0 or vr >= H_ or vc < 0 or vc >= W:
                continue
            v = u + off
            if blk[v] or C[v]:
                continue
            dz = z[v] - zu
            nd = du + lf * cell * (1.0 + a * 0.5 * (eu + E[v])) + (b * dz if dz > 0 else 0.0)
            if nd < D[v]:
                D[v] = nd; PAR[v] = u
                push(heap, (nd + h(v), nd, v))
    return _path(parent, s, g), float(dist[g]), expanded


def _path(parent, s, g):
    if parent[g] < 0 and g != s:
        return None
    out = [g]
    while out[-1] != s:
        out.append(int(parent[out[-1]]))
    return out[::-1]


def dijkstra_py(p, start, goal):
    t = time.perf_counter()
    path, cost, exp = _search(p, start, goal, False)
    return {"path": path, "cost": cost, "expanded": exp, "solve_s": time.perf_counter() - t, "build_s": 0.0}


def astar_py(p, start, goal, w=1.0):
    t = time.perf_counter()
    path, cost, exp = _search(p, start, goal, True, w=w)
    return {"path": path, "cost": cost, "expanded": exp, "solve_s": time.perf_counter() - t, "build_s": 0.0}


def astar_alt(p, start, goal, lm, w=1.0):
    """A* with the landmark heuristic (lm = Landmarks(p)); preprocessing is reported separately."""
    t0 = time.perf_counter()
    H = lm.heuristic(p, goal)
    t1 = time.perf_counter()
    path, cost, exp = _search(p, start, goal, True, H=H, w=w)
    return {"path": path, "cost": cost, "expanded": exp, "solve_s": time.perf_counter() - t1, "build_s": t1 - t0,
            "pre_s": lm.pre_s + lm.build_s, "pre_mb": lm.mem_mb}


def build_csr(p):
    W, H, n = p.W, p.H, p.W * p.H
    idx = np.arange(n, dtype=np.int64).reshape(H, W)
    rows, cols, vals = [], [], []
    for dr, dc, off, lf in _neighbours(W, H):
        rs = slice(max(0, -dr), H - max(0, dr)); cs = slice(max(0, -dc), W - max(0, dc))
        rd = slice(max(0, dr), H - max(0, -dr)); cd = slice(max(0, dc), W - max(0, -dc))
        ok = ~p.blocked[rs, cs] & ~p.blocked[rd, cd]
        dz = p.z[rd, cd] - p.z[rs, cs]
        w = lf * p.cell * (1.0 + p.alpha * 0.5 * (p.E[rs, cs] + p.E[rd, cd])) + p.beta * np.maximum(dz, 0)
        rows.append(idx[rs, cs][ok]); cols.append(idx[rd, cd][ok]); vals.append(w[ok])
    rows = np.concatenate(rows); cols = np.concatenate(cols); vals = np.concatenate(vals)
    return sparse.csr_matrix((vals, (rows, cols)), shape=(n, n))


def dijkstra_csgraph(p, start, goal, graph=None):
    t0 = time.perf_counter()
    G = graph if graph is not None else build_csr(p)
    t1 = time.perf_counter()
    s, g = p.idx(start), p.idx(goal)
    d, pred = cs_dijkstra(G, directed=True, indices=s, return_predecessors=True)
    t2 = time.perf_counter()
    pred = pred.astype(np.int64); pred[pred < 0] = -1
    return {"path": _path(pred, s, g), "cost": float(d[g]), "expanded": int(np.isfinite(d).sum()),
            "solve_s": t2 - t1, "build_s": t1 - t0, "edges": int(G.nnz)}


def coarsen(p, k):
    H2, W2 = p.H // k, p.W // k
    def blk(a, fn):
        return fn(a[:H2 * k, :W2 * k].reshape(H2, k, W2, k), axis=(1, 3))
    zc = blk(p.z, np.mean); Ec = blk(p.E, np.mean)
    bc = blk(p.blocked.astype(np.float32), np.mean) > 0.5
    return Problem(zc, Ec, bc, p.cell * k, p.alpha, p.beta)


def multires(p, start, goal, k=4, buffer_cells=3):
    t0 = time.perf_counter()
    pc = coarsen(p, k)
    cs = (min(start[0] // k, pc.H - 1), min(start[1] // k, pc.W - 1))
    cg = (min(goal[0] // k, pc.H - 1), min(goal[1] // k, pc.W - 1))
    pc.blocked[cs] = pc.blocked[cg] = False
    coarse = astar_py(pc, cs, cg)
    t1 = time.perf_counter()
    if coarse["path"] is None:
        return {"path": None, "cost": math.inf, "expanded": coarse["expanded"], "solve_s": t1 - t0, "build_s": 0.0}
    m = np.zeros((pc.H, pc.W), bool)
    for i in coarse["path"]:
        m[pc.rc(i)] = True
    m = binary_dilation(m, iterations=buffer_cells)
    fine_m = np.kron(m, np.ones((k, k), bool))
    full = np.zeros((p.H, p.W), bool); full[:fine_m.shape[0], :fine_m.shape[1]] = fine_m
    full[start] = full[goal] = True
    pr = Problem(p.z, p.E, p.blocked | ~full, p.cell, p.alpha, p.beta)
    fine = astar_py(pr, start, goal)
    t2 = time.perf_counter()
    return {"path": fine["path"], "cost": fine["cost"], "expanded": coarse["expanded"] + fine["expanded"],
            "solve_s": t2 - t0, "build_s": 0.0, "coarse_s": t1 - t0, "corridor_cells": int(full.sum())}


SOLVERS = {"dijkstra_py": dijkstra_py, "astar_py": astar_py, "dijkstra_csgraph": dijkstra_csgraph, "multires": multires}


def evaluate(p, path):
    """Route metrics independent of the solver."""
    if path is None:
        return None
    rc = np.array([divmod(i, p.W) for i in path])
    d = np.hypot(*np.diff(rc, axis=0).T) * p.cell
    e = p.E[rc[:, 0], rc[:, 1]]
    em = 0.5 * (e[1:] + e[:-1])
    zz = p.z[rc[:, 0], rc[:, 1]]
    climb = np.maximum(np.diff(zz), 0)
    cost = float((d * (1 + p.alpha * em)).sum() + p.beta * climb.sum())
    return {"length_km": float(d.sum() / 1000), "exposure_km": float((d * em).sum() / 1000),
            "exposed_length_km": float(d[em > 0].sum() / 1000), "exposed_frac": float(d[em > 0].sum() / max(d.sum(), 1)),
            "max_exposure": float(e.max()), "climb_m": float(climb.sum()), "cost": cost, "nodes": len(path)}
