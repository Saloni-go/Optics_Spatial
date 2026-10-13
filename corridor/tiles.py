"""Track 3 - tile overlay: precompute that survives radar edits (Customizable Route Planning idea on a grid).

The map is cut into tiles (250 x 250 cells).  Along every border between two tiles, "portal" pairs are
placed every `spacing` cells (a cell on each side; the two are neighbours).  Precompute = for every tile,
the cost between all of its portals with the route kept inside the tile (one small window Dijkstra per
portal, in C, tiles on parallel threads).  Together with the portal-to-portal steps across borders this is
a small overlay graph (~10 k nodes for 16 M cells).

  query(start, goal)  any start, any goal: connect the start to the portals of its tile and the portals of
                      the goal tile to the goal (two window searches), search the overlay, then unpack each
                      tile crossing into cells.  Unlike the Level 2 field it is not tied to one goal.
  update(changed)     after a radar edit only the tiles whose cells changed are recomputed (the
                      "customization" step of CRP: the partition and portals never change).

Routes are restricted to cross tile borders at portals, so they are near-optimal, not exact; spacing=1
(every border cell a portal) is exact, at a much larger overlay.  The gap is measured in E10.
"""
import math
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra as cs_dijkstra

from corridor import cgrid
from corridor.optimizer import Problem, evaluate

SQ2 = math.sqrt(2.0)


def _window_multi(p, win, src, tgt, reverse=False):
    import ctypes as ct
    z, E, blk = cgrid._arrays(p)
    r0, r1, c0, c1 = win
    src = np.ascontiguousarray(src, np.int32); tgt = np.ascontiguousarray(tgt, np.int32)
    out = np.empty((len(src), len(tgt)), np.float64)
    cgrid.lib().window_multi(p.H, p.W, z, E, blk, p.cell, p.alpha, p.beta, r0, r1, c0, c1,
                             len(src), src.ctypes.data_as(ct.c_void_p), len(tgt), tgt.ctypes.data_as(ct.c_void_p),
                             int(reverse), out.ctypes.data_as(ct.c_void_p))
    return out


class TileOverlay:
    def __init__(self, p, tile=250, spacing=25, threads=cgrid.THREADS, valleys=0):
        """valleys=w: also put a portal at every local minimum of the terrain along a border (window +/-w
        cells): hidden routes cross borders in valleys, so portals there cut the detour."""
        self.p, self.tile, self.spacing, self.threads, self.valleys = p, tile, spacing, threads, valleys
        self.nr, self.nc = math.ceil(p.H / tile), math.ceil(p.W / tile)
        t = time.perf_counter()
        self._place_portals()
        self.cliques = [None] * (self.nr * self.nc)
        self._compute_tiles(range(self.nr * self.nc))
        self._build_graph()
        self.pre_s = time.perf_counter() - t

    # ------------------------------------------------------------ structure (never changes)
    def tile_of(self, r, c):
        return (r // self.tile) * self.nc + (c // self.tile)

    def window(self, t):
        a, b = divmod(t, self.nc)
        return (a * self.tile, min((a + 1) * self.tile, self.p.H), b * self.tile, min((b + 1) * self.tile, self.p.W))

    def _place_portals(self):
        p, T, sp = self.p, self.tile, self.spacing
        blk = p.blocked
        cells, pairset = [], set()                         # portal cell list; (portal a, portal b) border steps
        index = {}

        def portal(r, c):
            i = r * p.W + c
            if i not in index:
                index[i] = len(cells); cells.append(i)
            return index[i]

        def segment(points):                               # pick portal pairs along one border segment
            if self.valleys:
                zz = np.array([min(p.z[a], p.z[b]) for a, b in points])
                w = self.valleys
                for j in range(len(points)):
                    lo, hi = max(0, j - w), min(len(points), j + w + 1)
                    (ra, ca), (rb, cb) = points[j]
                    if zz[j] == zz[lo:hi].min() and not blk[ra, ca] and not blk[rb, cb]:
                        pairset.add((portal(ra, ca), portal(rb, cb)))
            for k in range(sp // 2, len(points), sp):
                for d in sorted(range(-(sp // 2), sp - sp // 2), key=abs):   # nearest free pair to the slot
                    j = k + d
                    if 0 <= j < len(points):
                        (ra, ca), (rb, cb) = points[j]
                        if not blk[ra, ca] and not blk[rb, cb]:
                            pairset.add((portal(ra, ca), portal(rb, cb)))
                            break
        for a in range(self.nr):
            for b in range(self.nc):
                r0, r1, c0, c1 = self.window(a * self.nc + b)
                if c1 < p.W:                               # border with the tile to the right
                    segment([((r, c1 - 1), (r, c1)) for r in range(r0, r1)])
                if r1 < p.H:                               # border with the tile below
                    segment([((r1 - 1, c), (r1, c)) for c in range(c0, c1)])
        self.pairs = sorted(pairset)
        self.cells = np.array(cells, np.int64)
        self.tile_portals = [[] for _ in range(self.nr * self.nc)]
        for k, i in enumerate(self.cells):
            self.tile_portals[self.tile_of(*divmod(int(i), p.W))].append(k)

    # ------------------------------------------------------------ costs (recomputed on edits)
    def _compute_tiles(self, tiles):
        p = self.p

        def one(t):
            ks = self.tile_portals[t]
            if not ks:
                return t, None
            idx = self.cells[ks]
            return t, _window_multi(p, self.window(t), idx, idx)
        cgrid.lib()
        with ThreadPoolExecutor(max_workers=self.threads) as ex:
            for t, m in ex.map(one, list(tiles)):
                self.cliques[t] = m

    def _edges(self, ia, ib):
        """Costs of the border steps a -> b and b -> a (vectorised)."""
        p = self.p
        z, E = p.z.ravel(), p.E.ravel()
        ra, ca = np.divmod(ia, p.W); rb, cb = np.divmod(ib, p.W)
        lf = np.where((ra != rb) & (ca != cb), SQ2, 1.0) * p.cell
        base = lf * (1 + p.alpha * 0.5 * (E[ia] + E[ib]))
        dz = z[ib] - z[ia]
        return base + p.beta * np.maximum(dz, 0), base + p.beta * np.maximum(-dz, 0)

    def _edge(self, a, b):
        p = self.p
        (ra, ca), (rb, cb) = divmod(a, p.W), divmod(b, p.W)
        lf = SQ2 if (ra != rb and ca != cb) else 1.0
        dz = p.z[rb, cb] - p.z[ra, ca]
        return lf * p.cell * (1 + p.alpha * 0.5 * (p.E[ra, ca] + p.E[rb, cb])) + (p.beta * dz if dz > 0 else 0.0)

    def _build_graph(self):
        rows, cols, vals = [], [], []
        for t, ks in enumerate(self.tile_portals):
            m = self.cliques[t]
            if m is None:
                continue
            ks = np.array(ks)
            ii, jj = np.nonzero(np.isfinite(m) & (m > 0))
            rows.append(ks[ii]); cols.append(ks[jj]); vals.append(m[ii, jj])
        a = np.array([x for x, _ in self.pairs]); b = np.array([y for _, y in self.pairs])
        fw, bw = self._edges(self.cells[a], self.cells[b])
        rows += [a, b]; cols += [b, a]; vals += [fw, bw]
        n = len(self.cells)
        R, C, V = np.concatenate(rows), np.concatenate(cols), np.concatenate(vals)
        # duplicate (i, j) edges (a valley portal can coincide with a regular one): keep the cheapest -
        # building the CSR directly would ADD them
        o = np.lexsort((V, C, R))
        R, C, V = R[o], C[o], V[o]
        first = np.ones(len(R), bool); first[1:] = (R[1:] != R[:-1]) | (C[1:] != C[:-1])
        R, C, V = R[first], C[first], V[first]
        G = coo_matrix((V, (R, C)), shape=(n, n)).tocsr()
        self.csr = (np.ascontiguousarray(G.indptr, np.int64), np.ascontiguousarray(G.indices, np.int32),
                    np.ascontiguousarray(G.data, np.float64))
        self.edges = int(G.nnz)
        self.mem_mb = (sum(m.nbytes for m in self.cliques if m is not None) + sum(a.nbytes for a in self.csr)) / 2 ** 20

    def update(self, changed):
        """Radar edit: recompute only tiles containing a changed cell (CRP customization)."""
        t = time.perf_counter()
        rr, cc = np.nonzero(changed)
        tiles = np.unique((rr // self.tile) * self.nc + (cc // self.tile)) if len(rr) else []
        self._compute_tiles(tiles)
        self._build_graph()
        return {"update_s": time.perf_counter() - t, "tiles": len(tiles), "of": self.nr * self.nc}

    # ------------------------------------------------------------ queries
    def query(self, start, goal, unpack=True):
        import ctypes as ct
        p = self.p
        t0 = time.perf_counter()
        s, g = p.idx(start), p.idx(goal)
        ts, tg = self.tile_of(*start), self.tile_of(*goal)
        ps = np.array(self.tile_portals[ts], np.int32); pg = np.array(self.tile_portals[tg], np.int32)
        ds = _window_multi(p, self.window(ts), [s], self.cells[ps])[0]                # start -> its portals
        dg = _window_multi(p, self.window(tg), [g], self.cells[pg], reverse=True)[0]  # its portals -> goal
        n = len(self.cells)
        pred = np.empty(n, np.int32)
        best = ct.c_double()
        ip, ix, dv = self.csr
        V = ct.c_void_p
        bt = cgrid.lib().overlay_query(n, ip.ctypes.data_as(V), ix.ctypes.data_as(V), dv.ctypes.data_as(V),
                                       len(ps), ps.ctypes.data_as(V), ds.ctypes.data_as(V),
                                       len(pg), pg.ctypes.data_as(V), dg.ctypes.data_as(V), ct.byref(best),
                                       pred.ctypes.data_as(V))
        cost = best.value
        direct = math.inf
        if ts == tg:                                       # same tile: the route may stay inside it
            direct = _window_multi(p, self.window(ts), [s], [g])[0, 0]
        t1 = time.perf_counter()
        out = {"cost": min(cost, direct), "query_s": t1 - t0, "path": None}
        if not unpack or not math.isfinite(out["cost"]):
            return out
        if direct <= cost:
            seq_cells = [s, g]
        else:
            seq = []
            v_ = bt
            while v_ >= 0:
                seq.append(v_); v_ = pred[v_]
            seq_cells = [s] + [int(self.cells[k]) for k in seq[::-1]] + [g]
        path = [s]
        for ca, cb in zip(seq_cells[:-1], seq_cells[1:]):
            ra, rb = divmod(ca, p.W), divmod(cb, p.W)
            if ca == cb:
                continue
            if max(abs(ra[0] - rb[0]), abs(ra[1] - rb[1])) <= 1 and self.tile_of(*ra) != self.tile_of(*rb):
                path.append(cb); continue                  # border step between two tiles
            r0, r1, c0, c1 = self.window(self.tile_of(*ra))
            sub = Problem(p.z[r0:r1, c0:c1], p.E[r0:r1, c0:c1], p.blocked[r0:r1, c0:c1], p.cell, p.alpha, p.beta)
            rr = cgrid.dijkstra_c(sub, (ra[0] - r0, ra[1] - c0), (rb[0] - r0, rb[1] - c0))
            path += [(i // sub.W + r0) * p.W + (i % sub.W + c0) for i in rr["path"][1:]]
        out["path"] = path
        out["unpack_s"] = time.perf_counter() - t1
        return out
