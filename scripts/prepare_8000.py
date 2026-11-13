"""Scale test: an 8000 x 8000 DEM (64 M cells, 240 x 240 km) on the same grid as the 500-4000 DEMs.

Downloads the Copernicus GLO-30 tiles that the larger extent needs (12 instead of 4), warps them exactly
like scripts/prepare_data.py (bilinear to UTM 44N, 30 m, same snapped centre), and checks that the centre
4000 x 4000 window equals data/dem_4000.tif, so the 64 M map is a strict extension of the existing ones.
Does not change data/dem_500..4000 or common/config.SIZES.

Run:  python3 scripts/prepare_8000.py
"""
import math

import numpy as np
from osgeo import gdal, osr

from common.config import DATA, CRS_EPSG, CELL, NODATA, dem_path
from scripts.prepare_data import tile_url, center_utm

gdal.UseExceptions()
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
SIZE = 8000


def tiles_for(bounds):
    src = osr.SpatialReference(); src.ImportFromEPSG(CRS_EPSG)
    dst = osr.SpatialReference(); dst.ImportFromEPSG(4326); dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, dst)
    x0, y0, x1, y1 = bounds
    pts = [ct.TransformPoint(x, y)[:2] for x in np.linspace(x0, x1, 9) for y in np.linspace(y0, y1, 9)]
    lo, la = [p[0] for p in pts], [p[1] for p in pts]
    return [(a, b) for a in range(math.floor(min(la)), math.floor(max(la)) + 1)
            for b in range(math.floor(min(lo)), math.floor(max(lo)) + 1)]


def main():
    raw = DATA / "raw"; raw.mkdir(parents=True, exist_ok=True)
    cx, cy = center_utm()
    half = SIZE * CELL / 2
    bounds = (cx - half, cy - half, cx + half, cy + half)
    local = []
    for lat, lon in tiles_for(bounds):
        out = raw / f"cop30_N{lat}_E{lon}.tif"
        if not out.exists():
            print("downloading", out.name, flush=True)
            gdal.Translate(str(out), tile_url(lat, lon), creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
        local.append(str(out))
    vrt = str(raw / "cop30_mosaic_8000.vrt")
    gdal.BuildVRT(vrt, local)
    out = dem_path(SIZE)
    gdal.Warp(str(out), vrt, dstSRS=f"EPSG:{CRS_EPSG}", outputBounds=bounds, xRes=CELL, yRes=CELL,
              resampleAlg="bilinear", dstNodata=NODATA, outputType=gdal.GDT_Float32,
              creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "PREDICTOR=3", "BIGTIFF=IF_SAFER"])
    a = gdal.Open(str(out)).ReadAsArray()
    v = a[a != NODATA]
    print(f"dem_{SIZE}: {a.shape}, z {v.min():.0f}..{v.max():.0f} m, nodata {int((a == NODATA).sum())} cells")
    # the centre 4000 window must reproduce dem_4000 (same grid, same resampling)
    off = (SIZE - 4000) // 2
    b = gdal.Open(str(dem_path(4000))).ReadAsArray()
    d = np.abs(a[off:off + 4000, off:off + 4000] - b)
    print(f"centre vs dem_4000: max |diff| {d.max():.4f} m, mean {d.mean():.6f} m")
    gdal.DEMProcessing(str(DATA / f"hillshade_{SIZE}.tif"), str(out), "hillshade", zFactor=1.5, computeEdges=True,
                       creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])


if __name__ == "__main__":
    main()
