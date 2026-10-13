"""Phase 0: download Copernicus GLO-30 tiles, reproject to UTM 44N at 30 m and cut nested
square DEMs (500, 1000, 2000, 4000 cells) centred on the same point, plus a hillshade and
synthetic validation terrains.

Run:  run.bat scripts\\prepare_data.py
"""
import json
import numpy as np
from osgeo import gdal, osr

from common.config import (DATA, CRS_EPSG, CELL, CENTER_LONLAT, SIZES, NODATA, COP_TILES, dem_path)

gdal.UseExceptions()
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")


def tile_url(lat, lon):
    name = f"Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM"
    return f"/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"


def center_utm():
    src = osr.SpatialReference(); src.ImportFromEPSG(4326)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst = osr.SpatialReference(); dst.ImportFromEPSG(CRS_EPSG)
    x, y, _ = osr.CoordinateTransformation(src, dst).TransformPoint(*CENTER_LONLAT)
    # snap to the 30 m grid so all subsets share cell edges
    return round(x / CELL) * CELL, round(y / CELL) * CELL


def build_real():
    DATA.mkdir(exist_ok=True)
    raw = DATA / "raw"; raw.mkdir(exist_ok=True)
    local = []
    for lat, lon in COP_TILES:
        out = raw / f"cop30_N{lat}_E{lon}.tif"
        if not out.exists():
            print("downloading", out.name)
            gdal.Translate(str(out), tile_url(lat, lon), creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
        local.append(str(out))
    vrt = str(raw / "cop30_mosaic.vrt")
    gdal.BuildVRT(vrt, local)

    cx, cy = center_utm()
    big = max(SIZES)
    half = big * CELL / 2
    bounds = (cx - half, cy - half, cx + half, cy + half)
    big_path = dem_path(big)
    gdal.Warp(str(big_path), vrt, dstSRS=f"EPSG:{CRS_EPSG}", outputBounds=bounds, xRes=CELL, yRes=CELL,
              resampleAlg="bilinear", dstNodata=NODATA, outputType=gdal.GDT_Float32,
              creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "PREDICTOR=3"])
    ds = gdal.Open(str(big_path))
    assert (ds.RasterXSize, ds.RasterYSize) == (big, big), (ds.RasterXSize, ds.RasterYSize)
    arr = ds.GetRasterBand(1).ReadAsArray()
    nod = int((arr == NODATA).sum())
    print(f"dem_{big}: {big}x{big}, min {arr[arr != NODATA].min():.0f} m, max {arr.max():.0f} m, nodata cells {nod}")

    meta = {"crs": f"EPSG:{CRS_EPSG}", "cell_m": CELL, "center_lonlat": CENTER_LONLAT, "center_utm": [cx, cy],
            "source": "Copernicus GLO-30 DSM (AWS open data), bilinear to UTM 44N", "sizes": {}}
    for s in SIZES:
        off = (big - s) // 2
        out = dem_path(s)
        if s != big:
            gdal.Translate(str(out), str(big_path), srcWin=[off, off, s, s],
                           creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "PREDICTOR=3"])
        d = gdal.Open(str(out)); a = d.GetRasterBand(1).ReadAsArray(); gt = d.GetGeoTransform()
        v = a[a != NODATA]
        meta["sizes"][s] = {"path": out.name, "cells": s * s, "extent_km": s * CELL / 1000,
                            "xmin": gt[0], "ymax": gt[3], "z_min": float(v.min()), "z_max": float(v.max()),
                            "z_mean": float(v.mean()), "z_std": float(v.std()),
                            "relief_m": float(v.max() - v.min()), "nodata_cells": int((a == NODATA).sum())}
        print(s, meta["sizes"][s])
        gdal.DEMProcessing(str(DATA / f"hillshade_{s}.tif"), str(out), "hillshade", zFactor=1.5,
                           computeEdges=True, creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
    json.dump(meta, open(DATA / "dem_metadata.json", "w"), indent=1)


def write_array(path, arr, x0, y0, cell=CELL):
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(str(path), arr.shape[1], arr.shape[0], 1, gdal.GDT_Float32, ["COMPRESS=DEFLATE"])
    ds.SetGeoTransform((x0, cell, 0, y0, 0, -cell))
    srs = osr.SpatialReference(); srs.ImportFromEPSG(CRS_EPSG); ds.SetProjection(srs.ExportToWkt())
    b = ds.GetRasterBand(1); b.WriteArray(arr.astype(np.float32)); b.SetNoDataValue(NODATA)
    ds = None


def build_synthetic(n=401):
    """Simple terrains with known answers, used to validate every algorithm."""
    syn = DATA / "synthetic"; syn.mkdir(exist_ok=True)
    x0, y0 = 500000.0, 3300000.0
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    flat = np.full((n, n), 1000.0)
    # a 200 m high north-south wall (3 cells wide) at column 260; observer at the centre (col 200)
    ridge = flat.copy(); ridge[:, 259:262] = 1200.0
    # a V valley along the centre column: observer in the valley floor sees up both flanks
    valley = 1000.0 + 4.0 * np.abs(xx - n // 2)
    # cone hill centred, observer on the flank: back side of the cone is hidden
    cone = 1000.0 + np.clip(300.0 - 3.0 * np.hypot(xx - n // 2, yy - n // 2), 0, None)
    for name, a in (("flat", flat), ("ridge", ridge), ("valley", valley), ("cone", cone)):
        write_array(syn / f"{name}.tif", a, x0, y0)
    print("synthetic terrains written:", [p.name for p in syn.glob("*.tif")])


if __name__ == "__main__":
    build_synthetic()
    build_real()
