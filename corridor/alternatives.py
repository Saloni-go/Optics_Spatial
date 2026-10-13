"""Track 3 - several genuinely different corridors, not just the best one.

Via-node method ("choice routing"): a cost field FROM the start and one TO the goal give, for every cell v,
the cost of the best route forced through v:  via(v) = d(start, v) + d(v, goal).  Cells with via(v) close to
the optimum lie on good alternative routes.  Scanning them in increasing via cost and keeping only routes
that are far from the ones already chosen yields k diverse corridors from just two fields.

The forward field uses the same C search on the mirrored terrain: with z -> -z the climb term of a
backward search becomes the climb of the forward edge, so d(start, v) = backward field from the start.

Baseline: the penalty method (raise the cost near each chosen route and re-plan), one field per route.
"""
import time

import numpy as np
from scipy.ndimage import binary_dilation

from corridor import cgrid
from corridor.optimizer import Problem, evaluate


def _follow(nxt, v, stop=None):
    out = [v]
    while nxt[v] >= 0:
        v = int(nxt[v]); out.append(v)
    return out


def _near(path, shape, radius):
    m = np.zeros(shape, bool)
    m.flat[path] = True
    return binary_dilation(m, iterations=radius)


def overlap(a, b, shape, radius=3):
    """Fraction of route a's cells within `radius` cells of route b."""
    nb = _near(b, shape, radius)
    return float(nb.flat[a].mean())


def _plateaus(fs_next, fg_next):
    """Cells v whose start-tree edge (pred(v) -> v) is also a goal-tree edge: on such stretches (plateaus)
    the best route through any cell is the same, so one candidate per plateau is enough."""
    N = len(fs_next)
    pred = fs_next
    ok = pred >= 0
    m = np.zeros(N, bool)
    idx = np.nonzero(ok)[0]
    m[idx] = fg_next[pred[idx]] == idx
    return m


def _stamp(mask, cells, W, r):
    """Mark every cell within r (square) of the given cells (cheap alternative to a full-map dilation)."""
    rr, cc = np.divmod(np.asarray(cells, np.int64), W)
    H = len(mask) // W
    for dr in range(-r, r + 1):
        for dc in range(-r, r + 1):
            a, b = rr + dr, cc + dc
            ok = (a >= 0) & (a < H) & (b >= 0) & (b < W)
            mask[a[ok] * W + b[ok]] = True


def via_routes(p, start, goal, k=3, stretch=0.3, max_share=0.6, sep_cells=33, max_checks=3000, min_dev_m=3000.0):
    t = time.perf_counter()
    fg = cgrid.CostToGo(p, goal, threads=cgrid.THREADS)
    q = Problem(-p.z, p.E, p.blocked, p.cell, p.alpha, p.beta)       # mirrored terrain: forward field
    fs = cgrid.CostToGo(q, start, threads=cgrid.THREADS)
    t_fields = time.perf_counter() - t
    s = p.idx(start)
    opt = float(fg.dist[s])
    via = fs.dist + fg.dist
    best = _follow(fg.next, s)
    shape = (p.H, p.W)
    # a genuine alternative must leave the best route: only via cells at least min_dev_m away from it
    from scipy.ndimage import distance_transform_edt
    m0 = np.ones(shape, bool); m0.flat[best] = False
    far = distance_transform_edt(m0).ravel() * p.cell >= min_dev_m
    cand = np.nonzero((via <= (1 + stretch) * opt) & far)[0]
    cand = cand[np.argsort(via[cand], kind="stable")]
    routes = [{"path": best, "cost": opt, "via": None}]
    near = [_near(best, shape, 3).ravel()]                # cells within 3 of each chosen route (for overlap)
    taken = _near(best, shape, sep_cells).ravel()        # via cells that would give a route already covered
    checks = 0
    for v in cand:
        if len(routes) > k or checks >= max_checks:
            break
        if taken[v]:
            continue
        checks += 1
        head = _follow(fs.next, int(v))[::-1]                          # start ... v
        tail = _follow(fg.next, int(v))                                # v ... goal
        path = head + tail[1:]
        pa = np.asarray(path)
        # every via cell on this route's own detour gives (nearly) the same route: never try them again
        detour = pa[~np.any([m[pa] for m in near], axis=0)]
        if len(set(path)) < len(path) or max(float(m[pa].mean()) for m in near) > max_share:
            _stamp(taken, detour, p.W, 10)               # the whole detour corridor gives the same answer
            taken[int(v)] = True
            continue
        routes.append({"path": path, "cost": float(via[v]), "via": int(v)})
        near.append(_near(path, shape, 3).ravel())
        taken |= _near(path, shape, sep_cells).ravel()
    return routes, {"fields_s": t_fields, "total_s": time.perf_counter() - t, "checks": checks,
                    "candidates": int(len(cand))}


def penalty_routes(p, start, goal, k=3, factor=0.5, radius=33):
    """Baseline: after each route, make cells near it (1 + factor) times as costly and re-plan."""
    t = time.perf_counter()
    E = p.E.copy()
    mult = np.ones((p.H, p.W))
    routes = []
    for _ in range(k + 1):
        q = Problem(p.z, p.E, p.blocked, p.cell, p.alpha, p.beta)
        # extra cost via the exposure term: E' = E + factor * (1 + alpha E) / alpha near earlier routes
        q.E = np.ascontiguousarray(E + (mult - 1) * (1 + p.alpha * E) / max(p.alpha, 1e-9))
        f = cgrid.CostToGo(q, goal, threads=cgrid.THREADS)
        path, _ = f.route(start)
        routes.append({"path": path, "cost": evaluate(p, path)["cost"]})
        mult[_near(path, (p.H, p.W), radius)] = 1 + factor
    return routes, {"total_s": time.perf_counter() - t}
