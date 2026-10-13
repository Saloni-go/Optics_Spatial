"""Visualization performance: how long QGIS takes to load and draw rasters of each DEM size.

Layers per size: the DEM as written by the pipeline (DEFLATE, tiled), a plain GeoTIFF
(uncompressed, striped: what a naive export gives) and the same plain file with pyramids
(overviews 2-16).  Views at 1600 x 1600 px: full extent, zoomed to 1/8 of the width, and
1:1 (one screen pixel per cell).  Every render is "cold" for GDAL: each one opens a new layer (new dataset, empty block cache),
so the median is not a cache hit (the OS file cache stays warm).  Optional argument: GDAL cache
size in MB (e.g. 1) to see what a starved cache does to compressed, tiled files.

Results: results/shared/render_benchmark.csv, results/shared/fig_render_benchmark.png
Run:  run_qgis.bat qgis\\render_bench.py
"""
import csv
import statistics
import sys
import time
from pathlib import Path

from osgeo import gdal
from qgis.core import (QgsApplication, QgsRasterLayer, QgsMapSettings, QgsMapRendererSequentialJob,
                       QgsCoordinateReferenceSystem, QgsRectangle)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.config import dem_path   # noqa: E402

OUT = ROOT / "results/shared/render"; OUT.mkdir(parents=True, exist_ok=True)
qgs = QgsApplication([], False); qgs.initQgis()
CACHE_MB = int(sys.argv[1]) if len(sys.argv) > 1 else 0   # 0 = GDAL default (5% of RAM)
if CACHE_MB:
    gdal.SetCacheMax(CACHE_MB * 1024 * 1024)
REPS = 5


def render_once(path, extent):
    lay = QgsRasterLayer(str(path), "x")
    s = QgsMapSettings(); s.setLayers([lay]); s.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:32644"))
    s.setExtent(extent); s.setOutputSize(QSize(1600, 1600)); s.setBackgroundColor(QColor("white"))
    t = time.perf_counter(); j = QgsMapRendererSequentialJob(s); j.start(); j.waitForFinished()
    return time.perf_counter() - t


def bench(path, extent):
    ts = [render_once(path, extent) for _ in range(REPS)]
    return statistics.median(ts), ts[0]


rows = []
cases = []
for size in (500, 1000, 2000, 4000):
    plain = OUT / f"dem_{size}_plain.tif"
    if not plain.exists():
        gdal.Translate(str(plain), str(dem_path(size)), creationOptions=["COMPRESS=NONE", "TILED=NO"])
    pyr = OUT / f"dem_{size}_plain_pyramids.tif"
    if not pyr.exists():
        gdal.Translate(str(pyr), str(plain), creationOptions=["COMPRESS=NONE", "TILED=NO"])
        d = gdal.Open(str(pyr), gdal.GA_Update); d.BuildOverviews("AVERAGE", [2, 4, 8, 16]); d = None
    cases += [(size, "DEM deflate+tiled", dem_path(size)), (size, "DEM plain", plain), (size, "DEM plain + pyramids", pyr)]
cases.append((4000, "Track 2 count raster", ROOT / "results/flight/count_agl300.tif"))

for size, kind, path in cases:
    t = time.perf_counter(); lay = QgsRasterLayer(str(path), kind); load = time.perf_counter() - t
    full = lay.extent()
    zoom = full.buffered(-full.width() * 7 / 16)
    c = full.center(); half = 1600 * 30 / 2
    native = QgsRectangle(c.x() - half, c.y() - half, c.x() + half, c.y() + half)
    row = {"dem_id": size, "cells": size * size, "layer": kind, "file_mb": round(Path(path).stat().st_size / 2 ** 20, 2),
           "load_s": load}
    for name, ext in (("full", full), ("zoom", zoom), ("native", native)):
        med, first = bench(path, ext)
        row[f"render_{name}_s"] = med
        row[f"render_{name}_first_s"] = first
    rows.append(row)
    print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}, flush=True)

with open(ROOT / "results/shared/render_benchmark.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, axs = plt.subplots(1, 3, figsize=(13, 3.6), sharey=True)
for kind, c in (("DEM deflate+tiled", "#457b9d"), ("DEM plain", "#e76f51"), ("DEM plain + pyramids", "#2a9d8f")):
    rr = [r for r in rows if r["layer"] == kind]
    for ax, v in zip(axs, ("full", "zoom", "native")):
        ax.loglog([r["cells"] for r in rr], [r[f"render_{v}_s"] for r in rr], "o-", c=c, label=kind)
for ax, t in zip(axs, ("full extent", "zoomed to 1/8 width", "1:1 (one pixel per cell)")):
    ax.set_xlabel("raster cells"); ax.set_title(f"QGIS render, 1600 x 1600 px, {t}", fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
axs[0].set_ylabel("render time (s), median of 5 cold renders"); axs[0].legend(fontsize=8, frameon=False)
fig.savefig(ROOT / "results/shared/fig_render_benchmark.png", dpi=200, bbox_inches="tight")
qgs.exitQgis()
