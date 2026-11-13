"""Track 2 - visibility from a moving aircraft.

The route is sampled into observer positions; a viewshed (GDAL C++ engine, curvature and
refraction as in common/config) is computed at each, and the results are aggregated:

  count       how many sampled positions see each cell (uint16)
  first_seen  index of the first position that sees the cell (-1 = never)
  per_wp      visible km^2 and newly-seen km^2 at each position
  blind       cells inside the sensor corridor (<= radius from the route) never seen

Execution modes (all give identical results except 'adaptive'):
  baseline       re-open the DEM file and run on the full raster at every position
  cached         DEM loaded once into memory, full raster each time
  window         DEM cached, each viewshed runs on the window covering its radius only
  parallel       'window' split over worker processes
  adaptive       'window' with adaptive sampling: start coarse, refine where consecutive
                 viewsheds differ (Jaccard < tau)
"""
import time
import numpy as np
from osgeo import gdal

from common.config import CURV_COEFF, VISIBLE, INVISIBLE, OUT_OF_RANGE, dem_path
from common.dem_utils import DEM
from flight.route import resample, altitude_profile

gdal.UseExceptions()


class AltitudeModel:
    """Altitude along the route from a dense (100 m) profile, so every sampling density sees the
    same flight path."""

    def __init__(self, dem, vertices, mode="agl", agl=300.0, msl=None):
        dense = resample(vertices, 100.0)
        alt, ground, clear = altitude_profile(dem, dense, mode, agl, msl, spacing=100.0)
        self.s, self.alt, self.ground = dense[:, 2], alt, ground

    def __call__(self, s):
        return np.interp(s, self.s, self.alt)


def _mem_ds(z, gt, proj):
    ds = gdal.GetDriverByName("MEM").Create("", z.shape[1], z.shape[0], 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt); ds.SetProjection(proj)
    b = ds.GetRasterBand(1); b.WriteArray(np.where(np.isnan(z), -9999.0, z)); b.SetNoDataValue(-9999.0)
    return ds


def _window(dem, x, y, radius):
    c, r = dem.to_pixel(x, y)
    k = int(np.ceil(radius / dem.cell)) + 2
    c0 = max(int(c) - k, 0); r0 = max(int(r) - k, 0)
    c1 = min(int(c) + k + 1, dem.shape[1]); r1 = min(int(r) + k + 1, dem.shape[0])
    return c0, r0, c1, r1


def viewshed_at(dem, x, y, alt_msl, radius, target_h=0.0, mode="window", src=None):
    """Return (c0, r0, visible bool array) for one aircraft position."""
    c, r = dem.to_pixel(x, y)
    zc = dem.z[int(round(r)), int(round(c))]
    h = max(float(alt_msl - zc), 1.0)                      # GDAL wants height above the observer cell
    if mode == "baseline":
        ds = gdal.Open(dem.path); c0 = r0 = 0
    elif mode == "cached":
        ds = src; c0 = r0 = 0
    else:
        c0, r0, c1, r1 = _window(dem, x, y, radius if radius > 0 else 1e12)
        gt = (dem.gt[0] + c0 * dem.gt[1], dem.gt[1], 0, dem.gt[3] + r0 * dem.gt[5], 0, dem.gt[5])
        ds = _mem_ds(dem.z[r0:r1, c0:c1], gt, dem.proj)
    out = gdal.ViewshedGenerate(ds.GetRasterBand(1), "MEM", "", None, *dem.to_world(round(c), round(r)), h, target_h,
                                VISIBLE, INVISIBLE, OUT_OF_RANGE, OUT_OF_RANGE, CURV_COEFF, gdal.GVM_Edge,
                                max(radius, 0.0))
    a = out.GetRasterBand(1).ReadAsArray()
    ogt = out.GetGeoTransform()
    oc = int(round((ogt[0] - dem.gt[0]) / dem.gt[1])); orr = int(round((ogt[3] - dem.gt[3]) / dem.gt[5]))
    return oc, orr, a == VISIBLE


class Accumulator:
    def __init__(self, shape, cell):
        self.count = np.zeros(shape, np.uint16)
        self.first = np.full(shape, -1, np.int32)
        self.cell = cell
        self.per_wp = []

    def add(self, idx, c0, r0, vis):
        h, w = vis.shape
        cnt = self.count[r0:r0 + h, c0:c0 + w]
        fst = self.first[r0:r0 + h, c0:c0 + w]
        new = vis & (cnt == 0)
        fst[new] = idx
        cnt += vis
        a = self.cell ** 2 / 1e6
        self.per_wp.append((idx, float(vis.sum() * a), float(new.sum() * a)))


def run_route(dem, pts, alt_fn, radius, mode="window", target_h=0.0, workers=8):
    """pts: (n, 3) array x, y, s.  Returns Accumulator and timing dict."""
    acc = Accumulator(dem.shape, dem.cell)
    t0 = time.perf_counter()
    src = _mem_ds(dem.z, dem.gt, dem.proj) if mode == "cached" else None
    alts = alt_fn(pts[:, 2])
    if mode == "threads":
        # GDAL releases the GIL inside ViewshedGenerate: threads share the DEM, no process start-up,
        # no copying results between processes; results are accumulated in order as they arrive
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, (c0, r0, vis) in enumerate(ex.map(lambda k: viewshed_at(dem, pts[k, 0], pts[k, 1], alts[k], radius,
                                                                            target_h, "window"), range(len(pts)))):
                acc.add(i, c0, r0, vis)
    elif mode == "parallel":
        from concurrent.futures import ProcessPoolExecutor
        chunks = np.array_split(np.arange(len(pts)), min(workers, len(pts)))
        args = [(dem.path, dem.gt, pts[ix], alts[ix], ix, radius, target_h) for ix in chunks if len(ix)]
        with ProcessPoolExecutor(max_workers=len(args)) as ex:
            for part in ex.map(_worker, args):
                for idx, c0, r0, vis in part:
                    acc.add(idx, c0, r0, vis)
        acc.per_wp.sort()
    else:
        for i, (x, y, s) in enumerate(pts):
            c0, r0, vis = viewshed_at(dem, x, y, alts[i], radius, target_h, mode, src)
            acc.add(i, c0, r0, vis)
    return acc, {"viewsheds": len(pts), "compute_s": time.perf_counter() - t0}


def _worker(args):
    path, gt, pts, alts, ix, radius, target_h = args
    dem = DEM(path)
    out = []
    for k in range(len(pts)):
        c0, r0, vis = viewshed_at(dem, pts[k, 0], pts[k, 1], alts[k], radius, target_h, "window")
        out.append((int(ix[k]), c0, r0, vis))
    return out


def run_adaptive(dem, vertices, alt_fn, radius, coarse=4000.0, finest=250.0, tau=0.85, target_h=0.0,
                 criterion="similarity", eps=0.05):
    """Adaptive sampling.  Start every `coarse` m and refine a gap by inserting its midpoint:
      similarity  refine when the two end viewsheds have Jaccard similarity < tau (first version;
                  in a winding valley neighbouring views always differ, so it refines everywhere)
      gain        always look at the midpoint once, but keep refining that gap only if the midpoint
                  sees new ground: more than eps of its visible cells unseen from both ends.
    Stops at `finest` spacing."""
    t0 = time.perf_counter()
    base = resample(vertices, coarse)
    cache = {}

    def vs(s):
        if s not in cache:
            x = np.interp(s, base[:, 2], base[:, 0]); y = np.interp(s, base[:, 2], base[:, 1])
            cache[s] = (x, y) + viewshed_at(dem, x, y, float(alt_fn(np.array([s]))[0]), radius, target_h, "window")
        return cache[s]

    def jaccard(a, b):
        _, _, ac, ar, av = a; _, _, bc, br, bv = b
        c0, r0 = min(ac, bc), min(ar, br)
        c1 = max(ac + av.shape[1], bc + bv.shape[1]); r1 = max(ar + av.shape[0], br + bv.shape[0])
        A = np.zeros((r1 - r0, c1 - c0), bool); B = np.zeros_like(A)
        A[ar - r0:ar - r0 + av.shape[0], ac - c0:ac - c0 + av.shape[1]] = av
        B[br - r0:br - r0 + bv.shape[0], bc - c0:bc - c0 + bv.shape[1]] = bv
        u = (A | B).sum()
        return (A & B).sum() / u if u else 1.0

    def gain(a, b, m):
        """Share of the midpoint's visible cells that neither end sees."""
        _, _, mc, mr, mv = m
        seen = np.zeros_like(mv)
        for _, _, c, r, v in (a, b):
            r0, r1 = max(r, mr), min(r + v.shape[0], mr + mv.shape[0])
            c0, c1 = max(c, mc), min(c + v.shape[1], mc + mv.shape[1])
            if r1 > r0 and c1 > c0:
                seen[r0 - mr:r1 - mr, c0 - mc:c1 - mc] |= v[r0 - r:r1 - r, c0 - c:c1 - c]
        n = mv.sum()
        return float((mv & ~seen).sum() / n) if n else 0.0

    stack = [(base[i, 2], base[i + 1, 2]) for i in range(len(base) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a <= finest * 1.01:
            continue
        m = (a + b) / 2
        if criterion == "gain":
            if gain(vs(a), vs(b), vs(m)) > eps:
                stack += [(a, m), (m, b)]
        elif jaccard(vs(a), vs(b)) < tau:
            vs(m)
            stack += [(a, m), (m, b)]
    ss = sorted(cache)
    acc = Accumulator(dem.shape, dem.cell)
    for i, s in enumerate(ss):
        x, y, c0, r0, vis = cache[s]
        acc.add(i, c0, r0, vis)
    pts = np.array([[cache[s][0], cache[s][1], s] for s in ss])
    return acc, pts, {"viewsheds": len(ss), "compute_s": time.perf_counter() - t0}


def corridor_mask(dem, pts, radius):
    """Cells within `radius` of the sampled route (the area the sensor could cover)."""
    from scipy.ndimage import distance_transform_edt
    m = np.ones(dem.shape, bool)
    dense = pts
    c, r = dem.to_pixel(dense[:, 0], dense[:, 1])
    ok = (c >= 0) & (c < dem.shape[1]) & (r >= 0) & (r < dem.shape[0])
    m[np.rint(r[ok]).astype(int), np.rint(c[ok]).astype(int)] = False
    d = distance_transform_edt(m) * dem.cell
    return d <= radius
