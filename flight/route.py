"""Track 2 - flight routes: definition, resampling and altitude profiles."""
import numpy as np
from osgeo import osr

from common.config import CRS_EPSG

# Scenario route up the Alaknanda valley (lon, lat): near Devprayag -> Srinagar -> Rudraprayag ->
# Karnaprayag -> Chamoli -> Joshimath.  A plausible low-level helicopter route that stays in valleys.
ALAKNANDA = [(78.42, 30.10), (78.598, 30.146), (78.78, 30.222), (78.98, 30.285),
             (79.215, 30.262), (79.32, 30.405), (79.56, 30.555)]


def valley_route(dem, towns_utm, k=4, power=4.0, simplify_m=300.0):
    """Route that follows the valley floor between consecutive towns: least-cost path on a
    k-times coarser grid with cost per metre = (z / 1000)^power (strongly prefers low ground),
    then Douglas-Peucker simplified.  Returns list of (x, y)."""
    from scipy import sparse
    from scipy.sparse.csgraph import dijkstra
    H, W = dem.shape[0] // k, dem.shape[1] // k
    z = np.nan_to_num(dem.z[:H * k, :W * k], nan=9000).reshape(H, k, W, k).mean(axis=(1, 3))
    w = (z / 1000.0) ** power
    idx = np.arange(H * W).reshape(H, W)
    rows, cols, vals = [], [], []
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
        rs = slice(0, H - dr); rd = slice(dr, H)
        cs = slice(max(0, -dc), W - max(0, dc)); cd = slice(max(0, dc), W - max(0, -dc))
        L = np.hypot(dr, dc) * dem.cell * k
        c = L * 0.5 * (w[rs, cs] + w[rd, cd])
        a, b = idx[rs, cs].ravel(), idx[rd, cd].ravel()
        rows += [a, b]; cols += [b, a]; vals += [c.ravel(), c.ravel()]
    G = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(H * W, H * W))
    def node(x, y):
        c, r = dem.to_pixel(x, y)
        return int(min(max(r // k, 0), H - 1)) * W + int(min(max(c // k, 0), W - 1))
    path = []
    for (x0, y0), (x1, y1) in zip(towns_utm[:-1], towns_utm[1:]):
        s, t = node(x0, y0), node(x1, y1)
        _, pred = dijkstra(G, indices=s, return_predecessors=True)
        seg = [t]
        while seg[-1] != s:
            seg.append(pred[seg[-1]])
        seg = seg[::-1]
        path += seg if not path else seg[1:]
    pts = [dem.to_world(i % W * k + k / 2 - 0.5, i // W * k + k / 2 - 0.5) for i in path]
    pts[0], pts[-1] = tuple(towns_utm[0]), tuple(towns_utm[-1])
    return _douglas_peucker(pts, simplify_m)


def _douglas_peucker(pts, tol):
    p = np.asarray(pts, float)
    keep = np.zeros(len(p), bool); keep[0] = keep[-1] = True
    stack = [(0, len(p) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        d = p[b] - p[a]; n = np.hypot(*d) or 1.0
        dist = np.abs(d[0] * (p[a + 1:b, 1] - p[a, 1]) - d[1] * (p[a + 1:b, 0] - p[a, 0])) / n
        i = int(np.argmax(dist))
        if dist[i] > tol:
            m = a + 1 + i; keep[m] = True; stack += [(a, m), (m, b)]
    return [tuple(q) for q in p[keep]]


def load_route():
    """The scenario route (valley-following), built once by flight.run_flight."""
    import json
    from common.config import RESULTS
    f = RESULTS / "flight" / "route.geojson"
    return [tuple(c) for c in json.load(open(f))["features"][0]["geometry"]["coordinates"]]


def lonlat_to_utm(pts):
    src = osr.SpatialReference(); src.ImportFromEPSG(4326); src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst = osr.SpatialReference(); dst.ImportFromEPSG(CRS_EPSG)
    ct = osr.CoordinateTransformation(src, dst)
    return [ct.TransformPoint(lon, lat)[:2] for lon, lat in pts]


def length(vertices):
    v = np.asarray(vertices, float)
    return float(np.hypot(*np.diff(v, axis=0).T).sum())


def resample(vertices, spacing):
    """Points every `spacing` metres along the polyline (first and last vertex included).
    Returns array (n, 3): x, y, distance along route."""
    v = np.asarray(vertices, float)
    seg = np.hypot(*np.diff(v, axis=0).T)
    cum = np.concatenate([[0], np.cumsum(seg)])
    total = cum[-1]
    n = max(int(np.floor(total / spacing)), 1)
    s = np.linspace(0, total, n + 1) if np.isclose(n * spacing, total) else np.append(np.arange(0, total, spacing), total)
    x = np.interp(s, cum, v[:, 0]); y = np.interp(s, cum, v[:, 1])
    return np.column_stack([x, y, s])


def straight_route(dem, frac_len, angle_deg=30.0):
    """Straight route through the DEM centre, `frac_len` of the DEM width long."""
    h, w = dem.shape
    cx, cy = dem.to_world(w / 2, h / 2)
    L = frac_len * w * dem.cell
    a = np.radians(angle_deg)
    return [(cx - L / 2 * np.cos(a), cy - L / 2 * np.sin(a)), (cx + L / 2 * np.cos(a), cy + L / 2 * np.sin(a))]


def altitude_profile(dem, pts, mode="agl", agl=300.0, msl=None, smooth_m=3000.0, spacing=None):
    """Aircraft altitude (m above sea level) at each sampled point.

    agl : terrain following.  The ground under the route is smoothed with a running maximum over
          `smooth_m` (an aircraft cannot follow every bump), then `agl` metres are added.
    msl : constant altitude `msl`, raised where needed to keep `agl` clearance (reported).
    Returns (alt_msl, ground, clearance)."""
    ground = dem.elev_at(pts[:, 0], pts[:, 1])
    if mode == "agl":
        if spacing is None:
            spacing = np.median(np.diff(pts[:, 2])) if len(pts) > 1 else smooth_m
        k = max(int(round(smooth_m / max(spacing, 1.0) / 2)), 0)
        g = np.array([ground[max(0, i - k):i + k + 1].max() for i in range(len(ground))])
        alt = g + agl
    else:
        alt = np.maximum(np.full_like(ground, msl), ground + agl)
    return alt, ground, alt - ground
