"""Track 3 - radar exposure surface and traversal cost.

Exposure E(cell) for an aircraft at TARGET_AIRCRAFT m above ground:
    E = sum over radars that can see the aircraft there of  w(d),   w(d) = 1 - d / range
(GDAL viewshed with target height, same curvature model).  w falls linearly with distance, a
simple stand-in for the radar equation (closer = stronger return).  E = 0 means hidden.

Traversal cost of moving from cell u to neighbour v (directed):
    c(u, v) = L_uv * (1 + alpha * (E_u + E_v) / 2)  +  beta * max(0, z_v - z_u)
L_uv is 30 m or 42.4 m.  Cells where ground + AGL is above the aircraft ceiling are blocked.
alpha = 0, beta = 0 gives the shortest-distance baseline.
"""
import numpy as np
from osgeo import gdal

from common.config import CURV_COEFF, TARGET_AIRCRAFT, RADAR_HEIGHT, VISIBLE, INVISIBLE, OUT_OF_RANGE

gdal.UseExceptions()

CEILING = 5000.0      # m MSL, aircraft service ceiling for the low-level route
RADAR_RANGE_T3 = 40000.0


def exposure(dem, sites, radar_h=RADAR_HEIGHT, target_h=TARGET_AIRCRAFT, rng=RADAR_RANGE_T3, weighted=True):
    src = gdal.GetDriverByName("MEM").Create("", dem.shape[1], dem.shape[0], 1, gdal.GDT_Float32)
    src.SetGeoTransform(dem.gt); src.SetProjection(dem.proj)
    src.GetRasterBand(1).WriteArray(np.nan_to_num(dem.z, nan=-9999.0)); src.GetRasterBand(1).SetNoDataValue(-9999.0)
    E = np.zeros(dem.shape, np.float32)
    count = np.zeros(dem.shape, np.uint8)
    rr, cc = np.mgrid[0:dem.shape[0], 0:dem.shape[1]]
    for x, y, *_ in sites:
        c, r = dem.to_pixel(x, y)
        if not (0 <= c < dem.shape[1] and 0 <= r < dem.shape[0]):
            continue
        ds = gdal.ViewshedGenerate(src.GetRasterBand(1), "MEM", "", [], *dem.to_world(round(c), round(r)), radar_h, target_h,
                                   VISIBLE, INVISIBLE, OUT_OF_RANGE, OUT_OF_RANGE, CURV_COEFF, gdal.GVM_Edge, rng)
        a = ds.GetRasterBand(1).ReadAsArray(); g = ds.GetGeoTransform()
        c0 = int(round((g[0] - dem.gt[0]) / dem.gt[1])); r0 = int(round((g[3] - dem.gt[3]) / dem.gt[5]))
        vis = np.zeros(dem.shape, bool)
        vis[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] = a == VISIBLE
        if weighted:
            d = np.hypot(cc - c, rr - r) * dem.cell
            E += np.where(vis, np.clip(1 - d / rng, 0, 1), 0).astype(np.float32)
        else:
            E += vis
        count += vis
    return E, count


def blocked_mask(dem, agl=TARGET_AIRCRAFT, ceiling=CEILING):
    return np.isnan(dem.z) | (dem.z + agl > ceiling)
