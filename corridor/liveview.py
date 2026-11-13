"""Pan and zoom on the fly: radar coverage computed for the visible window only, at screen resolution.

Track 1 computes the cumulative viewshed (how many radars see an aircraft 150 m above each cell) for the
whole DEM at full resolution.  An interactive map never shows all of that at once: zoomed out, one
screen pixel covers many cells; zoomed in, only a small window is visible.  LiveCoverage answers every
pan / zoom with exactly what the screen can show:

  level of detail   a DEM pyramid (2x2 block means: 30 m, 60 m, 120 m ... 960 m).  For a view w x h cells
                    drawn on a canvas of px_w x px_h pixels the level is the finest k (power of two) with
                    w / k <= px_w * density and h / k <= px_h * density, i.e. about one computed cell per pixel.
  window            for each radar the viewshed runs on the box spanning the radar and the visible window,
                    clipped to the radar's range square (terrain between the radar and the view matters,
                    terrain beyond the view does not); radars whose range does not reach the view are skipped.
  parallel          one GDAL viewshed per radar, run on a thread pool (GDAL releases the GIL).

Cost per view is therefore bounded by the canvas size, not the DEM size: a 16 M-cell DEM and a 1 M-cell
DEM cost the same when zoomed out to the full extent.  When a radar moves, only the current view is
recomputed (the full-DEM coverage is not needed to redraw the screen).
"""
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from osgeo import gdal, gdal_array

from common.config import CURV_COEFF, RADAR_HEIGHT, TARGET_AIRCRAFT, VISIBLE, INVISIBLE, OUT_OF_RANGE

gdal.UseExceptions()

RANGE = 40000.0
ND = -9999.0


class LiveCoverage:
    def __init__(self, dem, radar_h=RADAR_HEIGHT, target_h=TARGET_AIRCRAFT, rng=RANGE, max_level=64, threads=None):
        self.dem, self.radar_h, self.target_h, self.rng = dem, radar_h, target_h, rng
        self.H, self.W = dem.shape
        self.cell = dem.cell
        self.threads = threads or min(12, os.cpu_count() or 4)
        self.pool = ThreadPoolExecutor(self.threads)
        t = time.perf_counter()
        z = np.where(np.isnan(dem.z), ND, dem.z).astype(np.float32)
        self.levels = {1: z}
        k = 1
        while k < max_level and min(z.shape) >= 64:
            h, w = z.shape[0] // 2 * 2, z.shape[1] // 2 * 2
            b = z[:h, :w].reshape(h // 2, 2, w // 2, 2)
            valid = b > ND / 2
            n = valid.sum(axis=(1, 3))
            s = np.where(valid, b, 0).sum(axis=(1, 3))
            z = np.where(n > 0, s / np.maximum(n, 1), ND).astype(np.float32)
            k *= 2
            self.levels[k] = z
        self.pyramid_s = time.perf_counter() - t
        self.pyramid_mb = sum(a.nbytes for k, a in self.levels.items() if k > 1) / 2 ** 20

    # ---------------------------------------------------------------- level of detail
    def level_for(self, view, px, density=1.0):
        """view = (r0, r1, c0, c1) full-resolution cells, px = (width, height) canvas pixels."""
        r0, r1, c0, c1 = view
        need = max((c1 - c0) / (px[0] * density), (r1 - r0) / (px[1] * density), 1.0)
        k = 2 ** math.ceil(math.log2(need) - 1e-9)
        return min(k, max(self.levels))

    # ---------------------------------------------------------------- one radar
    def _one(self, k, site, vbox):
        z = self.levels[k]
        Hk, Wk = z.shape
        ck_ = self.cell * k
        gt = self.dem.gt
        x, y = site
        rk = int((gt[3] - y) / ck_); ck = int((x - gt[0]) / ck_)
        if not (0 <= rk < Hk and 0 <= ck < Wk):
            return None
        R = int(math.ceil(self.rng / ck_)) + 1
        vr0, vr1, vc0, vc1 = vbox
        # range square must reach the view
        if vr1 <= rk - R or vr0 >= rk + R + 1 or vc1 <= ck - R or vc0 >= ck + R + 1:
            return None
        r0 = max(0, rk - R, min(vr0, rk)); r1 = min(Hk, rk + R + 1, max(vr1, rk + 1))
        c0 = max(0, ck - R, min(vc0, ck)); c1 = min(Wk, ck + R + 1, max(vc1, ck + 1))
        sub = np.ascontiguousarray(z[r0:r1, c0:c1])
        ds = gdal_array.OpenArray(sub)
        ds.SetGeoTransform((gt[0] + c0 * ck_, ck_, 0, gt[3] - r0 * ck_, 0, -ck_))
        ds.SetProjection(self.dem.proj)            # GDAL takes the earth radius for curvature from the SRS
        ds.GetRasterBand(1).SetNoDataValue(ND)
        ox, oy = gt[0] + (ck + 0.5) * ck_, gt[3] - (rk + 0.5) * ck_
        out = gdal.ViewshedGenerate(ds.GetRasterBand(1), "MEM", "", [], ox, oy, self.radar_h, self.target_h,
                                    VISIBLE, INVISIBLE, OUT_OF_RANGE, OUT_OF_RANGE, CURV_COEFF, gdal.GVM_Edge, self.rng)
        vis = out.GetRasterBand(1).ReadAsArray() == VISIBLE
        g = out.GetGeoTransform()
        orow = int(round((gt[3] - g[3]) / ck_)); ocol = int(round((g[0] - gt[0]) / ck_))
        # intersect with the view
        a0, a1 = max(orow, vr0), min(orow + vis.shape[0], vr1)
        b0, b1 = max(ocol, vc0), min(ocol + vis.shape[1], vc1)
        if a0 >= a1 or b0 >= b1:
            return None
        return (a0 - vr0, b0 - vc0, vis[a0 - orow:a1 - orow, b0 - ocol:b1 - ocol], sub.size)

    # ---------------------------------------------------------------- one view
    def compute(self, sites, view, px, density=1.0, level=None):
        """Coverage count (uint8, radars that see the aircraft) for the view at the chosen level.

        Returns dict(count, level, box (full-res r0, r1, c0, c1 covered by count), gt, ms, cells, radars)."""
        t = time.perf_counter()
        r0, r1, c0, c1 = (max(0, view[0]), min(self.H, view[1]), max(0, view[2]), min(self.W, view[3]))
        k = level or self.level_for((r0, r1, c0, c1), px, density)
        vbox = (r0 // k, -(-r1 // k), c0 // k, -(-c1 // k))
        Hk, Wk = self.levels[k].shape
        vbox = (vbox[0], min(vbox[1], Hk), vbox[2], min(vbox[3], Wk))
        count = np.zeros((vbox[1] - vbox[0], vbox[3] - vbox[2]), np.uint8)
        parts = list(self.pool.map(lambda s: self._one(k, s, vbox), sites))
        cells, used = 0, 0
        for p in parts:
            if p is None:
                continue
            a, b, vis, n = p
            count[a:a + vis.shape[0], b:b + vis.shape[1]] += vis
            cells += n; used += 1
        gt = self.dem.gt
        ck_ = self.cell * k
        return {"count": count, "level": k, "box": (vbox[0] * k, vbox[1] * k, vbox[2] * k, vbox[3] * k),
                "gt": (gt[0] + vbox[2] * ck_, ck_, 0, gt[3] - vbox[0] * ck_, 0, -ck_),
                "ms": 1000 * (time.perf_counter() - t), "cells": cells, "radars": used}

    def close(self):
        self.pool.shutdown(wait=False)


def upsample(count, k, shape):
    """Nearest-neighbour expansion of a level-k result to full resolution (for accuracy checks)."""
    return np.repeat(np.repeat(count, k, axis=0), k, axis=1)[:shape[0], :shape[1]]
