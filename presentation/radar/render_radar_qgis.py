"""QGIS (PyQGIS) map renders of the Track 1 radar rasters for the radar slide deck, plus the time QGIS
takes to draw each radar raster on this machine.

Outputs (presentation/radar/figs/): qgis_study_area.jpg, qgis_viewshed_R<i>.jpg, qgis_coverage_ground.jpg,
qgis_coverage_air150.jpg, render_radar.json
Run:  run_qgis.bat presentation\\radar\\render_radar_qgis.py
"""
import json
import statistics
import time
from pathlib import Path

from qgis.core import (QgsApplication, QgsRasterLayer, QgsVectorLayer, QgsCoordinateReferenceSystem, QgsColorRampShader,
                       QgsRasterShader, QgsSingleBandPseudoColorRenderer, QgsPalettedRasterRenderer, QgsLineSymbol,
                       QgsMarkerSymbol, QgsMapSettings, QgsMapRendererParallelJob, QgsMapRendererSequentialJob,
                       QgsRectangle, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling, QgsTextFormat,
                       QgsTextBufferSettings, QgsSingleSymbolRenderer)
from qgis.PyQt.QtGui import QColor, QPainter, QFont
from qgis.PyQt.QtCore import QSize

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "results"
OUT = Path(__file__).resolve().parent / "figs"; OUT.mkdir(parents=True, exist_ok=True)
qgs = QgsApplication([], False)
qgs.initQgis()
CRS = QgsCoordinateReferenceSystem("EPSG:32644")
RANGE = 40000.0
COUNT_STOPS = [(1, "#f6a04d"), (2, "#e8604c"), (3, "#c0392b"), (4, "#8e1b1b"), (6, "#4a0d0d")]


def raster(path, name):
    l = QgsRasterLayer(str(path), name)
    assert l.isValid(), path
    return l


def vector(path, name):
    l = QgsVectorLayer(str(path), name, "ogr")
    assert l.isValid(), path
    return l


def pseudo(layer, stops, opacity=1.0):
    sh = QgsColorRampShader(stops[0][0], stops[-1][0]); sh.setColorRampType(QgsColorRampShader.Interpolated)
    sh.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, QColor(c), f"{v:g}") for v, c in stops])
    rs = QgsRasterShader(); rs.setRasterShaderFunction(sh)
    r = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, rs)
    r.setClassificationMin(stops[0][0]); r.setClassificationMax(stops[-1][0])
    layer.setRenderer(r); layer.renderer().setOpacity(opacity)


def paletted(layer, classes, opacity=1.0):
    cl = [QgsPalettedRasterRenderer.Class(v, QColor(c), lab) for v, c, lab in classes]
    layer.setRenderer(QgsPalettedRasterRenderer(layer.dataProvider(), 1, cl)); layer.renderer().setOpacity(opacity)


def render(layers, path, extent, w=1400, h=1400):
    s = QgsMapSettings(); s.setLayers(layers); s.setDestinationCrs(CRS)
    s.setExtent(extent); s.setOutputSize(QSize(w, h)); s.setBackgroundColor(QColor("white"))
    j = QgsMapRendererParallelJob(s); j.start(); j.waitForFinished(); j.renderedImage().save(str(path), "JPG", 90)


dem = raster(ROOT / "data/dem_4000.tif", "DEM")
pseudo(dem, [(300, "#6f8f6a"), (1200, "#a9b88e"), (2200, "#d6cdb0"), (3500, "#c9b49a"), (5000, "#efe9e2"), (7100, "#ffffff")])
hs = raster(ROOT / "data/hillshade_4000.tif", "Hillshade")
hs.renderer().setOpacity(0.6); hs.setBlendMode(QPainter.CompositionMode_Multiply)

radars = vector(R / "shared/radars.geojson", "Radar sites")
radars.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
    {"name": "triangle", "color": "#e63946", "outline_color": "black", "size": "5"})))
lab = QgsPalLayerSettings(); lab.fieldName = "id"; lab.enabled = True
tf = QgsTextFormat(); f = QFont("Arial"); f.setBold(True); tf.setFont(f); tf.setSize(13)
buf = QgsTextBufferSettings(); buf.setEnabled(True); buf.setSize(1.2); buf.setColor(QColor("white")); tf.setBuffer(buf)
lab.setFormat(tf)
radars.setLabeling(QgsVectorLayerSimpleLabeling(lab)); radars.setLabelsEnabled(True)
rings = vector(R / "radar/range_rings.geojson", "Radar range 40 km")
rings.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "#222222", "width": "0.4", "line_style": "dash"}))

full = dem.extent()
render([radars, hs, dem], OUT / "qgis_study_area.jpg", full)

cg = raster(R / "radar/coverage_ground_count.tif", "ground"); pseudo(cg, COUNT_STOPS, 0.9)
ca = raster(R / "radar/coverage_air150_count.tif", "air"); pseudo(ca, COUNT_STOPS, 0.9)
render([radars, rings, cg, hs, dem], OUT / "qgis_coverage_ground.jpg", full)
render([radars, rings, ca, hs, dem], OUT / "qgis_coverage_air150.jpg", full)

for ft in radars.getFeatures():
    p = ft.geometry().asPoint(); rid = ft["id"]
    v = raster(R / f"radar/viewshed_{rid}.tif", rid)
    paletted(v, [(1, "#f2a541", "visible"), (0, "#1d3557", "blocked")], opacity=0.7)
    rings.setSubsetString(f"id = '{rid}'")
    k = RANGE * 1.05
    render([radars, rings, v, hs, dem], OUT / f"qgis_viewshed_{rid}.jpg",
           QgsRectangle(p.x() - k, p.y() - k, p.x() + k, p.y() + k), 900, 900)
    print("rendered", rid, flush=True)


# ---- render time of the radar rasters (same protocol as qgis/render_bench.py: new layer per render)
def render_once(path, extent):
    lay = QgsRasterLayer(str(path), "x")
    s = QgsMapSettings(); s.setLayers([lay]); s.setDestinationCrs(CRS)
    s.setExtent(extent); s.setOutputSize(QSize(1600, 1600)); s.setBackgroundColor(QColor("white"))
    t = time.perf_counter(); j = QgsMapRendererSequentialJob(s); j.start(); j.waitForFinished()
    return time.perf_counter() - t


rows = []
zoom = full.buffered(-full.width() * 7 / 16)
for name, path in (("DEM 4000 (input)", ROOT / "data/dem_4000.tif"),
                   ("Viewshed R1", R / "radar/viewshed_R1.tif"),
                   ("Coverage count, ground", R / "radar/coverage_ground_count.tif"),
                   ("Coverage count, aircraft 150 m", R / "radar/coverage_air150_count.tif")):
    t = time.perf_counter(); QgsRasterLayer(str(path), name); load = time.perf_counter() - t
    row = {"layer": name, "file_mb": round(Path(path).stat().st_size / 2 ** 20, 2), "load_s": load,
           "render_full_s": statistics.median(render_once(path, full) for _ in range(5)),
           "render_zoom_s": statistics.median(render_once(path, zoom) for _ in range(5))}
    rows.append(row); print(row, flush=True)
json.dump(rows, open(OUT / "render_radar.json", "w"), indent=1)
import os, sys
sys.stdout.flush(); os._exit(0)   # exitQgis() crashes here while layers are still referenced
