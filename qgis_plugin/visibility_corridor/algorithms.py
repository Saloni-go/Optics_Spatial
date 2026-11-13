"""Processing Toolbox algorithms: the project's best algorithm for each track, usable in models and batch runs.

    Track 1  Radar coverage                 GDAL viewshed per radar, union count (aircraft or ground target)
    Track 2  Route visibility               threaded window viewsheds along a flight line (F6 best mode)
    Track 3  Radar threat surface           detection hazard / exposure raster (RadarField)
             Least-exposure route           parallel C cost-to-go field (delta-stepping), exact
             Shortest route under a detection budget    LARAC + exact label search (certified gap)
    Check    Route detection check          P(detect) per route and the part outside the cumulative viewshed
"""
import math

import numpy as np
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsFeatureSink, QgsField,
                       QgsFields, QgsGeometry, QgsPointXY, QgsProcessing, QgsProcessingAlgorithm,
                       QgsProcessingException, QgsProcessingParameterEnum, QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterNumber, QgsProcessingParameterPoint,
                       QgsProcessingParameterRasterDestination, QgsProcessingParameterRasterLayer, QgsProject,
                       QgsWkbTypes)
from qgis.PyQt.QtCore import QVariant

MODES = ["detection", "exposure"]


# ------------------------------------------------------------------ shared helpers
def load_dem(alg, parameters, context, feedback):
    from common.dem_utils import DEM
    from .dock import prepare_dem
    lyr = alg.parameterAsRasterLayer(parameters, "DEM", context)
    path, note = prepare_dem(lyr.source())
    if note:
        feedback.pushInfo("DEM " + note)
    dem = DEM(path)
    return dem, QgsCoordinateReferenceSystem.fromWkt(dem.proj)


def points(alg, parameters, name, context, crs):
    src = alg.parameterAsSource(parameters, name, context)
    tr = QgsCoordinateTransform(src.sourceCrs(), crs, QgsProject.instance())
    out = []
    for f in src.getFeatures():
        g = f.geometry()
        if g.isEmpty():
            continue
        for p in (g.asMultiPoint() if g.isMultipart() else [g.asPoint()]):
            q = tr.transform(p); out.append((q.x(), q.y()))
    return out


def point(alg, parameters, name, context, crs, dem, P=None):
    q = alg.parameterAsPoint(parameters, name, context, crs)
    if not dem.contains(q.x(), q.y()):
        raise QgsProcessingException(f"{name.lower()} point is outside the DEM")
    c, r = dem.to_pixel(q.x(), q.y())
    return (r, c)


def write_tif(path, arr, dem, dtype, nodata):
    from common.dem_utils import write_raster
    write_raster(path, arr, dem.gt, dem.proj, dtype, nodata=nodata)


def route_fields():
    f = QgsFields()
    for name, t in (("name", QVariant.String), ("length_km", QVariant.Double), ("cost", QVariant.Double),
                    ("p_detect", QVariant.Double), ("covered_km", QVariant.Double), ("seconds", QVariant.Double),
                    ("note", QVariant.String)):
        f.append(QgsField(name, t))
    return f


def path_metrics(dem, field, covered, path):
    W = dem.shape[1]
    rc = np.column_stack(np.divmod(np.asarray(path), W))
    seg_km = np.hypot(*np.diff(rc, axis=0).T) * dem.cell / 1000.0
    h = field.E[rc[:, 0], rc[:, 1]]
    cov = covered[rc[:, 0], rc[:, 1]].astype(float)
    p = 1 - math.exp(-float((seg_km * 0.5 * (h[1:] + h[:-1])).sum())) if field.mode == "detection" else None
    return float(seg_km.sum()), p, float((seg_km * 0.5 * (cov[1:] + cov[:-1])).sum())


def line_feature(fields, dem, path, values):
    W = dem.shape[1]
    f = QgsFeature(fields)
    f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*dem.to_world(i % W, i // W)) for i in path]))
    f.setAttributes(values)
    return f


class Base(QgsProcessingAlgorithm):
    NAME, LABEL, GROUP, HELP = "", "", "", ""

    def name(self):
        return self.NAME

    def displayName(self):
        return self.LABEL

    def group(self):
        return self.GROUP

    def groupId(self):
        return self.GROUP.lower().replace(" ", "_")

    def shortHelpString(self):
        return self.HELP

    def createInstance(self):
        return type(self)()

    def add_dem_radars(self):
        self.addParameter(QgsProcessingParameterRasterLayer("DEM", "DEM (projected, metres; lat/lon is reprojected to UTM)"))
        self.addParameter(QgsProcessingParameterFeatureSource("RADARS", "Radar sites", [QgsProcessing.TypeVectorPoint]))

    def add_model(self):
        self.addParameter(QgsProcessingParameterEnum("MODEL", "Threat model", ["Detection probability", "Exposure (visible, distance-weighted)"],
                                                     defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber("RANGE", "Radar range (m)", QgsProcessingParameterNumber.Double, 40000, minValue=1000))


def radar_field(alg, parameters, context, dem, crs, feedback):
    from corridor.radarfield import RadarField
    sites = [s for s in points(alg, parameters, "RADARS", context, crs) if dem.contains(*s)]
    if not sites:
        raise QgsProcessingException("no radar site lies on the DEM")
    mode = MODES[alg.parameterAsEnum(parameters, "MODEL", context)]
    rng = alg.parameterAsDouble(parameters, "RANGE", context)
    feedback.pushInfo(f"{len(sites)} radars, {mode} model, range {rng / 1000:g} km")
    return RadarField(dem, sites, mode, rng=rng)


# ------------------------------------------------------------------ Track 1
class RadarCoverage(Base):
    NAME, LABEL, GROUP = "radar_coverage", "Radar coverage (cumulative viewshed)", "Track 1 Radar coverage"
    HELP = ("Number of radars that see each cell: GDAL viewshed from every radar (mast height above ground) to a target "
            "height above each cell, Earth curvature with standard refraction, circular range. Target 0 m = ground "
            "coverage, 150 m = low-flying aircraft (the Track 3 threat).")

    def initAlgorithm(self, config=None):
        self.add_dem_radars()
        self.addParameter(QgsProcessingParameterNumber("MAST", "Radar mast height (m)", QgsProcessingParameterNumber.Double, 30, minValue=0))
        self.addParameter(QgsProcessingParameterNumber("TARGET", "Target height above ground (m)", QgsProcessingParameterNumber.Double, 150, minValue=0))
        self.addParameter(QgsProcessingParameterNumber("RANGE", "Radar range (m)", QgsProcessingParameterNumber.Double, 40000, minValue=1000))
        self.addParameter(QgsProcessingParameterRasterDestination("OUTPUT", "Radar coverage count"))

    def processAlgorithm(self, parameters, context, feedback):
        from osgeo import gdal
        from common.config import CURV_COEFF, VISIBLE, INVISIBLE, OUT_OF_RANGE
        dem, crs = load_dem(self, parameters, context, feedback)
        sites = [s for s in points(self, parameters, "RADARS", context, crs) if dem.contains(*s)]
        mast, target = self.parameterAsDouble(parameters, "MAST", context), self.parameterAsDouble(parameters, "TARGET", context)
        rng = self.parameterAsDouble(parameters, "RANGE", context)
        count = np.zeros(dem.shape, np.uint8)
        band = dem.gdal_dataset().GetRasterBand(1)
        for i, (x, y) in enumerate(sites):
            if feedback.isCanceled():
                break
            c, r = (int(round(v)) for v in dem.to_pixel(x, y))
            cx, cy = dem.to_world(c, r)
            ds = gdal.ViewshedGenerate(band, "MEM", "", [], cx, cy, mast, target, VISIBLE, INVISIBLE, OUT_OF_RANGE,
                                       OUT_OF_RANGE, CURV_COEFF, gdal.GVM_Edge, rng)
            vis = ds.GetRasterBand(1).ReadAsArray() == VISIBLE
            g = ds.GetGeoTransform()
            c0 = int(round((g[0] - dem.gt[0]) / dem.gt[1])); r0 = int(round((g[3] - dem.gt[3]) / dem.gt[5]))
            rr, cc = np.ogrid[r0:r0 + vis.shape[0], c0:c0 + vis.shape[1]]
            vis &= np.hypot(cc - c, rr - r) * dem.cell <= rng
            count[r0:r0 + vis.shape[0], c0:c0 + vis.shape[1]] += vis.astype(np.uint8)
            feedback.setProgress(100 * (i + 1) / len(sites))
        out = self.parameterAsOutputLayer(parameters, "OUTPUT", context)
        write_tif(out, count, dem, gdal.GDT_Byte, 0)
        feedback.pushInfo(f"covered {100 * (count > 0).mean():.1f}% of the DEM")
        return {"OUTPUT": out}


# ------------------------------------------------------------------ Track 2
class RouteVisibility(Base):
    NAME, LABEL, GROUP = "route_visibility", "Route visibility (what the aircraft sees)", "Track 2 Flight visibility"
    HELP = ("Cumulative visibility from an aircraft flying along a line at a constant height above ground: one "
            "window viewshed every sampling step, run on threads (the fastest mode of benchmark F6). Output: how "
            "many sampled positions see each cell (0 = never seen).")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer("DEM", "DEM (projected, metres; lat/lon is reprojected to UTM)"))
        self.addParameter(QgsProcessingParameterFeatureSource("ROUTE", "Flight route (line)", [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterNumber("AGL", "Flight height above ground (m)", QgsProcessingParameterNumber.Double, 300, minValue=0))
        self.addParameter(QgsProcessingParameterNumber("RADIUS", "Sensor radius (m)", QgsProcessingParameterNumber.Double, 20000, minValue=500))
        self.addParameter(QgsProcessingParameterNumber("SPACING", "Sampling step along the route (m)", QgsProcessingParameterNumber.Double, 1000, minValue=30))
        self.addParameter(QgsProcessingParameterRasterDestination("OUTPUT", "Visibility count"))

    def processAlgorithm(self, parameters, context, feedback):
        from osgeo import gdal
        from flight.route import resample
        from flight.visibility import AltitudeModel, run_route
        dem, crs = load_dem(self, parameters, context, feedback)
        src = self.parameterAsSource(parameters, "ROUTE", context)
        tr = QgsCoordinateTransform(src.sourceCrs(), crs, QgsProject.instance())
        f = next(src.getFeatures(), None)
        if f is None:
            raise QgsProcessingException("the route layer is empty")
        g = f.geometry(); g.transform(tr)
        line = g.asMultiPolyline()[0] if g.isMultipart() else g.asPolyline()
        verts = [(p.x(), p.y()) for p in line]
        pts = resample(np.asarray(verts), self.parameterAsDouble(parameters, "SPACING", context))
        am = AltitudeModel(dem, verts, "agl", self.parameterAsDouble(parameters, "AGL", context), None)
        acc, t = run_route(dem, pts, am, self.parameterAsDouble(parameters, "RADIUS", context), mode="threads", workers=8)
        out = self.parameterAsOutputLayer(parameters, "OUTPUT", context)
        write_tif(out, acc.count, dem, gdal.GDT_UInt16, 0)
        feedback.pushInfo(f"{len(pts)} positions, seen {(acc.count > 0).sum() * dem.cell ** 2 / 1e6:,.0f} km2 in {t['compute_s']:.1f} s")
        return {"OUTPUT": out}


# ------------------------------------------------------------------ Track 3
class ThreatSurface(Base):
    NAME, LABEL, GROUP = "threat_surface", "Radar threat surface", "Track 3 Corridor planning"
    HELP = ("Per-cell radar threat for an aircraft 150 m above ground: detection hazard (-ln(1-p) per km, p falling "
            "with distance) or distance-weighted exposure, summed over the radars that see the cell.")

    def initAlgorithm(self, config=None):
        self.add_dem_radars(); self.add_model()
        self.addParameter(QgsProcessingParameterRasterDestination("OUTPUT", "Threat surface"))

    def processAlgorithm(self, parameters, context, feedback):
        from osgeo import gdal
        dem, crs = load_dem(self, parameters, context, feedback)
        F = radar_field(self, parameters, context, dem, crs, feedback)
        out = self.parameterAsOutputLayer(parameters, "OUTPUT", context)
        write_tif(out, F.E.astype(np.float32), dem, gdal.GDT_Float32, None)
        return {"OUTPUT": out}


class _RouteBase(Base):
    GROUP = "Track 3 Corridor planning"

    def add_route_params(self):
        self.add_dem_radars(); self.add_model()
        self.addParameter(QgsProcessingParameterPoint("START", "Start"))
        self.addParameter(QgsProcessingParameterPoint("END", "Goal"))
        self.addParameter(QgsProcessingParameterNumber("ALPHA", "Exposure weight alpha", QgsProcessingParameterNumber.Double, 10, minValue=0))
        self.addParameter(QgsProcessingParameterNumber("BETA", "Climb weight beta", QgsProcessingParameterNumber.Double, 2, minValue=0))

    def problem(self, parameters, context, feedback):
        from corridor.exposure import blocked_mask
        from corridor.optimizer import Problem
        dem, crs = load_dem(self, parameters, context, feedback)
        F = radar_field(self, parameters, context, dem, crs, feedback)
        p = Problem(dem.z, F.E, blocked_mask(dem), dem.cell, self.parameterAsDouble(parameters, "ALPHA", context),
                    self.parameterAsDouble(parameters, "BETA", context))
        snap = lambda rc: self._snap(p, rc)
        s = snap(point(self, parameters, "START", context, crs, dem)); g = snap(point(self, parameters, "END", context, crs, dem))
        return dem, crs, F, p, s, g

    @staticmethod
    def _snap(p, rc, radius=50):
        r, c = int(round(rc[0])), int(round(rc[1]))
        if not p.blocked[r, c]:
            return r, c
        r0, c0 = max(r - radius, 0), max(c - radius, 0)
        free = np.argwhere(~p.blocked[r0:r + radius + 1, c0:c + radius + 1])
        if not len(free):
            raise QgsProcessingException("point is above the flight ceiling and no free cell is near")
        k = int(np.argmin(np.hypot(free[:, 0] + r0 - r, free[:, 1] + c0 - c)))
        return int(free[k, 0] + r0), int(free[k, 1] + c0)


class LeastExposureRoute(_RouteBase):
    NAME, LABEL = "least_exposure_route", "Least-exposure route"
    HELP = ("Route that minimises length x (1 + alpha x threat) + beta x climb for an aircraft 150 m above ground, "
            "under a 5000 m ceiling. Exact: backward cost-to-go field computed in C with parallel delta-stepping.")

    def initAlgorithm(self, config=None):
        self.add_route_params()
        self.addParameter(QgsProcessingParameterFeatureSink("OUTPUT", "Least-exposure route", QgsProcessing.TypeVectorLine))

    def processAlgorithm(self, parameters, context, feedback):
        import time
        from corridor import cgrid
        dem, crs, F, p, s, g = self.problem(parameters, context, feedback)
        t = time.perf_counter()
        ctg = cgrid.CostToGo(p, g, threads=cgrid.THREADS)
        path, cost = ctg.route(s)
        if not path:
            raise QgsProcessingException("no route: start and goal are not connected below the ceiling")
        secs = time.perf_counter() - t
        covered = F.E > 0
        L, pd, ck = path_metrics(dem, F, covered, path)
        fields = route_fields()
        sink, dest = self.parameterAsSink(parameters, "OUTPUT", context, fields, QgsWkbTypes.LineString, crs)
        sink.addFeature(line_feature(fields, dem, path, [f"alpha={p.alpha:g}", round(L, 2), float(cost), pd, round(ck, 2),
                                                         round(secs, 3), "exact (cost-to-go field)"]), QgsFeatureSink.FastInsert)
        feedback.pushInfo(f"{L:.1f} km, cost {cost:.0f}" + (f", P(detect) {100 * pd:.1f}%" if pd is not None else "") + f", {secs:.2f} s")
        return {"OUTPUT": dest}


class RiskBudgetRoute(_RouteBase):
    NAME, LABEL = "risk_budget_route", "Shortest route under a detection budget"
    HELP = ("Shortest (length + climb) route whose detection probability stays at or below the budget: Lagrangian "
            "relaxation (LARAC) on parallel cost-to-go fields, then an exact label-setting search in a corridor. "
            "The result reports the certified gap to the best possible length. Needs the detection model.")

    def initAlgorithm(self, config=None):
        self.add_route_params()
        self.addParameter(QgsProcessingParameterNumber("PMAX", "Maximum P(detect) (%)", QgsProcessingParameterNumber.Double, 50, minValue=0.1, maxValue=99.9))
        self.addParameter(QgsProcessingParameterFeatureSink("OUTPUT", "Route under budget", QgsProcessing.TypeVectorLine))

    def processAlgorithm(self, parameters, context, feedback):
        import time
        from corridor import cgrid
        from corridor.riskcsp import RiskCSP
        if MODES[self.parameterAsEnum(parameters, "MODEL", context)] != "detection":
            raise QgsProcessingException("the detection budget needs the detection probability model")
        dem, crs, F, p, s, g = self.problem(parameters, context, feedback)
        pmax = self.parameterAsDouble(parameters, "PMAX", context) / 100
        t = time.perf_counter()
        r = RiskCSP(p, g, threads=cgrid.THREADS).query(s, pmax, width_cells=15, resolution=1e-2, max_labels=4_000_000)
        secs = time.perf_counter() - t
        if r.get("path") is None:
            raise QgsProcessingException(f"no route with P(detect) <= {100 * pmax:g}% exists ({r['solves']} searches)")
        L, pd, ck = path_metrics(dem, F, F.E > 0, r["path"])
        fields = route_fields()
        sink, dest = self.parameterAsSink(parameters, "OUTPUT", context, fields, QgsWkbTypes.LineString, crs)
        note = f"LARAC, {r['solves']} fields, within {r['gap_pct']:.1f}% of the optimal length"
        sink.addFeature(line_feature(fields, dem, r["path"], [f"P<={100 * pmax:g}%", round(L, 2), None, pd, round(ck, 2),
                                                              round(secs, 2), note]), QgsFeatureSink.FastInsert)
        feedback.pushInfo(f"{L:.1f} km, P(detect) {100 * pd:.1f}%, {note}, {secs:.1f} s")
        return {"OUTPUT": dest}


# ------------------------------------------------------------------ cross-track check
class RouteDetectionCheck(Base):
    NAME, LABEL, GROUP = "route_detection_check", "Route detection check (coverage vs detection)", "Cross-track checks"
    HELP = ("For every line: length, length inside the cumulative radar viewshed (aircraft 150 m above ground), "
            "P(detect) under the detection model, and the detection probability accumulated outside the viewshed, "
            "which must be 0: a path the radars cannot see cannot be detected.")

    def initAlgorithm(self, config=None):
        self.add_dem_radars()
        self.addParameter(QgsProcessingParameterNumber("RANGE", "Radar range (m)", QgsProcessingParameterNumber.Double, 40000, minValue=1000))
        self.addParameter(QgsProcessingParameterFeatureSource("ROUTES", "Routes (lines)", [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSink("OUTPUT", "Routes with detection metrics", QgsProcessing.TypeVectorLine))

    def processAlgorithm(self, parameters, context, feedback):
        from corridor.radarfield import RadarField
        dem, crs = load_dem(self, parameters, context, feedback)
        sites = [s for s in points(self, parameters, "RADARS", context, crs) if dem.contains(*s)]
        F = RadarField(dem, sites, "detection", rng=self.parameterAsDouble(parameters, "RANGE", context))
        covered = F.E > 0
        src = self.parameterAsSource(parameters, "ROUTES", context)
        tr = QgsCoordinateTransform(src.sourceCrs(), crs, QgsProject.instance())
        fields = QgsFields(src.fields())
        for n in ("length_km", "covered_km", "p_detect", "p_outside"):
            fields.append(QgsField(n, QVariant.Double))
        sink, dest = self.parameterAsSink(parameters, "OUTPUT", context, fields, QgsWkbTypes.LineString, crs)
        W = dem.shape[1]
        for f in src.getFeatures():
            g = QgsGeometry(f.geometry()); g.transform(tr)
            dense = g.densifyByDistance(dem.cell / 2)
            pts = [v for v in dense.vertices()]
            cells = []
            for v in pts:
                c, r = dem.to_pixel(v.x(), v.y())
                r, c = int(round(r)), int(round(c))
                if 0 <= r < dem.shape[0] and 0 <= c < W and (not cells or cells[-1] != r * W + c):
                    cells.append(r * W + c)
            if len(cells) < 2:
                continue
            L, pd, ck = path_metrics(dem, F, covered, cells)
            rc = np.column_stack(np.divmod(np.asarray(cells), W))
            h = np.where(covered[rc[:, 0], rc[:, 1]], 0.0, F.E[rc[:, 0], rc[:, 1]])
            seg = np.hypot(*np.diff(rc, axis=0).T) * dem.cell / 1000
            pout = 1 - math.exp(-float((seg * 0.5 * (h[1:] + h[:-1])).sum()))
            o = QgsFeature(fields); o.setGeometry(g)
            o.setAttributes(list(f.attributes()) + [round(L, 2), round(ck, 2), pd, pout])
            sink.addFeature(o, QgsFeatureSink.FastInsert)
            feedback.pushInfo(f"feature {f.id()}: {L:.1f} km, {ck:.1f} km covered, P(detect) {100 * pd:.2f}%, outside coverage {pout:.2g}")
        return {"OUTPUT": dest}


ALGORITHMS = [RadarCoverage, RouteVisibility, ThreatSurface, LeastExposureRoute, RiskBudgetRoute, RouteDetectionCheck]
