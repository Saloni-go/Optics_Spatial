"""Track 2 - idea 4: how fast QGIS draws the Track 2 outputs, and how fast the flight playback runs.

  V1  each Track 2 raster (as written: DEFLATE + tiled) vs the same raster with internal overviews
      (pyramids 2..16), drawn at 1600 x 1600 px: full extent, zoomed to 1/8, and 1:1 (one cell per pixel).
      Every render opens a fresh layer (cold GDAL cache); median of 5.
  V2  playback: render every 8th frame of the Temporal Controller animation (cumulative range) for the
      first-seen raster + aircraft layer, with and without overviews: seconds per frame -> achievable fps.
Results: <results>/flight/qgis/render_bench.csv, playback.json, fig_render_track2.png
Run (no QGIS window needed):  QT_QPA_PLATFORM=offscreen python3 qgis/track2_render_bench.py <repo>
"""
import csv
import json
import statistics
import sys
import time
from pathlib import Path

from osgeo import gdal
from qgis.core import (QgsApplication, QgsProject, QgsRasterLayer, QgsMapSettings, QgsMapRendererSequentialJob,
                       QgsCoordinateReferenceSystem, QgsRectangle, QgsDateTimeRange, QgsInterval, Qgis)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

REPO = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(REPO))
R = REPO / "results" / "linux" / "flight"
OUT = R / "qgis"
TMP = OUT / "render"; TMP.mkdir(parents=True, exist_ok=True)
app = QgsApplication([], False); app.initQgis()
REPS = 5
LAYERS = {"times seen (uint16)": R / "count_agl300.tif",
          "first seen, seconds (float32)": OUT / "first_seen_seconds_agl300.tif",
          "P(seen) Monte Carlo (float32)": R / "idea2" / "p_seen_valley.tif",
          "dwell, forward camera (float32)": R / "idea2" / "dwell_valley_forward.tif"}


def with_overviews(src):
    dst = TMP / (src.stem + "_ovr.tif")
    if not dst.exists():
        gdal.Translate(str(dst), str(src), creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
        d = gdal.Open(str(dst), gdal.GA_Update); d.BuildOverviews("NEAREST", [2, 4, 8, 16]); d = None
    return dst


def settings(layers, extent):
    s = QgsMapSettings(); s.setLayers(layers); s.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:32644"))
    s.setExtent(extent); s.setOutputSize(QSize(1600, 1600)); s.setBackgroundColor(QColor("white"))
    return s


def render(s):
    t = time.perf_counter(); j = QgsMapRendererSequentialJob(s); j.start(); j.waitForFinished()
    return time.perf_counter() - t


def views(lay):
    full = lay.extent(); zoom = full.buffered(-full.width() * 7 / 16)
    c = full.center(); half = 1600 * 30 / 2
    return {"full": full, "zoom 1/8": zoom, "1:1": QgsRectangle(c.x() - half, c.y() - half, c.x() + half, c.y() + half)}


rows = []
for name, path in LAYERS.items():
    for variant, p in (("as written", path), ("with overviews", with_overviews(path))):
        row = {"layer": name, "variant": variant, "file_mb": round(p.stat().st_size / 2 ** 20 + (Path(str(p) + ".ovr").stat().st_size / 2 ** 20 if Path(str(p) + ".ovr").exists() else 0), 2)}
        for vname, ext in views(QgsRasterLayer(str(p), "x")).items():
            ts = []
            for _ in range(REPS):
                lay = QgsRasterLayer(str(p), "x")          # fresh layer = cold GDAL cache; keep a reference,
                ts.append(render(settings([lay], ext)))  # map settings only hold a weak pointer to it
                del lay
            row[f"{vname} s"] = statistics.median(ts)
        rows.append(row)
        print(row, flush=True)
with open(OUT / "render_bench.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

# ---- V2 playback frame rate
from qgis.core import QgsVectorLayer
ns = {}
exec(open(REPO / "qgis" / "track2_layers.py").read(), ns)
pr = QgsProject.instance(); pr.setCrs(QgsCoordinateReferenceSystem("EPSG:32644"))
ns["build"](pr, REPO)
fs = pr.mapLayersByName("Seen so far, 300 m AGL")[0]
ac = pr.mapLayersByName("Aircraft (300 m AGL)")[0]
hs = pr.mapLayersByName("Hillshade")[0]
rng = pr.timeSettings().temporalRange()
T0 = rng.begin()
play = {}
for variant in ("as written", "with overviews"):
    lay = fs
    if variant == "with overviews":
        lay = QgsRasterLayer(str(with_overviews(Path(fs.source()))), "fs_ovr")
        lay.setRenderer(fs.renderer().clone())
        tp, tq = lay.temporalProperties(), fs.temporalProperties()
        tp.setIsActive(True); tp.setMode(tq.mode()); tp.setTemporalRepresentationOffset(tq.temporalRepresentationOffset())
        tp.setTemporalRepresentationScale(tq.temporalRepresentationScale())
        pr.addMapLayer(lay, False)
    for ext_name, ext in (("route extent", ac.extent().buffered(15000)), ("zoom 1/8", ac.extent().buffered(-ac.extent().width() * 7 / 16))):
        ts = []
        for k in range(0, 163, 8):
            s = settings([ac, lay, hs], ext)
            s.setIsTemporal(True)
            s.setTemporalRange(QgsDateTimeRange(T0, T0.addSecs(17 * (k + 1))))
            ts.append(render(s))
        play[f"{variant} | {ext_name}"] = {"frames": len(ts), "median_s": statistics.median(ts), "max_s": max(ts),
                                            "fps": 1 / statistics.median(ts)}
        print(variant, ext_name, play[f"{variant} | {ext_name}"], flush=True)
json.dump(play, open(OUT / "playback.json", "w"), indent=1)

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, axs = plt.subplots(1, 2, figsize=(12, 3.8))
names = list(LAYERS)
for j, (variant, c) in enumerate((("as written", "#e76f51"), ("with overviews", "#2a9d8f"))):
    for k, v in enumerate(("full", "zoom 1/8", "1:1")):
        x = [i + (k - 1) * 0.27 for i in range(len(names))]
        y = [r[f"{v} s"] for r in rows if r["variant"] == variant]
        axs[0].scatter(x, y, c=c, marker="os^"[k], s=35, label=f"{variant}, {v}" if True else None)
axs[0].set_xticks(range(len(names))); axs[0].set_xticklabels([n.replace(" (", "\n(") for n in names], fontsize=7)
axs[0].set_yscale("log"); axs[0].set_ylabel("render time (s), 1600 x 1600 px"); axs[0].legend(fontsize=6.5, frameon=False, ncol=2)
axs[0].set_title("QGIS draw time of Track 2 rasters (16 M cells), cold cache", fontsize=9)
ks = list(play)
axs[1].barh(range(len(ks)), [play[k]["fps"] for k in ks], color=["#e76f51", "#e76f51", "#2a9d8f", "#2a9d8f"])
axs[1].set_yticks(range(len(ks))); axs[1].set_yticklabels(ks, fontsize=7.5); axs[1].set_xlabel("playback frames per second")
axs[1].set_title("Flight playback in the Temporal Controller (hillshade + seen-so-far + aircraft)", fontsize=9)
fig.savefig(OUT / "fig_render_track2.png", dpi=200, bbox_inches="tight")
app.exitQgis()
