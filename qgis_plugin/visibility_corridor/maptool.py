"""Map tool with the demo's controls:

    left click         new start (route by lookup)          right click   new goal
    drag a radar       move it                              R / X         add radar at cursor / remove nearest
    + / -              exposure weight alpha x2 / /2        B             shortest route under the detection budget
"""
from qgis.core import QgsCoordinateTransform, QgsPointXY, QgsProject, QgsWkbTypes
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor


class CorridorMapTool(QgsMapTool):
    start = pyqtSignal(float, float)          # world x, y in the DEM CRS
    goal = pyqtSignal(float, float)
    move_radar = pyqtSignal(int, float, float)
    add_radar = pyqtSignal(float, float)
    remove_radar = pyqtSignal(int)
    key = pyqtSignal(str)
    hover = pyqtSignal(float, float)          # mouse moved (no button): live preview from the cursor

    PICK_PX = 12

    def __init__(self, canvas, dem_crs, radar_points):
        super().__init__(canvas)
        self.canvas, self.dem_crs, self.radar_points = canvas, dem_crs, radar_points   # radar_points(): [(x, y)] DEM CRS
        self.drag = None
        self.last = None
        self.marker = QgsVertexMarker(canvas)
        self.marker.setIconType(QgsVertexMarker.ICON_TRIANGLE); self.marker.setColor(QColor("#d00000"))
        self.marker.setIconSize(14); self.marker.setPenWidth(2); self.marker.hide()
        self.band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self.band.setColor(QColor(208, 0, 0, 160)); self.band.setWidth(1); self.band.setLineStyle(Qt.DashLine)
        self.setCursor(Qt.CrossCursor)

    # ---------------------------------------------------------------- coordinates
    def _to_dem(self, pt):
        tr = QgsCoordinateTransform(self.canvas.mapSettings().destinationCrs(), self.dem_crs, QgsProject.instance())
        p = tr.transform(pt)
        return p.x(), p.y()

    def _to_map(self, x, y):
        tr = QgsCoordinateTransform(self.dem_crs, self.canvas.mapSettings().destinationCrs(), QgsProject.instance())
        return tr.transform(QgsPointXY(x, y))

    def _nearest_radar(self, pos):
        best, bi = None, None
        for i, (x, y) in enumerate(self.radar_points()):
            px = self.toCanvasCoordinates(self._to_map(x, y))
            d = ((px.x() - pos.x()) ** 2 + (px.y() - pos.y()) ** 2) ** 0.5
            if best is None or d < best:
                best, bi = d, i
        return bi, best

    # ---------------------------------------------------------------- mouse
    def canvasPressEvent(self, e):
        pos = e.pos()
        if e.button() == Qt.LeftButton:
            i, d = self._nearest_radar(pos)
            if i is not None and d < self.PICK_PX:
                self.drag = i
                x, y = self.radar_points()[i]
                self.band.reset(QgsWkbTypes.LineGeometry); self.band.addPoint(self._to_map(x, y))
                self.band.addPoint(self.toMapCoordinates(pos))
                self.marker.setCenter(self.toMapCoordinates(pos)); self.marker.show()
                return
            self.start.emit(*self._to_dem(self.toMapCoordinates(pos)))
        elif e.button() == Qt.RightButton:
            self.goal.emit(*self._to_dem(self.toMapCoordinates(pos)))

    def canvasMoveEvent(self, e):
        self.last = self.toMapCoordinates(e.pos())
        if self.drag is not None:
            self.marker.setCenter(self.last)
            self.band.movePoint(self.last)
        elif e.buttons() == Qt.NoButton:
            self.hover.emit(*self._to_dem(self.last))

    def canvasReleaseEvent(self, e):
        if self.drag is None:
            return
        i, self.drag = self.drag, None
        self.marker.hide(); self.band.reset(QgsWkbTypes.LineGeometry)
        if self._nearest_radar(e.pos())[0] == i and self._nearest_radar(e.pos())[1] < 3:
            return                                            # a click on a radar, not a drag
        self.move_radar.emit(i, *self._to_dem(self.toMapCoordinates(e.pos())))

    # ---------------------------------------------------------------- keys
    def keyPressEvent(self, e):
        k = {Qt.Key_R: "r", Qt.Key_X: "x", Qt.Key_B: "b", Qt.Key_Plus: "+", Qt.Key_Equal: "=",
             Qt.Key_Minus: "-"}.get(e.key(), e.text().lower())
        if k == "r" and self.last is not None:
            self.add_radar.emit(*self._to_dem(self.last))
        elif k == "x" and self.last is not None:
            i, _ = self._nearest_radar(self.toCanvasCoordinates(self.last))
            if i is not None:
                self.remove_radar.emit(i)
        elif k in ("+", "=", "-", "b"):
            self.key.emit(k)
        else:
            e.ignore()
            return
        e.accept()

    def deactivate(self):
        self.marker.hide(); self.band.reset(QgsWkbTypes.LineGeometry)
        super().deactivate()

    def clean(self):
        self.canvas.scene().removeItem(self.marker)
        self.canvas.scene().removeItem(self.band)
