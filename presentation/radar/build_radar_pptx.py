"""Builds presentation/Radar_Visibility_Assessment.pptx (radar part only) from the results in results/radar/
and the figures in presentation/radar/figs/.  Also writes rough PNG previews of every slide (PIL) so the
layout can be checked without PowerPoint.

Run:  run.bat presentation\\radar\\build_radar_pptx.py [preview_dir]
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RES = ROOT / "results" / "radar"
FIG = HERE / "figs"
OUT = ROOT / "presentation" / "Radar_Visibility_Assessment.pptx"
PREV = Path(sys.argv[1]) if len(sys.argv) > 1 else None

NAVY, ORANGE, DORANGE, RED = "1D3557", "F2A541", "B5650A", "E63946"
INK, MUTED, TINT, WHITE, PALE = "1F2933", "55606E", "EEF2F6", "FFFFFF", "C9D6E6"
W, H, X0, CW = 13.333, 7.5, 0.6, 12.13
FONT = "Calibri"

S = json.load(open(RES / "stats.json"))
B = json.load(open(RES / "benchmark_summary.json"))
RJ = json.load(open(FIG / "render_radar.json"))

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(W), Inches(H)
pages = []          # preview draw lists, one per slide
warnings = []


# ------------------------------------------------------------------ text measuring (preview + fit check)
def _font(size, bold):
    return ImageFont.truetype(r"C:\Windows\Fonts\calibrib.ttf" if bold else r"C:\Windows\Fonts\calibri.ttf",
                              max(int(round(size * 96 / 72)), 1))


def _norm(paras):
    if isinstance(paras, str):
        paras = [paras]
    """-> paragraphs as lists of (text, bold, colour or None) runs."""
    return [[(p, False, None)] if isinstance(p, str) else [(r + (None,))[:3] for r in p] for p in paras]


def _wrap(paras, w, size, bold):
    """-> list of lines; each line is a list of (word, bold, colour); None marks a paragraph gap."""
    lines = []
    for k, runs in enumerate(_norm(paras)):
        if k:
            lines.append(None)
        cur, cw = [], 0.0
        for text, b, c in runs:
            f = _font(size, bold or b)
            for j, piece in enumerate(text.split("\n")):
                if j:
                    lines.append(cur); cur, cw = [], 0.0
                for word in piece.split(" "):
                    ww = f.getlength(word + " ")
                    if cur and cw + f.getlength(word) > w * 96:
                        lines.append(cur); cur, cw = [], 0.0
                    cur.append((word, bold or b, c)); cw += ww
        lines.append(cur)
    return lines


def _height(lines, size):
    return sum(size * 0.45 / 72 if l is None else size * 1.2 / 72 for l in lines)


# ------------------------------------------------------------------ primitives
def rgb(h):
    return RGBColor.from_string(h)


def new_slide(title=None, notes="", dark=False):
    s = prs.slides.add_slide(prs.slide_layouts[5])               # Title Only
    pages.append([("bg", NAVY if dark else WHITE)])
    if dark:
        s.background.fill.solid(); s.background.fill.fore_color.rgb = rgb(NAVY)
    t = s.shapes.title
    if title is None:
        t._element.getparent().remove(t._element)
    else:
        t.left, t.top, t.width, t.height = Inches(X0), Inches(0.42), Inches(CW), Inches(0.8)
        tf = t.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
        r = p.add_run(); r.text = title
        r.font.size, r.font.bold, r.font.name, r.font.color.rgb = Pt(36), True, FONT, rgb(WHITE if dark else NAVY)
        lines = _wrap(title, CW, 36, True)
        if len(lines) > 1:
            warnings.append(f"slide {len(pages)}: title wraps: {title}")
        pages[-1].append(("text", X0, 0.42 + (0.8 - 36 * 1.2 / 72) / 2, CW, lines, 36, WHITE if dark else NAVY, "l"))
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    if title is not None and not dark:
        T(s, "Radar visibility assessment", X0, 7.02, 6, 0.26, 10, color=MUTED)
        T(s, str(len(pages)), W - X0 - 1, 7.02, 1, 0.26, 10, color=MUTED, align="r")
    return s


def rect(s, x, y, w, h, fill, round_=True):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if round_ else MSO_SHAPE.RECTANGLE,
                            Inches(x), Inches(y), Inches(w), Inches(h))
    if round_:
        sh.adjustments[0] = min(0.08 / min(w, h), 0.5)
    sh.fill.solid(); sh.fill.fore_color.rgb = rgb(fill); sh.line.fill.background(); sh.shadow.inherit = False
    pages[-1].append(("rect", x, y, w, h, fill))
    return sh


def T(s, paras, x, y, w, h, size=14, bold=False, color=INK, align="l", valign="t"):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE}[valign]
    for k, runs in enumerate(_norm(paras)):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[align]
        if k:
            p.space_before = Pt(size * 0.45)
        for text, b, c in runs:
            r = p.add_run(); r.text = text
            r.font.size, r.font.bold, r.font.name, r.font.color.rgb = Pt(size), bool(bold or b), FONT, rgb(c or color)
    lines = _wrap(paras, w, size, bold)
    th = _height(lines, size)
    if th > h + 0.03:
        warnings.append(f"slide {len(pages)}: text {th:.2f}in > box {h:.2f}in: {str(paras)[:60]}")
    if any(l and sum(_font(size, b).getlength(wd + ' ') for wd, b, _ in l) > w * 96 + size for l in lines):
        warnings.append(f"slide {len(pages)}: word wider than box: {str(paras)[:60]}")
    pages[-1].append(("text", x, y + ((h - th) / 2 if valign == "m" else 0), w, lines, size, color, align))
    return tb


def img(s, path, x, y, w, h, alt=""):
    """Fit the picture inside the box, centred, keeping its aspect ratio."""
    iw, ih = Image.open(path).size
    k = min(w / iw, h / ih); pw, ph = iw * k, ih * k
    px, py = x + (w - pw) / 2, y + (h - ph) / 2
    pic = s.shapes.add_picture(str(path), Inches(px), Inches(py), Inches(pw), Inches(ph))
    pic._element.nvPicPr.cNvPr.set("descr", alt)
    pages[-1].append(("img", px, py, pw, ph, str(path)))
    return px, py, pw, ph


def card(s, x, y, w, h, head, body, fill=TINT, hsize=16, bsize=14):
    rect(s, x, y, w, h, fill)
    T(s, head, x + 0.2, y + 0.14, w - 0.4, hsize * 1.25 / 72, hsize, bold=True, color=NAVY)
    T(s, body, x + 0.2, y + 0.2 + hsize * 1.25 / 72, w - 0.4, h - 0.34 - hsize * 1.25 / 72, bsize)


def stat(s, x, y, w, big, label, size=40, color=DORANGE, lcolor=INK):
    T(s, big, x, y, w, size * 1.2 / 72, size, bold=True, color=color)
    T(s, label, x, y + size * 1.2 / 72 + 0.04, w, 0.75, 14, color=lcolor)


def table(s, x, y, colw, rows, rh=0.42, size=14):
    for i, row in enumerate(rows):
        cx = x
        for j, cell in enumerate(row):
            rect(s, cx, y + i * rh, colw[j] - 0.03, rh - 0.03, NAVY if i == 0 else TINT, round_=False)
            T(s, cell, cx + 0.12, y + i * rh, colw[j] - 0.27, rh - 0.03, size, bold=(i == 0 or j == 0),
              color=WHITE if i == 0 else INK, valign="m")
            cx += colw[j]


def arrow(s, x1, y1, x2, y2, head=True, color=MUTED):
    """Straight connector; with head=True it ends in an arrowhead at (x2, y2)."""
    cn = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    cn.line.color.rgb = rgb(color); cn.line.width = Pt(1.75)
    if head:
        ln = cn.line._get_or_add_ln()
        tail = ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
        ln.append(tail)
    pages[-1].append(("line", x1, y1, x2, y2, color, head))


def chip(s, x, y, fill, label, color=INK):
    rect(s, x, y + 0.03, 0.26, 0.2, fill, round_=False)
    T(s, label, x + 0.34, y, 2.2, 0.26, 14, color=color)


pc = lambda v, d=1: f"{v * 100:.{d}f}%"
e1, e2, e3, e4, e5, e6 = B["E1"], B["E2"], B["E3"], B["E4"], B["E5"], B["E6"]
val = B["validation"]

# ================================================================== 1 title
s = new_slide(None, dark=True, notes=(
    "My part of the project is radar visibility assessment. The question is simple: given a radar standing on "
    "the ground in mountain terrain, which parts of the terrain can it actually see? The picture on the right is one "
    "real result, the viewshed of our radar R5 drawn in QGIS."))
T(s, "Radar Visibility\nAssessment", 0.7, 2.4, 6.2, 1.55, 46, bold=True, color=WHITE)
T(s, "Which terrain can a stationary radar see, and what does it cost to compute?", 0.7, 4.2, 6.0, 0.85, 20, color=WHITE)
T(s, "Large-Scale Terrain Data Analysis · Garhwal Himalaya · Copernicus GLO-30", 0.7, 5.35, 6.2, 0.6, 14, color=PALE)
img(s, FIG / "qgis_viewshed_R5.jpg", 7.25, 0.85, 5.5, 5.5, "QGIS map of the viewshed of radar R5 over shaded terrain")
T(s, "Viewshed of radar R5 in QGIS: orange visible, blue blocked", 7.25, 6.45, 5.5, 0.3, 12, color=PALE)

# ================================================================== 2 objective and workflow
s = new_slide("Objective and evaluation criteria", notes=(
    "The objective has two halves. First build the application: compute the visible terrain for a radar. Second, "
    "evaluate it against the criteria in the problem statement. These five boxes are the criteria, and under each "
    "is how I measured it. The next slide shows the whole methodology as a flow chart."))
T(s, "Compute which terrain a stationary ground radar can see, then measure what each method costs and how accurate it is.",
  X0, 1.5, CW, 0.75, 20)
T(s, "Evaluated for", X0, 2.65, 4, 0.35, 18, bold=True, color=NAVY)
crit = [("Computational complexity", "expected big-O against the fitted exponent"),
        ("Runtime and scalability", "time against cells, range and radars"),
        ("Memory efficiency", "peak memory of every run"),
        ("Accuracy", "agreement and kappa against the exact method"),
        ("Visualization", "QGIS maps and render time")]
for i, (hd, sub) in enumerate(crit):
    x = X0 + i * 2.475
    rect(s, x, 3.2, 2.23, 2.6, NAVY)
    T(s, hd, x + 0.2, 3.4, 1.83, 0.9, 18, bold=True, color=WHITE)
    T(s, sub, x + 0.2, 4.45, 1.83, 1.2, 15, color=PALE)
T(s, "Radar mast 30 m · range 40 km · DEM cells 30 m · study area 120 × 120 km in the Garhwal Himalaya",
  X0, 6.15, CW, 0.4, 14, color=MUTED)

# ================================================================== 3 methodology flow chart
s = new_slide("Methodology flow chart", notes=(
    "This is the whole methodology on one page; read it from left to right. Data: we download the Copernicus "
    "elevation tiles, join and reproject them, and cut four DEM sizes; separately we generate four synthetic test "
    "terrains. Method: the visibility model defines what visible means, and three algorithms implement it. "
    "Experiments: the same algorithms feed three activities, the six-radar scenario, the benchmarks E1 to E6, and the "
    "validation, which also uses the synthetic terrains. Each produces an output, and each output answers one of the "
    "evaluation criteria: the rasters give the QGIS maps, the benchmark tables give complexity, runtime and memory, "
    "and the agreement tables give accuracy."))
COLS = {"A": (0.6, 2.0), "B": (3.0, 2.0), "C": (5.4, 2.3), "D": (8.1, 2.2), "E": (10.7, 2.03)}
for k, lab in zip("ABCDE", ("DATA", "METHOD", "EXPERIMENTS", "OUTPUTS", "EVALUATION")):
    T(s, lab, COLS[k][0], 1.4, COLS[k][1], 0.3, 14, bold=True, color=DORANGE)


def fbox(col, y, h, head, body, fill=TINT, hc=NAVY, bc=INK):
    x, w = COLS[col]
    rect(s, x, y, w, h, fill)
    T(s, [[(head, True, hc)], [(body, False, bc)]], x + 0.14, y, w - 0.28, h, 14, valign="m")
    return x, y, w, h


R1, R2, R3 = (1.85, 1.0), (3.8, 1.0), (5.75, 1.0)          # (top, height) of the three experiment rows
fbox("A", 1.85, 0.85, "Copernicus GLO-30", "4 tiles, 30 m cells")
fbox("A", 3.05, 0.85, "Mosaic and reproject", "UTM zone 44N")
fbox("A", 4.25, 0.85, "Four nested DEMs", "0.25M to 16M cells")
fbox("A", 5.75, 1.0, "Synthetic terrains", "flat, valley, ridge, cone")
fbox("B", 1.85, 1.5, "Visibility model", "30 m mast, line of sight, Earth curvature, target 0 or 150 m")
fbox("B", 4.25, 0.85, "Three algorithms", "naive, R2, GDAL")
rows = [("Scenario", "six radars, 40 km range", "Rasters and vectors", "GeoTIFF and GeoJSON",
         "Visualization", "QGIS maps, render time"),
        ("Benchmarks", "E1 to E6, 5 repeats each", "Benchmark tables", "time, memory, fitted exponents",
         "Complexity, runtime, memory", "scaling and optimisations"),
        ("Validation", "known answers, exact reference", "Agreement tables", "agreement and kappa",
         "Accuracy", "fast methods against exact")]
for (top, h), (c1, c2, d1, d2, e1_, e2_) in zip((R1, R2, R3), rows):
    fbox("C", top, h, c1, c2, fill=NAVY, hc=WHITE, bc=PALE)
    fbox("D", top, h, d1, d2)
    fbox("E", top, h, e1_, e2_, fill=ORANGE, hc=NAVY, bc=INK)
    yc = top + h / 2
    arrow(s, 7.7, yc, 8.1, yc); arrow(s, 10.3, yc, 10.7, yc); arrow(s, 5.15, yc, 5.4, yc)
arrow(s, 1.6, 2.7, 1.6, 3.05); arrow(s, 1.6, 3.9, 1.6, 4.25)               # data chain
arrow(s, 4.0, 3.35, 4.0, 4.25)                                              # model -> algorithms
arrow(s, 2.6, 4.675, 3.0, 4.675)                                            # DEMs -> algorithms
arrow(s, 5.0, 4.675, 5.15, 4.675, head=False)                               # algorithms -> bus
arrow(s, 5.15, R1[0] + R1[1] / 2, 5.15, R3[0] + R3[1] / 2, head=False)      # bus to the three experiments
arrow(s, 2.6, R3[0] + R3[1] / 2, 5.15, R3[0] + R3[1] / 2, head=False)       # synthetic terrains -> validation

# ================================================================== 3 data
s = new_slide("The terrain data", notes=(
    "The only real input is a digital elevation model: a grid where every cell stores the ground height. We use "
    "Copernicus GLO-30, which has 30 metre cells, over the Garhwal Himalaya around Rudraprayag. We cut four square "
    "DEMs around the same centre. The resolution stays at 30 metres and only the area grows, from a quarter of a "
    "million cells to 16 million. That lets us measure how cost grows with data size. The red triangles are the six "
    "radar sites used later."))
img(s, FIG / "qgis_study_area.jpg", X0, 1.5, 5.3, 5.3, "QGIS map of the 120 km study area with six radar sites")
x = 6.35
T(s, [[("Source  ", True), ("Copernicus GLO-30 surface model, 30 m cells, four tiles from the public AWS archive.", False)],
      [("Area  ", True), ("Garhwal Himalaya, centred on Rudraprayag, reprojected to UTM zone 44N.", False)],
      [("Sizes  ", True), ("four nested DEMs with the same resolution and growing coverage.", False)]],
  x, 1.5, 6.38, 2.5, 16)
for i, (big, a, b) in enumerate((("0.25M", "500 × 500", "15 km"), ("1M", "1000 × 1000", "30 km"),
                                 ("4M", "2000 × 2000", "60 km"), ("16M", "4000 × 4000", "120 km"))):
    xx = x + i * 1.62
    rect(s, xx, 4.2, 1.5, 1.5, TINT)
    T(s, big, xx + 0.15, 4.3, 1.2, 0.5, 26, bold=True, color=DORANGE)
    T(s, [a, b + " wide"], xx + 0.15, 4.85, 1.3, 0.75, 14)
T(s, "Cells per DEM. Elevation in the largest ranges from 315 m to 7,074 m. Red triangles mark the six radar sites.",
  x, 5.95, 6.38, 0.75, 14, color=MUTED)

# ================================================================== 4 visibility model
s = new_slide("How visibility is decided", notes=(
    "This is the core concept. A cell is visible if the straight line from the radar to that cell is not cut by any "
    "terrain in between. The figure is a real 30 kilometre profile from radar R1. The solid line reaches its target, "
    "so that ground is visible. The dashed line hits the ridge in front, so its target is blocked. Two refinements: "
    "the Earth curves, so far terrain drops below the horizon, about 108 metres at 40 kilometres; and the target can "
    "be the ground or an aircraft 150 metres above it. Every algorithm applies exactly this same rule."))
img(s, FIG / "fig_los_concept.png", X0, 1.55, 7.9, 3.1, "Terrain profile with a visible and a blocked sight line")
T(s, "Real 30 km terrain profile west of radar R1. The solid sight line reaches its target; the dashed one is cut by the ridge in front.",
  X0, 4.8, 7.9, 0.6, 14, color=MUTED)
T(s, "Output raster, one value per cell", X0, 5.75, 4, 0.3, 14, bold=True, color=NAVY)
chip(s, X0, 6.2, ORANGE, "1 visible"); chip(s, X0 + 2.2, 6.2, NAVY, "0 blocked"); chip(s, X0 + 4.4, 6.2, "B8C0CA", "255 out of range")
for i, (hd, body) in enumerate((("Radar", "On a 30 m mast at the centre of its cell"),
                                ("Line-of-sight rule", "Visible if no terrain in between rises above the sight line"),
                                ("Earth curvature", "With refraction, far terrain drops by about 108 m at 40 km"),
                                ("Target height", "0 m for ground, 150 m for a low-flying aircraft"))):
    card(s, 8.8, 1.55 + i * 1.32, 3.93, 1.17, hd, body)

# ================================================================== 5 algorithms
s = new_slide("Three algorithms, one interface", notes=(
    "I compared three ways to compute the viewshed. Naive draws a separate line to every single cell, so it is "
    "exact but slow: the cost is cells times radius. R2 only shoots rays to the cells on the boundary and remembers "
    "the highest slope seen so far along each ray, the horizon, so every cell is handled once. GDAL is a compiled "
    "library routine that sweeps outward from the radar and derives each cell from its nearer neighbours. Naive is "
    "our truth, GDAL is what we use in practice, and R2 is our own fast implementation for comparison."))
algs = [("Naive line of sight", "A separate sight line to every cell, sampled every half cell.",
         "cells × radius, about N^1.5", "Exact but slow: the reference"),
        ("R2 ray casting", "Rays only to the boundary cells, with a running horizon along each ray.",
         "proportional to N", "Fast approximation, written in NumPy"),
        ("GDAL viewshed", "Sweeps outward from the radar; each cell is derived from its nearer neighbours (C++).",
         "proportional to N", "Fastest: used for all real runs")]
for i, (nm, how, cost, role) in enumerate(algs):
    x = X0 + i * 4.13
    rect(s, x, 1.55, 3.87, 4.35, TINT)
    T(s, nm, x + 0.25, 1.75, 3.37, 0.4, 22, bold=True, color=NAVY)
    T(s, [[("How  ", True), (how, False)], [("Cost  ", True), (cost, False)], [("Role  ", True), (role, False)]],
      x + 0.25, 2.4, 3.37, 2.2, 15)
    T(s, (f"{e1['naive']['projected_16M_s'] / 60:.0f} min", f"{e1['r2']['compute_s'][-1]:.1f} s",
          f"{e1['gdal']['compute_s'][-1]:.2f} s")[i], x + 0.25, 4.7, 3.37, 0.6, 32, bold=True, color=DORANGE)
    T(s, "for 16M cells" + (" (projected)" if i == 0 else ""), x + 0.25, 5.33, 3.37, 0.3, 14)
T(s, "N is the number of DEM cells. All three share one function interface, so every experiment can swap the algorithm.",
  X0, 6.2, CW, 0.5, 15, color=MUTED)

# ================================================================== 6 validation 1
cone = val["synthetic"]["cone"]
s = new_slide("Validation 1: terrains with known answers", notes=(
    "Before trusting any result I checked correctness. These four terrains are not real; they are generated by "
    "formulas, so the right answer is obvious. On a flat plain and in a V-shaped valley everything must be visible. "
    "With a 200 metre wall, everything behind the wall must be hidden. All three algorithms get these three exactly "
    "right. The cone has no simple answer, so there I compare the two fast methods with the exact one."))
img(s, FIG / "fig_synthetic_validation.png", X0, 1.55, 7.9, 4.15, "Four synthetic terrains and their viewsheds")
T(s, "Top: elevation. Bottom: computed viewshed, orange visible and blue blocked. The triangle is the radar.",
  X0, 5.85, 7.9, 0.6, 14, color=MUTED)
stat(s, 8.8, 1.55, 3.93, "100%", "correct on flat, valley and ridge, for all three algorithms", size=54)
card(s, 8.8, 3.6, 3.93, 1.75, "Cone: no simple answer",
     f"Against the exact method, GDAL agrees on {pc(cone['gdal']['vs_naive']['agreement'], 2)} of cells and R2 on "
     f"{pc(cone['r2']['vs_naive']['agreement'], 2)}.")

# ================================================================== 7 validation 2
r5, r10 = val["real"]["dem_500_range_0"], val["real"]["dem_1000_range_10000"]
s = new_slide("Validation 2: real terrain against exact", notes=(
    "On real terrain nobody knows the true answer, so the exact naive method becomes the reference and I compare "
    "the two fast methods with it cell by cell. Both agree on about 99.7 to 99.8 percent of cells. I also report "
    "kappa, because only about three percent of cells are visible: an algorithm that said 'everything is hidden' "
    "would already score 97 percent. Kappa removes that chance agreement, and it is still about 0.96. The last panel "
    "shows where GDAL differs from exact: only thin edges of the visible patches."))
img(s, RES / "fig_algorithm_comparison.png", X0, 1.5, CW, 3.16, "Viewsheds from the three algorithms and a difference map")
cell = lambda d: f"{pc(d['agreement'], 2)}  (kappa {d['kappa']:.3f})"
table(s, X0, 4.9, [3.3, 2.55, 2.55], [["Test", "GDAL", "R2"],
                                      ["500 × 500, unlimited range", cell(r5["gdal"]), cell(r5["r2"])],
                                      ["1000 × 1000, 10 km range", cell(r10["gdal"]), cell(r10["r2"])]], rh=0.5)
T(s, [[("Why kappa  ", True), ("only about 3% of cells are visible, so calling everything hidden would already score 97%.", False)],
      [("Error type  ", True), ("R2 leans towards false-visible; GDAL's errors are balanced.", False)]],
  9.3, 4.9, 3.43, 1.95, 14)

# ================================================================== 8 individual viewsheds
s = new_slide("Scenario: six radars, one viewshed each", notes=(
    "Now the realistic scenario. Six radars are placed on ridge tops by a fixed rule: the highest points between "
    "1500 and 3200 metres, at least 22 kilometres apart. Each has a 30 metre mast and a 40 kilometre range. These "
    "are the six output rasters, drawn in QGIS. Orange is visible ground, blue is blocked. Even from a ridge top a "
    "radar sees only 4 to 14 percent of the ground inside its range circle, because the mountains hide the valleys."))
g = 2.45
for i, rd in enumerate(S["radars"]):
    x, y = X0 + (i % 3) * (g + 0.2), 1.5 + (i // 3) * (g + 0.27)
    img(s, FIG / f"qgis_viewshed_{rd['id']}.jpg", x, y, g, g, f"QGIS map of the viewshed of radar {rd['id']}")
    rect(s, x + 0.08, y + 0.08, 0.5, 0.3, NAVY)
    T(s, rd["id"], x + 0.08, y + 0.08, 0.5, 0.3, 14, bold=True, color=WHITE, align="c", valign="m")
rows = [["Radar", "Ground", "Aircraft 150 m"]] + [[rd["id"], pc(rd["ground_visible_frac"]), pc(rd["air150_visible_frac"])]
                                                 for rd in S["radars"]]
table(s, 8.75, 1.5, [1.05, 1.25, 1.68], rows, rh=0.4)
chip(s, 8.75, 4.5, ORANGE, "visible"); chip(s, 10.3, 4.5, NAVY, "blocked")
T(s, "Share of the area inside each 40 km range circle that the radar sees. Maps rendered in QGIS from the output GeoTIFFs.",
  8.75, 4.95, 3.98, 1.3, 14, color=MUTED)

# ================================================================== 9 combined coverage
s = new_slide("Scenario: combined coverage", notes=(
    "Adding the six viewsheds gives a count raster: for every cell, how many radars see it. On the left is the "
    "ground, on the right an aircraft flying 150 metres above the ground. Together the radars see about one sixth "
    "of the ground. Raising the target by only 150 metres roughly doubles coverage to 36 percent, because the "
    "aircraft clears the nearby ridges. And the radars hardly overlap: under 2 percent of the ground is seen twice."))
m = 4.6
T(s, "Ground", X0, 1.45, m, 0.32, 16, bold=True, color=NAVY)
T(s, "Aircraft 150 m above ground", X0 + m + 0.3, 1.45, m, 0.32, 16, bold=True, color=NAVY)
img(s, FIG / "qgis_coverage_ground.jpg", X0, 1.85, m, m, "QGIS map of how many radars see each ground cell")
img(s, FIG / "qgis_coverage_air150.jpg", X0 + m + 0.3, 1.85, m, m, "QGIS map of how many radars detect an aircraft at 150 m")
for i, (c, lab) in enumerate((("F6A04D", "1 radar"), ("E8604C", "2"), ("C0392B", "3"), ("8E1B1B", "4 or more"))):
    chip(s, X0 + i * 1.55, 6.58, c, lab)
sx = X0 + 2 * m + 0.6
stat(s, sx, 1.85, 2.3, pc(S["union_ground_frac_of_dem"]), "of the ground seen by at least one radar", size=36)
stat(s, sx, 3.4, 2.3, pc(S["union_air150_frac_of_dem"]), "of the airspace at 150 m", size=36)
stat(s, sx, 4.7, 2.3, pc(S["multi_covered_ground_frac"]), "of the ground seen by two or more", size=36)

# ================================================================== 10 protocol
s = new_slide("How the benchmarks were run", notes=(
    "For the evaluation, every single measurement runs in its own fresh Python process, so the memory peak is not "
    "affected by earlier runs. Each configuration is repeated five times and I report the median. For each run I "
    "record total runtime including reading the DEM, compute time of the algorithm alone, and peak memory. There "
    "are six experiments: three vary a parameter and three test an optimisation. All numbers on the next slides are "
    "from Machine 1, a 2-core machine."))
for i, (hd, body) in enumerate((("Fresh process per run", "Peak memory is not polluted by earlier runs."),
                                ("5 repeats, median reported", "3 for the slowest cases; every raw run is kept in a CSV."),
                                ("Three numbers per run", "Runtime with DEM read, compute time only, peak memory."))):
    card(s, X0, 1.55 + i * 1.42, 5.2, 1.25, hd, body)
T(s, "Machine 1: Intel i5-6300U, 2 cores / 4 threads, 15.9 GB RAM, Windows 11, GDAL 3.13.1, Python 3.12.",
  X0, 5.95, 5.2, 0.75, 14, color=MUTED)
table(s, 6.2, 1.55, [0.85, 3.25, 2.43], [["", "What varies", "Algorithms"],
                                         ["E1", "DEM size, 0.25M to 16M cells", "all three"],
                                         ["E2", "Radar range, 5 to 60 km", "GDAL, R2"],
                                         ["E3", "Mast height, 10 to 300 m", "GDAL"],
                                         ["E4", "Number of radars, 1 to 16", "GDAL, 3 modes"],
                                         ["E5", "Full DEM or range window", "GDAL, R2"],
                                         ["E6", "Cell size, 30 to 120 m", "GDAL"]], rh=0.62)

# ================================================================== 11 E1
g1, rr2, nv = e1["gdal"], e1["r2"], e1["naive"]
s = new_slide("E1: cost against DEM size", notes=(
    "This is the main complexity result. Both axes are logarithmic, so the slope of each line is the exponent of "
    "growth. Naive has slope 1.54, matching the expected N to the 1.5. R2 has slope 1.02, matching linear. GDAL "
    "measures 0.72, a little below linear, most likely because fixed start-up costs weigh more at the small sizes. In absolute terms: for "
    "16 million cells GDAL needs a quarter of a second, R2 about four and a half seconds, and naive would need about "
    "160 minutes, which is why naive was only run up to 1 million cells and projected beyond. Memory grows with the "
    "DEM held in RAM."))
img(s, RES / "fig_bench_size.png", X0, 1.55, 8.4, 3.7, "Compute time and peak memory against DEM cells")
T(s, [[("Fitted exponents  ", True), (f"naive {nv['exponent']:.2f} (expected 1.5), R2 {rr2['exponent']:.2f} (expected 1), "
                                      f"GDAL {g1['exponent']:.2f} (expected 1).", False)],
      [("Peak memory at 16M cells  ", True), (f"GDAL {g1['peak_mb'][-1]:.0f} MB, R2 {rr2['peak_mb'][-1]:.0f} MB.", False)]],
  X0, 5.5, 8.4, 1.3, 14)
T(s, "Compute time at 16M cells", 9.4, 1.55, 3.33, 0.3, 14, bold=True, color=NAVY)
stat(s, 9.4, 1.95, 3.33, f"{g1['compute_s'][-1]:.2f} s", "GDAL", size=36)
stat(s, 9.4, 3.2, 3.33, f"{rr2['compute_s'][-1]:.1f} s", "R2 ray casting", size=36)
stat(s, 9.4, 4.45, 3.33, f"{nv['projected_16M_s'] / 60:.0f} min", "naive, projected from 1M cells", size=36)

# ================================================================== 12 E2 E3
s = new_slide("E2 and E3: range and mast height", notes=(
    "Two parameter studies. Left: increasing the radar range increases the number of cells inside the range circle, "
    "so cost rises. Right: raising the mast from 10 to 300 metres increases the visible ground about seven times, "
    "but the compute time does not move at all. So height changes the answer, not the cost, while range changes "
    "the cost."))
img(s, RES / "fig_bench_range.png", X0, 1.5, 5.8, 3.65, "Compute time against radar range")
img(s, RES / "fig_bench_height.png", 6.93, 1.5, 5.8, 3.65, "Visible ground and compute time against mast height")
T(s, [[("Range  ", True), (f"GDAL goes from {e2['gdal']['compute_s'][0]:.3f} s at 5 km to {e2['gdal']['compute_s'][-1]:.2f} s at 60 km; "
                           f"R2 from {e2['r2']['compute_s'][0]:.2f} s to {e2['r2']['compute_s'][-1]:.1f} s. "
                           "Cost follows the area in range.", False)]], X0, 5.4, 5.8, 1.4, 14)
T(s, [[("Mast height  ", True), (f"visible ground rises from {pc(e3[0]['visible_frac'], 2)} at 10 m to {pc(e3[-1]['visible_frac'])} "
                                 f"at 300 m, while compute stays at {e3[1]['compute_s']:.2f} s. "
                                 "Height changes the answer, not the cost.", False)]], 6.93, 5.4, 5.8, 1.4, 14)

# ================================================================== 13 E4
s = new_slide("E4: many radars, threads or processes", notes=(
    "With many radars the viewsheds are independent, so they can run in parallel. I compared one after another, "
    "a pool of threads, and a pool of separate processes. Threads win: GDAL releases Python's global lock while it "
    "computes, so threads really run side by side. Processes lose on this machine: each one has to start a new "
    "Python and gets its own copy of the data, which costs time and more than a gigabyte of memory. Machine 1 has "
    "only two cores, so the best possible gain is about two times; on Machine 2, with 12 cores, the same code reached "
    "4.2 times."))
img(s, RES / "fig_bench_radars.png", X0, 1.55, 8.4, 3.6, "Compute time and memory against number of radars for three modes")
T(s, "GDAL releases Python's lock, so threads run side by side with no start-up cost. Each process starts its own Python "
     "and holds its own copy of the data. Machine 1 has 2 cores, so the gain caps near 2×.", X0, 5.4, 8.4, 1.3, 14)
T(s, "16 radars, against sequential", 9.4, 1.55, 3.33, 0.3, 14, bold=True, color=NAVY)
stat(s, 9.4, 1.95, 3.33, f"{e4['speedup_threads'][-1]:.1f}×", "faster with threads", size=36)
stat(s, 9.4, 3.2, 3.33, f"{e4['speedup'][-1]:.2f}×", "with processes: slower than sequential", size=36)
stat(s, 9.4, 4.7, 3.33, f"{e4['parallel8']['total_peak_mb'][-1] / 1024:.2f} GB",
     f"memory with processes; threads use {e4['threads12']['total_peak_mb'][-1] / 1024:.2f} GB", size=36)

# ================================================================== 14 E5 E6
gf, gw = e5["gdal_full"][0], e5["gdal_window"][0]
s = new_slide("E5 and E6: clipping and a coarser DEM", notes=(
    "Two more optimisations. Left: a radar with a 10 kilometre range does not need the whole 120 kilometre DEM, so "
    "I read only the window that covers its range. That cuts total time about seven times and memory from 242 to 73 "
    "megabytes. The benefit shrinks as the range grows. Right: using coarser cells makes the computation faster, "
    "but accuracy drops. Plain agreement still looks like 99.96 percent, but kappa falls to 0.78, which shows that "
    "a real share of the visible cells is being lost."))
img(s, RES / "fig_bench_clipping.png", X0, 1.55, 7.1, 3.2, "Runtime and memory for full and window reads")
img(s, RES / "fig_bench_resolution.png", 8.0, 1.55, 4.73, 3.2, "Compute time and agreement against cell size")
T(s, [[("Region clipping  ", True), (f"reading only the range window at 10 km cuts total runtime from {gf['runtime_s']:.2f} s to "
                                     f"{gw['runtime_s']:.2f} s and memory from {gf['peak_mb']:.0f} MB to {gw['peak_mb']:.0f} MB. "
                                     "The gain shrinks as the window nears the whole DEM.", False)]], X0, 5.0, 7.1, 1.7, 14)
T(s, [[("Coarser DEM  ", True), (f"120 m cells compute {e6[0]['compute_s'] / e6[-1]['compute_s']:.1f}× faster, but kappa against "
                                 f"the 30 m result falls to {e6[-1]['kappa']:.2f}.", False)]], 8.0, 5.0, 4.73, 1.7, 14)

# ================================================================== machine comparison
TB = json.load(open(FIG / "teammate_benchmark_summary.json"))
MM, TM = json.load(open(RES / "machine.json")), json.load(open(FIG / "teammate_machine.json"))
cmp_rows = [("GDAL, 16M cells", e1["gdal"]["compute_s"][-1], TB["E1"]["gdal"]["compute_s"][-1]),
            ("R2, 16M cells", e1["r2"]["compute_s"][-1], TB["E1"]["r2"]["compute_s"][-1]),
            ("Naive, 1M cells", e1["naive"]["compute_s"][-1], TB["E1"]["naive"]["compute_s"][-1]),
            ("GDAL, 60 km range", e2["gdal"]["compute_s"][-1], TB["E2"]["gdal"]["compute_s"][-1]),
            ("16 radars, one after another", e4["sequential"]["compute_s"][-1], TB["E4"]["sequential"]["compute_s"][-1]),
            ("16 radars, in parallel threads", e4["threads12"]["compute_s"][-1], TB["E4"]["threads12"]["compute_s"][-1])]
ratios = [m / t for _, m, t in cmp_rows]
single, par = ratios[:5], ratios[5]
sec = lambda v: f"{v:.2f} s" if v < 10 else f"{v:.0f} s"
s = new_slide("Machine 1 against Machine 2", notes=(
    "The same code ran on the same data on two machines, with the same software versions: QGIS, GDAL, Python "
    "and NumPy are identical, and both run Windows 11. Only the hardware differs. Machine 1 has a 2-core Intel "
    "i5-6300U with 16 gigabytes; Machine 2 has a 12-core AMD Ryzen 9 7900X with 31 gigabytes. "
    f"Everything that is about the answer is identical: coverage, accuracy, even peak memory. Only time differs. Work "
    f"that runs on one core is about {min(single):.1f} to {max(single):.1f} times slower on Machine 1, because each core "
    f"is older and slower. Work that runs in parallel is {par:.1f} times slower, because Machine 1 has 2 cores against "
    f"12; that is also why its thread speedup stops at {e4['speedup_threads'][-1]:.1f} times while Machine 2 reached "
    f"{TB['E4']['speedup_threads'][-1]:.1f}. So the conclusions hold on both machines; only the absolute times move."))
for i, (hd, cpu, cores, fill, hc, bc) in enumerate(((
        "Machine 1", "Intel Core i5-6300U", f"{MM['cores_physical']} cores / {MM['cores_logical']} threads", TINT, NAVY, INK),
        ("Machine 2", "AMD Ryzen 9 7900X", f"{TM['cores_physical']} cores / {TM['cores_logical']} threads", NAVY, WHITE, PALE))):
    ram = (MM if i == 0 else TM)["ram_gb"]
    y = 1.5 + i * 2.1
    rect(s, X0, y, 3.7, 1.9, fill)
    T(s, [[(hd, True, hc)], [(cpu, False, bc)], [(cores, False, bc)], [(f"{ram:.1f} GB RAM", False, bc)]],
      X0 + 0.22, y, 3.26, 1.9, 16, valign="m")
T(s, f"Same on both: Windows 11, QGIS 3.44.12, GDAL {MM['gdal']}, Python {MM['python']}, NumPy {MM['numpy']}",
  X0, 5.8, 3.7, 0.95, 14, color=MUTED)
table(s, 4.6, 1.5, [3.53, 1.5, 1.5, 1.6], [["Compute time", "Machine 1", "Machine 2", "M1 slower by"]] +
      [[nm, sec(m), sec(t), f"{m / t:.1f}×"] for nm, m, t in cmp_rows] +
      [["Thread speedup, 16 radars", f"{e4['speedup_threads'][-1]:.1f}×", f"{TB['E4']['speedup_threads'][-1]:.1f}×", "fewer cores"]],
      rh=0.47)
T(s, [[("Identical on both  ", True), (f"coverage, accuracy and peak memory (GDAL at 16M cells: {e1['gdal']['peak_mb'][-1]:.0f} MB "
                                      f"against {TB['E1']['gdal']['peak_mb'][-1]:.0f} MB).", False)],
      [("Why Machine 1 is slower  ", True), (f"single-core work is {min(single):.1f}–{max(single):.1f}× slower on an older, slower CPU; "
                                             f"parallel work is {par:.1f}× slower because it has 2 cores instead of 12.", False)]],
  4.6, 5.45, 8.13, 1.35, 14)

# ================================================================== 15 QGIS
s = new_slide("Visualization in QGIS", notes=(
    "How the code connects to QGIS. All the code runs on the Python that ships with QGIS, so it uses the same GDAL "
    "library. The results are written as standard GeoTIFF and GeoJSON files in the same coordinate system as the "
    "DEM, so they overlay correctly. A PyQGIS script then builds a styled project and renders the maps you have "
    "seen. For visualization performance I timed QGIS drawing each radar raster: they draw about "
    "four to five times faster than the DEM itself. They are small one-byte rasters, well under a megabyte each, "
    "against 38 megabytes for the DEM. The exact times vary between sessions on Machine 1, so the ratio is the "
    "number to quote."))
img(s, FIG / "qgis_coverage_ground.jpg", X0, 1.5, 4.9, 4.9, "QGIS map of ground coverage by the six radars")
T(s, "Ground coverage layer over the hillshade, rendered by PyQGIS", X0, 6.5, 4.9, 0.3, 12, color=MUTED)
x = 5.95
T(s, [[("Same Python  ", True), ("all code runs on the Python that ships with QGIS 3.44, with the same GDAL.", False)],
      [("Standard outputs  ", True), ("viewsheds and coverage as GeoTIFF, radar sites and range rings as GeoJSON, all in UTM 44N.", False)],
      [("PyQGIS scripts  ", True), ("build the styled project file and render the maps without opening the window.", False)]],
  x, 1.5, 6.78, 2.45, 15)
f2 = lambda v: f"{v:.2f} s"
table(s, x, 4.15, [3.5, 1.64, 1.64], [["QGIS render time", "Full extent", "Zoomed"]] +
      [[{"DEM 4000 (input)": "DEM, 16M cells (input)"}.get(r["layer"], r["layer"]), f2(r["render_full_s"]), f2(r["render_zoom_s"])]
       for r in RJ[:3]], rh=0.46)
T(s, "1600 × 1600 px, median of 5 renders on Machine 1; values vary between sessions.", x, 6.1, 6.78, 0.5, 14, color=MUTED)

# ================================================================== 16 conclusions
s = new_slide("Conclusions", dark=True, notes=(
    "To summarise. GDAL is the method to use: linear cost and about 0.2 percent error. The exact method is only "
    "useful as a reference. Memory is governed by how much DEM is loaded, so clipping is the most effective saving. "
    "For many radars, use threads. Coarser data is faster but loses accuracy, and only kappa shows it. The limits: "
    "this is purely geometric line of sight, with no radar beam or signal model, and the elevation data is a surface "
    "model that includes trees and buildings."))
concl = [("GDAL is the practical choice", f"linear cost, {g1['compute_s'][-1]:.2f} s for 16M cells, about 0.2% error."),
         ("The exact method is a reference only", "its N^1.5 cost means hours at 16M cells."),
         ("Memory follows the DEM held in RAM", "clipping to the range window is the best saving."),
         ("Use threads for many radars", "processes cost start-up time and memory."),
         ("A coarser DEM trades accuracy for speed", "and only kappa reveals the loss.")]
for i, (hd, body) in enumerate(concl):
    y = 1.55 + i * 0.86
    rect(s, X0, y, 0.55, 0.55, ORANGE)
    T(s, str(i + 1), X0, y, 0.55, 0.55, 20, bold=True, color=NAVY, align="c", valign="m")
    T(s, [[(hd + ": ", True), (body, False)]], X0 + 0.8, y, CW - 0.8, 0.6, 18, color=WHITE, valign="m")
T(s, "Limits: geometric line of sight only, with no beam or signal model; the surface model includes trees and buildings; "
     "the naive exponent rests on two DEM sizes.", X0, 6.05, CW, 0.75, 14, color=PALE)

prs.save(OUT)
print("written", OUT, "slides", len(pages))
for w_ in warnings:
    print("WARN", w_)

# ------------------------------------------------------------------ rough previews
if PREV:
    PREV.mkdir(parents=True, exist_ok=True)
    D = 96
    for n, page in enumerate(pages, 1):
        im = Image.new("RGB", (int(W * D), int(H * D)), "#" + page[0][1]); dr = ImageDraw.Draw(im)
        for it in page[1:]:
            if it[0] == "rect":
                _, x, y, w, h, c = it
                dr.rectangle([x * D, y * D, (x + w) * D, (y + h) * D], fill="#" + c)
            elif it[0] == "img":
                _, x, y, w, h, p = it
                im.paste(Image.open(p).convert("RGB").resize((int(w * D), int(h * D))), (int(x * D), int(y * D)))
            elif it[0] == "line":
                _, x1, y1, x2, y2, c, head = it
                dr.line([x1 * D, y1 * D, x2 * D, y2 * D], fill="#" + c, width=2)
                if head:
                    import math
                    a = math.atan2(y2 - y1, x2 - x1); L, Wd = 9, 5
                    tip = (x2 * D, y2 * D)
                    bx, by = tip[0] - L * math.cos(a), tip[1] - L * math.sin(a)
                    dr.polygon([tip, (bx - Wd * math.sin(a), by + Wd * math.cos(a)),
                                (bx + Wd * math.sin(a), by - Wd * math.cos(a))], fill="#" + c)
            else:
                _, x, y, w, lines, size, c, al = it
                yy = y * D
                for l in lines:
                    if l is None:
                        yy += size * 0.45 / 72 * D; continue
                    tw = sum(_font(size, b).getlength(wd + " ") for wd, b, _ in l)
                    xx = x * D + {"l": 0, "c": (w * D - tw) / 2, "r": w * D - tw}[al]
                    for wd, b, rc in l:
                        f = _font(size, b); dr.text((xx, yy), wd, font=f, fill="#" + (rc or c)); xx += f.getlength(wd + " ")
                    yy += size * 1.2 / 72 * D
        im.save(PREV / f"slide_{n:02d}.png")
    print("previews in", PREV)
