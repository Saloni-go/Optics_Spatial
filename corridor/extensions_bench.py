"""Track 3 - experiments for the extensions (after the interactive framework).

    run.bat -m corridor.extensions_bench bank        E7  alpha bank: instant alpha slider
    run.bat -m corridor.extensions_bench par         E8  parallel cost-to-go field (delta-stepping, OpenMP)
    run.bat -m corridor.extensions_bench csp         E9  exact risk budget (LARAC + coarse label setting)
    run.bat -m corridor.extensions_bench tiles       E10 tile overlay (CRP-style customizable precompute)
    run.bat -m corridor.extensions_bench altitude    E11 3-D routing: altitude as a decision
    run.bat -m corridor.extensions_bench placement   E12 radar placement game (defender vs router)
    run.bat -m corridor.extensions_bench uncertain   E13 uncertain radar positions
    run.bat -m corridor.extensions_bench alternatives E14 distinct alternative corridors
    run.bat -m corridor.extensions_bench montecarlo  E15 detection model: Monte Carlo + sensitivity
    run.bat -m corridor.extensions_bench figs

Results: results/corridor/extensions/*.json and fig_*.png.
"""
import json
import math
import os
import sys
import time

import numpy as np

from common.config import RESULTS
from corridor import cgrid
from corridor.optimizer import Problem, evaluate
from corridor.prep import problem, endpoints

OUT = RESULTS / "corridor" / "extensions"
SIZE = 4000


def dump(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(obj, open(OUT / f"{name}.json", "w"), indent=1, default=float)
    print("wrote", OUT / f"{name}.json")


def load(name):
    return json.load(open(OUT / f"{name}.json"))


def free_starts(blocked, n, rng, ref=None, min_sep=0):
    free = np.argwhere(~blocked)
    out = []
    while len(out) < n:
        a = free[rng.integers(len(free))]
        if ref is None or np.hypot(a[0] - ref[0], a[1] - ref[1]) >= min_sep:
            out.append((int(a[0]), int(a[1])))
    return out


# ---------------------------------------------------------------- E7 alpha bank
def bank(size=SIZE):
    from corridor.interactive_core import AlphaBank
    p, dem = problem(size)
    s0, g = endpoints(p.blocked)
    rng = np.random.default_rng(3)
    starts = [s0] + free_starts(p.blocked, 9, rng, g, 0.3 * size)
    ladders = {"5 alphas": (2, 5, 10, 20, 50), "11 alphas": (1, 2, 3, 5, 7, 10, 14, 20, 30, 50, 100)}
    out = {"size": size, "ladders": {}, "tests": []}
    banks = {}
    for name, al in ladders.items():
        b = AlphaBank(p, g, al, threads=6)
        banks[name] = b
        out["ladders"][name] = {"alphas": list(al), "build_s": b.pre_s, "mem_mb": b.mem_mb}
        print(name, out["ladders"][name])
    # serial build for the parallel speed-up
    b1 = AlphaBank(p, g, ladders["5 alphas"], threads=1)
    out["ladders"]["5 alphas"]["build_serial_s"] = b1.pre_s
    del b1
    for a in (1, 2, 3, 5, 7, 10, 14, 20, 30, 50, 70, 100):
        p.alpha = float(a)
        exact = cgrid.CostToGo(p, g)
        row = {"alpha": a, "exact_field_s": exact.pre_s}
        for name, b in banks.items():
            gaps, ts = [], []
            for s in starts:
                t = time.perf_counter()
                path, cost, used = b.route(s, a)
                ts.append(time.perf_counter() - t)
                gaps.append(100 * (cost / exact.dist[p.idx(s)] - 1))
            row[name] = {"used": used, "gap_mean": float(np.mean(gaps)), "gap_max": float(np.max(gaps)),
                         "lookup_ms": 1000 * float(np.median(ts))}
        out["tests"].append(row); print(row)
        del exact
    p.alpha = 10.0
    dump("e7_bank", out)


# ---------------------------------------------------------------- E8 parallel field (delta-stepping)
def par():
    out = {"scaling": [], "delta": [], "bank": None, "repair_vs_rebuild": []}
    for size in (1000, 2000, 4000):
        p, dem = problem(size)
        s, g = endpoints(p.blocked)
        ser = [cgrid.CostToGo(p, g) for _ in range(3)]
        ref = ser[0]; fin = np.isfinite(ref.dist)
        row = {"size": size, "nodes": p.H * p.W, "dijkstra_s": float(np.median([c.pre_s for c in ser])), "threads": {}}
        del ser
        for th in (1, 2, 4, 8, 12, 16, 24):
            cs = [cgrid.CostToGo(p, g, threads=th) for _ in range(3)]
            err = max(float(np.abs(c.dist[fin] - ref.dist[fin]).max()) for c in cs)
            row["threads"][th] = {"s": float(np.median([c.pre_s for c in cs])), "max_err": err,
                                  "relax_per_edge": cs[0].relaxations / (8 * fin.sum()), "phases": cs[0].phases}
            print(size, th, row["threads"][th]); del cs
        out["scaling"].append(row)
        if size == 4000:
            for k in (1, 4, 16, 64, 256):
                cs = [cgrid.CostToGo(p, g, threads=12, delta=k * p.cell) for _ in range(3)]
                out["delta"].append({"delta_cells": k, "s": float(np.median([c.pre_s for c in cs])),
                                     "relax_per_edge": cs[0].relaxations / (8 * fin.sum()), "phases": cs[0].phases})
                print("delta", out["delta"][-1]); del cs
            from corridor.interactive_core import AlphaBank
            b = AlphaBank(p, g, (2, 5, 10, 20, 50))
            out["bank"] = {"alphas": b.alphas, "build_s": b.pre_s, "mem_mb": b.mem_mb}
            print("bank", out["bank"])
        del ref
    # incremental repair vs parallel rebuild after radar edits (same events as E3)
    from corridor.interactive_core import Planner
    from corridor.interactive_bench import _move_target
    rng = np.random.default_rng(11)
    P = Planner(4000, "exposure")
    P.ctg = cgrid.CostToGo(P.p, P.goal)
    for dist in (1000, 5000, 10000, 20000, 5000, 10000):
        i = int(rng.integers(len(P.field.sites)))
        x, y = _move_target(P.field, P.dem, i, dist, rng)
        changed, tf = P.field.move(i, x, y)
        cgrid.set_exposure(P.p, P.field.E)
        rep = P.ctg.repair(changed)
        fresh = cgrid.CostToGo(P.p, P.goal, threads=12)
        fin = np.isfinite(fresh.dist)
        out["repair_vs_rebuild"].append({"move_km": dist / 1000, "changed_frac": float((changed > 0).mean()),
                                         "field_update_s": tf, "repair_s": rep["repair_s"], "parallel_rebuild_s": fresh.pre_s,
                                         "max_err": float(np.abs(P.ctg.dist[fin] - fresh.dist[fin]).max())})
        print(out["repair_vs_rebuild"][-1])
    dump("e8_parallel", out)


# ---------------------------------------------------------------- E9 exact risk budget
def _detection_problem(size):
    from common.config import dem_path
    from common.dem_utils import DEM
    from corridor.exposure import blocked_mask
    from corridor.prep import sites_for
    from corridor.radarfield import RadarField
    from corridor.interactive_core import scenario_endpoints
    dem = DEM(dem_path(size))
    F = RadarField(dem, sites_for(dem, size, 6), "detection")
    blk = blocked_mask(dem)
    s, g = scenario_endpoints(dem, size, blk)
    return Problem(dem.z, F.E, blk, dem.cell, 0.0, 2.0), F, s, g


def csp():
    from corridor.riskcsp import RiskCSP, budget_units, p_of
    out = {"scenario": [], "validation": []}
    # validation (1000 map; budgets relative to the least possible risk there, since every small-map
    # route is almost surely detected): corridor answer vs the exact search over the whole map
    p, F, s, g = _detection_problem(1000)
    C = RiskCSP(p, g); C.bounds()
    if os.environ.get("SKIP_VALIDATION"):
        p = None
    for f in ((2.0, 1.5, 1.2, 1.05) if p is not None else ()):
        Rmin = float(C.hR[p.idx(s)])
        pm = p_of(Rmin * f)
        r = C.query(s, pm)
        if r.get("path") is None:
            continue
        whole = C.exact(s, budget_units(pm), r["larac_L"], [list(range(p.H * p.W))], width_cells=0)
        out["validation"].append({"budget_x_Rmin": f, "larac_L": r["larac_L"], "corridor_L": r["L"], "LB": r["LB"],
                                  "whole_map_L": whole.get("L", r["larac_L"]), "whole_map_status": whole["status"],
                                  "whole_map_labels": whole["labels"], "corridor_labels": r.get("labels"),
                                  "larac_gap_pct": r["larac_gap_pct"], "gap_pct": r["gap_pct"],
                                  "larac_s": r["larac_s"], "exact_s": r.get("exact_s")})
        print("validation", out["validation"][-1])
    # scenario on 16 M cells
    p, F, s, g = _detection_problem(SIZE)
    C = RiskCSP(p, g)
    t = time.perf_counter(); C.bounds(); tb = time.perf_counter() - t
    out["bounds_s"] = tb
    try:
        old = {r["p_max"]: r for r in json.load(open(RESULTS / "corridor" / "interactive" / "e5b_risk_budget.json"))["runs"]}
    except FileNotFoundError:
        old = {}
    for pm in (0.9, 0.75, 0.5, 0.35, 0.25):
        # 16 M cells: narrower corridor (+/-450 m), 1 % risk resolution, 8 M label cap (~1 min worst case)
        r = C.query(s, pm, width_cells=15, resolution=1e-2, max_labels=8_000_000)
        r.pop("path", None)
        o = old.get(pm, {})
        r.update({"bisection_length_km": o.get("length_km"), "bisection_p": o.get("p_detect"),
                  "bisection_solves": o.get("solves"), "bisection_s": o.get("seconds")})
        out["scenario"].append(r)
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    dump("e9_csp", out)


# ---------------------------------------------------------------- E10 tile overlay (CRP-style)
def tiles():
    from corridor.tiles import TileOverlay
    from corridor.interactive_core import Planner
    from corridor.interactive_bench import _move_target
    P = Planner(SIZE, "exposure")
    p = P.p
    rng = np.random.default_rng(21)
    free = np.argwhere(~p.blocked)
    pairs = []
    while len(pairs) < 20:
        a, b = free[rng.integers(len(free))], free[rng.integers(len(free))]
        if np.hypot(*(a - b)) > 0.3 * SIZE:
            pairs.append(((int(a[0]), int(a[1])), (int(b[0]), int(b[1]))))
    exact = [float(cgrid.CostToGo(p, g, threads=cgrid.THREADS).dist[p.idx(s)]) for s, g in pairs]
    lm = cgrid.CLandmarks(p, 4)
    alt_s = [cgrid.alt_c(p, s, g, lm)["solve_s"] for s, g in pairs]
    out = {"size": SIZE, "alt_pre_s": lm.pre_s, "alt_query_s": float(np.median(alt_s)), "variants": [], "updates": []}
    del lm
    for spacing, val in ((25, 0), (10, 0), (25, 10), (50, 5)):
        T = TileOverlay(p, 250, spacing, valleys=val)
        q = [T.query(s, g) for s, g in pairs]
        gaps = [100 * (r["cost"] / e - 1) for r, e in zip(q, exact)]
        chk = [abs(evaluate(p, r["path"])["cost"] / r["cost"] - 1) for r in q[:5]]
        row = {"spacing": spacing, "valleys": val, "tile": 250, "portals": len(T.cells), "edges": T.edges, "pre_s": T.pre_s,
               "mem_mb": T.mem_mb, "query_ms": 1000 * float(np.median([r["query_s"] for r in q])),
               "unpack_ms": 1000 * float(np.median([r["unpack_s"] for r in q])),
               "gap_mean": float(np.mean(gaps)), "gap_max": float(np.max(gaps)), "unpack_check": float(max(chk))}
        out["variants"].append(row); print(row)
        if (spacing, val) == (25, 10):
            keep = T
        else:
            del T
    # radar edits: recompute only touched tiles
    T = keep
    for dist in (1000, 5000, 10000, 20000):
        i = int(rng.integers(len(P.field.sites)))
        x, y = _move_target(P.field, P.dem, i, dist, rng)
        changed, tf = P.field.move(i, x, y)
        cgrid.set_exposure(p, P.field.E)
        u = T.update(changed)
        g2 = [100 * (T.query(s, g, unpack=False)["cost"] /
                     float(cgrid.CostToGo(p, g, threads=cgrid.THREADS).dist[p.idx(s)]) - 1) for s, g in pairs[:5]]
        t = time.perf_counter(); lm = cgrid.CLandmarks(p, 4); t_lm = time.perf_counter() - t; del lm
        f = cgrid.CostToGo(p, pairs[0][1], threads=cgrid.THREADS)
        row = {"move_km": dist / 1000, "changed_frac": float((changed > 0).mean()), "field_update_s": tf,
               "tiles": u["tiles"], "of": u["of"], "overlay_update_s": u["update_s"], "gap_after_mean": float(np.mean(g2)),
               "landmarks_rebuild_s": t_lm, "field_rebuild_s": f.pre_s}
        out["updates"].append(row); print(row)
    dump("e10_tiles", out)


# ---------------------------------------------------------------- E11 3-D routing (altitude)
def altitude(size=2000):
    from common.config import dem_path
    from common.dem_utils import DEM
    from corridor.altitude import Layered
    from corridor.exposure import blocked_mask
    from corridor.prep import sites_for
    from corridor.interactive_core import scenario_endpoints
    out = {"size": size, "runs": [], "fixed": [], "timing": []}
    dem = DEM(dem_path(size))
    sites = sites_for(dem, size, 6)
    s, g = scenario_endpoints(dem, size, blocked_mask(dem))
    A = Layered(dem, sites, "detection")
    out["prep_s"], out["levels"], out["gamma"] = A.prep_s, A.levels, A.gamma
    for l, a in enumerate(A.levels):                       # fixed height (the old model at 150 m)
        f = A.field(g, 1.0, only=[l]); path, cost = A.route(f, s, l)
        if path:
            d = A.describe(path); d.update({"agl": a, "cost": cost}); out["fixed"].append(d); print("fixed", d)
    for gs in (0.0, 0.5, 1.0, 2.0, 4.0):
        f = A.field(g, gs); path, cost = A.route(f, s)
        d = A.describe(path); d.update({"gamma_scale": gs, "cost": cost, "field_s": f["s"]})
        if gs == 1.0:
            step = max(1, len(path) // 2000)
            d["path_sample"] = [int(v) for v in path[::step]]
        out["runs"].append(d); print("free", {k: v for k, v in d.items() if k != "path_sample"})
    out["timing"].append({"size": size, "nodes": len(A.levels) * A.N, "s": f["s"], "mem_mb": f["mem_mb"]})
    del A, f
    big = DEM(dem_path(4000))
    B = Layered(big, sites_for(big, 4000, 6), "detection")
    s4, g4 = scenario_endpoints(big, 4000, blocked_mask(big))
    f = B.field(g4, 1.0)
    path, cost = B.route(f, s4)
    d = B.describe(path)
    out["timing"].append({"size": 4000, "nodes": len(B.levels) * B.N, "s": f["s"], "mem_mb": f["mem_mb"], "prep_s": B.prep_s,
                          "p_detect": d["p_detect"], "per_level_km": d["per_level_km"]})
    f1 = B.field(g4, 1.0, only=[1]); p1, c1 = B.route(f1, s4, 1)
    out["timing"][-1]["p_detect_fixed150"] = B.describe(p1)["p_detect"]
    print("4000", out["timing"][-1])
    dump("e11_altitude", out)


# ---------------------------------------------------------------- E12 radar placement game
def _snap(blocked, r, c):
    free = np.argwhere(~blocked)
    k = int(np.argmin(np.hypot(free[:, 0] - r, free[:, 1] - c)))
    return int(free[k, 0]), int(free[k, 1])


def placement(size=2000, K=6, n_random=30):
    from common.config import dem_path
    from common.dem_utils import DEM
    from corridor.exposure import blocked_mask
    from corridor.placement import Game, candidate_peaks
    from corridor.prep import sites_for
    dem = DEM(dem_path(size))
    blk = blocked_mask(dem)
    s, g = endpoints(blk)
    H, W = blk.shape
    entries = [s, _snap(blk, H // 2, int(0.05 * W)), _snap(blk, int(0.95 * H), W // 2)]
    cands = candidate_peaks(dem, 40)
    hand = []
    for x, y in sites_for(dem, size, K):
        c, r = dem.to_pixel(x, y); hand.append((int(round(r)), int(round(c))))
    G = Game(dem, blk, entries, g, cands + hand)
    hand_idx = list(range(len(cands), len(cands) + len(hand)))
    nc = len(cands)
    G.cands = cands                                       # greedy / coverage choose among the peaks only
    sel, trace, t_greedy = G.greedy(K)
    cov = G.coverage_greedy(K)
    def score(sel_):
        pd, k, path = G.attacker(sel_)
        return pd, k, path
    out = {"size": size, "K": K, "entries": entries, "goal": g, "candidates": cands, "prep_s": G.prep_s,
           "greedy": {"sites": [cands[i] for i in sel], "curve": trace, "s": t_greedy}}
    cov_curve = [score(cov[:k + 1])[0] for k in range(K)]
    out["coverage"] = {"sites": [cands[i] for i in cov], "curve": cov_curve}
    pd_h, k_h, path_h = score(hand_idx)
    out["hand"] = {"sites": hand, "p_detect": pd_h, "entry": k_h}
    rng = np.random.default_rng(5)
    out["random"] = [score(list(rng.choice(nc, K, replace=False)))[0] for _ in range(n_random)]
    # coverage (area seen) of each placement, for the comparison
    def area(sel_):
        seen = np.zeros(blk.shape, bool)
        for i in sel_:
            r0, c0, a_ = G.contrib[i]; seen[r0:r0 + a_.shape[0], c0:c0 + a_.shape[1]] |= a_ > 0
        return float(seen.mean())
    out["greedy"]["area"] = area(sel); out["coverage"]["area"] = area(cov); out["hand"]["area"] = area(hand_idx)
    for name, sl in (("greedy", sel), ("coverage", cov), ("hand", hand_idx)):
        pd, k, path = score(sl)
        out[name]["route"] = [int(v) for v in path[::max(1, len(path) // 1500)]]
        out[name]["entry"] = k
    out["evals"] = G.evals
    print({k: v for k, v in out.items() if k not in ("candidates",)} if False else
          {"greedy": out["greedy"]["curve"], "coverage": out["coverage"]["curve"], "hand": pd_h,
           "random_median": float(np.median(out["random"])), "random_max": float(np.max(out["random"])), "evals": G.evals})
    dump("e12_placement", out)


# ---------------------------------------------------------------- E13 uncertain radar positions
def uncertain(size=2000, S_plan=16, S_test=40):
    from common.config import dem_path
    from common.dem_utils import DEM
    from corridor.exposure import blocked_mask
    from corridor.prep import sites_for
    from corridor import uncertainty as U
    dem = DEM(dem_path(size)); blk = blocked_mask(dem)
    s, g = endpoints(blk)
    sites = sites_for(dem, size, 6)
    out = {"size": size, "runs": []}
    for sigma in (1000.0, 3000.0):
        rng = np.random.default_rng(int(sigma))
        Hs = [U.hazard(dem, U.sample_sites(sites, sigma, rng, dem)) for _ in range(S_plan)]
        Ht = [U.hazard(dem, U.sample_sites(sites, sigma, rng, dem)) for _ in range(S_test)]
        H0 = U.hazard(dem, sites)
        stack = np.stack(Hs)
        surfaces = {"nominal": H0, "expected": stack.mean(axis=0), "envelope q90": np.quantile(stack, 0.9, axis=0)}
        del stack
        row = {"sigma_m": sigma, "routes": {}}
        for name, H in surfaces.items():
            path, L = U.plan(dem, blk, np.ascontiguousarray(H), s, g)
            ps = np.array([U.p_detect(Hx, path, dem.shape[1], dem.cell) for Hx in Ht])
            q0 = Problem(dem.z, H0, blk, dem.cell, 0.0, 2.0)
            Lc = evaluate(q0, path)["cost"]                       # length + beta x climb
            J = Lc + 10.0 * 1000.0 * -np.log(np.clip(1 - ps, 1e-300, 1))   # planner objective, alpha = 10
            row["routes"][name] = {"length_km": L, "J_mean": float(J.mean()), "J_p90": float(np.quantile(J, 0.9)),
                                   "p_mean": float(ps.mean()), "p_p90": float(np.quantile(ps, 0.9)),
                                   "p_max": float(ps.max()), "p_nominal_world": U.p_detect(H0, path, dem.shape[1], dem.cell)}
            print(sigma, name, row["routes"][name])
        out["runs"].append(row)
    dump("e13_uncertain", out)


# ---------------------------------------------------------------- E14 alternative corridors
def alternatives():
    from corridor.alternatives import via_routes, penalty_routes, overlap
    from corridor.interactive_core import Planner
    P = Planner(SIZE, "exposure")
    p, s, g = P.p, P.start, P.goal
    out = {"size": SIZE}
    shape = (p.H, p.W)
    for name, fn in (("via-node", via_routes), ("penalty", penalty_routes)):
        routes, info = fn(p, s, g, k=3)
        base = evaluate(p, routes[0]["path"])["cost"]
        rows = []
        for i, r in enumerate(routes):
            ev = evaluate(p, r["path"])
            rows.append({"stretch_pct": 100 * (ev["cost"] / base - 1), "length_km": ev["length_km"],
                         "exposure_km": ev["exposure_km"],
                         "max_overlap": max([overlap(r["path"], q["path"], shape) for j, q in enumerate(routes) if j != i] or [0]),
                         "path": [int(v) for v in r["path"][::max(1, len(r["path"]) // 1500)]]})
        out[name] = {"info": info, "routes": rows}
        print(name, info, [{k: round(v, 3) for k, v in r.items() if k != "path"} for r in rows])
    dump("e14_alternatives", out)


# ---------------------------------------------------------------- E15 detection model: Monte Carlo + sensitivity
def montecarlo(size=2000, flights=200_000):
    from common.config import dem_path
    from common.dem_utils import DEM
    from corridor.exposure import blocked_mask
    from corridor.prep import sites_for
    from corridor.radarfield import RadarField, P_MAX, D50
    dem = DEM(dem_path(size)); blk = blocked_mask(dem)
    s, g = endpoints(blk)
    sites = sites_for(dem, size, 6)
    W, cell = dem.shape[1], dem.cell
    rng = np.random.default_rng(9)
    out = {"size": size, "flights": flights, "routes": [], "sensitivity": []}

    def per_radar_R(F, path):
        rc = np.array([divmod(i, W) for i in path])
        seg = np.hypot(*np.diff(rc, axis=0).T) * cell / 1000
        Rs = []
        for r0, c0, a in F.contrib:
            rr, cc = rc[:, 0] - r0, rc[:, 1] - c0
            ok = (rr >= 0) & (rr < a.shape[0]) & (cc >= 0) & (cc < a.shape[1])
            h = np.zeros(len(rc)); h[ok] = a[rr[ok], cc[ok]]
            Rs.append(seg * 0.5 * (h[1:] + h[:-1]))
        return np.array(Rs)                                  # radars x segments
    F = RadarField(dem, sites, "detection")
    for a in (0, 5, 10, 20, 50, 100):
        p = Problem(dem.z, F.E, blk, cell, float(a), 2.0)
        f = cgrid.CostToGo(p, g, threads=cgrid.THREADS)
        path, _ = f.route(s)
        R = per_radar_R(F, path)
        # Monte Carlo: segments merged into 100 chunks; each radar detects in a chunk with prob 1-exp(-R_chunk)
        chunks = np.array_split(np.arange(R.shape[1]), 100)
        q = np.array([[1 - np.exp(-R[r, c].sum()) for c in chunks] for r in range(R.shape[0])])   # radars x chunks
        det = 0
        for _ in range(flights // 20000):
            u = rng.random((20000,) + q.shape)
            det += int((u < q).any(axis=(1, 2)).sum())
        p_mc = det / flights
        Rr = R.sum(axis=1)
        p_ind = 1 - math.exp(-Rr.sum())
        p_corr = 1 - float(np.prod(1 / (1 + Rr)))              # per-radar exponential target fluctuation
        row = {"alpha": a, "length_km": evaluate(p, path)["length_km"], "p_analytic": p_ind, "p_mc": p_mc,
               "mc_ci95": 1.96 * math.sqrt(max(p_mc * (1 - p_mc), 1e-12) / flights), "p_fluctuating": p_corr}
        out["routes"].append(row); print(row)
    # sensitivity to the model parameters: nominal route vs route re-optimised for each parameter set
    p0 = Problem(dem.z, F.E, blk, cell, 10.0, 2.0)
    nominal, _ = cgrid.CostToGo(p0, g, threads=cgrid.THREADS).route(s)
    from corridor.alternatives import overlap
    for pm in (0.25, 0.5, 0.75):
        for d50 in (10000.0, 20000.0, 30000.0):
            Fx = RadarField(dem, sites, "detection", p_max=pm, d50=d50)
            px = Problem(dem.z, Fx.E, blk, cell, 10.0, 2.0)
            re, _ = cgrid.CostToGo(px, g, threads=cgrid.THREADS).route(s)
            pn = 1 - math.exp(-per_radar_R(Fx, nominal).sum()); pr = 1 - math.exp(-per_radar_R(Fx, re).sum())
            Jn, Jr = evaluate(px, nominal)["cost"], evaluate(px, re)["cost"]
            row = {"p_max": pm, "d50_km": d50 / 1000, "p_nominal_route": pn, "p_reoptimised": pr,
                   "regret_pct": 100 * (Jn / Jr - 1), "overlap": overlap(re, nominal, dem.shape, 10),
                   "len_nominal": evaluate(px, nominal)["length_km"], "len_reopt": evaluate(px, re)["length_km"]}
            out["sensitivity"].append(row); print(row)
    dump("e15_montecarlo", out)


STEPS = {"bank": bank, "par": par, "csp": csp, "tiles": tiles, "altitude": altitude, "placement": placement,
         "uncertain": uncertain, "alternatives": alternatives, "montecarlo": montecarlo}


def figs():
    from common.plots import plt, save
    try:
        e = load("e7_bank")
        fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
        for name, c in (("5 alphas", "#457b9d"), ("11 alphas", "#e76f51")):
            T = e["tests"]
            a = [t["alpha"] for t in T]
            axs[0].plot(a, [max(t[name]["gap_mean"], 1e-4) for t in T], "o-", c=c, label=f"{name}: mean over 10 starts")
            axs[0].plot(a, [max(t[name]["gap_max"], 1e-4) for t in T], "x:", c=c, label=f"{name}: worst start")
            for al in e["ladders"][name]["alphas"]:
                axs[0].axvline(al, c=c, lw=0.4, alpha=0.4)
        axs[0].set_xscale("log"); axs[0].set_yscale("log")
        axs[0].set_xlabel("alpha requested by the slider"); axs[0].set_ylabel("cost above exact (%; 0 at 1e-4)")
        axs[0].set_title("Route shown instantly = nearest banked alpha", fontsize=9); axs[0].legend(fontsize=7, frameon=False)
        L = e["ladders"]
        names = list(L)
        axs[1].bar(np.arange(len(names)) - 0.2, [L[n]["build_s"] for n in names], 0.4, label="build time (s, 6 threads)")
        axs[1].bar(np.arange(len(names)) + 0.2, [L[n]["mem_mb"] / 100 for n in names], 0.4, label="memory (100 MB)")
        if "build_serial_s" in L["5 alphas"]:
            axs[1].scatter([-0.2], [L["5 alphas"]["build_serial_s"]], marker="_", s=600, c="k", label="5 alphas, 1 thread")
        axs[1].set_xticks(range(len(names))); axs[1].set_xticklabels(names)
        axs[1].set_title("Cost of the bank (16 M cells)", fontsize=9); axs[1].legend(fontsize=7, frameon=False)
        save(fig, OUT / "fig_e7_bank.png")
    except FileNotFoundError:
        pass
    try:
        e = load("e8_parallel")
        fig, axs = plt.subplots(1, 3, figsize=(14, 3.8))
        for row, c in zip(e["scaling"], ("#2a9d8f", "#457b9d", "#8338ec")):
            th = sorted(int(k) for k in row["threads"])
            t = [row["threads"][str(k)]["s"] if str(k) in row["threads"] else row["threads"][k]["s"] for k in th]
            axs[0].plot(th, [row["dijkstra_s"] / x for x in t], "o-", c=c, label=f"{row['nodes'] / 1e6:.0f} M cells")
        axs[0].plot([1, 12], [1, 12], "k:", lw=0.8, label="ideal")
        axs[0].axvline(12, c="grey", lw=0.6, ls="--")
        axs[0].set_xlabel("threads (12 physical cores, 24 logical)"); axs[0].set_ylabel("speed-up over serial Dijkstra")
        axs[0].set_title("Parallel cost-to-go field (exact)", fontsize=9); axs[0].legend(fontsize=7, frameon=False)
        d = e["delta"]
        axs[1].plot([r["delta_cells"] for r in d], [r["s"] for r in d], "o-", c="#e76f51", label="time (s)")
        ax2 = axs[1].twinx()
        ax2.plot([r["delta_cells"] for r in d], [r["relax_per_edge"] for r in d], "s--", c="#264653", label="relaxations per edge")
        axs[1].set_xscale("log"); axs[1].set_xlabel("bucket width delta (cells of cost)"); axs[1].set_ylabel("seconds, 12 threads, 16 M cells")
        ax2.set_ylabel("relaxations per edge"); axs[1].set_title("Bucket width trade-off", fontsize=9)
        rr = e["repair_vs_rebuild"]
        x = np.arange(len(rr))
        axs[2].bar(x - 0.2, [r["repair_s"] for r in rr], 0.4, label="incremental repair (1 core)")
        axs[2].bar(x + 0.2, [r["parallel_rebuild_s"] for r in rr], 0.4, label="full rebuild (12 cores)")
        axs[2].set_xticks(x); axs[2].set_xticklabels([f"{r['move_km']:g} km" for r in rr])
        axs[2].set_xlabel("radar moved by"); axs[2].set_ylabel("s"); axs[2].legend(fontsize=7, frameon=False)
        axs[2].set_title("After a radar edit (16 M cells)", fontsize=9)
        fig.subplots_adjust(wspace=0.55)
        save(fig, OUT / "fig_e8_parallel.png")
    except FileNotFoundError:
        pass
    figs_more()


def _basemap(ax, size, f=4):
    from common.config import dem_path
    from common.dem_utils import DEM
    from corridor.interactive import hillshade
    dem = DEM(dem_path(size))
    z = np.nan_to_num(dem.z[::f, ::f].astype(np.float64), nan=0.0)
    H, W = dem.shape
    ax.imshow(hillshade(z), cmap="gray", extent=(0, W, H, 0), vmin=0, vmax=1)
    ax.imshow(z, cmap="terrain", alpha=0.3, extent=(0, W, H, 0))
    ax.set_xticks([]); ax.set_yticks([])
    return dem


def figs_more():
    from common.plots import plt, save
    # E9 risk budget
    try:
        e = load("e9_csp")
        fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
        v = e["validation"]
        x = np.arange(len(v))
        axs[0].bar(x - 0.2, [r["larac_gap_pct"] for r in v], 0.4, label="LARAC route", color="#457b9d")
        axs[0].bar(x + 0.2, [r["gap_pct"] for r in v], 0.4, label="+ exact corridor search", color="#2a9d8f")
        axs[0].set_xticks(x); axs[0].set_xticklabels([f"{r['budget_x_Rmin']:g} x min risk" for r in v])
        axs[0].set_ylabel("length above the certified lower bound (%)")
        axs[0].set_title("1 M cells: exact search closes the gap (= whole-map optimum)", fontsize=9)
        axs[0].legend(fontsize=7, frameon=False)
        sc = [r for r in e["scenario"] if r.get("larac_s")]
        x = np.arange(len(sc))
        axs[1].bar(x - 0.2, [r.get("bisection_s") or 0 for r in sc], 0.4, label="bisection (before)", color="#bbbbbb")
        axs[1].bar(x + 0.2, [r["larac_s"] + (r.get("exact_s") or 0) for r in sc], 0.4, label="LARAC + exact/splice", color="#e76f51")
        ax2 = axs[1].twinx()
        ax2.plot(x, [r["gap_pct"] for r in sc], "ko-", label="certified gap (%)")
        ax2.set_ylabel("certified gap to optimum (%)")
        axs[1].set_xticks(x); axs[1].set_xticklabels([f"<= {100 * r['p_max']:.0f}%" for r in sc])
        axs[1].set_ylabel("seconds"); axs[1].set_xlabel("detection budget (16 M cells)")
        axs[1].set_title("Risk-budget query on the full map", fontsize=9); axs[1].legend(fontsize=7, frameon=False, loc="upper left")
        save(fig, OUT / "fig_e9_csp.png")
    except FileNotFoundError:
        pass
    # E10 tiles
    try:
        e = load("e10_tiles")
        fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
        for r in e["variants"]:
            lab = f"every {r['spacing']} cells" + (f" + valleys" if r["valleys"] else "")
            axs[0].scatter(r["portals"], r["gap_mean"], s=60, label=f"{lab}: {r['query_ms']:.0f} ms/query, pre {r['pre_s']:.0f} s")
            axs[0].errorbar(r["portals"], r["gap_mean"], yerr=[[0], [r["gap_max"] - r["gap_mean"]]], fmt="none", c="grey", lw=0.8)
        axs[0].set_xlabel("portals (overlay nodes)"); axs[0].set_ylabel("route cost above exact (%; bar = worst)")
        axs[0].set_title(f"Any-pair queries on 16 M cells (ALT exact: {1000 * e['alt_query_s']:.0f} ms)", fontsize=9)
        axs[0].legend(fontsize=6.5, frameon=False)
        u = e["updates"]; x = np.arange(len(u))
        axs[1].bar(x - 0.27, [r["overlay_update_s"] for r in u], 0.27, label="overlay: touched tiles only")
        axs[1].bar(x, [r["landmarks_rebuild_s"] for r in u], 0.27, label="landmarks (ALT) rebuild")
        axs[1].bar(x + 0.27, [r["field_rebuild_s"] for r in u], 0.27, label="one goal field (parallel)")
        for i, r in enumerate(u):
            axs[1].text(i - 0.27, r["overlay_update_s"], f"{r['tiles']}/{r['of']}", ha="center", va="bottom", fontsize=6)
        axs[1].set_xticks(x); axs[1].set_xticklabels([f"{r['move_km']:g} km" for r in u]); axs[1].set_xlabel("radar moved by")
        axs[1].set_ylabel("s"); axs[1].set_title("Keeping precompute valid after a radar edit", fontsize=9)
        axs[1].legend(fontsize=7, frameon=False)
        save(fig, OUT / "fig_e10_tiles.png")
    except FileNotFoundError:
        pass
    # E11 altitude
    try:
        e = load("e11_altitude")
        fig, axs = plt.subplots(1, 2, figsize=(12, 5), gridspec_kw={"width_ratios": [1.1, 1]})
        dem = _basemap(axs[0], e["size"], 2)
        run = [r for r in e["runs"] if "path_sample" in r][0]
        N = dem.shape[0] * dem.shape[1]; W = dem.shape[1]
        ps = np.array(run["path_sample"]); lv = ps // N; cc = ps % N
        cols = ["#2a9d8f", "#e9c46a", "#f4a261", "#e63946"]
        for l, a in enumerate(e["levels"]):
            m = lv == l
            axs[0].scatter((cc % W)[m], (cc // W)[m], s=3, c=cols[l], label=f"{a:.0f} m above ground")
        axs[0].legend(fontsize=7, markerscale=4, loc="lower left"); axs[0].set_title("Free-altitude route (detection model)", fontsize=9)
        rows = [(f"fixed {r['agl']:.0f} m", r) for r in e["fixed"]] + [(f"free, gamma x{r['gamma_scale']:g}", r) for r in e["runs"]]
        y = np.arange(len(rows)); left = np.zeros(len(rows))
        for l, a in enumerate(e["levels"]):
            v = np.array([r["per_level_km"][f"{int(a)} m"] for _, r in rows])
            axs[1].barh(y, v, left=left, color=cols[l]); left += v
        for i, (_, r) in enumerate(rows):
            axs[1].text(left[i] + 1, i, f"P(detect) {100 * r['p_detect']:.1f}%", va="center", fontsize=7)
        axs[1].set_yticks(y); axs[1].set_yticklabels([n for n, _ in rows], fontsize=8); axs[1].invert_yaxis()
        axs[1].set_xlabel("km flown at each height"); axs[1].set_xlim(0, left.max() * 1.35)
        axs[1].set_title("Height use and detection risk", fontsize=9)
        save(fig, OUT / "fig_e11_altitude.png")
    except FileNotFoundError:
        pass
    # E12 placement
    try:
        e = load("e12_placement")
        fig, axs = plt.subplots(1, 2, figsize=(12, 5), gridspec_kw={"width_ratios": [1, 1.1]})
        k = np.arange(1, e["K"] + 1)
        axs[0].plot(k, [100 * v for v in e["greedy"]["curve"]], "o-", c="#e63946", label="routing-aware greedy")
        axs[0].plot(k, [100 * v for v in e["coverage"]["curve"]], "s-", c="#457b9d", label="coverage greedy (area seen)")
        axs[0].scatter([e["K"]], [100 * e["hand"]["p_detect"]], marker="*", s=160, c="#2a9d8f", zorder=5, label="hand-placed (scenario)")
        axs[0].boxplot([[100 * v for v in e["random"]]], positions=[e["K"] + 0.4], widths=0.3)
        axs[0].set_xlim(0.5, e["K"] + 0.9)
        axs[0].set_xticks(list(k) + [e["K"] + 0.4]); axs[0].set_xticklabels([str(i) for i in k] + ["random"])
        axs[0].set_xlabel("radars placed"); axs[0].set_ylabel("attacker's best-route P(detect) (%)")
        axs[0].set_title("Defender's score (box: random placements)", fontsize=9); axs[0].legend(fontsize=7, frameon=False)
        dem = _basemap(axs[1], e["size"], 2)
        W = dem.shape[1]
        for name, c, mk in (("greedy", "#e63946", "^"), ("coverage", "#457b9d", "s")):
            st = np.array(e[name]["sites"]); rt = np.array(e[name]["route"])
            axs[1].scatter(st[:, 1], st[:, 0], marker=mk, s=70, c=c, edgecolors="white", zorder=5, label=f"{name} radars")
            axs[1].plot(rt % W, rt // W, c=c, lw=1.6)
        for r, c in e["entries"]:
            axs[1].scatter(c, r, marker="o", s=40, c="white", edgecolors="k", zorder=6)
        axs[1].scatter(e["goal"][1], e["goal"][0], marker="*", s=180, c="#ffd60a", edgecolors="k", zorder=6)
        axs[1].legend(fontsize=7, loc="lower left"); axs[1].set_title("Radars and the attacker's reply", fontsize=9)
        save(fig, OUT / "fig_e12_placement.png")
    except FileNotFoundError:
        pass
    # E13 uncertainty
    try:
        e = load("e13_uncertain")
        fig, axs = plt.subplots(1, 2 * len(e["runs"]), figsize=(14, 3.6))
        for i, run in enumerate(e["runs"]):
            names = list(run["routes"]); x = np.arange(len(names))
            ax = axs[2 * i]
            for j, (key, lab) in enumerate((("p_mean", "mean"), ("p_p90", "90th pct"), ("p_max", "worst"))):
                ax.bar(x + (j - 1) * 0.25, [100 * run["routes"][n][key] for n in names], 0.25, label=lab)
            ax.set_xticks(x)
            ax.set_xticklabels([n + chr(10) + f"{run['routes'][n]['length_km']:.0f} km" for n in names], fontsize=7)
            ax.set_title(f"+/- {run['sigma_m'] / 1000:g} km: P(detect), unseen scenarios", fontsize=8)
            ax.set_ylabel("%"); ax.legend(fontsize=6, frameon=False)
            ax = axs[2 * i + 1]
            ax.bar(x - 0.2, [run["routes"][n]["J_mean"] / 1000 for n in names], 0.4, label="mean", color="#457b9d")
            ax.bar(x + 0.2, [run["routes"][n]["J_p90"] / 1000 for n in names], 0.4, label="90th pct", color="#e76f51")
            ax.set_xticks(x); ax.set_xticklabels(names, fontsize=7); ax.legend(fontsize=6, frameon=False)
            ax.set_title(f"+/- {run['sigma_m'] / 1000:g} km: planner objective (thousands)", fontsize=8)
        save(fig, OUT / "fig_e13_uncertain.png")
    except FileNotFoundError:
        pass
    # E14 alternatives
    try:
        e = load("e14_alternatives")
        fig, axs = plt.subplots(1, 2, figsize=(12, 5.4))
        for ax, name in zip(axs, ("via-node", "penalty")):
            dem = _basemap(ax, e["size"], 4); W = dem.shape[1]
            for i, (r, c) in enumerate(zip(e[name]["routes"], ("#00e5ff", "#ff006e", "#ffbe0b", "#8338ec"))):
                pth = np.array(r["path"])
                ax.plot(pth % W, pth // W, c=c, lw=2 if i == 0 else 1.5,
                        label=f"{'best' if i == 0 else f'alt {i}'}: +{r['stretch_pct']:.1f}% cost, overlap {100 * r['max_overlap']:.0f}%")
            ax.legend(fontsize=7, loc="lower left")
            ax.set_title(f"{name} ({e[name]['info']['total_s']:.1f} s)", fontsize=9)
        save(fig, OUT / "fig_e14_alternatives.png")
    except FileNotFoundError:
        pass
    # E15 Monte Carlo + sensitivity
    try:
        e = load("e15_montecarlo")
        fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
        rr = e["routes"]
        axs[0].errorbar([100 * r["p_analytic"] for r in rr], [100 * r["p_mc"] for r in rr],
                        yerr=[100 * r["mc_ci95"] for r in rr], fmt="o", c="#2a9d8f", label=f"simulated ({e['flights']:,} flights)")
        axs[0].scatter([100 * r["p_analytic"] for r in rr], [100 * r["p_fluctuating"] for r in rr], marker="x", c="#e63946",
                       label="fluctuating-target model")
        axs[0].plot([0, 100], [0, 100], "k:", lw=0.8)
        axs[0].set_xlabel("P(detect) from the formula (%)"); axs[0].set_ylabel("P(detect) (%)")
        axs[0].set_title("Formula vs simulation; model sensitivity", fontsize=9); axs[0].legend(fontsize=7, frameon=False)
        S = e["sensitivity"]
        pm = sorted({r["p_max"] for r in S}); dd = sorted({r["d50_km"] for r in S})
        M = np.array([[next(r["regret_pct"] for r in S if r["p_max"] == a and r["d50_km"] == b) for b in dd] for a in pm])
        im = axs[1].imshow(M, cmap="Reds", aspect="auto")
        for i in range(len(pm)):
            for j in range(len(dd)):
                ov = next(r["overlap"] for r in S if r["p_max"] == pm[i] and r["d50_km"] == dd[j])
                axs[1].text(j, i, f"+{M[i, j]:.1f}%\n{100 * ov:.0f}% same route", ha="center", va="center", fontsize=7,
                            color="white" if M[i, j] > 0.6 * M.max() else "black")
        axs[1].set_xticks(range(len(dd))); axs[1].set_xticklabels([f"{d:g} km" for d in dd]); axs[1].set_xlabel("range at which p halves (d50)")
        axs[1].set_yticks(range(len(pm))); axs[1].set_yticklabels([f"{a:g}" for a in pm]); axs[1].set_ylabel("p per km at close range")
        axs[1].set_title("Cost of planning with the wrong model parameters", fontsize=9)
        fig.colorbar(im, ax=axs[1], label="objective above the re-optimised route (%)")
        save(fig, OUT / "fig_e15_montecarlo.png")
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    steps = dict(STEPS, figs=figs)
    for k in (list(steps) if what == "all" else [what]):
        t = time.perf_counter(); steps[k](); print(f"[{k}] {time.perf_counter() - t:.1f} s", flush=True)
