"""Track 3 benchmark jobs (one process per run, see common/bench.py)."""
import time

from common.bench import child_main
from common.config import dem_path
from common.dem_utils import DEM
from corridor.exposure import exposure
from corridor.optimizer import SOLVERS, evaluate, multires
from corridor.prep import problem, endpoints, sites_for


def job_solve(j):
    size = int(j["dem_id"])
    t0 = time.perf_counter()
    p, dem = problem(size, float(j.get("alpha", 10)), float(j.get("beta", 2)))
    s, g = endpoints(p.blocked, float(j.get("f0", 0.1)), float(j.get("f1", 0.9)))
    t1 = time.perf_counter()
    alg = j.get("impl", j["algorithm"])
    if alg == "multires":
        r = multires(p, s, g, k=int(j.get("k", 4)), buffer_cells=int(j.get("buffer", 3)))
    elif alg in ("dijkstra_c", "astar_c", "alt_c"):
        from corridor import cgrid
        if alg == "alt_c":
            lm = cgrid.CLandmarks(p, k=int(j.get("landmarks", 4)), threads=int(j.get("threads", 8)))
            r = cgrid.alt_c(p, s, g, lm)
        else:
            r = getattr(cgrid, alg)(p, s, g)
    elif alg == "astar_alt":
        from corridor.optimizer import Landmarks, astar_alt
        lm = Landmarks(p, k=int(j.get("landmarks", 4)))
        r = astar_alt(p, s, g, lm)                         # build_s = heuristic array; pre_s = landmarks
    else:
        r = SOLVERS[alg](p, s, g)
    ev = evaluate(p, r["path"]) or {}
    return {"compute_s": r["solve_s"] + r["build_s"], "solve_s": r["solve_s"], "build_s": r["build_s"],
            "pre_s": r.get("pre_s", 0.0),
            "io_s": t1 - t0, "graph_nodes": p.W * p.H, "expanded": r["expanded"], "route_cost": r["cost"],
            **{f"route_{k}": v for k, v in ev.items()}}


def job_multi_query(j):
    """Plan `queries` routes on the same cost surface (seeded random endpoints at least a third of
    the diagonal apart).  csgraph: build the graph once, one C Dijkstra per query.
    alt: build graph + landmarks once, then one Python ALT A* per query.  astar: plain A* per query."""
    import numpy as np
    from corridor.optimizer import build_csr, dijkstra_csgraph, astar_py, astar_alt, Landmarks
    size = int(j["dem_id"]); q = int(j.get("queries", 8)); alg = j.get("impl", j["algorithm"])
    p, dem = problem(size, float(j.get("alpha", 10)), float(j.get("beta", 2)))
    rng = np.random.default_rng(7)
    free = np.argwhere(~p.blocked)
    pairs = []
    while len(pairs) < q:
        a, b = free[rng.integers(len(free))], free[rng.integers(len(free))]
        if np.hypot(*(a - b)) > size * 1.414 / 3:
            pairs.append((tuple(int(x) for x in a), tuple(int(x) for x in b)))
    t0 = time.perf_counter()
    pre_s, expanded, costs = 0.0, [], []
    if alg == "csgraph":
        G = build_csr(p); pre_s = time.perf_counter() - t0
        for s, g in pairs:
            r = dijkstra_csgraph(p, s, g, graph=G); costs.append(r["cost"]); expanded.append(r["expanded"])
    elif alg == "alt":
        lm = Landmarks(p, k=int(j.get("landmarks", 4))); pre_s = time.perf_counter() - t0
        for s, g in pairs:
            r = astar_alt(p, s, g, lm); costs.append(r["cost"]); expanded.append(r["expanded"])
    elif alg == "alt_c":
        from corridor import cgrid
        lm = cgrid.CLandmarks(p, k=int(j.get("landmarks", 4)), threads=int(j.get("threads", 8))); pre_s = time.perf_counter() - t0
        for s, g in pairs:
            r = cgrid.alt_c(p, s, g, lm); costs.append(r["cost"]); expanded.append(r["expanded"])
    elif alg == "dijkstra_c":
        from corridor import cgrid
        for s, g in pairs:
            r = cgrid.dijkstra_c(p, s, g); costs.append(r["cost"]); expanded.append(r["expanded"])
    else:
        for s, g in pairs:
            r = astar_py(p, s, g); costs.append(r["cost"]); expanded.append(r["expanded"])
    total = time.perf_counter() - t0
    return {"compute_s": total, "pre_s": pre_s, "per_query_s": (total - pre_s) / q, "queries": q,
            "mean_expanded": float(np.mean(expanded)), "graph_nodes": p.W * p.H, "cost_sum": float(sum(costs))}


def job_exposure(j):
    size = int(j["dem_id"]); n = int(j["radar_count"])
    dem = DEM(dem_path(size))
    sites = sites_for(dem, size, n)
    t = time.perf_counter()
    E, _ = exposure(dem, sites)
    return {"compute_s": time.perf_counter() - t, "exposed_frac": float((E > 0).mean())}


if __name__ == "__main__":
    child_main({"solve": job_solve, "exposure": job_exposure, "multi_query": job_multi_query})
