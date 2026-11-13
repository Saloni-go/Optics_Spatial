"""Pan and zoom on the fly: a canvas overlay that shows radar coverage for exactly the visible window.

Every time the map extent settles (pan, zoom, resize, radar moved) the visible window is sent to
corridor.liveview.LiveCoverage on a worker thread; the result (one cell per screen pixel, full resolution
when zoomed in) is drawn as an image over the map.  While a newer view is waiting, older results are
dropped, so a fast pan never queues work.
"""
import threading

import numpy as np
from qgis.core import QgsCoordinateTransform, QgsProject, QgsRectangle
from qgis.gui import QgsMapCanvasItem
from qgis.PyQt.QtCore import QObject, QRectF, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QImage, QPainter

# radar count -> RGBA (0 = transparent); 1..8+ radars, yellow -> dark red
LUT = np.array([[0, 0, 0, 0], [255, 237, 160, 120], [254, 217, 118, 140], [254, 178, 76, 155], [253, 141, 60, 170],
                [252, 78, 42, 180], [227, 26, 28, 190], [189, 0, 38, 200], [128, 0, 38, 210]], np.uint8)


class CoverageItem(QgsMapCanvasItem):
    def __init__(self, canvas):
        super().__init__(canvas)
        self.img = None
        self.setZValue(-5)                       # below rubber bands and markers

    def set_image(self, img, rect):
        self.img = img
        self.setRect(rect)
        self.update()

    def clear(self):
        self.img = None
        self.update()

    def paint(self, painter, *args):
        if self.img is None:
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.drawImage(QRectF(self.boundingRect()), self.img)


class LiveCoverageView(QObject):
    done = pyqtSignal(object)

    def __init__(self, canvas, engine, dem_crs, sites_fn, on_result=None):
        super().__init__()
        self.canvas, self.L, self.dem_crs, self.sites_fn, self.on_result = canvas, engine, dem_crs, sites_fn, on_result
        self.item = CoverageItem(canvas)
        self.density = 1.0
        self.enabled = False
        self.gen = 0                # newest request
        self.running = False
        self.pending = None
        self.debounce = QTimer(); self.debounce.setSingleShot(True); self.debounce.setInterval(60)
        self.debounce.timeout.connect(self.request)
        self.done.connect(self._finished)
        canvas.extentsChanged.connect(self.schedule)

    # ---------------------------------------------------------------- requests
    def set_enabled(self, on):
        self.enabled = on
        if on:
            self.request()
        else:
            self.gen += 1; self.item.clear()

    def schedule(self):
        if self.enabled:
            self.debounce.start()

    def _view(self):
        tr = QgsCoordinateTransform(self.canvas.mapSettings().destinationCrs(), self.dem_crs, QgsProject.instance())
        ext = tr.transformBoundingBox(self.canvas.extent())
        gt, cell = self.L.dem.gt, self.L.cell
        c0 = int(np.floor((ext.xMinimum() - gt[0]) / cell)); c1 = int(np.ceil((ext.xMaximum() - gt[0]) / cell))
        r0 = int(np.floor((gt[3] - ext.yMaximum()) / cell)); r1 = int(np.ceil((gt[3] - ext.yMinimum()) / cell))
        r0, r1 = max(0, r0), min(self.L.H, r1); c0, c1 = max(0, c0), min(self.L.W, c1)
        if r1 <= r0 or c1 <= c0:
            return None, None
        ms = self.canvas.mapSettings()
        sz = ms.outputSize(); dpr = ms.devicePixelRatio() or 1.0
        # pixels covered by the DEM part of the view
        fx = (c1 - c0) * cell / max(ext.width(), 1e-9); fy = (r1 - r0) * cell / max(ext.height(), 1e-9)
        px = (max(1, int(sz.width() * dpr * min(fx, 1.0))), max(1, int(sz.height() * dpr * min(fy, 1.0))))
        return (r0, r1, c0, c1), px

    def request(self):
        if not self.enabled:
            return
        view, px = self._view()
        self.gen += 1
        if view is None:
            self.item.clear(); return
        job = (self.gen, view, px, list(self.sites_fn()), self.density)
        if self.running:
            self.pending = job; return
        self._start(job)

    def _start(self, job):
        self.running = True

        def run():
            gen, view, px, sites, dens = job
            try:
                out = self.L.compute(sites, view, px, density=dens)
                out["gen"] = gen
            except Exception as e:                                    # noqa: BLE001 - shown in the panel
                out = {"gen": gen, "error": str(e)}
            self.done.emit(out)
        threading.Thread(target=run, daemon=True).start()

    def _finished(self, out):
        self.running = False
        if self.pending is not None:
            job, self.pending = self.pending, None
            self._start(job)                     # a newer view is waiting: skip drawing this one
            return
        if out.get("gen") != self.gen or not self.enabled:
            return
        if "error" not in out:
            self._draw(out)
        if self.on_result:
            self.on_result(out)

    def _draw(self, out):
        c = out["count"]
        rgba = np.ascontiguousarray(LUT[np.minimum(c, len(LUT) - 1)])
        h, w = c.shape
        img = QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
        g = out["gt"]
        rect = QgsRectangle(g[0], g[3] + h * g[5], g[0] + w * g[1], g[3])
        tr = QgsCoordinateTransform(self.dem_crs, self.canvas.mapSettings().destinationCrs(), QgsProject.instance())
        self.item.set_image(img, tr.transformBoundingBox(rect))

    def remove(self):
        self.enabled = False
        try:
            self.canvas.extentsChanged.disconnect(self.schedule)
        except Exception:                                             # noqa: BLE001
            pass
        self.canvas.scene().removeItem(self.item)
        self.L.close()
