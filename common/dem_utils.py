"""Raster I/O and coordinate helpers shared by the three tracks."""
import json
import numpy as np
from osgeo import gdal, ogr, osr

from common.config import CRS_EPSG, NODATA

gdal.UseExceptions()


class DEM:
    """A DEM held in memory: elevation array (float32, NaN for no-data) + georeferencing."""

    def __init__(self, path, window=None):
        ds = gdal.Open(str(path))
        b = ds.GetRasterBand(1)
        gt = list(ds.GetGeoTransform())
        if window:  # (xoff, yoff, xsize, ysize) in pixels: read only part of the file
            xo, yo, xs, ys = window
            z = b.ReadAsArray(xo, yo, xs, ys).astype(np.float32)
            gt[0] += xo * gt[1]; gt[3] += yo * gt[5]
        else:
            z = b.ReadAsArray().astype(np.float32)
        nd = b.GetNoDataValue()
        if nd is not None:
            z[z == nd] = np.nan
        self.z, self.gt, self.proj, self.path = z, tuple(gt), ds.GetProjection(), str(path)
        self.cell = gt[1]
        self.has_nodata = bool(np.isnan(z).any())
        self._ds = None

    def gdal_dataset(self):
        """In-memory GDAL dataset sharing the elevation array (no copy unless there is no-data)."""
        if self._ds is None:
            from osgeo import gdal_array
            arr = np.where(np.isnan(self.z), -9999.0, self.z).astype(np.float32) if self.has_nodata else self.z
            ds = gdal_array.OpenArray(arr)
            ds.SetGeoTransform(self.gt); ds.SetProjection(self.proj)
            if self.has_nodata:
                ds.GetRasterBand(1).SetNoDataValue(-9999.0)
            self._ds, self._arr = ds, arr
        return self._ds

    @property
    def shape(self):
        return self.z.shape

    def to_pixel(self, x, y):
        """World (m) -> fractional (col, row) of the cell centre grid."""
        return (x - self.gt[0]) / self.gt[1] - 0.5, (y - self.gt[3]) / self.gt[5] - 0.5

    def to_world(self, col, row):
        return self.gt[0] + (col + 0.5) * self.gt[1], self.gt[3] + (row + 0.5) * self.gt[5]

    def elev_at(self, x, y):
        c, r = self.to_pixel(x, y)
        return bilinear(self.z, np.atleast_1d(c), np.atleast_1d(r))

    def contains(self, x, y):
        c, r = self.to_pixel(x, y)
        return 0 <= c < self.shape[1] - 1 and 0 <= r < self.shape[0] - 1


def bilinear(z, c, r):
    """Bilinear interpolation of z at fractional (col, row) arrays."""
    c = np.clip(c, 0, z.shape[1] - 1.000001); r = np.clip(r, 0, z.shape[0] - 1.000001)
    c0 = np.floor(c).astype(np.int64); r0 = np.floor(r).astype(np.int64)
    fc = c - c0; fr = r - r0
    z00 = z[r0, c0]; z01 = z[r0, c0 + 1]; z10 = z[r0 + 1, c0]; z11 = z[r0 + 1, c0 + 1]
    return (z00 * (1 - fc) * (1 - fr) + z01 * fc * (1 - fr) + z10 * (1 - fc) * fr + z11 * fc * fr)


def srs_wkt(epsg=CRS_EPSG):
    s = osr.SpatialReference(); s.ImportFromEPSG(epsg)
    return s.ExportToWkt()


def write_raster(path, arr, gt, proj=None, dtype=gdal.GDT_Byte, nodata=None, compress=True):
    drv = gdal.GetDriverByName("GTiff")
    opts = ["COMPRESS=DEFLATE", "TILED=YES"] if compress else []
    ds = drv.Create(str(path), arr.shape[1], arr.shape[0], 1, dtype, opts)
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj or srs_wkt())
    b = ds.GetRasterBand(1)
    if nodata is not None:
        b.SetNoDataValue(nodata)
    b.WriteArray(arr)
    ds.FlushCache()
    ds = None


def write_points_geojson(path, pts, props=None, epsg=CRS_EPSG):
    """pts: list of (x, y); props: list of dicts. Written in the project CRS."""
    feats = []
    for i, (x, y) in enumerate(pts):
        p = props[i] if props else {}
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(x), float(y)]},
                      "properties": p})
    _dump(path, feats, epsg)


def write_lines_geojson(path, lines, props=None, epsg=CRS_EPSG):
    """lines: list of [(x, y), ...]."""
    feats = []
    for i, ln in enumerate(lines):
        p = props[i] if props else {}
        feats.append({"type": "Feature", "geometry": {"type": "LineString",
                      "coordinates": [[float(x), float(y)] for x, y in ln]}, "properties": p})
    _dump(path, feats, epsg)


def _dump(path, feats, epsg):
    fc = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{epsg}"}},
          "features": feats}
    with open(path, "w") as f:
        json.dump(fc, f)


def read_geojson_points(path):
    fc = json.load(open(path))
    return [(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1], f["properties"]) for f in fc["features"]]
