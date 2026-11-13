"""Map layers that show the planner state: DEM (hillshade + tint), radar threat, radars, start/goal, routes."""
import itertools

import numpy as np
from osgeo import gdal
from qgis.core import (QgsColorRampShader, QgsCoordinateReferenceSystem, QgsFeature, QgsField, QgsGeometry,
                       QgsHillshadeRenderer, QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings, QgsPointXY,
                       QgsProject, QgsRasterLayer, QgsRasterShader, QgsSingleBandPseudoColorRenderer,
                       QgsTextBufferSettings, QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsCategorizedSymbolRenderer,
                       QgsRendererCategory)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

GROUP = "Visibility Corridor"
_ids = itertools.count(1)


class LayerSet:
    def __init__(self, planner, dem_source):
        self.P = planner
        self.uid = next(_ids)
        self.crs = QgsCoordinateReferenceSystem.fromWkt(planner.dem.proj)
        self.threat_path = f"/vsimem/visibility_corridor_threat_{self.uid}.tif"
        root = QgsProject.instance().layerTreeRoot()
        old = root.findGroup(GROUP)
        if old is not None:
            QgsProject.instance().removeMapLayers([l.layerId() for l in old.findLayers()])
            root.removeChildNode(old)
        self.group = root.insertGroup(0, GROUP)
        self.route = self._vector("LineString", "Route (exact)", [QgsField("cost", QVariant.Double),
                                                                  QgsField("length_km", QVariant.Double)])
        self.route.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "0,229,255", "width": "0.9",
                                                                    "capstyle": "round", "joinstyle": "round"}))
        self.stage = self._vector("LineString", "Route (first answer)", [QgsField("stage", QVariant.String)])
        self.stage.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "255,209,102", "width": "0.6",
                                                                    "line_style": "dash"}))
        self.ends = self._vector("Point", "Start / goal", [QgsField("role", QVariant.String)])
        cats = [QgsRendererCategory("start", QgsMarkerSymbol.createSimple(
                    {"name": "circle", "color": "6,214,160", "size": "3.6", "outline_color": "0,0,0"}), "start"),
                QgsRendererCategory("goal", QgsMarkerSymbol.createSimple(
                    {"name": "star", "color": "255,214,10", "size": "6", "outline_color": "0,0,0"}), "goal")]
        self.ends.setRenderer(QgsCategorizedSymbolRenderer("role", cats))
        self.radars = self._vector("Point", "Radars", [QgsField("id", QVariant.String)])
        self.radars.renderer().setSymbol(QgsMarkerSymbol.createSimple(
            {"name": "triangle", "color": "208,0,0", "size": "4.4", "outline_color": "255,255,255", "outline_width": "0.4"}))
        lab = QgsPalLayerSettings(); lab.fieldName = "id"
        fmt = QgsTextFormat(); fmt.setSize(9); fmt.setColor(QColor("#7a0000"))
        buf = QgsTextBufferSettings(); buf.setEnabled(True); buf.setSize(1); buf.setColor(QColor("white"))
        fmt.setBuffer(buf); lab.setFormat(fmt)
        lab.yOffset = -4
        self.radars.setLabeling(QgsVectorLayerSimpleLabeling(lab)); self.radars.setLabelsEnabled(True)
        self.write_threat()
        self.threat = QgsRasterLayer(self.threat_path, "Radar threat", "gdal")
        self._style_threat()
        self.tint = QgsRasterLayer(dem_source, "Elevation", "gdal")
        self._style_tint()
        self.hill = QgsRasterLayer(dem_source, "Hillshade", "gdal")
        self.hill.setRenderer(QgsHillshadeRenderer(self.hill.dataProvider(), 1, 315, 45))
        for lyr in (self.route, self.stage, self.ends, self.radars, self.threat, self.tint, self.hill):
            QgsProject.instance().addMapLayer(lyr, False)
            self.group.addLayer(lyr)
        self.update_all()

    # ---------------------------------------------------------------- helpers
    def _vector(self, geom, name, fields):
        lyr = QgsVectorLayer(f"{geom}?crs={self.crs.authid() or 'EPSG:4326'}", name, "memory")
        if not self.crs.authid():
            lyr.setCrs(self.crs)
        lyr.dataProvider().addAttributes(fields)
        lyr.updateFields()
        return lyr

    def _style_tint(self):
        z = self.P.dem.z
        lo, hi = float(np.nanpercentile(z, 2)), float(np.nanpercentile(z, 98))
        ramp = [(0.0, "#2b83ba"), (0.25, "#abdda4"), (0.5, "#ffffbf"), (0.75, "#d7a35b"), (1.0, "#f5f5f5")]
        items = [QgsColorRampShader.ColorRampItem(lo + f * (hi - lo), QColor(c)) for f, c in ramp]
        sh = QgsColorRampShader(lo, hi); sh.setColorRampItemList(items)
        rs = QgsRasterShader(); rs.setRasterShaderFunction(sh)
        r = QgsSingleBandPseudoColorRenderer(self.tint.dataProvider(), 1, rs)
        r.setOpacity(0.35)
        self.tint.setRenderer(r)

    def _style_threat(self):
        items = [QgsColorRampShader.ColorRampItem(1, QColor(255, 51, 25, 20), "low"),
                 QgsColorRampShader.ColorRampItem(255, QColor(255, 38, 13, 200), "high")]
        sh = QgsColorRampShader(1, 255); sh.setColorRampItemList(items)
        rs = QgsRasterShader(); rs.setRasterShaderFunction(sh)
        self.threat.setRenderer(QgsSingleBandPseudoColorRenderer(self.threat.dataProvider(), 1, rs))

    def write_threat(self):
        """Threat surface (radar exposure / detection hazard) as a byte raster in GDAL's memory file system;
        QGIS reads the same GDAL instance, so a repaint is enough after an edit."""
        E = self.P.field.E
        m = float(E.max()) or 1.0
        b = np.where(E > 0, np.clip(1 + 254 * E / m, 1, 255), 0).astype(np.uint8)
        d = self.P.dem
        ds = gdal.GetDriverByName("GTiff").Create(self.threat_path, b.shape[1], b.shape[0], 1, gdal.GDT_Byte)
        ds.SetGeoTransform(d.gt); ds.SetProjection(d.proj)
        band = ds.GetRasterBand(1); band.SetNoDataValue(0); band.WriteArray(b)
        ds.FlushCache(); ds = None

    def _points(self, path):
        W = self.P.p.W
        to_world = self.P.dem.to_world
        return [QgsPointXY(*to_world(i % W, i // W)) for i in path]

    @staticmethod
    def _replace(layer, feats):
        pr = layer.dataProvider()
        pr.truncate()
        if feats:
            pr.addFeatures(feats)
        layer.updateExtents()
        layer.triggerRepaint()

    # ---------------------------------------------------------------- updates
    def update_route(self, stage=None):
        P = self.P
        if stage is not None and stage.get("level", 1) > 1 and stage.get("path"):
            f = QgsFeature(self.stage.fields()); f.setGeometry(QgsGeometry.fromPolylineXY(self._points(stage["path"])))
            f.setAttributes([stage.get("stage", "")])
            self._replace(self.stage, [f])
            return
        self._replace(self.stage, [])
        feats = []
        if getattr(P, "path", None):
            g = QgsGeometry.fromPolylineXY(self._points(P.path))
            f = QgsFeature(self.route.fields()); f.setGeometry(g)
            f.setAttributes([float(P.cost), round(g.length() / 1000.0, 2)])
            feats.append(f)
        self._replace(self.route, feats)

    def update_ends(self):
        P = self.P
        feats = []
        for role, (r, c) in (("start", P.start), ("goal", P.goal)):
            f = QgsFeature(self.ends.fields()); f.setAttributes([role])
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*P.dem.to_world(c, r)))); feats.append(f)
        self._replace(self.ends, feats)

    def update_radars(self):
        feats = []
        for i, (x, y) in enumerate(self.P.field.sites):
            f = QgsFeature(self.radars.fields()); f.setAttributes([f"R{i + 1}"])
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y))); feats.append(f)
        self._replace(self.radars, feats)

    def update_threat(self):
        self.write_threat()
        self.threat.dataProvider().reloadData()
        self.threat.triggerRepaint()

    def update_all(self):
        self.update_radars(); self.update_ends(); self.update_route()

    def extent(self):
        return self.hill.extent()

    def all(self):
        return [self.route, self.stage, self.ends, self.radars, self.threat, self.tint, self.hill]

    def remove(self):
        root = QgsProject.instance().layerTreeRoot()
        g = root.findGroup(GROUP)
        if g is not None:
            QgsProject.instance().removeMapLayers([l.layerId() for l in g.findLayers()])
            root.removeChildNode(g)
        gdal.Unlink(self.threat_path)
