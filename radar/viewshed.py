"""Track 1 - viewshed algorithms for a stationary radar / observer.

All three algorithms answer the same question with the same physical model:
  * observer at the centre of the cell containing (x, y), eye at ground + observer_h
  * a cell is visible if its point at ground + target_h can be seen
  * Earth curvature with refraction: elevation drop = curv * d^2 / (2 R)
  * cells farther than max_dist (m) are OUT_OF_RANGE (max_dist <= 0 means unlimited)
Output: uint8 array, VISIBLE=1, INVISIBLE=0, OUT_OF_RANGE=255 (no-data cells -> 255 too).

  naive_los   exact line of sight to every cell, sampling the profile every half cell with
              bilinear interpolation.  O(N * R) for N cells and R cells of radius.  Reference.
  r2          R2 ray casting (Franklin & Ray 1994): rays from the observer to every cell on the
              (each cell takes the answer of the ray passing closest to its centre)
              boundary, one horizon per ray.  O(R^2) = O(N).  Vectorised over rays with numpy.
  gdal        GDAL ViewshedGenerate (C++, Wang et al. 2000 reference-plane algorithm), O(N).
"""
import numpy as np
from osgeo import gdal

from common.config import EARTH_R, CURV_COEFF, VISIBLE, INVISIBLE, OUT_OF_RANGE
from common.dem_utils import DEM, bilinear

gdal.UseExceptions()


def _observer(dem, x, y, observer_h):
    c, r = dem.to_pixel(x, y)
    oc, orow = int(round(c)), int(round(r))
    if not (0 <= oc < dem.shape[1] and 0 <= orow < dem.shape[0]):
        raise ValueError("observer outside DEM")
    zo = float(dem.z[orow, oc]) + observer_h
    return oc, orow, zo


def _drop(d_m, curvature):
    return CURV_COEFF * d_m ** 2 / (2 * EARTH_R) if curvature else 0.0


# --------------------------------------------------------------------------- naive
def naive_los(dem, x, y, observer_h, target_h=0.0, max_dist=0.0, curvature=True, step=0.5, budget=4e6):
    nr, nc = dem.shape
    oc, orow, zo = _observer(dem, x, y, observer_h)
    cell = dem.cell
    rr, cc = np.mgrid[0:nr, 0:nc]
    dcell = np.hypot(cc - oc, rr - orow)
    out = np.full((nr, nc), OUT_OF_RANGE, np.uint8)
    inr = np.ones_like(dcell, bool) if max_dist <= 0 else (dcell * cell <= max_dist)
    inr &= ~np.isnan(dem.z)
    out[orow, oc] = VISIBLE
    inr[orow, oc] = False
    tr, tc = rr[inr], cc[inr]
    td = dcell[inr]
    order = np.argsort(td)
    tr, tc, td = tr[order], tc[order], td[order]
    tz = dem.z[tr, tc] + target_h - _drop(td * cell, curvature)
    tslope = (tz - zo) / (td * cell)
    vis = np.empty(len(tr), bool)
    n = len(tr)
    i = 0
    while i < n:
        # targets are sorted by distance; pick a chunk whose (targets x samples) fits the budget
        k = max(1, int(budget // max(np.ceil(td[i] / step), 1)))
        while k > 1 and k * np.ceil(td[min(i + k, n) - 1] / step) > budget:
            k //= 2
        j = min(i + k, n)
        nsamp = max(int(np.ceil(td[j - 1] / step)), 2)
        f = (np.arange(1, nsamp) / nsamp)[None, :]          # fractions along the segment, endpoints excluded
        sc = oc + (tc[i:j, None] - oc) * f
        sr = orow + (tr[i:j, None] - orow) * f
        sd = td[i:j, None] * f * cell
        sz = bilinear(dem.z, sc, sr) - _drop(sd, curvature)
        s = (sz - zo) / sd
        vis[i:j] = tslope[i:j] >= s.max(axis=1)
        i = j
    out[tr, tc] = np.where(vis, VISIBLE, INVISIBLE)
    return out


# ------------------------------------------------------------------------------ R2
def r2(dem, x, y, observer_h, target_h=0.0, max_dist=0.0, curvature=True):
    nr, nc = dem.shape
    oc, orow, zo = _observer(dem, x, y, observer_h)
    cell = dem.cell
    if max_dist > 0:
        R = int(np.ceil(max_dist / cell))
    else:
        R = max(oc, nc - 1 - oc, orow, nr - 1 - orow)
    # boundary cells of the square of Chebyshev radius R -> 8R rays
    a = np.arange(-R, R + 1)
    b = np.arange(-R + 1, R)
    dx = np.concatenate([a, a, np.full(b.size, -R), np.full(b.size, R)]).astype(np.float64)
    dy = np.concatenate([np.full(a.size, -R), np.full(a.size, R), b, b]).astype(np.float64)
    seglen = np.hypot(dx, dy) / R * cell                      # metres per step along each ray
    horizon = np.full(dx.size, -np.inf)
    alive = np.ones(dx.size, bool)
    vis = np.zeros((nr, nc), bool)
    # Several rays cross most cells.  The cell takes the answer of the ray that passes closest to its
    # centre (best = that ray's offset in cells; inf = no ray yet).  "Visible if any ray sees it" was
    # biased: about 20x more false-visible than false-hidden cells, visible area ~8% too high.
    best = np.full((nr, nc), np.inf, np.float32)
    vflat, bflat = vis.ravel(), best.ravel()
    z = dem.z
    for i in range(1, R + 1):
        c = oc + dx * (i / R)
        r = orow + dy * (i / R)
        alive &= (c >= 0) & (c <= nc - 1) & (r >= 0) & (r <= nr - 1)
        if not alive.any():
            break
        ca, ra = c[alive], r[alive]
        d = seglen[alive] * i
        zs = bilinear(z, ca, ra) - _drop(d, curvature)          # terrain along the ray
        ic, ir = np.rint(ca).astype(np.int64), np.rint(ra).astype(np.int64)
        # the ray point lies inside cell (ir, ic): test the interpolated surface at that point,
        # which is consistent with the horizon built from the same interpolation
        ok = (zs + target_h - zo) / d >= horizon[alive]
        off = np.hypot(ca - ic, ra - ir).astype(np.float32)
        idx = ir * nc + ic
        sel = np.nonzero(off < bflat[idx])[0]
        sel = sel[np.argsort(off[sel])[::-1]]                    # closest written last, so it wins ties
        bflat[idx[sel]] = off[sel]
        vflat[idx[sel]] = ok[sel]
        horizon[alive] = np.maximum(horizon[alive], (zs - zo) / d)
    out = np.where(vis, VISIBLE, INVISIBLE).astype(np.uint8)
    out[~np.isfinite(best)] = OUT_OF_RANGE
    out[orow, oc] = VISIBLE
    _apply_range(out, dem, oc, orow, max_dist)
    return out


def _apply_range(out, dem, oc, orow, max_dist):
    """Mark cells beyond max_dist (only the bounding window needs the distance test; the rest of
    the grid is already OUT_OF_RANGE) and no-data cells."""
    if max_dist > 0:
        k = int(np.ceil(max_dist / dem.cell)) + 1
        r0, r1 = max(orow - k, 0), min(orow + k + 1, dem.shape[0])
        c0, c1 = max(oc - k, 0), min(oc + k + 1, dem.shape[1])
        rr, cc = np.ogrid[r0:r1, c0:c1]
        sub = out[r0:r1, c0:c1]
        sub[(np.hypot(cc - oc, rr - orow) * dem.cell) > max_dist] = OUT_OF_RANGE
    if dem.has_nodata:
        out[np.isnan(dem.z)] = OUT_OF_RANGE


# ---------------------------------------------------------------------------- GDAL
def gdal_viewshed(dem, x, y, observer_h, target_h=0.0, max_dist=0.0, curvature=True, src_path=None):
    """Runs GDAL's C++ viewshed on the DEM file (or an in-memory copy of dem.z)."""
    oc, orow, _ = _observer(dem, x, y, observer_h)
    cx, cy = dem.to_world(oc, orow)                              # same observer cell as the others
    src = dem.gdal_dataset()          # zero-copy view of the in-memory DEM
    band = src.GetRasterBand(1)
    ds = gdal.ViewshedGenerate(band, "MEM", "", None, cx, cy, observer_h, target_h,
                               VISIBLE, INVISIBLE, OUT_OF_RANGE, OUT_OF_RANGE,
                               CURV_COEFF if curvature else 0.0, gdal.GVM_Edge, max(max_dist, 0.0))
    arr = ds.GetRasterBand(1).ReadAsArray()
    ogt = ds.GetGeoTransform()
    out = np.full(dem.shape, OUT_OF_RANGE, np.uint8)
    c0 = int(round((ogt[0] - dem.gt[0]) / dem.gt[1])); r0 = int(round((ogt[3] - dem.gt[3]) / dem.gt[5]))
    out[r0:r0 + arr.shape[0], c0:c0 + arr.shape[1]] = arr
    _apply_range(out, dem, oc, orow, max_dist)
    return out


ALGORITHMS = {"naive": naive_los, "r2": r2, "gdal": gdal_viewshed}


def viewshed(algorithm, dem, x, y, observer_h, target_h=0.0, max_dist=0.0, curvature=True):
    return ALGORITHMS[algorithm](dem, x, y, observer_h, target_h, max_dist, curvature)


def window_for(dem_path, x, y, max_dist, pad=2):
    """Pixel window that just covers a circle of radius max_dist (region clipping)."""
    ds = gdal.Open(str(dem_path)); gt = ds.GetGeoTransform()
    c = (x - gt[0]) / gt[1]; r = (y - gt[3]) / gt[5]
    k = int(np.ceil(max_dist / gt[1])) + pad
    xo = max(int(c) - k, 0); yo = max(int(r) - k, 0)
    xe = min(int(c) + k + 1, ds.RasterXSize); ye = min(int(r) + k + 1, ds.RasterYSize)
    return xo, yo, xe - xo, ye - yo


def agreement(a, b):
    """Agreement statistics between two viewsheds on the cells both consider in range."""
    m = (a != OUT_OF_RANGE) & (b != OUT_OF_RANGE)
    va, vb = a[m] == VISIBLE, b[m] == VISIBLE
    n = m.sum()
    agree = (va == vb).mean()
    pa, pb = va.mean(), vb.mean()
    pe = pa * pb + (1 - pa) * (1 - pb)
    kappa = (agree - pe) / (1 - pe) if pe < 1 else 1.0
    return {"cells": int(n), "agreement": float(agree), "kappa": float(kappa),
            "false_visible": float((vb & ~va).sum() / max(n, 1)), "false_hidden": float((~vb & va).sum() / max(n, 1)),
            "visible_frac_ref": float(pa), "visible_frac_test": float(pb)}
