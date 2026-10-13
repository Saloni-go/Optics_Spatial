"""Track 3 - radar threat surface that can be updated one radar at a time.

Each radar contributes only inside its range window, so the surface is kept as a sum of per-radar
windows.  Moving, adding or removing a radar recomputes one viewshed (GDAL, ~0.1 s on the 16 M-cell
DEM) and reports exactly which cells changed, which is what the incremental route repair needs.

Two threat models, both additive per cell so the same route solvers apply:

  exposure   (as before)   E = sum over radars that see the aircraft of (1 - d / range)

  detection  (new)         each radar that sees the aircraft detects it with probability p(d) per
                           kilometre flown, p(d) = p_max / (1 + (d / d50)^4) (radar-equation-like fall-off
                           with the fourth power of range).  The chance of staying undetected over a
                           route is the product of (1 - p) over every kilometre and radar, so
                               -ln P(undetected) = sum over the route of length_km * H(cell),
                               H = sum over radars of -ln(1 - p_r(d))
                           H is additive; minimising distance + alpha * (length x H) trades distance
                           against the log-probability of detection, and
                               P(detected) = 1 - exp(-sum(length_km x H)).
"""
import time
import numpy as np
from osgeo import gdal

from common.config import CURV_COEFF, RADAR_HEIGHT, TARGET_AIRCRAFT, VISIBLE, INVISIBLE, OUT_OF_RANGE

gdal.UseExceptions()

RANGE = 40000.0
P_MAX, D50 = 0.5, 20000.0          # detection model: 50% per km at close range, halved at 20 km


class RadarField:
    def __init__(self, dem, sites, mode="exposure", radar_h=RADAR_HEIGHT, target_h=TARGET_AIRCRAFT, rng=RANGE):
        self.dem, self.mode, self.radar_h, self.target_h, self.rng = dem, mode, radar_h, target_h, rng
        self.ds = dem.gdal_dataset()
        self.E = np.zeros(dem.shape, np.float64)
        self.sites, self.contrib = [], []
        for x, y in sites:
            self.add(x, y)

    # ---------------------------------------------------------------- one radar
    def _contribution(self, x, y):
        dem = self.dem
        c, r = dem.to_pixel(x, y)
        c, r = int(round(c)), int(round(r))
        cx, cy = dem.to_world(c, r)
        out = gdal.ViewshedGenerate(self.ds.GetRasterBand(1), "MEM", "", [], cx, cy, self.radar_h, self.target_h,
                                    VISIBLE, INVISIBLE, OUT_OF_RANGE, OUT_OF_RANGE, CURV_COEFF, gdal.GVM_Edge, self.rng)
        vis = out.GetRasterBand(1).ReadAsArray() == VISIBLE
        g = out.GetGeoTransform()
        c0 = int(round((g[0] - dem.gt[0]) / dem.gt[1])); r0 = int(round((g[3] - dem.gt[3]) / dem.gt[5]))
        rr, cc = np.mgrid[r0:r0 + vis.shape[0], c0:c0 + vis.shape[1]]
        d = np.hypot(cc - c, rr - r) * dem.cell
        if self.mode == "detection":
            p = P_MAX / (1.0 + (d / D50) ** 4)
            val = -np.log1p(-np.clip(p, 0, 0.999))
        else:
            val = np.clip(1.0 - d / self.rng, 0, 1)
        return r0, c0, np.where(vis, val, 0.0)

    def _apply(self, contrib, sign):
        r0, c0, a = contrib
        self.E[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] += sign * a

    # ---------------------------------------------------------------- edits
    # Each edit returns (changed, seconds): changed is a uint8 H x W mask with 1 where the threat went
    # up (or both ways) and 2 where it only went down, the form CostToGo.repair() expects.
    def add(self, x, y):
        t = time.perf_counter()
        cb = self._contribution(x, y)
        box = self._box([cb]); before = self.E[box].copy()
        self._apply(cb, +1)
        self.sites.append((x, y)); self.contrib.append(cb)
        return self._changed(box, before), time.perf_counter() - t

    def remove(self, i):
        t = time.perf_counter()
        cb = self.contrib.pop(i); self.sites.pop(i)
        box = self._box([cb]); before = self.E[box].copy()
        self._apply(cb, -1)
        np.maximum(self.E, 0, out=self.E)              # clear float round-off
        return self._changed(box, before), time.perf_counter() - t

    def move(self, i, x, y):
        t = time.perf_counter()
        old = self.contrib[i]
        new = self._contribution(x, y)
        box = self._box([old, new]); before = self.E[box].copy()
        self._apply(old, -1); self._apply(new, +1)
        np.maximum(self.E, 0, out=self.E)
        self.sites[i] = (x, y); self.contrib[i] = new
        return self._changed(box, before), time.perf_counter() - t

    @staticmethod
    def _box(cbs):
        r0 = min(c[0] for c in cbs); c0 = min(c[1] for c in cbs)
        r1 = max(c[0] + c[2].shape[0] for c in cbs); c1 = max(c[1] + c[2].shape[1] for c in cbs)
        return (slice(r0, r1), slice(c0, c1))

    def _changed(self, box, before, tol=1e-12):
        m = np.zeros(self.dem.shape, np.uint8)
        d = self.E[box] - before
        sub = m[box]
        sub[d > tol] = 1
        sub[d < -tol] = 2
        return m

    # ---------------------------------------------------------------- route metrics
    def detection_probability(self, path, W, cell):
        """P(detected) along a route under the detection model (needs mode='detection')."""
        if path is None:
            return None
        rc = np.array([divmod(i, W) for i in path])
        h = self.E[rc[:, 0], rc[:, 1]]
        seg_km = np.hypot(*np.diff(rc, axis=0).T) * cell / 1000.0
        return float(1.0 - np.exp(-(seg_km * 0.5 * (h[1:] + h[:-1])).sum()))
