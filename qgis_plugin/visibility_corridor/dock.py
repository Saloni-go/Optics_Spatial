"""Planner dock: scenario set-up, the interactive map tool, weights, risk budget, status and the timing log."""
import json
import math
import os
import threading
import time

from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsMapLayerProxyModel, QgsProject, QgsTask, QgsVectorFileWriter, QgsWkbTypes)
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QSlider, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout,
                                 QGroupBox, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton, QScrollArea, QSpinBox,
                                 QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from . import ENGINE

DATA = os.path.join(ENGINE, "data")
BANK = (2.5, 5, 10, 20, 40, 80)
HELP = ("<b>Map controls</b> (planner tool active):<br>"
        "left click = start &nbsp;&middot;&nbsp; right click = goal<br>"
        "drag a radar = move it &nbsp;&middot;&nbsp; <b>R</b> / <b>X</b> = add / remove radar at the cursor<br>"
        "<b>+</b> / <b>&minus;</b> = exposure weight &alpha; &times;2 / &divide;2 &nbsp;&middot;&nbsp; "
        "<b>B</b> = shortest route under the detection budget<br>"
        "wheel = zoom &nbsp;&middot;&nbsp; middle-drag or hold <b>Space</b> = pan (live coverage follows the view)")


def scenarios():
    f = os.path.join(DATA, "scenarios.json")
    return json.load(open(f)) if os.path.exists(f) else {}


def prepare_dem(path):
    """Return a DEM path in a projected metric CRS: a geographic DEM is warped to its UTM zone (bilinear)."""
    from osgeo import gdal, osr
    ds = gdal.Open(path)
    srs = osr.SpatialReference(wkt=ds.GetProjection())
    if not srs.IsGeographic():
        return path, None
    gt = ds.GetGeoTransform()
    lon = gt[0] + gt[1] * ds.RasterXSize / 2; lat = gt[3] + gt[5] * ds.RasterYSize / 2
    epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1
    res = max(10.0, round(abs(gt[1]) * 111320 * math.cos(math.radians(lat)) / 10) * 10)
    import hashlib
    import tempfile
    tag = hashlib.md5(f"{os.path.abspath(path)}{os.path.getmtime(path)}".encode()).hexdigest()[:10]
    out = os.path.join(tempfile.gettempdir(), f"visibility_corridor_dem_{tag}_utm{epsg}.tif")
    if os.path.exists(out):
        return out, f"reprojected to EPSG:{epsg} (cached)"
    gdal.Warp(out, ds, dstSRS=f"EPSG:{epsg}", xRes=res, yRes=res, resampleAlg="bilinear", dstNodata=-9999)
    return out, f"reprojected to EPSG:{epsg} at {res:g} m"


class CorridorDock(QDockWidget):
    def __init__(self, iface):
        super().__init__("Visibility Corridor")
        self.iface, self.canvas = iface, iface.mapCanvas()
        self.setObjectName("VisibilityCorridorDock")
        self.P = self.layers = self.tool = self.task = self.live = None
        self.busy = False
        self.n_logged = 0
        self._seen_ctg = None
        self.timer = QTimer(self); self.timer.setInterval(150); self.timer.timeout.connect(self.poll)
        self._build_ui()

    # ================================================================ UI
    def _build_ui(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(6, 6, 6, 6)

        g = QGroupBox("Scenario"); f = QFormLayout(g)
        self.dem_combo = QComboBox()
        for key, s in sorted(scenarios().items(), key=lambda kv: int(kv[0])):
            self.dem_combo.addItem(s["title"], ("bundled", key))
        self.dem_combo.addItem("DEM raster layer from the project", ("layer", None))
        self.dem_layer = QgsMapLayerComboBox(); self.dem_layer.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.dem_layer.setAllowEmptyLayer(True); self.dem_layer.setLayer(None)
        self.radar_combo = QComboBox()
        self.radar_combo.addItem("Scenario radar sites", "scenario")
        self.radar_combo.addItem("Automatic ridge-top sites", "auto")
        self.radar_combo.addItem("Point layer from the project", "layer")
        self.n_radars = QSpinBox(); self.n_radars.setRange(1, 30); self.n_radars.setValue(6)
        self.radar_layer = QgsMapLayerComboBox(); self.radar_layer.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.radar_layer.setAllowEmptyLayer(True); self.radar_layer.setLayer(None)
        self.mode = QComboBox(); self.mode.addItem("Detection probability", "detection"); self.mode.addItem("Exposure (visible cells)", "exposure")
        self.load_btn = QPushButton("Load scenario and precompute"); self.load_btn.clicked.connect(self.load)
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.hide()
        f.addRow("DEM", self.dem_combo); f.addRow("", self.dem_layer)
        f.addRow("Radars", self.radar_combo)
        nr = QHBoxLayout(); nr.addWidget(QLabel("count")); nr.addWidget(self.n_radars); nr.addWidget(self.radar_layer, 1)
        f.addRow("", nr)
        f.addRow("Threat model", self.mode)
        f.addRow(self.load_btn); f.addRow(self.progress)
        self.dem_combo.currentIndexChanged.connect(self._sync); self.radar_combo.currentIndexChanged.connect(self._sync)
        lay.addWidget(g)

        g = QGroupBox("Interact"); v = QVBoxLayout(g)
        self.tool_btn = QPushButton("Planner map tool"); self.tool_btn.setCheckable(True); self.tool_btn.setEnabled(False)
        self.tool_btn.toggled.connect(self._tool_toggled)
        v.addWidget(self.tool_btn)
        hl = QLabel(HELP); hl.setWordWrap(True); v.addWidget(hl)
        h = QHBoxLayout()
        self.alpha_spin = QDoubleSpinBox(); self.alpha_spin.setRange(0.25, 1000); self.alpha_spin.setDecimals(2); self.alpha_spin.setValue(10)
        self.alpha_spin.setPrefix("alpha = ")
        b_half = QToolButton(); b_half.setText("÷2"); b_half.clicked.connect(lambda: self.set_alpha(self.P.p.alpha / 2))
        b_dbl = QToolButton(); b_dbl.setText("×2"); b_dbl.clicked.connect(lambda: self.set_alpha(self.P.p.alpha * 2))
        b_set = QToolButton(); b_set.setText("Set"); b_set.clicked.connect(lambda: self.set_alpha(self.alpha_spin.value()))
        for x in (self.alpha_spin, b_half, b_dbl, b_set):
            h.addWidget(x)
        v.addLayout(h)
        # on the fly: alpha slider (bank lookups while dragging, exact field on release) and hover preview
        h = QHBoxLayout()
        self.alpha_slider = QSlider(Qt.Horizontal); self.alpha_slider.setRange(0, 100)      # log scale 0.25 .. 160
        self.alpha_slider.setValue(self._slider_from_alpha(10))
        self.alpha_slider.setToolTip("Drag: route from the precomputed alpha bank at every step; release: exact route")
        self.alpha_slider.valueChanged.connect(self._slide_preview)
        self.alpha_slider.sliderReleased.connect(lambda: self.set_alpha(self._alpha_from_slider(self.alpha_slider.value())))
        h.addWidget(QLabel("alpha live")); h.addWidget(self.alpha_slider, 1)
        v.addLayout(h)
        self.hover_box = QCheckBox("Live route preview from the cursor (Level 2 lookup on every mouse move)")
        self.hover_box.setChecked(True)
        v.addWidget(self.hover_box)
        self.hover_info = QLabel(""); self.hover_info.setWordWrap(True); v.addWidget(self.hover_info)
        h = QHBoxLayout()
        self.budget = QSpinBox(); self.budget.setRange(1, 99); self.budget.setValue(50); self.budget.setPrefix("P(detect) ≤ "); self.budget.setSuffix(" %")
        self.budget_btn = QPushButton("Shortest route under budget"); self.budget_btn.clicked.connect(self.risk_budget)
        h.addWidget(self.budget); h.addWidget(self.budget_btn, 1)
        v.addLayout(h)
        self.interact_box = g; g.setEnabled(False)
        lay.addWidget(g)

        g = QGroupBox("Pan and zoom on the fly"); v = QVBoxLayout(g)
        self.live_box = QCheckBox("Live radar coverage for the visible window")
        self.live_box.setToolTip("Every pan / zoom recomputes how many radars see an aircraft (150 m above ground) "
                                 "for the visible window only, at one cell per screen pixel; full 30 m resolution when zoomed in")
        self.live_box.setChecked(True); self.live_box.toggled.connect(self._live_toggled)
        self.live_density = QComboBox()
        self.live_density.addItem("1 computed cell per screen pixel", 1.0)
        self.live_density.addItem("2 per pixel (sharper, slower)", 2.0)
        self.live_density.addItem("1 per 2 pixels (fastest)", 0.5)
        self.live_density.currentIndexChanged.connect(self._live_density)
        v.addWidget(self.live_box); v.addWidget(self.live_density)
        legend = " ".join(f"<span style='background:rgb({r},{gg},{b});'>&nbsp;{i}&nbsp;</span>"
                          for i, (r, gg, b) in enumerate([(255, 237, 160), (254, 217, 118), (254, 178, 76), (253, 141, 60),
                                                          (252, 78, 42), (227, 26, 28)], 1))
        v.addWidget(QLabel("radars that see the aircraft: " + legend + "+"))
        self.live_info = QLabel(""); self.live_info.setWordWrap(True); v.addWidget(self.live_info)
        self.live_group = g; g.setEnabled(False)
        lay.addWidget(g)

        g = QGroupBox("Status"); v = QVBoxLayout(g)
        self.status = QLabel("Load a scenario to start."); self.status.setWordWrap(True); v.addWidget(self.status)
        lay.addWidget(g)

        g = QGroupBox("What answered each action, and how fast"); v = QVBoxLayout(g)
        self.log_table = QTableWidget(0, 3)
        self.log_table.setHorizontalHeaderLabels(["Action", "ms", "How"])
        self.log_table.verticalHeader().hide()
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self.log_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents); hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        fnt = QFont(); fnt.setPointSize(8); self.log_table.setFont(fnt)
        self.log_table.setWordWrap(True)
        v.addWidget(self.log_table)
        self.export_btn = QPushButton("Export route, radars and threat surface…"); self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export)
        v.addWidget(self.export_btn)
        lay.addWidget(g, 1)
        self.log_table.setMinimumHeight(140)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(w)                                  # small screens: the panel scrolls instead of clipping
        self.setWidget(scroll)
        self._sync()

    def _sync(self):
        custom = self.dem_combo.currentData()[0] == "layer"
        self.dem_layer.setEnabled(custom)
        src = self.radar_combo.currentData()
        if custom and src == "scenario":
            self.radar_combo.setCurrentIndex(1); src = "auto"
        self.n_radars.setEnabled(src == "auto")
        self.radar_layer.setEnabled(src == "layer")

    def message(self, text, level=Qgis.Info, secs=5):
        self.iface.messageBar().pushMessage("Visibility Corridor", text, level, secs)

    # ================================================================ load
    def load(self):
        if self.busy:
            return
        kind, key = self.dem_combo.currentData()
        spec = {"mode": self.mode.currentData(), "radars": self.radar_combo.currentData(), "n": self.n_radars.value()}
        if kind == "bundled":
            s = scenarios()[key]
            spec.update(dem=os.path.join(DATA, s["dem"]), sites=s["sites"], ends=(s["start"], s["goal"]), title=s["title"])
        else:
            lyr = self.dem_layer.currentLayer()
            if lyr is None:
                self.message("Choose a DEM raster layer first.", Qgis.Warning); return
            spec.update(dem=lyr.source(), sites=None, ends=None, title=lyr.name())
        if spec["radars"] == "auto":
            spec["sites"] = None
        elif spec["radars"] == "layer":
            pl = self.radar_layer.currentLayer()
            if pl is None:
                self.message("Choose a point layer with the radar sites.", Qgis.Warning); return
            spec["radar_layer"] = (pl, [f.geometry().asPoint() for f in pl.getFeatures() if not f.geometry().isEmpty()])
        self.shutdown(keep_ui=True)
        self.busy = True
        self.load_btn.setEnabled(False); self.progress.show()
        self.status.setText(f"Loading <b>{spec['title']}</b>: radar threat surface, cost-to-go field, alpha bank …")

        def work(task):
            from corridor.interactive_core import Planner
            from common.dem_utils import DEM
            note = None
            dem_file, note = prepare_dem(spec["dem"])
            dem = DEM(dem_file)
            sites = spec["sites"]
            if "radar_layer" in spec:
                lyr, pts = spec["radar_layer"]
                tr = QgsCoordinateTransform(lyr.crs(), QgsCoordinateReferenceSystem.fromWkt(dem.proj), QgsProject.instance())
                sites = [(p.x(), p.y()) for p in (tr.transform(q) for q in pts)]
                sites = [s for s in sites if dem.contains(*s)]
                if not sites:
                    raise ValueError("none of the radar points lies on the DEM")
            P = Planner(mode=spec["mode"], dem=dem, sites=sites, n_radars=spec["n"], ends=spec["ends"])
            P.precompute(landmarks=False, bank=BANK)
            P.set_start(P.start)
            from corridor.liveview import LiveCoverage
            return {"P": P, "dem_file": dem_file, "note": note, "live": LiveCoverage(P.dem)}

        self.task = QgsTask.fromFunction("Visibility Corridor: precompute", work, on_finished=self._loaded)
        QgsApplication.taskManager().addTask(self.task)

    def _loaded(self, exception, result=None):
        self.busy = False; self.task = None
        self.load_btn.setEnabled(True); self.progress.hide()
        if exception is not None or result is None:
            self.status.setText(f"<span style='color:#b00'>Loading failed: {exception}</span>")
            self.message(f"Loading failed: {exception}", Qgis.Critical, 10)
            return
        from .layers import LayerSet
        from .maptool import CorridorMapTool
        self.P = result["P"]
        prj = QgsProject.instance()
        others = len(prj.mapLayers())
        self.layers = LayerSet(self.P, result["dem_file"])
        if others == 0:
            prj.setCrs(self.layers.crs)
        for combo in (self.dem_layer, self.radar_layer):        # the planner's own layers are not inputs
            combo.setExceptedLayerList(self.layers.all())
        tr = QgsCoordinateTransform(self.layers.crs, self.canvas.mapSettings().destinationCrs(), prj)
        self.canvas.setExtent(tr.transformBoundingBox(self.layers.extent())); self.canvas.refresh()
        self.tool = CorridorMapTool(self.canvas, self.layers.crs, lambda: self.P.field.sites)
        self.tool.start.connect(self.on_start); self.tool.goal.connect(self.on_goal)
        self.tool.move_radar.connect(self.on_move_radar); self.tool.add_radar.connect(self.on_add_radar)
        self.tool.remove_radar.connect(self.on_remove_radar); self.tool.key.connect(self.on_key)
        self.tool.hover.connect(self.on_hover)
        self.tool.deactivated.connect(lambda: self.tool_btn.setChecked(False))
        self.tool_btn.setEnabled(True); self.interact_box.setEnabled(True); self.export_btn.setEnabled(True)
        self.budget.setEnabled(self.P.mode == "detection"); self.budget_btn.setEnabled(self.P.mode == "detection")
        self.alpha_spin.setValue(self.P.p.alpha)
        self.log_table.setRowCount(0); self.n_logged = 0
        self._seen_ctg = self.P.ctg
        from .liveitem import LiveCoverageView
        self.live = LiveCoverageView(self.canvas, result["live"], self.layers.crs, lambda: self.P.field.sites,
                                     on_result=self._live_result)
        self.live.density = self.live_density.currentData()
        self.live_group.setEnabled(True)
        self.live.set_enabled(self.live_box.isChecked())
        self.tool_btn.setChecked(True)
        self.timer.start()
        self.refresh()
        if result["note"]:
            self.message("DEM " + result["note"], Qgis.Info, 8)

    def _tool_toggled(self, on):
        if self.tool is None:
            return
        if on:
            self.canvas.setMapTool(self.tool); self.canvas.setFocus()
        elif self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)

    # ================================================================ actions
    def _rc(self, x, y):
        c, r = self.P.dem.to_pixel(x, y)
        r, c = int(round(r)), int(round(c))
        if not (0 <= r < self.P.p.H and 0 <= c < self.P.p.W):
            self.message("That point is outside the DEM.", Qgis.Warning, 3); return None
        if self.P.p.blocked[r, c]:
            self.message("That cell is above the flight ceiling (blocked).", Qgis.Warning, 3); return None
        return r, c

    def _ready(self):
        if self.P is None or self.busy:
            if self.busy:
                self.message("Still working on the previous request…", Qgis.Info, 2)
            return False
        return True

    def on_start(self, x, y):
        if self._ready() and (rc := self._rc(x, y)):
            self.P.set_start(rc)
            self.layers.update_ends(); self.layers.update_route(); self.refresh()

    def on_goal(self, x, y):
        if self._ready() and (rc := self._rc(x, y)):
            self.P.set_goal(rc, background=True)
            self.layers.update_ends(); self.layers.update_route(); self.refresh()

    def _radar_edit(self, kind, **kw):
        if not self._ready():
            return
        self.P.edit_radar(kind, background=True, **kw)
        self.layers.update_radars(); self.layers.update_threat(); self.layers.update_route(); self.refresh()
        if self.live is not None:
            self.live.request()

    def on_move_radar(self, i, x, y):
        if self.P is not None and self.P.dem.contains(x, y):
            self._radar_edit("move", i=i, x=x, y=y)

    def on_add_radar(self, x, y):
        if self.P is not None and self.P.dem.contains(x, y):
            self._radar_edit("add", x=x, y=y)

    def on_remove_radar(self, i):
        if self.P is not None and len(self.P.field.sites) > 1:
            self._radar_edit("remove", i=i)

    def set_alpha(self, alpha):
        if not self._ready():
            return
        alpha = max(0.25, min(float(alpha), 1000.0))

        def stage(r):
            if threading.current_thread() is threading.main_thread():
                self.layers.update_route(r)
        self.P.set_alpha(alpha, on_route=stage, background=True)
        self.alpha_spin.setValue(alpha)
        self.alpha_slider.blockSignals(True); self.alpha_slider.setValue(self._slider_from_alpha(alpha))
        self.alpha_slider.blockSignals(False)
        self._preview(None, "")
        self.layers.update_route(); self.refresh()

    # ---------------------------------------------------------------- on the fly
    def _live_toggled(self, on):
        if self.live is not None:
            self.live.set_enabled(on)
        if not on:
            self.live_info.setText("")

    def _live_density(self):
        if self.live is not None:
            self.live.density = self.live_density.currentData(); self.live.request()

    def _live_result(self, out):
        if "error" in out:
            self.live_info.setText(f"<span style='color:#b00'>live coverage failed: {out['error']}</span>"); return
        k = out["level"]; h, w = out["count"].shape
        how = (f"coverage for the view: {w} × {h} cells at {k * self.P.p.cell:g} m (level {k})"
               + (", exact" if k == 1 else "") + f", {out['radars']} radars in reach")
        self.live_info.setText(f"{how} &nbsp;·&nbsp; <b>{out['ms']:.0f} ms</b>")
        self.P.log("pan / zoom", out["ms"] / 1000, how)
        self.refresh()

    @staticmethod
    def _alpha_from_slider(v):
        return round(0.25 * 2 ** (v / 100 * math.log2(160 / 0.25)), 2)

    @staticmethod
    def _slider_from_alpha(a):
        return int(round(100 * math.log2(max(a, 0.25) / 0.25) / math.log2(160 / 0.25)))

    def _preview(self, path, label):
        from qgis.core import QgsGeometry, QgsPointXY
        from qgis.gui import QgsRubberBand
        from qgis.PyQt.QtGui import QColor
        if getattr(self, "band", None) is None:
            self.band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
            self.band.setColor(QColor(255, 79, 216, 220)); self.band.setWidth(2)
        if not path:
            self.band.reset(QgsWkbTypes.LineGeometry); self.hover_info.setText(""); return
        W = self.P.p.W; to_world = self.P.dem.to_world
        step = max(1, len(path) // 1500)                                   # about one vertex per screen pixel
        g = QgsGeometry.fromPolylineXY([QgsPointXY(*to_world(i % W, i // W)) for i in path[::step] + [path[-1]]])
        tr = QgsCoordinateTransform(self.layers.crs, self.canvas.mapSettings().destinationCrs(), QgsProject.instance())
        g.transform(tr)
        self.band.setToGeometry(g, None)
        self.hover_info.setText(label)

    def on_hover(self, x, y):
        """Route from the cursor to the goal, drawn while the mouse moves: one Level 2 lookup per event."""
        P = self.P
        if P is None or self.busy or not self.hover_box.isChecked() or P.ctg is None:
            return
        c, r = P.dem.to_pixel(x, y)
        r, c = int(round(r)), int(round(c))
        if not (0 <= r < P.p.H and 0 <= c < P.p.W) or P.p.blocked[r, c]:
            self._preview(None, ""); return
        t = time.perf_counter()
        path, cost = P.ctg.route((r, c))
        ms = 1000 * (time.perf_counter() - t)
        if not path:
            self._preview(None, ""); return
        pd = P.detection_probability(path) if P.mode == "detection" else None
        km = len(path) * P.p.cell / 1000
        self._preview(path, f"<span style='color:#c0007a'>From the cursor:</span> about {km:.0f} km"
                            + (f", P(detect) {100 * pd:.1f}%" if pd is not None else "") + f" &nbsp;·&nbsp; lookup {ms:.2f} ms")

    def _slide_preview(self, v):
        """While the alpha slider moves: route from the alpha bank (nearest precomputed alpha), no search."""
        P = self.P
        alpha = self._alpha_from_slider(v)
        if P is None or self.busy or not self.alpha_slider.isSliderDown():
            return
        if not P._bank_ok():
            self.hover_info.setText(f"alpha {alpha:g}: alpha bank rebuilding, release to compute exactly"); return
        t = time.perf_counter()
        path, cost, a = P.bank.route(P.start, alpha)
        ms = 1000 * (time.perf_counter() - t)
        pd = P.detection_probability(path) if P.mode == "detection" else None
        self._preview(path, f"alpha {alpha:g} (bank alpha {a:g})" + (f": P(detect) {100 * pd:.1f}%" if pd is not None else "")
                      + f" &nbsp;·&nbsp; bank lookup {ms:.1f} ms; release for the exact route")

    def on_key(self, k):
        if self.P is None:
            return
        if k in ("+", "="):
            self.set_alpha(self.P.p.alpha * 2)
        elif k == "-":
            self.set_alpha(self.P.p.alpha / 2)
        elif k == "b" and self.P.mode == "detection":
            self.risk_budget()

    def risk_budget(self):
        if not self._ready() or self.P.mode != "detection":
            return
        if self.P.ctg is None:
            self.message("The cost-to-go field is still being rebuilt; try again in a moment.", Qgis.Info, 3); return
        p_max = self.budget.value() / 100.0
        self.busy = True; self.progress.show(); self.budget_btn.setEnabled(False)
        P = self.P

        def work(task):
            return P.risk_budget(p_max)

        def done(exception, rb=None):
            self.busy = False; self.progress.hide(); self.budget_btn.setEnabled(True); self.task = None
            if exception is not None or rb is None:
                self.message(f"Risk budget failed: {exception}", Qgis.Critical, 8); return
            how = (f"LARAC, {rb['solves']} fields, {rb['length_km']:.0f} km, P(detect) {100 * rb['p_detect']:.0f}%, "
                   f"within {rb['gap_pct']:.1f}% of optimal" if rb["found"]
                   else f"no route under {100 * p_max:.0f}% exists ({rb['solves']} searches); route unchanged")
            P.log(f"risk budget {100 * p_max:.0f}%", rb["seconds"], how)
            self.layers.update_route(); self.refresh()

        self.task = QgsTask.fromFunction("Visibility Corridor: risk budget", work, on_finished=done)
        QgsApplication.taskManager().addTask(self.task)

    # ================================================================ refresh
    def poll(self):
        """Background field rebuilds finish on worker threads: redraw when the field object changes."""
        P = self.P
        if P is None:
            return
        ctg = P.ctg
        if ctg is not None and ctg is not self._seen_ctg and not self.busy:
            self._seen_ctg = ctg
            if P.events and P.events[-1]["action"] != "set alpha (exact)":
                P.path, P.cost = ctg.route(P.start)
            self.layers.update_route()
            self.refresh()
        elif ctg is None:
            self._seen_ctg = None
        if len(P.events) > self.n_logged:
            self.refresh()

    def refresh(self):
        P = self.P
        if P is None:
            return
        for e in P.events[self.n_logged:]:
            self.log_table.insertRow(0)
            for j, val in enumerate((e["action"], f"{e['ms']:.1f}", e["how"])):
                it = QTableWidgetItem(val)
                if j == 1:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.log_table.setItem(0, j, it)
        self.n_logged = len(P.events)
        self.log_table.resizeRowsToContents()
        length = None
        if getattr(P, "path", None):
            W = P.p.W
            pts = [divmod(i, W) for i in P.path]
            length = sum(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(pts, pts[1:])) * P.p.cell / 1000
        pd = P.detection_probability() if getattr(P, "path", None) and P.mode == "detection" else None
        cells = P.p.H * P.p.W
        rows = [f"Grid <b>{P.p.H} × {P.p.W}</b> = {cells / 1e6:.1f} M cells, {P.p.cell:g} m &nbsp;·&nbsp; "
                f"{len(P.field.sites)} radars &nbsp;·&nbsp; {P.mode} model",
                f"alpha = <b>{P.p.alpha:g}</b> &nbsp;·&nbsp; beta = {P.p.beta:g} &nbsp;·&nbsp; "
                + ("field <span style='color:#060'>ready</span>" if P.ctg is not None else "field <span style='color:#b60'>rebuilding…</span>")]
        if length is not None:
            rows.append(f"Route <b>{length:.1f} km</b> &nbsp;·&nbsp; cost {P.cost / 1000:.1f} k"
                        + (f" &nbsp;·&nbsp; P(detect) <b>{100 * pd:.1f}%</b>" if pd is not None else ""))
        self.status.setText("<br>".join(rows))

    # ================================================================ export
    def export(self):
        if self.P is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Export to folder")
        if not folder:
            return
        from osgeo import gdal
        stamp = time.strftime("%Y%m%d_%H%M%S")
        opts = QgsVectorFileWriter.SaveVectorOptions(); opts.driverName = "GPKG"
        out = os.path.join(folder, f"corridor_{stamp}.gpkg")
        for i, lyr in enumerate((self.layers.route, self.layers.radars, self.layers.ends)):
            opts.layerName = lyr.name().split(" (")[0].replace(" / ", "_").replace(" ", "_").lower()
            opts.actionOnExistingFile = (QgsVectorFileWriter.CreateOrOverwriteFile if i == 0
                                         else QgsVectorFileWriter.CreateOrOverwriteLayer)
            QgsVectorFileWriter.writeAsVectorFormatV3(lyr, out, QgsProject.instance().transformContext(), opts)
        tif = os.path.join(folder, f"threat_{stamp}.tif")
        gdal.Translate(tif, self.layers.threat_path, creationOptions=["COMPRESS=DEFLATE"])
        self.message(f"Saved {os.path.basename(out)} and {os.path.basename(tif)} in {folder}", Qgis.Success, 6)

    # ================================================================ teardown
    def shutdown(self, keep_ui=False):
        self.timer.stop()
        if self.live is not None:
            self.live.remove(); self.live = None
        if getattr(self, "band", None) is not None:
            self.canvas.scene().removeItem(self.band); self.band = None
        if self.tool is not None:
            if self.canvas.mapTool() is self.tool:
                self.canvas.unsetMapTool(self.tool)
            self.tool.clean(); self.tool = None
        if self.layers is not None:
            self.layers.remove(); self.layers = None
        self.P = None
        if keep_ui:
            self.tool_btn.setChecked(False); self.tool_btn.setEnabled(False)
            self.interact_box.setEnabled(False); self.export_btn.setEnabled(False); self.live_group.setEnabled(False)

    def closeEvent(self, e):
        if self.tool is not None and self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)
        super().closeEvent(e)
