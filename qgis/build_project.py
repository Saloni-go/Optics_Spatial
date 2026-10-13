"""Builds qgis/terrain_visibility.qgz with every output styled, grouped per track, and exports
QGIS map renders for the report/slides (results/shared/qgis_*.png).

Run:  run_qgis.bat qgis\\build_project.py
"""
import sys
from pathlib import Path

from qgis.core import (QgsApplication, QgsProject, QgsRasterLayer, QgsVectorLayer, QgsCoordinateReferenceSystem,
                       QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer, QgsPalettedRasterRenderer,
                       QgsHillshadeRenderer, QgsLineSymbol, QgsMarkerSymbol, QgsCategorizedSymbolRenderer,
                       QgsRendererCategory, QgsMapSettings, QgsMapRendererParallelJob, QgsRectangle, QgsPalLayerSettings,
                       QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsFillSymbol)
from qgis.PyQt.QtGui import QColor, QPainter
from qgis.PyQt.QtCore import QSize

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"
qgs = QgsApplication([], False)
qgs.initQgis()
P = QgsProject.instance()
P.setCrs(QgsCoordinateReferenceSystem("EPSG:32644"))


def raster(path, name):
    l = QgsRasterLayer(str(path), name)
    assert l.isValid(), path
    return l


def vector(path, name):
    l = QgsVectorLayer(str(path), name, "ogr")
    assert l.isValid(), path
    return l


def pseudo(layer, stops, mode=QgsColorRampShader.Interpolated, opacity=1.0, labels=None):
    sh = QgsColorRampShader(stops[0][0], stops[-1][0]); sh.setColorRampType(mode)
    sh.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, QColor(c), (labels or {}).get(v, f"{v:g}")) for v, c in stops])
    rs = QgsRasterShader(); rs.setRasterShaderFunction(sh)
    r = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, rs)
    r.setClassificationMin(stops[0][0]); r.setClassificationMax(stops[-1][0])
    layer.setRenderer(r); layer.renderer().setOpacity(opacity)


def paletted(layer, classes, opacity=1.0):
    cl = [QgsPalettedRasterRenderer.Class(v, QColor(c), lab) for v, c, lab in classes]
    layer.setRenderer(QgsPalettedRasterRenderer(layer.dataProvider(), 1, cl)); layer.renderer().setOpacity(opacity)


def add(layer, group, visible=True):
    P.addMapLayer(layer, False)
    node = group.addLayer(layer)
    node.setItemVisibilityChecked(visible)
    return layer


root = P.layerTreeRoot()
g3 = root.addGroup("Track 3 - Optimal visibility corridor")
g2 = root.addGroup("Track 2 - Flight-route visibility")
g1 = root.addGroup("Track 1 - Radar visibility")
gb = root.addGroup("Base terrain (Copernicus GLO-30, UTM 44N)")

# ---- base
dem = raster(ROOT / "data/dem_4000.tif", "DEM 4000 (30 m)")
pseudo(dem, [(300, "#6f8f6a"), (1200, "#a9b88e"), (2200, "#d6cdb0"), (3500, "#c9b49a"), (5000, "#efe9e2"), (7100, "#ffffff")])
hs = raster(ROOT / "data/hillshade_4000.tif", "Hillshade")
hs.renderer().setOpacity(0.6)
add(dem, gb); add(hs, gb)
from qgis.core import QgsPainting
hs.setBlendMode(QPainter.CompositionMode_Multiply)

# ---- track 1
radars = vector(R / "shared/radars.geojson", "Radar sites")
radars.setRenderer(radars.renderer().__class__(QgsMarkerSymbol.createSimple(
    {"name": "triangle", "color": "#e63946", "outline_color": "black", "size": "4"})))
lab = QgsPalLayerSettings(); lab.fieldName = "id"; lab.enabled = True
tf = QgsTextFormat(); tf.setSize(9); lab.setFormat(tf)
radars.setLabeling(QgsVectorLayerSimpleLabeling(lab)); radars.setLabelsEnabled(True)
rings = vector(R / "radar/range_rings.geojson", "Radar range 40 km")
rings.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "#222222", "width": "0.3", "line_style": "dash"}))
cg = raster(R / "radar/coverage_ground_count.tif", "Ground visible: number of radars")
pseudo(cg, [(1, "#fde0c5"), (2, "#f59e72"), (3, "#e8604c"), (4, "#c0392b"), (6, "#7b241c")], opacity=0.75)
ca = raster(R / "radar/coverage_air150_count.tif", "Aircraft 150 m AGL detectable: number of radars")
pseudo(ca, [(1, "#fde0c5"), (2, "#f59e72"), (3, "#e8604c"), (4, "#c0392b"), (6, "#7b241c")], opacity=0.75)
add(radars, g1); add(rings, g1); add(cg, g1); add(ca, g1, False)
for f in sorted((R / "radar").glob("viewshed_R*.tif")):
    v = raster(f, f"Viewshed {f.stem.split('_')[1]}")
    paletted(v, [(1, "#f2a541", "visible"), (0, "#1d3557", "blocked")], opacity=0.6)
    add(v, g1, False)

# ---- track 2
route = vector(R / "flight/route.geojson", "Flight route (Alaknanda valley)")
route.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "#1d3557", "width": "0.8"}))
wps = vector(R / "flight/waypoints_agl300.geojson", "Sampled positions (1 km)")
wps.renderer().setSymbol(QgsMarkerSymbol.createSimple({"name": "circle", "color": "white", "outline_color": "#1d3557", "size": "1.4"}))
for case, vis in (("agl300", True), ("msl5500", False)):
    c = raster(R / f"flight/count_{case}.tif", f"Times seen ({case})")
    pseudo(c, [(1, "#fcfdbf"), (5, "#fd9668"), (15, "#de4968"), (30, "#8c2981"), (50, "#3b0f70")], opacity=0.75)
    b = raster(R / f"flight/blind_{case}.tif", f"Blind spots in 20 km corridor ({case})")
    paletted(b, [(1, "#4895ef", "never seen")], opacity=0.55)
    add(c, g2, vis); add(b, g2, vis)
add(route, g2); add(wps, g2, False)
for n in (route, wps):
    root.findLayer(n.id()).setItemVisibilityChecked(True if n is route else False)

# ---- track 3
ex = raster(R / "corridor/exposure.tif", "Radar exposure (aircraft 150 m AGL)")
pseudo(ex, [(0.0, "#ffffff00"), (0.01, "#fee5d9"), (0.5, "#fcae91"), (1.0, "#fb6a4a"), (2.0, "#de2d26"), (3.5, "#a50f15")], opacity=0.65)
blk = raster(R / "corridor/blocked.tif", "Above ceiling (blocked)")
paletted(blk, [(1, "#6c757d", "blocked")], opacity=0.5)
routes = vector(R / "corridor/routes.geojson", "Corridor routes")
cats = []
for name, col in (("shortest", "#1d3557"), ("alpha_1", "#a8dadc"), ("alpha_3", "#457b9d"), ("alpha_10", "#2a9d8f"),
                  ("alpha_30", "#f4a261"), ("alpha_100", "#8338ec")):
    cats.append(QgsRendererCategory(name, QgsLineSymbol.createSimple({"color": col, "width": "0.9"}), name))
routes.setRenderer(QgsCategorizedSymbolRenderer("name", cats))
add(routes, g3); add(ex, g3); add(blk, g3)

P.writeEntry("Paths", "/Absolute", False)
out = ROOT / "qgis/terrain_visibility.qgz"
P.write(str(out))
print("project written:", out)


# ---- QGIS renders for slides
def render(layers, path, w=1600, h=1600, extent=None):
    s = QgsMapSettings(); s.setLayers(layers); s.setDestinationCrs(P.crs())
    s.setExtent(extent or dem.extent()); s.setOutputSize(QSize(w, h)); s.setBackgroundColor(QColor("white"))
    j = QgsMapRendererParallelJob(s); j.start(); j.waitForFinished(); j.renderedImage().save(str(path))


S = R / "shared"; S.mkdir(exist_ok=True)
render([radars, rings, cg, hs, dem], S / "qgis_track1_coverage.png")
render([route, P.mapLayersByName("Blind spots in 20 km corridor (agl300)")[0], P.mapLayersByName("Times seen (agl300)")[0], hs, dem],
       S / "qgis_track2_agl300.png")
render([radars, routes, blk, ex, hs, dem], S / "qgis_track3_routes.png")
render([hs, dem], S / "qgis_dem.png")
print("renders written")
qgs.exitQgis()
