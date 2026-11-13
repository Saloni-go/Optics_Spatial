"""Track 2 - idea 4: add the Track 2 laptop results (ideas 1-3) to a QGIS project as a styled group,
with flight playback through the Temporal Controller.

Inside a running QGIS (Python console or the MCP bridge):
    exec(open("<repo>/qgis/track2_layers.py").read()); build(QgsProject.instance(), "<repo>")
Standalone:   python3 qgis/track2_layers.py <repo> <out.qgz>

Playback: the "first seen" raster holds, per cell, the flight time (s) at which it was first seen; its
temporal mode "represents temporal values" with accumulation shows every cell from that moment on,
and the waypoints layer moves the aircraft.  The time range is cumulative (each frame starts at
take-off), so seen cells accumulate and the aircraft leaves a trail.  Open View > Panels > Temporal Controller and press play.
"""
import json
from pathlib import Path

from qgis.core import (Qgis, QgsProject, QgsRasterLayer, QgsVectorLayer, QgsColorRampShader, QgsRasterShader,
                       QgsSingleBandPseudoColorRenderer, QgsPalettedRasterRenderer, QgsMarkerSymbol, QgsLineSymbol,
                       QgsSingleSymbolRenderer, QgsField, QgsInterval, QgsDateTimeRange, QgsVectorLayerTemporalProperties,
                       QgsPalLayerSettings, QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsTextBufferSettings,
                       QgsFeatureRequest, QgsCoordinateReferenceSystem)
from qgis.PyQt.QtCore import QDateTime, QDate, QTime, Qt, QVariant
from qgis.PyQt.QtGui import QColor

GROUP = "Track 2 - laptop results (track2-extensions)"
T0 = QDateTime(QDate(2026, 11, 13), QTime(6, 0, 0), Qt.UTC)      # take-off time used for playback
SPEED = 60.0


def _ramp(layer, stops, mode=QgsColorRampShader.Interpolated, opacity=1.0, lo=None, hi=None):
    sh = QgsColorRampShader(lo if lo is not None else stops[0][0], hi if hi is not None else stops[-1][0])
    sh.setColorRampType(mode)
    sh.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, QColor(c), lab) for v, c, lab in stops])
    rs = QgsRasterShader(); rs.setRasterShaderFunction(sh)
    r = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, rs)
    r.setClassificationMin(sh.minimumValue()); r.setClassificationMax(sh.maximumValue())
    layer.setRenderer(r); layer.renderer().setOpacity(opacity)


def _raster(path, name, group, visible=False):
    l = QgsRasterLayer(str(path), name)
    assert l.isValid(), path
    QgsProject.instance().addMapLayer(l, False)
    node = group.addLayer(l); node.setItemVisibilityChecked(visible); node.setExpanded(False)
    return l


def _vector(path, name, group, visible=True):
    l = QgsVectorLayer(str(path), name, "ogr")
    assert l.isValid(), path
    QgsProject.instance().addMapLayer(l, False)
    node = group.addLayer(l); node.setItemVisibilityChecked(visible); node.setExpanded(False)
    return l


def build(project, repo):
    repo = Path(repo); R = repo / "results" / "linux" / "flight"
    root = project.layerTreeRoot()
    old = root.findGroup(GROUP)
    if old:
        for lid in old.findLayerIds():
            project.removeMapLayer(lid)
        root.removeChildNode(old)
    top = root.insertGroup(0, GROUP)
    g_play = top.addGroup("Playback (Temporal Controller)")
    g_base = top.addGroup("Baseline: valley 300 m AGL vs cruise 5500 m")
    g_sens = top.addGroup("Idea 2: sensors and uncertainty")
    g_use = top.addGroup("Idea 3: use cases")
    g_bg = top.addGroup("Background")

    # ---- background
    hs = _raster(repo / "data" / "hillshade_4000.tif", "Hillshade", g_bg, True)
    hs.renderer().setOpacity(1.0)
    towns = _vector(R / "towns.geojson", "Towns", g_play)
    towns.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({"name": "square", "color": "#ffffff",
                                                                            "outline_color": "#000000", "size": "2.2"})))
    lab = QgsPalLayerSettings(); lab.fieldName = "name"
    tf = QgsTextFormat(); tf.setSize(8); b = QgsTextBufferSettings(); b.setEnabled(True); b.setSize(0.8); tf.setBuffer(b)
    lab.setFormat(tf); towns.setLabeling(QgsVectorLayerSimpleLabeling(lab)); towns.setLabelsEnabled(True)
    route = _vector(R / "route.geojson", "Route (166 km, Alaknanda valley)", g_play)
    route.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({"color": "#1d3557", "width": "0.7"})))

    # ---- playback: aircraft positions with a time field, first-seen raster as temporal values
    fc = json.load(open(R / "waypoints_agl300.geojson"))
    for f in fc["features"]:                           # flight time of each position as an ISO timestamp
        f["properties"]["t"] = T0.addSecs(int(round(f["properties"]["dist_km"] * 1000 / SPEED))).toString(Qt.ISODate)
    ap = R / "qgis" / "aircraft_agl300.geojson"
    json.dump(fc, open(ap, "w"))
    mem = QgsVectorLayer(str(ap), "Aircraft (300 m AGL)", "ogr")
    assert mem.isValid()
    project.addMapLayer(mem, False); g_play.insertLayer(0, mem)
    mem.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({"name": "triangle", "color": "#e63946",
                                                                          "outline_color": "#ffffff", "size": "4"})))
    tp = mem.temporalProperties()
    tp.setIsActive(True)
    tp.setMode(Qgis.VectorTemporalMode.FeatureDateTimeInstantFromField)
    tp.setStartField("t"); tp.setFixedDuration(17.0); tp.setDurationUnits(Qgis.TemporalUnit.Seconds)
    for case, name, col in (("agl300", "Seen so far, 300 m AGL", "#f2a541"), ("msl5500", "Seen so far, 5500 m MSL", "#8338ec")):
        fs = _raster(R / "qgis" / f"first_seen_seconds_{case}.tif", name, g_play, case == "agl300")
        _ramp(fs, [(0, col, "take-off"), (2767, col, "landing")], opacity=0.75)
        tpr = fs.temporalProperties()
        tpr.setIsActive(True)
        tpr.setMode(Qgis.RasterTemporalMode.RepresentsTemporalValues)
        tpr.setTemporalRepresentationOffset(T0)
        tpr.setTemporalRepresentationScale(QgsInterval(1, Qgis.TemporalUnit.Seconds))
        if hasattr(tpr, "setAccumulatePixels"):        # newer QGIS; on 3.44 use a cumulative time range instead
            tpr.setAccumulatePixels(True)
    end = T0.addSecs(2767)
    project.timeSettings().setTemporalRange(QgsDateTimeRange(T0, end))
    project.timeSettings().setTimeStep(17.0); project.timeSettings().setTimeStepUnit(Qgis.TemporalUnit.Seconds)
    project.timeSettings().setFramesPerSecond(12.0)
    if hasattr(project.timeSettings(), "setIsTemporalRangeCumulative"):
        project.timeSettings().setIsTemporalRangeCumulative(True)   # every frame starts at take-off

    # ---- baseline
    for case, lbl in (("agl300", "300 m AGL"), ("msl5500", "5500 m MSL")):
        c = _raster(R / f"count_{case}.tif", f"Times seen, {lbl}", g_base, False)
        _ramp(c, [(1, "#fcfdbf", "1"), (5, "#fc8961", "5"), (15, "#b73779", "15"), (40, "#51127c", "40+"), (80, "#000004", "")], opacity=0.8)
        bl = _raster(R / f"blind_{case}.tif", f"Blind spots in 20 km corridor, {lbl}", g_base, False)
        bl.setRenderer(QgsPalettedRasterRenderer(bl.dataProvider(), 1, [QgsPalettedRasterRenderer.Class(1, QColor("#1d4ed8"), "never seen")]))
        bl.renderer().setOpacity(0.5)

    # ---- idea 2
    I2 = R / "idea2"
    for prof in ("valley", "cruise"):
        for s, lbl in (("forward", "forward camera"), ("side", "side cameras"), ("omni_gsd3", "omni, 3 m resolution")):
            d = _raster(I2 / f"dwell_{prof}_{s}.tif", f"Dwell time (s), {prof}, {lbl}", g_sens, False)
            _ramp(d, [(8, "#440154", "8 s"), (60, "#21918c", "60 s"), (300, "#fde725", "300 s+")], opacity=0.85)
        p = _raster(I2 / f"p_seen_{prof}.tif", f"P(seen) with DEM + position error, {prof}", g_sens, False)
        _ramp(p, [(0.05, "#d73027", "rarely"), (0.5, "#fee08b", "50%"), (0.95, "#1a9850", "reliable"), (1.0, "#006837", "")], opacity=0.85)

    # ---- idea 3
    U = R / "usecases"
    fu = _raster(U / "fleet_union.tif", "Several aircraft: area seen together", g_use, False)
    fu.setRenderer(QgsPalettedRasterRenderer(fu.dataProvider(), 1, [QgsPalettedRasterRenderer.Class(1, QColor("#2a9d8f"), "seen")]))
    fu.renderer().setOpacity(0.6)
    fr = _vector(U / "fleet_routes.geojson", "Several aircraft: parallel routes", g_use, False)
    fr.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({"color": "#264653", "width": "0.5", "line_style": "dash"})))
    top.setExpanded(True)
    return {"layers": len(top.findLayerIds()), "range": [T0.toString(Qt.ISODate), end.toString(Qt.ISODate)]}


if __name__ == "__main__":
    import sys
    from qgis.core import QgsApplication
    app = QgsApplication([], False); app.initQgis()
    pr = QgsProject.instance(); pr.setCrs(QgsCoordinateReferenceSystem("EPSG:32644"))
    print(build(pr, sys.argv[1])); pr.write(sys.argv[2]); app.exitQgis()
