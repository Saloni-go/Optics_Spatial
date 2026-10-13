"""Track 3 - experiments for the interactive framework (what to precompute vs compute on the fly).

    run.bat -m corridor.interactive_bench ladder        E1 precompute-vs-query curve (Levels 0-2)
    run.bat -m corridor.interactive_bench anytime       E2 alpha changed: time to first / good / exact route
    run.bat -m corridor.interactive_bench incremental   E3 radar moved / added / removed, start moved
    run.bat -m corridor.interactive_bench lod           E4 pan / zoom with the Level 3 pyramid
    run.bat -m corridor.interactive_bench detection     E5 detection-probability routing vs exposure routing
    run.bat -m corridor.interactive_bench risk          E5b shortest route under a detection-risk budget
    run.bat -m corridor.interactive_bench figs          figures + latency budget table (E6) from the JSON
    run.bat -m corridor.interactive_bench all

Results: results/corridor/interactive/*.json and fig_*.png.  Every route is checked against an exact
C Dijkstra on the same cost surface; the checks are stored next to the timings.
"""
import json
import math
import sys
import time

import numpy as np

from common.config import RESULTS
from corridor import cgrid
from corridor.optimizer import Problem, evaluate
from corridor.prep import problem, endpoints

OUT = RESULTS / "corridor" / "interactive"
SIZE = 4000
RNG = np.random.default_rng(7)


def dump(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(obj, open(OUT / f"{name}.json", "w"), indent=1)
    print("wrote", OUT / f"{name}.json")


def free_cells(blocked, n, rng, min_sep=0):
    free = np.argwhere(~blocked)
    out = []
    while len(out) < n:
        a, b = free[rng.integers(len(free))], free[rng.integers(len(free))]
        if np.hypot(*(a - b)) >= min_sep:
            out.append(((int(a[0]), int(a[1])), (int(b[0]), int(b[1]))))
    return out


def timed(f, *a, **k):
    t = time.perf_counter()
    r = f(*a, **k)
    return r, time.perf_counter() - t


# ---------------------------------------------------------------- E1 precompute-vs-query ladder
def ladder(size=SIZE, n=20):
    p, dem = problem(size)
    goal = endpoints(p.blocked)[1]
    pairs = free_cells(p.blocked, n, RNG, min_sep=0.3 * size)              # workload B: any start, any goal
    starts = [a for a, _ in free_cells(p.blocked, n, RNG, min_sep=0.3 * size)]  # workload A: fixed goal
    exact_B = [cgrid.dijkstra_c(p, s, g) for s, g in pairs]
    exact_A = [cgrid.dijkstra_c(p, s, goal) for s in starts]
    rows = []

    def row(name, level, pre_s, mem_mb, qa, qb, ea, eb, gap):
        rows.append({"strategy": name, "level": level, "pre_s": pre_s, "mem_mb": mem_mb,
                     "query_fixed_goal_ms": 1000 * float(np.mean(qa)) if qa else None,
                     "query_any_pair_ms": 1000 * float(np.mean(qb)) if qb else None,
                     "expanded_fixed_goal": float(np.mean(ea)) if ea else None,
                     "expanded_any_pair": float(np.mean(eb)) if eb else None, "max_gap_pct": gap})
        print(rows[-1])

    def gap(res, ex):
        return max(100 * (r["cost"] / e["cost"] - 1) for r, e in zip(res, ex))

    # Level 0: nothing precomputed
    ra = [cgrid.dijkstra_c(p, s, goal) for s in starts]; rb = [cgrid.dijkstra_c(p, s, g) for s, g in pairs]
    row("Dijkstra (C)", 0, 0.0, 0.0, [r["solve_s"] for r in ra], [r["solve_s"] for r in rb],
        [r["expanded"] for r in ra], [r["expanded"] for r in rb], gap(rb, exact_B))
    ra = [cgrid.astar_c(p, s, goal) for s in starts]; rb = [cgrid.astar_c(p, s, g) for s, g in pairs]
    row("A* geo heuristic (C)", 0, 0.0, 0.0, [r["solve_s"] for r in ra], [r["solve_s"] for r in rb],
        [r["expanded"] for r in ra], [r["expanded"] for r in rb], gap(rb, exact_B))
    # Level 1: landmarks
    for k in (1, 2, 4, 8):
        lm = cgrid.CLandmarks(p, k)
        ra = [cgrid.alt_c(p, s, goal, lm) for s in starts]; rb = [cgrid.alt_c(p, s, g, lm) for s, g in pairs]
        row(f"ALT, {k} landmark{'s' if k > 1 else ''} (C)", 1, lm.pre_s, lm.mem_mb, [r["solve_s"] for r in ra],
            [r["solve_s"] for r in rb], [r["expanded"] for r in ra], [r["expanded"] for r in rb], gap(rb, exact_B))
        del lm
    # Level 2: cost-to-go field for the goal; any-pair queries need one field per goal
    ctg = cgrid.CostToGo(p, goal)
    qa, ga = [], []
    for s, e in zip(starts, exact_A):
        (path, cost), dt = timed(ctg.route, s)
        qa.append(dt); ga.append(100 * (cost / e["cost"] - 1))
    row("Level 2 cost-to-go field (C)", 2, ctg.pre_s, ctg.mem_mb, qa, None, [0] * len(qa), None, max(ga))
    rows[-1]["note"] = "query = lookup; a new goal costs one field (pre_s)"
    dump("e1_ladder", {"size": size, "nodes": p.H * p.W, "n_queries": n, "rows": rows})


# ---------------------------------------------------------------- E2 anytime after alpha changes
def anytime_exp(size=SIZE):
    from corridor.interactive_core import Pyramid, progressive, anytime
    p, dem = problem(size)
    s, g = endpoints(p.blocked)
    pyr = Pyramid(p)
    out = {"size": size, "pyramid_pre_s": pyr.pre_s, "runs": []}
    for alpha in (2.0, 5.0, 20.0, 50.0):
        p.alpha = alpha; pyr.set_weights(alpha, p.beta)
        opt = cgrid.dijkstra_c(p, s, g)
        field, ft = timed(cgrid.CostToGo, p, g)
        stages = [{"stage": r["stage"], "t_s": r["elapsed_s"], "gap_pct": 100 * (r["cost"] / opt["cost"] - 1),
                   "corridor_frac": r.get("corridor_frac")} for r in progressive(pyr, s, g)]
        rwa = [{"stage": r["stage"], "t_s": r["elapsed_s"], "gap_pct": 100 * (r["cost"] / opt["cost"] - 1),
                "expanded": r["expanded"]} for r in anytime(p, s, g, weights=(3.0, 1.5, 1.0))]
        out["runs"].append({"alpha": alpha, "dijkstra_s": opt["solve_s"], "field_s": field.pre_s,
                            "progressive": stages, "weighted_astar": rwa})
        print(alpha, stages, rwa)
    dump("e2_anytime", out)


# ---------------------------------------------------------------- E3 incremental replanning
def _move_target(field, dem, i, dist, rng):
    x, y = field.sites[i]
    H, W = dem.shape
    for _ in range(64):
        a = rng.uniform(0, 2 * math.pi)
        nx, ny = x + dist * math.cos(a), y + dist * math.sin(a)
        c, r = dem.to_pixel(nx, ny)
        if 0.02 * W < c < 0.98 * W and 0.02 * H < r < 0.98 * H:
            return nx, ny
    return x, y


def incremental(sizes=(1000, 2000, 4000), dstar_sizes=(1000, 2000, 4000)):
    from corridor.interactive_core import Planner
    rng = np.random.default_rng(11)
    out = {"runs": []}
    for size in sizes:
        P = Planner(size, "exposure")
        P.ctg = cgrid.CostToGo(P.p, P.goal)
        ds = None
        if size in dstar_sizes:
            ds, t_init = timed(cgrid.DStar, P.p, P.start, P.goal)
            out["runs"].append({"size": size, "event": "D* Lite initial plan", "dstar_ms": 1000 * t_init})
        events = [("move", 1000), ("move", 5000), ("move", 10000), ("move", 20000), ("move", 5000), ("move", 10000),
                  ("add", None), ("remove", None)]
        for kind, dist in events:
            i = int(rng.integers(len(P.field.sites)))
            if kind == "move":
                x, y = _move_target(P.field, P.dem, i, dist, rng)
                changed, tf = P.field.move(i, x, y)
            elif kind == "add":
                fr = free_cells(P.p.blocked, 1, rng)[0][0]
                x, y = P.dem.to_world(fr[1], fr[0])
                changed, tf = P.field.add(x, y)
            else:
                changed, tf = P.field.remove(len(P.field.sites) - 1)
            cgrid.set_exposure(P.p, P.field.E)
            rep = P.ctg.repair(changed)
            fresh = cgrid.CostToGo(P.p, P.goal)
            fin = np.isfinite(fresh.dist)
            err = float(np.abs(P.ctg.dist[fin] - fresh.dist[fin]).max())
            dj = cgrid.dijkstra_c(P.p, P.start, P.goal)
            row = {"size": size, "event": f"{kind} radar" + (f" {dist / 1000:g} km" if dist else ""),
                   "changed_frac": float((changed > 0).mean()), "field_update_ms": 1000 * tf,
                   "repair_ms": 1000 * rep["repair_s"], "affected_frac": rep["affected"] / changed.size,
                   "full_field_ms": 1000 * fresh.pre_s, "dijkstra_ms": 1000 * dj["solve_s"], "repair_max_err": err}
            if ds is not None:
                u = ds.update(changed)
                path, cost = ds.route()
                row.update({"dstar_ms": 1000 * u["replan_s"], "dstar_expanded": u["expanded"],
                            "dstar_gap_pct": 100 * (cost / dj["cost"] - 1)})
            P.ctg = fresh if err > 1e-6 else P.ctg          # never carry a wrong field forward
            out["runs"].append(row); print(row)
        # start moved: the main interaction
        for s, _ in free_cells(P.p.blocked, 5, rng, min_sep=0.3 * size):
            (path, cost), tl = timed(P.ctg.route, s)
            dj = cgrid.dijkstra_c(P.p, s, P.goal)
            row = {"size": size, "event": "start moved", "lookup_ms": 1000 * tl, "dijkstra_ms": 1000 * dj["solve_s"],
                   "lookup_gap_pct": 100 * (cost / dj["cost"] - 1)}
            if ds is not None:
                u = ds.plan(s); dpath, dcost = ds.route()
                row.update({"dstar_ms": 1000 * u["replan_s"], "dstar_expanded": u["expanded"],
                            "dstar_gap_pct": 100 * (dcost / dj["cost"] - 1)})
            out["runs"].append(row); print(row)
        del ds, P
    dump("e3_incremental", out)


# ---------------------------------------------------------------- E4 level of detail
def lod(size=SIZE):
    """Pan/zoom two ways: (a) the Level 2 field is valid -> draw the exact route, decimated to the
    screen; (b) it is not (being rebuilt) -> pyramid preview (whole route coarse, window re-solved)."""
    from scipy.spatial import cKDTree
    from corridor.interactive_core import Pyramid
    p, dem = problem(size)
    s, g = endpoints(p.blocked)
    exact = cgrid.dijkstra_c(p, s, g)
    ex_rc = np.array([divmod(i, p.W) for i in exact["path"]])
    pyr = Pyramid(p)
    rows = []
    for view in (4000, 2000, 1000, 500, 250):
        for frac in (0.2, 0.4, 0.6, 0.8):
            cr, cc = ex_rc[int(frac * (len(ex_rc) - 1))]
            r0 = int(np.clip(cr - view // 2, 0, p.H - view)); c0 = int(np.clip(cc - view // 2, 0, p.W - view))
            inside = lambda a: a[(a[:, 0] >= r0) & (a[:, 0] < r0 + view) & (a[:, 1] >= c0) & (a[:, 1] < c0 + view)]
            px = view * p.cell / 800                                  # metres per screen pixel
            # (a) field valid
            t = time.perf_counter()
            step = max(1, view // 800)
            drawn = inside(ex_rc)[::step]
            ta = time.perf_counter() - t
            # (b) pyramid preview
            o = pyr.route(s, g, (r0, r0 + view, c0, c0 + view))
            shown = np.array(o["refined"] or o["coarse"])
            vis = inside(shown) if len(shown) else shown
            ins = inside(ex_rc)
            off = cKDTree(ins).query(vis)[0] * p.cell if len(vis) else None
            rows.append({"view_cells": view, "frac": frac, "exact_draw_ms": 1000 * ta, "exact_points": len(drawn),
                         "preview_ms": 1000 * o["total_s"], "level": o["level"], "view_level": o["view_level"],
                         "preview_in_view": bool(len(vis)),
                         "preview_offset_px_median": float(np.median(off) / px) if off is not None else None,
                         "preview_offset_m_median": float(np.median(off)) if off is not None else None})
            print(rows[-1])
    dump("e4_lod", {"size": size, "exact_ms": 1000 * exact["solve_s"], "pyramid_pre_s": pyr.pre_s,
                    "pyramid_mb": pyr.mem_mb, "screen_px": 800, "rows": rows})


# ---------------------------------------------------------------- E5 detection-probability routing
def detection(size=SIZE):
    from common.config import dem_path
    from common.dem_utils import DEM
    from corridor.exposure import blocked_mask
    from corridor.prep import sites_for
    from corridor.radarfield import RadarField
    from corridor.interactive_core import scenario_endpoints
    dem = DEM(dem_path(size))
    sites = sites_for(dem, size, 6)
    blk = blocked_mask(dem)
    Fe = RadarField(dem, sites, "exposure"); Fd = RadarField(dem, sites, "detection")
    s, g = scenario_endpoints(dem, size, blk)
    pe = Problem(dem.z, Fe.E, blk, dem.cell, 0.0, 2.0)
    pd = Problem(dem.z, Fd.E, blk, dem.cell, 0.0, 2.0)
    out = {"size": size, "start": s, "goal": g, "routes": []}
    for model, p, alphas in (("exposure", pe, (0, 1, 2, 5, 10, 20, 50, 100)),
                             ("detection", pd, (0, 0.5, 1, 2, 5, 10, 20, 50, 100, 200))):
        for a in alphas:
            p.alpha = float(a)
            r = cgrid.dijkstra_c(p, s, g)
            ev = evaluate(pe, r["path"])
            pdet = Fd.detection_probability(r["path"], p.W, p.cell)
            out["routes"].append({"model": model, "alpha": a, "length_km": ev["length_km"], "exposure_km": ev["exposure_km"],
                                  "exposed_frac": ev["exposed_frac"], "p_detect": pdet, "climb_m": ev["climb_m"],
                                  "solve_s": r["solve_s"], "path": r["path"][::10] + [r["path"][-1]]})
            print(model, a, round(ev["length_km"], 1), round(pdet, 4))
    OUT.mkdir(parents=True, exist_ok=True)
    np.save(OUT / "detection_H.npy", Fd.E.astype(np.float32))
    dump("e5_detection", out)


def risk(size=SIZE):
    """E5b: shortest route with P(detect) <= budget (Lagrangian bisection on the risk price)."""
    from corridor.interactive_core import Planner
    P = Planner(size, "detection")
    out = {"size": size, "runs": []}
    for pm in (0.9, 0.75, 0.5, 0.35, 0.25):
        r = P.risk_budget(pm)
        out["runs"].append(r)
        print(pm, {k: v for k, v in r.items() if k != "trace"})
    dump("e5b_risk_budget", out)


# ---------------------------------------------------------------- figures + E6 latency budget
def figs():
    from common.plots import plt, save
    L = lambda n: json.load(open(OUT / f"{n}.json"))
    S = {}
    # E1
    try:
        e1 = L("e1_ladder"); rows = e1["rows"]
        fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
        for r in rows:
            q = r["query_any_pair_ms"] if r["query_any_pair_ms"] is not None else r["query_fixed_goal_ms"]
            mk = "s" if r["level"] == 2 else ("o" if r["level"] == 1 else "^")
            axs[0].loglog(max(r["pre_s"], 0.05), q, mk, ms=8, label=r["strategy"])
        axs[0].set_xlabel("precompute (s; 0 plotted at 0.05)"); axs[0].set_ylabel("time per route (ms)")
        axs[0].set_title(f"Precompute vs query, {e1['nodes'] / 1e6:.0f} M nodes", fontsize=9); axs[0].legend(fontsize=6.5, frameon=False)
        qn = np.arange(0, 101)
        for r in rows:
            q = (r["query_fixed_goal_ms"]) / 1000
            axs[1].plot(qn, r["pre_s"] + qn * q, label=r["strategy"])
        axs[1].set_yscale("log"); axs[1].set_xlabel("routes requested (same goal, new start each click)")
        axs[1].set_ylabel("total time (s)"); axs[1].set_title("Which level pays off after how many clicks", fontsize=9)
        axs[1].legend(fontsize=6.5, frameon=False)
        save(fig, OUT / "fig_e1_ladder.png")
        S["e1"] = rows
    except FileNotFoundError:
        pass
    # E2
    try:
        e2 = L("e2_anytime")
        fig, ax = plt.subplots(figsize=(6.5, 3.8))
        for i, run in enumerate(e2["runs"]):
            c = plt.cm.viridis(i / max(len(e2["runs"]) - 1, 1))
            ax.plot([st["t_s"] for st in run["progressive"]], [max(st["gap_pct"], 1e-3) for st in run["progressive"]],
                    "o-", c=c, label=f"coarse-to-fine, a={run['alpha']:g}")
            ax.plot([st["t_s"] for st in run["weighted_astar"]], [max(st["gap_pct"], 1e-3) for st in run["weighted_astar"]],
                    "x--", c=c, alpha=0.6, label=f"weighted A*, a={run['alpha']:g}")
        ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlabel("time since alpha changed (s)")
        ax.set_ylabel("route cost above optimum (%; 0 at 0.001)"); ax.legend(fontsize=6, frameon=False, ncol=2)
        ax.set_title("Anytime answers after the exposure weight changes", fontsize=9)
        save(fig, OUT / "fig_e2_anytime.png")
    except FileNotFoundError:
        pass
    # E3
    try:
        e3 = L("e3_incremental"); runs = [r for r in e3["runs"] if "radar" in r["event"]]
        fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
        for size, c in zip((1000, 2000, 4000), ("#2a9d8f", "#457b9d", "#8338ec")):
            rr = [r for r in runs if r["size"] == size]
            if not rr:
                continue
            axs[0].scatter([r["changed_frac"] * 100 for r in rr], [r["repair_ms"] / r["full_field_ms"] for r in rr], c=c,
                           label=f"field repair, {size}^2")
            if "dstar_ms" in rr[0]:
                axs[0].scatter([r["changed_frac"] * 100 for r in rr], [r["dstar_ms"] / r["dijkstra_ms"] for r in rr], c=c,
                               marker="x", label=f"D* Lite vs fresh Dijkstra, {size}^2")
        axs[0].axhline(1, c="k", lw=0.8, ls=":"); axs[0].set_yscale("log")
        axs[0].set_xlabel("cells whose threat changed (%)"); axs[0].set_ylabel("incremental / from scratch (time)")
        axs[0].set_title("When does repairing beat recomputing?", fontsize=9); axs[0].legend(fontsize=6.5, frameon=False)
        st = [r for r in e3["runs"] if r["event"] == "start moved"]
        sizes = sorted({r["size"] for r in st})
        w = 0.25
        for j, (key, lab) in enumerate((("lookup_ms", "Level 2 lookup"), ("dstar_ms", "D* Lite replan"), ("dijkstra_ms", "fresh Dijkstra"))):
            vals = [np.mean([r.get(key, np.nan) for r in st if r["size"] == s]) for s in sizes]
            axs[1].bar(np.arange(len(sizes)) + (j - 1) * w, [max(v, 1e-3) for v in vals], w, label=lab)
        axs[1].set_yscale("log"); axs[1].set_xticks(range(len(sizes))); axs[1].set_xticklabels([f"{s}^2" for s in sizes])
        axs[1].set_ylabel("ms"); axs[1].set_title("Start moved (click)", fontsize=9); axs[1].legend(fontsize=7, frameon=False)
        axs[1].axhline(16, c="k", lw=0.8, ls=":")
        save(fig, OUT / "fig_e3_incremental.png")
    except FileNotFoundError:
        pass
    # E4
    try:
        e4 = L("e4_lod"); rows = e4["rows"]
        views = sorted({r["view_cells"] for r in rows}, reverse=True)
        med = lambda k, v: float(np.median([r[k] for r in rows if r["view_cells"] == v and r[k] is not None] or [np.nan]))
        fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
        axs[0].plot(views, [max(med("exact_draw_ms", v), 1e-3) for v in views], "o-", c="#2a9d8f", label="draw known route, decimated (adopted)")
        axs[0].plot(views, [med("preview_ms", v) for v in views], "s-", c="#457b9d", label="re-solve each view on pyramid (rejected)")
        axs[0].axhline(e4["exact_ms"], c="#e63946", ls="--", label="full-res search every frame")
        axs[0].axhline(16, c="k", lw=0.7, ls=":")
        axs[0].set_xscale("log"); axs[0].set_yscale("log"); axs[0].invert_xaxis()
        axs[0].set_xlabel("view width (cells; right = zoomed in)"); axs[0].set_ylabel("ms per pan/zoom")
        axs[0].legend(fontsize=7, frameon=False); axs[0].set_title("Pan / zoom latency", fontsize=9)
        axs[1].plot(views, [med("preview_offset_px_median", v) for v in views], "s-", c="#457b9d", label="re-solve each view (rejected)")
        axs[1].plot(views, [0 for v in views], "o-", c="#2a9d8f", label="draw known route (adopted)")
        axs[1].set_xscale("log"); axs[1].invert_xaxis(); axs[1].set_xlabel("view width (cells)")
        axs[1].set_ylabel("median offset from exact route (screen px)"); axs[1].legend(fontsize=7, frameon=False)
        axs[1].set_title("What the user sees vs the exact route", fontsize=9)
        save(fig, OUT / "fig_e4_lod.png")
    except FileNotFoundError:
        pass
    # E5
    try:
        e5 = L("e5_detection")
        fig, ax = plt.subplots(figsize=(6.5, 3.8))
        for model, c in (("exposure", "#457b9d"), ("detection", "#e63946")):
            rr = sorted([r for r in e5["routes"] if r["model"] == model], key=lambda r: r["length_km"])
            ax.plot([r["length_km"] for r in rr], [100 * r["p_detect"] for r in rr], "o-", c=c, label=f"optimised for {model}")
        try:
            rb = [r for r in L("e5b_risk_budget")["runs"] if r["found"]]
            ax.scatter([r["length_km"] for r in rb], [100 * r["p_detect"] for r in rb], marker="*", s=140, c="#ffb703",
                       edgecolors="k", zorder=5, label="risk budget query (<= 90/75/50/35/25%)")
            for r in rb:
                ax.axhline(100 * r["p_max"], c="#ffb703", lw=0.6, ls=":")
        except FileNotFoundError:
            pass
        ax.set_xlabel("route length (km)"); ax.set_ylabel("probability of being detected (%)")
        ax.set_title("Both objectives give almost the same trade-off; the detection model makes it a probability", fontsize=9)
        ax.legend(fontsize=8, frameon=False)
        save(fig, OUT / "fig_e5_detection.png")
    except FileNotFoundError:
        pass
    budget()


def budget():
    """E6 latency budget at the largest size, from the measured results."""
    L = lambda n: json.load(open(OUT / f"{n}.json"))
    cls = lambda ms: "frame (<16 ms)" if ms < 16 else "interactive (<100 ms)" if ms < 100 else "responsive (<1 s)" if ms < 1000 else "background (>1 s)"
    rows = []
    try:
        e3 = L("e3_incremental"); big = max(r["size"] for r in e3["runs"])
        st = [r for r in e3["runs"] if r["size"] == big and r["event"] == "start moved"]
        rad = [r for r in e3["runs"] if r["size"] == big and "move radar" in r["event"]]
        m = lambda rr, k: float(np.median([r[k] for r in rr if k in r]))
        rows += [("click new start", "Level 2 lookup", m(st, "lookup_ms")),
                 ("click new start", "D* Lite replan", m(st, "dstar_ms")) if any("dstar_ms" in r for r in st) else None,
                 ("click new start", "no precompute (C Dijkstra)", m(st, "dijkstra_ms")),
                 ("drag a radar", "threat surface update (one viewshed)", m(rad, "field_update_ms")),
                 ("drag a radar", "+ Level 2 field repair", m(rad, "repair_ms")),
                 ("drag a radar", "+ full field recompute", m(rad, "full_field_ms"))]
    except FileNotFoundError:
        pass
    try:
        e2 = L("e2_anytime"); pr = [r["progressive"] for r in e2["runs"]]
        rows += [("change alpha", "first route (coarse x16)", 1000 * float(np.median([p[0]["t_s"] for p in pr]))),
                 ("change alpha", "within ~0.3% (full-res corridor)", 1000 * float(np.median([p[-2]["t_s"] for p in pr]))),
                 ("change alpha", "exact + field rebuilt", 1000 * float(np.median([r["field_s"] for r in e2["runs"]])))]
    except FileNotFoundError:
        pass
    try:
        e4 = L("e4_lod")
        for v in (4000, 250):
            rr = [r for r in e4["rows"] if r["view_cells"] == v]
            if rr:
                rows.append(("pan / zoom", f"draw known route, view {v} cells", float(np.median([r["exact_draw_ms"] for r in rr]))))
                rows.append(("pan / zoom", f"(rejected) re-solve view on pyramid, {v} cells", float(np.median([r["preview_ms"] for r in rr]))))
    except FileNotFoundError:
        pass
    try:
        e1 = L("e1_ladder")
        for r in e1["rows"]:
            if r["strategy"].startswith("ALT, 4"):
                rows.append(("new goal", "ALT 4 landmarks (any pair)", r["query_any_pair_ms"]))
    except FileNotFoundError:
        pass
    rows = [{"interaction": a, "strategy": b, "ms": c, "class": cls(c)} for a, b, c in filter(None, rows)]
    dump("e6_budget", rows)
    for r in rows:
        print(f"{r['interaction']:16s} {r['strategy']:40s} {r['ms']:10.2f} ms  {r['class']}")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    steps = {"ladder": ladder, "anytime": anytime_exp, "incremental": incremental, "lod": lod,
             "detection": detection, "risk": risk, "figs": figs, "budget": budget}
    for k in (steps if what == "all" else [what]):
        if what == "all" and k == "budget":
            continue
        t = time.perf_counter(); steps[k](); print(f"[{k}] {time.perf_counter() - t:.1f} s")
