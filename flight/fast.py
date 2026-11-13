"""Track 2 - idea 1: making the route computation cheaper.

Three independent optimisations on top of flight/visibility.py (same GDAL engine, same physics):

  shared        No per-position copy of the DEM.  F6 showed that 'cached' (whole DEM, no copy) beats
                'window' (copy a radius window for every position): the copy costs more than the smaller
                search saves.  Here every thread opens a zero-copy GDAL view of the one in-memory DEM
                array (gdal_array.OpenArray) and GDAL clips the work to the radius itself.
                Exact: identical to 'window'.

  multires      Fine near, coarse far.  Inside r_near the viewshed runs on the 30 m DEM; beyond it, on a
                k-times coarser DEM (block mean) over the full radius, and the coarse answer is used for
                cells farther than r_near.  Most of the 20 km disc is far field, so work drops roughly by
                k^2 there.  Approximate: accuracy is measured (Jaccard) against the exact result.

  TiledAccumulator
                Count / first-seen rasters kept only for the tiles the route actually sees (allocated on
                first touch) instead of two full-map arrays.  Same results, lower peak memory when the
                corridor covers a small part of the map.
"""
import threading
import time

import numpy as np
from osgeo import gdal, gdal_array

from common.config import CURV_COEFF, VISIBLE, INVISIBLE, OUT_OF_RANGE
from flight.visibility import Accumulator

gdal.UseExceptions()


# --------------------------------------------------------------------------- shared DEM view
class SharedDEM:
    """Zero-copy GDAL datasets over dem.z, one per thread (GDAL datasets are not shared across threads)."""

    def __init__(self, z, gt, proj):
        self.arr = np.ascontiguousarray(np.where(np.isnan(z), -9999.0, z), dtype=np.float32)
        self.gt, self.proj = gt, proj
        self._tl = threading.local()

    def band(self):
        ds = getattr(self._tl, "ds", None)
        if ds is None:
            ds = gdal_array.OpenArray(self.arr)
            ds.SetGeoTransform(self.gt); ds.SetProjection(self.proj)
            ds.GetRasterBand(1).SetNoDataValue(-9999.0)
            self._tl.ds = ds
        return ds.GetRasterBand(1)


def _viewshed(band, gt, ox, oy, h, target_h, radius):
    """GDAL viewshed; returns (c0, r0, visible bool) in the pixel frame of geotransform gt."""
    out = gdal.ViewshedGenerate(band, "MEM", "", None, ox, oy, h, target_h, VISIBLE, INVISIBLE,
                                OUT_OF_RANGE, OUT_OF_RANGE, CURV_COEFF, gdal.GVM_Edge, max(radius, 0.0))
    a = out.GetRasterBand(1).ReadAsArray()
    og = out.GetGeoTransform()
    return int(round((og[0] - gt[0]) / gt[1])), int(round((og[3] - gt[3]) / gt[5])), a == VISIBLE


def viewshed_shared(dem, shared, x, y, alt_msl, radius, target_h=0.0):
    c, r = dem.to_pixel(x, y)
    rc, cc = int(round(r)), int(round(c))
    h = max(float(alt_msl - dem.z[rc, cc]), 1.0)
    return _viewshed(shared.band(), dem.gt, *dem.to_world(cc, rc), h, target_h, radius)


# --------------------------------------------------------------------------- multi-resolution
class Coarse:
    """k-times coarser copy of the DEM (block mean), with a shared zero-copy view."""

    def __init__(self, dem, k):
        t = time.perf_counter()
        H, W = dem.shape[0] // k, dem.shape[1] // k
        z = np.nan_to_num(dem.z[:H * k, :W * k], nan=-9999.0).reshape(H, k, W, k).mean(axis=(1, 3))
        self.k, self.z = k, z.astype(np.float32)
        self.gt = (dem.gt[0], dem.gt[1] * k, 0.0, dem.gt[3], 0.0, dem.gt[5] * k)
        self.shared = SharedDEM(self.z, self.gt, dem.proj)
        self.build_s = time.perf_counter() - t


_DISKS = {}


def _disk(radius_cells):
    """Boolean disk of the given radius (cells), centred in a (2K+1)^2 array; cached."""
    K = int(np.ceil(radius_cells)) + 16       # margin: coarse blocks overshoot the circle by < k cells
    key = (K, round(radius_cells, 6))
    d = _DISKS.get(key)
    if d is None:
        yy, xx = np.ogrid[-K:K + 1, -K:K + 1]
        d = _DISKS[key] = (np.hypot(yy, xx) <= radius_cells)
    return d, K


def _disk_window(radius_cells, rc, cc, r0, c0, h, w):
    """Slice of the cached disk centred at (rc, cc) covering rows r0..r0+h, cols c0..c0+w."""
    d, K = _disk(radius_cells)
    return d[r0 - rc + K:r0 - rc + K + h, c0 - cc + K:c0 - cc + K + w]


def viewshed_multires(dem, shared, coarse, x, y, alt_msl, radius, r_near, target_h=0.0):
    """Exact 30 m viewshed within r_near, coarse viewshed (upsampled) from r_near to radius."""
    c, r = dem.to_pixel(x, y)
    rc, cc = int(round(r)), int(round(c))
    ox, oy = dem.to_world(cc, rc)
    h = max(float(alt_msl - dem.z[rc, cc]), 1.0)
    # far field on the coarse grid: observer at the same altitude above sea level
    k = coarse.k
    kr, kc = min(rc // k, coarse.z.shape[0] - 1), min(cc // k, coarse.z.shape[1] - 1)
    hk = max(float(alt_msl - coarse.z[kr, kc]), 1.0)
    cxk = coarse.gt[0] + (kc + 0.5) * coarse.gt[1]; cyk = coarse.gt[3] + (kr + 0.5) * coarse.gt[5]
    k0, kr0, kv = _viewshed(coarse.shared.band(), coarse.gt, cxk, cyk, hk, target_h, radius)
    a, b = kv.shape
    vis = np.broadcast_to(kv[:, None, :, None], (a, k, b, k)).reshape(a * k, b * k)   # one-pass upsample
    c0, r0 = k0 * k, kr0 * k
    vis = vis[:dem.shape[0] - r0, :dem.shape[1] - c0]
    # cells of the coarse block beyond the radius (block edges overshoot the circle)
    vis &= _disk_window(radius / dem.cell, rc, cc, r0, c0, *vis.shape)
    # near field, exact, written over the coarse answer inside r_near
    nc0, nr0, nv = _viewshed(shared.band(), dem.gt, ox, oy, h, target_h, r_near)
    ra, rb = max(nr0, r0), min(nr0 + nv.shape[0], r0 + vis.shape[0])
    ca, cb = max(nc0, c0), min(nc0 + nv.shape[1], c0 + vis.shape[1])
    inside = _disk_window(r_near / dem.cell, rc, cc, ra, ca, rb - ra, cb - ca)
    sub = vis[ra - r0:rb - r0, ca - c0:cb - c0]
    np.copyto(sub, nv[ra - nr0:rb - nr0, ca - nc0:cb - nc0], where=inside)
    return c0, r0, vis


# --------------------------------------------------------------------------- tiled accumulator
class TiledAccumulator:
    """Same interface as visibility.Accumulator, but stores count / first-seen per tile on demand."""

    def __init__(self, shape, cell, tile=256):
        self.shape, self.cell, self.T = shape, cell, tile
        self.tiles = {}                     # (ti, tj) -> [count uint16, first int32]
        self.per_wp = []

    def add(self, idx, c0, r0, vis):
        T = self.T
        h, w = vis.shape
        a = self.cell ** 2 / 1e6
        nvis = nnew = 0
        for ti in range(r0 // T, (r0 + h - 1) // T + 1):
            for tj in range(c0 // T, (c0 + w - 1) // T + 1):
                ra, rb = max(r0, ti * T), min(r0 + h, (ti + 1) * T)
                ca, cb = max(c0, tj * T), min(c0 + w, (tj + 1) * T)
                v = vis[ra - r0:rb - r0, ca - c0:cb - c0]
                if not v.any():
                    continue
                t = self.tiles.get((ti, tj))
                if t is None:
                    th, tw = min(T, self.shape[0] - ti * T), min(T, self.shape[1] - tj * T)
                    t = self.tiles[(ti, tj)] = [np.zeros((th, tw), np.uint16), np.full((th, tw), -1, np.int32)]
                cnt = t[0][ra - ti * T:rb - ti * T, ca - tj * T:cb - tj * T]
                fst = t[1][ra - ti * T:rb - ti * T, ca - tj * T:cb - tj * T]
                new = v & (cnt == 0)
                fst[new] = idx
                cnt += v
                nvis += int(v.sum()); nnew += int(new.sum())
        self.per_wp.append((idx, nvis * a, nnew * a))

    @property
    def count(self):
        out = np.zeros(self.shape, np.uint16)
        for (ti, tj), (c, _) in self.tiles.items():
            out[ti * self.T:ti * self.T + c.shape[0], tj * self.T:tj * self.T + c.shape[1]] = c
        return out

    def seen_cells(self):
        return sum(int((c > 0).sum()) for c, _ in self.tiles.values())

    def mem_mb(self):
        return sum(c.nbytes + f.nbytes for c, f in self.tiles.values()) / 2 ** 20


# --------------------------------------------------------------------------- route driver
def run_route_fast(dem, pts, alt_fn, radius, mode="shared_threads", workers=12, k=3, r_near=5000.0,
                   tiled=False, target_h=0.0):
    """mode: shared | shared_threads | multires | multires_threads.  Returns (accumulator, info)."""
    t0 = time.perf_counter()
    acc = TiledAccumulator(dem.shape, dem.cell) if tiled else Accumulator(dem.shape, dem.cell)
    shared = SharedDEM(dem.z, dem.gt, dem.proj)
    coarse = Coarse(dem, k) if mode.startswith("multires") else None
    alts = alt_fn(pts[:, 2])

    def one(i):
        x, y = pts[i, 0], pts[i, 1]
        if coarse is not None:
            return viewshed_multires(dem, shared, coarse, x, y, alts[i], radius, r_near, target_h)
        return viewshed_shared(dem, shared, x, y, alts[i], radius, target_h)

    if mode.endswith("threads"):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, (c0, r0, vis) in enumerate(ex.map(one, range(len(pts)))):
                acc.add(i, c0, r0, vis)
    else:
        for i in range(len(pts)):
            acc.add(i, *one(i))
    return acc, {"viewsheds": len(pts), "compute_s": time.perf_counter() - t0,
                 "coarse_build_s": coarse.build_s if coarse else 0.0}
