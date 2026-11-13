"""Track 2 - idea 2: a realistic sensor instead of "everything in line of sight within 20 km".

A cell counts as *observed* from a position only if all of these hold:
  1. line of sight (the GDAL viewshed, as before);
  2. inside the sensor's horizontal field of view, measured from the aircraft heading
     (omni = 360 deg; forward camera; side-looking pair; ...);
  3. inside its vertical field of view: depression angle below the horizon between
     min_dep and max_dep (a nadir camera only looks steeply down);
  4. seen sharply enough: ground sample distance
        GSD = slant_range * ifov / cos(incidence)
     at most gsd_max metres.  ifov = angular size of one pixel; incidence = angle between
     the line of sight and the terrain normal (a slope facing away is smeared out).
Each position stands for spacing / speed seconds of flight, so the count raster becomes
dwell time (seconds a cell is observed).
"""
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from flight.fast import SharedDEM, _viewshed
from flight.visibility import Accumulator


@dataclass(frozen=True)
class Sensor:
    name: str = "omni"
    sectors: tuple = ((0.0, 360.0),)   # (centre bearing relative to heading, width) in degrees
    min_dep: float = -90.0             # depression angle limits (deg below horizontal); -90 = no limit
    max_dep: float = 90.0
    ifov: float = 0.0                  # rad per pixel; 0 = no resolution limit
    gsd_max: float = math.inf          # metres

    def describe(self):
        return {"name": self.name, "sectors": self.sectors, "min_dep": self.min_dep, "max_dep": self.max_dep,
                "ifov_mrad": self.ifov * 1e3, "gsd_max_m": self.gsd_max}


# a 6000-pixel-wide camera with a 60 deg lens: 0.175 mrad per pixel
CAM_IFOV = math.radians(60) / 6000
SENSORS = {
    "omni": Sensor("omni"),
    "omni_gsd3": Sensor("omni_gsd3", ifov=CAM_IFOV, gsd_max=3.0),
    "forward": Sensor("forward", sectors=((0.0, 90.0),), min_dep=5.0, max_dep=60.0, ifov=CAM_IFOV, gsd_max=3.0),
    "side": Sensor("side", sectors=((90.0, 60.0), (-90.0, 60.0)), min_dep=10.0, max_dep=70.0, ifov=CAM_IFOV, gsd_max=3.0),
    "nadir": Sensor("nadir", min_dep=45.0, max_dep=90.0, ifov=CAM_IFOV, gsd_max=3.0),
}


def headings(pts):
    """Heading (radians, clockwise from north) of the route at each sampled point."""
    dx = np.gradient(pts[:, 0]); dy = np.gradient(pts[:, 1])
    return np.arctan2(dx, dy)


def sensor_mask(dem, rc, cc, ox, oy, alt, heading, r0, c0, vis, s):
    """vis with every cell the sensor cannot observe switched off (FOV, depression, resolution).
    Only the cells already in line of sight are evaluated (a few % of the window)."""
    omni = s.sectors == ((0.0, 360.0),)
    if omni and s.min_dep <= -90 and s.max_dep >= 90 and not s.ifov:
        return vis
    cell = dem.cell
    ir, ic = np.nonzero(vis)
    # cheap tests first; every test shrinks the index list the next one works on
    dxm = (ic + (c0 - cc)).astype(np.float32) * cell          # east metres from the aircraft
    dym = ((rc - r0) - ir).astype(np.float32) * cell          # north metres (rows grow southward)
    if not omni:
        bearing = np.degrees(np.arctan2(dxm, dym)) - math.degrees(heading)
        sec = np.zeros(len(ir), bool)
        for centre, width in s.sectors:
            d = (bearing - centre + 180.0) % 360.0 - 180.0
            sec |= np.abs(d) <= width / 2
        ir, ic, dxm, dym = ir[sec], ic[sec], dxm[sec], dym[sec]
    ground = np.hypot(dxm, dym)
    dz = np.float32(alt) - dem.z[ir + r0, ic + c0]                # aircraft height above the cell
    if s.min_dep > -90 or s.max_dep < 90:
        lo, hi = math.tan(math.radians(max(s.min_dep, -89.9))), math.tan(math.radians(min(s.max_dep, 89.9)))
        g = np.maximum(ground, 1e-3)
        k = (dz >= lo * g) & (dz <= hi * g)                       # depression angle without arctan
        ir, ic, dxm, dym, ground, dz = ir[k], ic[k], dxm[k], dym[k], ground[k], dz[k]
    if s.ifov:
        gx, gn = _gradients(dem)
        R, C = ir + r0, ic + c0
        gxi, gni = gx[R, C], gn[R, C]
        slant = np.sqrt(ground * ground + dz * dz)
        # terrain normal (east, north, up) = (-gx, -gn, 1); line of sight to the aircraft = (-dx, -dy, dz)
        # GSD = slant * ifov / cos(incidence) <= gsd_max   <=>   slant^2 * ifov * |n| <= gsd_max * (n . los)
        dot = gxi * dxm + gni * dym + dz
        k = slant * slant * s.ifov * np.sqrt(gxi * gxi + gni * gni + 1) <= s.gsd_max * np.maximum(dot, 0)
        ir, ic = ir[k], ic[k]
    out = np.zeros_like(vis)
    out[ir, ic] = True
    return out


_GRAD = {}


def _gradients(dem):
    """dz/d(east) and dz/d(north) for the whole DEM, float32, computed once per DEM."""
    key = id(dem.z)
    if key not in _GRAD:
        gs, ge = np.gradient(np.nan_to_num(dem.z, nan=0.0).astype(np.float32), dem.cell)
        _GRAD.clear(); _GRAD[key] = (ge.astype(np.float32), (-gs).astype(np.float32))
    return _GRAD[key]


class _Ctx:
    def __init__(self, dem):
        self.shared = SharedDEM(dem.z, dem.gt, dem.proj)


def run_sensor(dem, xs, ys, alts, heads, radius, sensor, workers=12, target_h=0.0, shared=None):
    """Observed cells for each position (shared zero-copy DEM view + threads).
    Returns (Accumulator, info)."""
    t0 = time.perf_counter()
    shared = shared or SharedDEM(dem.z, dem.gt, dem.proj)
    acc = Accumulator(dem.shape, dem.cell)

    def one(i):
        c, r = dem.to_pixel(xs[i], ys[i])
        rc, cc = int(round(r)), int(round(c))
        if not (0 <= rc < dem.shape[0] and 0 <= cc < dem.shape[1]):
            return 0, 0, np.zeros((0, 0), bool)
        ox, oy = dem.to_world(cc, rc)
        h = max(float(alts[i] - dem.z[rc, cc]), 1.0)
        c0, r0, vis = _viewshed(shared.band(), dem.gt, ox, oy, h, target_h, radius)
        return c0, r0, sensor_mask(dem, rc, cc, ox, oy, float(alts[i]), float(heads[i]), r0, c0, vis, sensor)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (c0, r0, vis) in enumerate(ex.map(one, range(len(xs)))):
            if vis.size:
                acc.add(i, c0, r0, vis)
    return acc, {"viewsheds": len(xs), "compute_s": time.perf_counter() - t0}


def dwell_seconds(count, spacing_m, speed_ms):
    """Seconds each cell is observed: every sampled position stands for spacing / speed seconds."""
    return count.astype(np.float32) * (spacing_m / speed_ms)
