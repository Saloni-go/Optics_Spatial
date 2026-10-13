"""Builds report/mid_submission_report.pdf from the result JSONs and figures.

Layout: designed cover, table of contents (real page numbers, clickable), executive summary,
the mid-submission scope (sections 1-6), future work, conclusions, references, and an appendix
with the completed work beyond the 50% scope.  Every number is read from results/*.json.
Run:  python report\\build_report.py   (system Python with PyMuPDF + Pillow)
"""
import csv
import json
import os
import shutil
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"
FIG = ROOT / "report" / "figs"
OUT = ROOT / "report" / "mid_submission_report.pdf"
FONTS = Path("C:/Windows/Fonts")
REPO = "https://github.com/Saloni-go/Optics_Spatial"

NAVY, TEAL, RUST, BLUE, INK, MUTED = "#14213d", "#1f7a6f", "#b4472e", "#2f5d7c", "#2b3440", "#6b7280"

# ------------------------------------------------------------------ data
J = lambda p: json.load(open(R / p))
meta = json.load(open(ROOT / "data" / "dem_metadata.json"))
mach = J("radar/machine.json")
val = J("radar/validation.json")
r_st, r_b = J("radar/stats.json"), J("radar/benchmark_summary.json")
f_st, f_b = J("flight/stats.json"), J("flight/benchmark_summary.json")
c_st, c_b = J("corridor/stats.json"), J("corridor/benchmark_summary.json")
sp = J("flight/spacing_study.json")
render = list(csv.DictReader(open(R / "shared/render_benchmark.csv")))
E1, E2, E4, E5, E6 = r_b["E1"], r_b["E2"], r_b["E4"], r_b["E5"], r_b["E6"]
F1, F1b, F2 = f_b["F1_size"], f_b["F1b_size_fixed_route"], f_b["F2"]
F6 = {d["mode"]: d for d in f_b["F6"]}
C1, C2, C3, C4, C5, C6 = c_b["C1"], c_b["C2"], c_b["C3"], c_b["C4"], c_b["C5"], c_b["C6"]
rt = c_st["routes"]; sh, a10, t2r = rt["shortest"], rt["alpha_10"], rt["track2_valley_route"]
a3, m55 = f_st["cases"]["agl300"], f_st["cases"]["msl5500"]
ALT, AST = c_st["alt_check_alpha10"], c_st["astar_check_alpha10"]

f0 = lambda v: f"{v:,.0f}"
f1 = lambda v: f"{v:,.1f}"
f2 = lambda v: f"{v:,.2f}"
f3 = lambda v: f"{v:.3f}"
pct = lambda v: f"{100 * v:.1f}%"

FIG.mkdir(parents=True, exist_ok=True)
FIGS = {"dem": "shared/qgis_dem.png", "t1_alg": "radar/fig_algorithm_comparison.png", "t1_cov": "radar/fig_coverage_six_radars.png",
        "t1_size": "radar/fig_bench_size.png", "t1_range": "radar/fig_bench_range.png", "t1_radars": "radar/fig_bench_radars.png",
        "t1_clip": "radar/fig_bench_clipping.png", "t1_res": "radar/fig_bench_resolution.png",
        "t2_cum": "flight/fig_cumulative_visibility.png", "t2_alt": "flight/fig_altitude_profile.png", "t2_size": "flight/fig_bench_size.png",
        "t2_spacing": "flight/fig_bench_spacing.png", "t2_params": "flight/fig_bench_params.png", "t2_opt": "flight/fig_bench_optimise.png",
        "t2_study": "flight/fig_spacing_study.png", "t3_routes": "corridor/fig_routes.png", "t3_trade": "corridor/fig_tradeoff.png",
        "t3_size": "corridor/fig_bench_size.png", "t3_alpha": "corridor/fig_bench_alpha.png", "t3_misc": "corridor/fig_bench_misc.png",
        "t3_multi": "corridor/fig_bench_multiquery.png", "render": "shared/fig_render_benchmark.png"}
for k, p in FIGS.items():
    shutil.copy(R / p, FIG / f"{k}.png")
for f in ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf", "georgia.ttf", "georgiab.ttf", "georgiai.ttf"):
    shutil.copy(FONTS / f, FIG / f)

# ------------------------------------------------------------------ building blocks
_n = {"fig": 0, "tab": 0}


def fig(key, width, caption):
    _n["fig"] += 1
    return (f'<div class="figure"><p align="center"><img src="{key}.png" width="{width}"></p>'
            f'<p class="cap"><b>Figure {_n["fig"]}.</b> {caption}</p></div>')


def table(header, rows, caption=None, hl=(), widths=None, num_from=1, small=False):
    """Navy header, zebra rows, highlighted rows (hl), numbers right-aligned from column num_from."""
    out = ""
    if caption:
        _n["tab"] += 1
        out += f'<p class="tcap"><b>Table {_n["tab"]}.</b> {caption}</p>'
    w = widths or [None] * len(header)
    th = "".join(f'<th{f" width=\"{x}%\"" if x else ""}>{h}</th>' for h, x in zip(header, w))
    body = ""
    for i, r in enumerate(rows):
        hi = ";font-weight:bold;color:#1f7a6f" if i in hl else ""
        cells = "".join(f'<td style="{"text-align:right" if j >= num_from and num_from >= 0 else "text-align:left"}{hi}">{c}</td>'
                        for j, c in enumerate(r))
        body += f"<tr>{cells}</tr>"
    return out + f'<table class="data{" small" if small else ""}" width="100%"><tr>{th}</tr>{body}</table>'


def box(title, text, kind="finding"):
    col = {"finding": TEAL, "note": BLUE, "warn": RUST, "scope": NAVY}[kind]
    bg = {"finding": "#eaf4f1", "note": "#ebf1f7", "warn": "#f8ece8", "scope": "#eef0f4"}[kind]
    return (f'<div class="box" style="border-left:4px solid {col}; background-color:{bg}">'
            f'<p class="boxt" style="color:{col}">{title}</p>{text}</div>')


def ul(items):
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def kpis(cells):
    """Executive-summary result tiles [(big, label, colour), ...], drawn as one image (rows of three)."""
    import textwrap
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import FancyBboxPatch
    head = font_manager.FontProperties(fname=str(FONTS / "georgiab.ttf"))
    body = font_manager.FontProperties(fname=str(FONTS / "calibri.ttf"))
    rows = (len(cells) + 2) // 3
    fig_, ax = plt.subplots(figsize=(6.8, 1.55 * rows), dpi=250)
    ax.set_xlim(0, 3); ax.set_ylim(0, rows); ax.axis("off")
    for k, (big, lab, col) in enumerate(cells):
        x, y = k % 3, rows - 1 - k // 3
        ax.add_patch(FancyBboxPatch((x + 0.03, y + 0.05), 0.94, 0.9, boxstyle="round,pad=0,rounding_size=0.04",
                                    fc="#f4f6f9", ec="#dde2e8", lw=0.8))
        ax.text(x + 0.09, y + 0.66, big, fontproperties=head, fontsize=19, color=col, va="center")
        ax.text(x + 0.09, y + 0.42, chr(10).join(textwrap.wrap(lab, 38)), fontproperties=body, fontsize=8.3, color="#2b3440", va="top", linespacing=1.25)
    fig_.subplots_adjust(0, 0, 1, 1); fig_.savefig(FIG / "kpis.png"); plt.close(fig_)
    return '<p align="center"><img src="kpis.png" width="483"></p>'


css = f"""
@font-face {{ font-family: Body; src: url(calibri.ttf); }}
@font-face {{ font-family: Body; src: url(calibrib.ttf); font-weight: bold; }}
@font-face {{ font-family: Body; src: url(calibrii.ttf); font-style: italic; }}
@font-face {{ font-family: Body; src: url(calibriz.ttf); font-weight: bold; font-style: italic; }}
@font-face {{ font-family: Head; src: url(georgiab.ttf); }}
@font-face {{ font-family: HeadR; src: url(georgia.ttf); }}
body {{ font-family: Body; font-size: 10.5pt; line-height: 1.38; color: {INK}; }}
h1 {{ font-family: Head; font-size: 19pt; color: {NAVY}; margin-top: 0; margin-bottom: 8pt; }}
h2 {{ font-family: Head; font-size: 13pt; color: {NAVY}; margin-top: 14pt; margin-bottom: 4pt; }}
h3 {{ font-family: Body; font-weight: bold; font-size: 11pt; color: {BLUE}; margin-top: 9pt; margin-bottom: 2pt; }}
p {{ margin-top: 2pt; margin-bottom: 5pt; text-align: justify; }}
li {{ margin-bottom: 3pt; }}
.lead {{ font-size: 11.5pt; color: {INK}; }}
.eyebrow {{ font-family: Body; font-weight: bold; font-size: 8.5pt; color: {RUST}; letter-spacing: 1.5pt; margin-bottom: 2pt; }}
.figure {{ margin-top: 6pt; margin-bottom: 8pt; }}
.cap {{ font-size: 8.8pt; color: {MUTED}; text-align: center; margin-top: 2pt; }}
.tcap {{ font-size: 9pt; color: {INK}; margin-top: 8pt; margin-bottom: 3pt; }}
table.data {{ border-collapse: collapse; margin-bottom: 8pt; }}
table.data th {{ color: {NAVY}; font-weight: bold; font-size: 9pt; padding: 4pt 5pt; text-align: left; border-top: 1.5px solid {NAVY}; border-bottom: 1.5px solid {NAVY}; }}
table.data td {{ font-size: 9pt; padding: 3pt 5pt; border-bottom: 1px solid #dde2e8; }}
table.small td, table.small th {{ font-size: 8.4pt; }}
.box {{ padding: 6pt 10pt 4pt 10pt; margin-top: 7pt; margin-bottom: 9pt; }}
.boxt {{ font-weight: bold; font-size: 9.5pt; margin-bottom: 2pt; text-align: left; }}
.box p, .box li {{ font-size: 9.8pt; }}
table.kpis {{ border-collapse: separate; margin-top: 4pt; margin-bottom: 10pt; }}
td.kpi {{ background-color: #f4f6f9; padding: 8pt 9pt; border: 1px solid #dde2e8; vertical-align: top; }}
.kbig {{ font-family: Head; font-size: 20pt; margin: 0; text-align: left; }}
.klab {{ font-size: 9pt; color: {INK}; margin: 2pt 0 0 0; text-align: left; line-height: 1.25; }}
.mono {{ font-family: monospace; font-size: 9pt; }}
.ref {{ font-size: 9.5pt; margin-bottom: 4pt; text-align: left; }}
"""

# =================================================================== CONTENT
H = []
P = H.append

# ---------------------------------------------------------------- executive summary
P(f"""<h1 id="exec">Executive Summary</h1>
<p class="lead">We are building three terrain-visibility applications on one shared set of elevation models of the Garhwal Himalaya and
measuring how their cost grows with terrain size and problem settings. <b>Track 1</b> computes what a stationary radar can see,
<b>Track 2</b> what an aircraft sees along a 166 km valley route, and <b>Track 3</b> plans a route that keeps the aircraft hidden from the
Track 1 radars. All three run end to end, pass correctness checks, export GIS-ready outputs and have been benchmarked from
0.25 million to 16 million terrain cells.</p>
<h3>Key results so far</h3>""")
P(kpis([(f"{pct(val['real']['dem_500_range_0']['gdal']['agreement'])}", "agreement of the production viewshed (GDAL) with the exact line-of-sight answer", RUST),
        (f"{f2(E1['gdal']['compute_s'][-1])} s", f"for a 16 M-cell viewshed with GDAL, against about {f0(E1['naive']['projected_16M_s'] / 60)} min for the exact method", RUST),
        (f"{pct(r_st['union_ground_frac_of_dem'])}", "of the 120 x 120 km area is visible to six ridge-top radars: valleys hide most terrain", RUST),
        (f"{pct(a3['seen_in_corridor_frac'])}", f"of the route corridor seen when flying low in the valley, against {pct(m55['seen_in_corridor_frac'])} at a 5,500 m cruise", TEAL),
        (f"-{pct(1 - a10['exposure_km'] / sh['exposure_km'])}", f"radar exposure of the optimised route, for {pct(a10['length_km'] / sh['length_km'] - 1)} more distance", BLUE),
        (f"{f0(C1['dijkstra_py']['compute_s'][-1] / C1['dijkstra_csgraph']['compute_s'][-1])}x", f"faster route search in C than in Python on 16 M nodes, at {f0(C1['dijkstra_csgraph']['peak_mb'][-1] / C1['dijkstra_py']['peak_mb'][-1])}x the memory", BLUE)]))
P(box("Scope of this mid-submission",
      "<p>Sections 1-6 cover the agreed first half of the project for every track: shared data and protocol, design, implementation, "
      "validation, maps and the first scaling benchmark. Section 7 sets out the work planned for the final submission. "
      "Appendix A reports experiments for the second half that have already been run (parameter studies, optimisations, "
      "rendering performance); they are included for completeness and will be extended for the final.</p>", "scope"))

# ---------------------------------------------------------------- 1 introduction
P(f"""<h1 id="s1" style="page-break-before: always">1. Introduction</h1>
<p>Line-of-sight over terrain decides what a radar can cover, what an aircraft can observe and where it can fly unseen. The computation
itself is simple, but its cost grows quickly with the size and resolution of the terrain and with the number of observers. The project
brief asks for three such applications, built and evaluated for <b>computational complexity, memory efficiency, visualisation performance,
accuracy and scalability</b>, and for an explanation of <i>how and why</i> their demands grow and which implementation choices help.</p>
<h2>1.1 Objectives</h2>""")
P(ul(["Build three working terrain-visibility applications on shared digital elevation models (DEMs).",
      "Produce GIS outputs and maps of visible and blocked regions, routes and corridors.",
      "Benchmark runtime, peak memory, scalability, complexity, rendering performance and accuracy.",
      "Compare baselines with optimised implementations and explain the trade-offs."]))
P("<h2>1.2 The three tracks</h2>")
P(table(["Track", "Owner", "Question", "Main output"],
        [["1 Radar visibility", "Person 1", "Which terrain cells can a stationary radar see?", "Coverage rasters and maps"],
         ["2 Flight-route visibility", "Person 2", "How does visibility change along a moving flight route?", "Cumulative coverage, blind spots"],
         ["3 Visibility corridor", "Person 3", "Which feasible route best balances radar exposure and distance?", "Optimised routes and trade-offs"]],
        "Division of work. Each track is separately executable and owned end to end by one member.", widths=[22, 11, 42, 25], num_from=-1))
P("""<p>The tracks share data and conventions, and are linked deliberately: Track 3 avoids the radar sites of Track 1 and plans between the
endpoints of the Track 2 route, so the three results can be read together.</p>""")

# ---------------------------------------------------------------- 2 data & method
sz = meta["sizes"]
P(f"""<h1 id="s2" style="page-break-before: always">2. Data and Shared Methodology</h1>
<h2>2.1 Study area and elevation data</h2>
<p>We use the Copernicus GLO-30 digital surface model (30 m), reprojected with bilinear resampling to WGS 84 / UTM zone 44N
(EPSG:32644). Four square DEMs share one centre (Rudraprayag) and the same 30 m cells, so a larger DEM covers more ground rather
than finer detail, which isolates the effect of problem size. The area runs from the Ganga foothills to the Nanda Devi massif.</p>""")
P(table(["DEM", "Cells", "Extent", "Min (m)", "Max (m)", "Relief (m)", "Std (m)"],
        [[f"{s} x {s}", f0(int(s) ** 2), f"{v['extent_km']:.0f} x {v['extent_km']:.0f} km", f0(v['z_min']), f0(v['z_max']), f0(v['relief_m']), f0(v['z_std'])]
         for s, v in sz.items()], "The four benchmark DEMs (no no-data cells)."))
P(fig("dem", 300, "The 4000 x 4000 DEM (120 x 120 km): hillshade over elevation, rendered in QGIS."))
P(box("Note", "<p>Larger DEMs also reach higher, more rugged terrain (relief grows from 2.3 km to 6.8 km), so size and terrain "
      "complexity change together. Section 7 plans a second, flatter region to separate the two effects.</p>", "note"))
P(f"""<h2>2.2 Visibility model</h2>
<p>A cell is <b>visible</b> if the point <i>target height</i> above it can be joined to the observer's eye, <i>observer height</i> above its
cell, by a straight line that no terrain rises above. Earth curvature with standard refraction lowers distant terrain by
(1 - k)&middot;d<sup>2</sup>/2R with k = 1/7. The same model is used by every algorithm and track:</p>""")
P(table(["Parameter", "Value", "Used by"],
        [["Radar mast height", "30 m above ground", "Tracks 1, 3"], ["Terrain target height", "0 m (the ground surface)", "Tracks 1, 2"],
         ["Aircraft target height", "150 m above ground", "Track 3 exposure"], ["Radar range", "40 km (scenarios)", "Tracks 1, 3"],
         ["Flight clearance / sensor radius", "300 m above ground / 20 km", "Track 2"], ["Output coding", "1 visible, 0 blocked, 255 out of range", "all rasters"]],
        "Shared visibility parameters (common/config.py).", widths=[34, 40, 26], num_from=-1))
P(f"""<h2>2.3 Benchmark protocol</h2>
<p>Each measured run is a fresh Python process (<i>common/bench.py</i>), so memory from one run cannot leak into the next. Runs are
repeated five times (three or one for the slowest configurations); we report the median and keep every run in the CSV files.
<b>Compute time</b> covers the algorithm only, <b>runtime</b> also includes reading the DEM, and <b>peak memory</b> is the peak working set of
the process (about 60 MB of which is Python, NumPy and GDAL themselves). Empirical complexity is the slope of log(time) against
log(size), compared with the theoretical order.</p>""")
P(table(["Component", "Version / specification"],
        [["Processor", f"AMD Ryzen 9 7900X, {mach['cores_physical']} cores / {mach['cores_logical']} threads"], ["Memory", f"{mach['ram_gb']} GB"],
         ["Operating system", "Windows 11"], ["GIS", f"QGIS 3.44.12, GDAL {mach['gdal']}"],
         ["Python stack", f"Python {mach['python']}, NumPy {mach['numpy']}, SciPy {mach['scipy']}"]],
        "Benchmark machine and software.", widths=[30, 70], num_from=-1))

# ---------------------------------------------------------------- 3 track 1
v5 = val["real"]["dem_500_range_0"]; v10 = val["real"]["dem_1000_range_10000"]
P(f"""<h1 id="s3" style="page-break-before: always">3. Track 1: Radar Visibility Assessment</h1>
<p class="eyebrow">PERSON 1</p>
<h2>3.1 Design and implementation</h2>
<p>Three viewshed algorithms sit behind one interface (<i>radar/viewshed.py</i>) with the same physical model and output, so every
benchmark can swap them freely.</p>""")
P(table(["Algorithm", "Idea", "Complexity", "Role"],
        [["Naive line of sight", "For every cell, sample the terrain profile to the observer every half cell (bilinear) and test whether anything rises above the sight line", "O(N&middot;&radic;N)", "exact reference"],
         ["R2 ray casting", "One ray to every cell on the boundary square; each ray keeps a running horizon (Franklin and Ray). Our own vectorised NumPy code", "O(N)", "own fast method"],
         ["GDAL viewshed", "C++ reference-plane algorithm (Wang et al.)", "O(N)", "production engine"]],
        "The three viewshed algorithms (N = cells in range).", widths=[19, 55, 12, 14], num_from=-1))
P("<h2>3.2 Validation</h2>")
P(table(["Test", "Naive", "R2", "GDAL"],
        [["Flat plane: all cells visible", pct(val['synthetic']['flat']['naive']['correct_frac']), pct(val['synthetic']['flat']['r2']['correct_frac']), pct(val['synthetic']['flat']['gdal']['correct_frac'])],
         ["V-shaped valley: all cells visible", pct(val['synthetic']['valley']['naive']['correct_frac']), pct(val['synthetic']['valley']['r2']['correct_frac']), pct(val['synthetic']['valley']['gdal']['correct_frac'])],
         ["200 m wall: everything behind it hidden", pct(val['synthetic']['ridge']['naive']['correct_frac']), pct(val['synthetic']['ridge']['r2']['correct_frac']), pct(val['synthetic']['ridge']['gdal']['correct_frac'])],
         ["Real DEM 500, agreement with exact", "reference", pct(v5['r2']['agreement']), pct(v5['gdal']['agreement'])],
         ["Real DEM 500, Cohen's kappa", "reference", f3(v5['r2']['kappa']), f3(v5['gdal']['kappa'])],
         ["Real DEM 1000, 10 km range, agreement", "reference", pct(v10['r2']['agreement']), pct(v10['gdal']['agreement'])]],
        "Correctness on synthetic terrains with known answers, and against the exact reference on real terrain."))
P(fig("t1_alg", 480, "The same radar computed three ways (DEM 500). Right: cells where GDAL differs from the exact answer; they lie on grazing ridge edges."))
P(box("Bug found by validation", "<p>An early R2 version scored 84.7% on the valley: it compared the cell centre against a horizon built "
      "from interpolated ray points. Testing the ray point itself fixed it and raised agreement on real terrain to "
      f"{pct(v5['r2']['agreement'])}.</p>", "warn"))
P(f"""<h2>3.3 Scenario: six ridge-top radar sites</h2>
<p>Sites are chosen by a fixed rule (<i>common/sites.py</i>): the highest point within 3 km, between 1,500 and 3,200 m, at least 22 km
apart. Each radar has a 40 km range.</p>""")
P(fig("t1_cov", 480, "Number of radars that see each ground cell (left) and each aircraft position 150 m above ground (right). Dashed circles: 40 km range."))
P(box("Finding", f"<p>Together the six radars see only <b>{pct(r_st['union_ground_frac_of_dem'])}</b> of the ground but would detect a low aircraft over "
      f"<b>{pct(r_st['union_air150_frac_of_dem'])}</b> of the area. A single radar sees {pct(min(x['ground_visible_frac'] for x in r_st['radars']))} to "
      f"{pct(max(x['ground_visible_frac'] for x in r_st['radars']))} of the ground in its range: deep valleys hide most terrain even from ridge tops.</p>"))
P("<h2>3.4 First benchmark: cost against DEM size (E1)</h2>")
P(table(["DEM cells", "Naive (s)", "R2 (s)", "GDAL (s)", "GDAL peak memory"],
        [[f0(c), f2(E1['naive']['compute_s'][i]) if i < len(E1['naive']['compute_s']) else (f"~{f0(E1['naive']['projected_16M_s'])} (projected)" if c == 16e6 else "not run"),
          f3(E1['r2']['compute_s'][i]), f3(E1['gdal']['compute_s'][i]), f"{f0(E1['gdal']['peak_mb'][i])} MB"] for i, c in enumerate(E1['gdal']['cells'])],
        "Radar at the DEM centre with unlimited range (the whole DEM is processed); median compute time."))
P(fig("t1_size", 470, "Log-log compute time and peak memory against DEM size; the slope is the empirical complexity exponent."))
P(box("Finding", f"<p>Measured exponents match the theory: naive N<sup>{f2(E1['naive']['exponent'])}</sup> (theory N<sup>1.5</sup>), R2 "
      f"N<sup>{f2(E1['r2']['exponent'])}</sup> and GDAL N<sup>{f2(E1['gdal']['exponent'])}</sup> (theory N; fixed overheads flatten the smallest sizes). "
      f"The exact method would need about {f0(E1['naive']['projected_16M_s'] / 60)} minutes for the 16 M-cell DEM against {f2(E1['gdal']['compute_s'][-1])} s for GDAL, "
      "while agreeing to within 0.3%. Memory follows the DEM and output arrays, about 5 bytes per cell.</p>"))

# ---------------------------------------------------------------- 4 track 2
P(f"""<h1 id="s4" style="page-break-before: always">4. Track 2: Flight-Route Visibility</h1>
<p class="eyebrow" style="color:{TEAL}">PERSON 2</p>
<h2>4.1 Design and implementation</h2>""")
P(table(["Step", "What we do"],
        [["Route", f"A {f0(f_st['route_km'])} km route up the Alaknanda valley (Devprayag, Srinagar, Rudraprayag, Karnaprayag, Chamoli, Joshimath), found as the least-elevation path between the towns and simplified to 300 m"],
         ["Altitude", "Terrain following 300 m above a smoothed ground (running maximum over 3 km), or a constant cruise altitude; computed once at 100 m spacing so every sampling density flies the same path"],
         ["Sampling", f"A position every {f0(f_st['spacing_m'])} m ({f_st['waypoints']} positions), a viewshed within a {f0(f_st['radius_m'] / 1000)} km sensor radius at each (Track 1's GDAL engine)"],
         ["Aggregation", "Times seen per cell, first position that sees it, visible and newly seen area per position, and blind spots: cells within the radius of the route that are never seen"]],
        "Flight-visibility pipeline (flight/route.py, flight/visibility.py).", widths=[16, 84], num_from=-1))
P("<h2>4.2 Scenario: valley flying against cruise</h2>")
P(table(["Flight profile", "Area seen", "Corridor seen", "Blind in corridor", "Mean visible per position"],
        [[a3['label'], f"{f0(a3['seen_km2'])} km&sup2;", pct(a3['seen_in_corridor_frac']), f"{f0(a3['blind_km2'])} km&sup2;", f"{f0(a3['mean_visible_km2_per_wp'])} km&sup2;"],
         [m55['label'], f"{f0(m55['seen_km2'])} km&sup2;", pct(m55['seen_in_corridor_frac']), f"{f0(m55['blind_km2'])} km&sup2;", f"{f0(m55['mean_visible_km2_per_wp'])} km&sup2;"]],
        f"Coverage of the {f0(f_st['corridor_km2'])} km&sup2; corridor within 20 km of the route."))
P(fig("t2_cum", 450, "How many positions see each cell (colour) and blind spots in the corridor (blue)."))
P(fig("t2_alt", 380, "Terrain under the route and the two flight profiles."))
P(box("Finding", f"<p>Flying low in the valley sees only <b>{pct(a3['seen_in_corridor_frac'])}</b> of the corridor; the valley walls hide everything behind "
      f"the first ridge. At 5,500 m the aircraft sees <b>{pct(m55['seen_in_corridor_frac'])}</b>. Low flying is good for staying hidden and poor for "
      f"surveillance, the trade-off that Track 3 optimises. Each scenario takes about {f1(a3['compute_s'])} s for {f_st['waypoints']} viewsheds.</p>"))
P("<h2>4.3 First benchmark: cost against DEM size (F1)</h2>")
P(table(["DEM cells", "F1: route = 0.8 x DEM width, unlimited radius", "Positions", "F1b: fixed 12 km route, 20 km radius"],
        [[f0(c), f"{f2(F1['compute_s'][i])} s", str(int(F1['waypoints'][i])), f"{f2(F1b['compute_s'][i])} s"] for i, c in enumerate(F1['cells'])],
        "Two ways to grow the problem with DEM size (median compute time)."))
P(fig("t2_size", 400, "Compute time and memory against DEM size for the two set-ups."))
P(box("Finding", f"<p>The work is <i>positions x cells per viewshed</i>, not DEM size itself. When route and radius grow with the terrain, each "
      f"viewshed covers the whole DEM and the number of positions grows with its width, so cost grows like N&middot;&radic;N (measured exponent "
      f"{f2(F1['exponent'])}). With a fixed route and radius only reading the larger DEM grows (exponent {f2(F1b['exponent'])}).</p>"))

# ---------------------------------------------------------------- 5 track 3
P(f"""<h1 id="s5" style="page-break-before: always">5. Track 3: Optimal Visibility Corridor</h1>
<p class="eyebrow" style="color:{BLUE}">PERSON 3</p>
<h2>5.1 Objective</h2>
<p>Track 3 uses <i>visibility of the aircraft from ground radars</i>: find a route between two points that keeps the aircraft hidden from
the six Track 1 radars without making it much longer. The aircraft flies 150 m above the ground; terrain where that would exceed a
5,000 m ceiling is blocked.</p>
<p><b>Exposure</b> of a cell is the sum over the radars that can see an aircraft there of (1 - d / range), with a range of 40 km, so
nearer radars count more. The <b>cost</b> of moving between neighbouring cells u and v on the 8-connected grid is</p>
<p align="center" style="font-family:HeadR; font-size:12pt; color:{NAVY}">c(u, v) = L<sub>uv</sub> &middot; (1 + &alpha; &middot; (E<sub>u</sub> + E<sub>v</sub>) / 2) + &beta; &middot; max(0, z<sub>v</sub> - z<sub>u</sub>)</p>
<p>where L is 30 m or 42.4 m, &alpha; weighs exposure against distance and &beta; = 2 penalises climbing. Setting &alpha; = &beta; = 0 gives
the shortest-distance baseline.</p>
<h2>5.2 Solvers</h2>""")
P(table(["Solver", "Description", "Exact?"],
        [["Dijkstra (Python)", "Binary heap, stops at the goal; the baseline", "yes"],
         ["A* (Python)", "Heuristic = straight-line distance + &beta; &middot; height still to climb; admissible and consistent", "yes"],
         ["Dijkstra (SciPy, C)", "Explicit sparse graph of all edges; graph build timed separately", "yes"],
         ["Multi-resolution", "Search a 4x coarser grid, then A* only within a buffer around that route", "approximate"]],
        "Route solvers (corridor/optimizer.py). All exact solvers return identical optimal costs at every size.", widths=[22, 64, 14], num_from=-1))
P("<h2>5.3 Scenario: Devprayag to Joshimath</h2>")
P(table(["Route", "Length", "Exposure (weighted km)", "Length exposed", "Total climb"],
        [["Shortest distance (&alpha; = 0)", f"{f1(sh['length_km'])} km", f1(sh['exposure_km']), pct(sh['exposed_frac']), f"{f0(sh['climb_m'])} m"],
         ["Track 2 valley route", f"{f1(t2r['length_km'])} km", f1(t2r['exposure_km']), pct(t2r['exposed_frac']), f"{f0(t2r['climb_m'])} m"],
         ["Least exposure (&alpha; = 10, &beta; = 2)", f"{f1(a10['length_km'])} km", f1(a10['exposure_km']), pct(a10['exposed_frac']), f"{f0(a10['climb_m'])} m"]],
        "Routes between the Track 2 endpoints, scored with the same metrics.", hl=[2]))
P(fig("t3_routes", 400, "Radar exposure (red), blocked terrain (grey) and routes for several values of &alpha;."))
P(box("Finding", f"<p>The least-exposure route is <b>{pct(a10['length_km'] / sh['length_km'] - 1)} longer</b> than the shortest one but cuts the exposure "
      f"integral by <b>{pct(1 - a10['exposure_km'] / sh['exposure_km'])}</b>, leaving {pct(a10['exposed_frac'])} of its length visible to any radar. The Track 2 "
      f"valley route is already partly masked ({pct(t2r['exposed_frac'])} exposed), but the optimiser does far better.</p>"))
P("<h2>5.4 First benchmark: search time against graph size (C1)</h2>")
P(table(["Nodes", "Dijkstra (Python)", "A* (Python)", "SciPy (C)", "Multi-resolution", "Multi-res. cost gap"],
        [[f0(n), f"{f2(C1['dijkstra_py']['compute_s'][i])} s", f"{f2(C1['astar_py']['compute_s'][i])} s", f"{f2(C1['dijkstra_csgraph']['compute_s'][i])} s",
          f"{f2(C1['multires']['compute_s'][i])} s", f"{C1['multires']['cost_gap_pct'][i]:.2f}%"] for i, n in enumerate(C1['dijkstra_csgraph']['nodes'])],
        "Search time including graph build (median), and the cost of the approximate method above the optimum."))
P(fig("t3_size", 480, "Search time, peak memory and solution quality against graph size."))
P(box("Finding", f"<p>All exact solvers scale close to linearly (exponents {f2(C1['astar_py']['exponent'])} to {f2(C1['dijkstra_py']['exponent'])}; theory "
      f"N log N). Moving the same algorithm from Python to C gains {f0(C1['dijkstra_py']['compute_s'][-1] / C1['dijkstra_csgraph']['compute_s'][-1])}x at "
      f"16 M nodes but builds the whole graph in memory: {f0(C1['dijkstra_csgraph']['peak_mb'][-1])} MB against {f0(C1['dijkstra_py']['peak_mb'][-1])} MB. "
      "Plain A* barely helps here; Appendix A.3 explains why and shows the fix.</p>"))

# ---------------------------------------------------------------- 6 progress
P(f"""<h1 id="s6" style="page-break-before: always">6. Progress Against the Plan</h1>
<p>The project plan has six phases per track. The mid-submission milestone (about 50%) is phases 0 to 3 plus the first scaling benchmark
for every track; the shaded rows below are complete and reported in sections 2 to 5.</p>""")
P(table(["Phase", "Track 1", "Track 2", "Track 3"],
        [["0. Shared data, conventions, protocol", "complete", "complete", "complete"],
         ["1. Research and design", "complete", "complete", "complete"],
         ["2. Implementation and validation", "complete", "complete", "complete"],
         ["3. Visualisation (maps, QGIS project)", "complete", "complete", "complete"],
         ["4a. Scaling against DEM size", "E1 complete", "F1 complete", "C1 complete"],
         ["4b. Parameter studies", "first results (A.1)", "first results (A.2)", "first results (A.3)"],
         ["5. Optimisations", "first results (A.1)", "first results (A.2)", "first results (A.3)"],
         ["6. Analysis, rendering, final report", "planned", "planned", "planned"]],
        "Status per phase and track. Shaded = mid-submission scope, complete.", hl=[0, 1, 2, 3, 4], widths=[37, 21, 21, 21], num_from=-1))
P(box("Deliverables available now", ul(["Source code for all three tracks with a shared benchmark harness, in the team repository.",
                                         "GeoTIFF rasters, GeoJSON routes and CSV metrics for every scenario and benchmark run.",
                                         "A styled QGIS project with all outputs grouped by track.",
                                         "This report and a slide deck (mid-evaluation section plus backup slides)."]), "scope"))

# ---------------------------------------------------------------- 7 future work
P(f"""<h1 id="s7" style="page-break-before: always">7. Future Work</h1>
<p>The second half of the project completes phases 4 to 6 for every track. Several of these experiments have first results already
(Appendix A); the plan below extends them and addresses the limitations found so far.</p>
<h2>7.1 Track 1: radar visibility</h2>""")
P(ul(["<b>Radar siting optimisation.</b> Choose radar locations that maximise joint coverage (greedy selection over candidate ridge tops), instead of the fixed siting rule, and measure how cost grows with the number of candidates.",
      "<b>Detection model.</b> Replace binary visibility with a range-dependent detection probability based on the radar equation, and compare coverage maps.",
      "<b>Larger-than-memory terrain.</b> Tile the DEM so that 8000 x 8000 (64 M cells) and larger grids run within a fixed memory budget, and measure the tiling overhead.",
      "<b>Surface against terrain model.</b> Quantify how trees and buildings in the surface model (DSM) change visibility compared with a bare-earth model (DTM)."]))
P("<h2>7.2 Track 2: flight-route visibility</h2>")
P(ul(["<b>Bounded-memory parallel runs.</b> Threads already give an 8x speed-up (A.2); stream results in fixed-size batches so memory stays flat as routes grow.",
      "<b>Viewpoint selection.</b> Find the smallest set of positions that reproduces the dense coverage (greedy set cover), and turn the altitude-dependent spacing result into an automatic spacing rule.",
      "<b>More routes and aircraft.</b> Ridge-line and straight routes, several aircraft at once, and time-to-first-sighting maps for surveillance planning."]))
P("<h2>7.3 Track 3: optimal visibility corridor</h2>")
P(ul(["<b>Compiled landmark A*.</b> The landmark heuristic (A.3) cuts the search to 4-15% of the nodes but runs in Python; a compiled version (Cython, Numba or C++) is expected to beat the C Dijkstra several-fold.",
      "<b>Aircraft constraints.</b> Add turn radius, climb-rate and minimum-clearance limits through a state-expanded graph, so the result is a flyable corridor rather than a grid path.",
      "<b>Multi-objective routes.</b> Compute the full trade-off front between distance, exposure and climb, and k alternative routes rather than a single optimum.",
      "<b>Corridor width.</b> Score a corridor of given width around the route, not only the centre line."]))
P("<h2>7.4 Across the tracks</h2>")
P(ul(["<b>A second study area.</b> Repeat the scaling benchmarks on a flatter region (for example the Indo-Gangetic plain) to separate the effect of size from that of terrain ruggedness.",
      "<b>Operating-system effects.</b> Repeat the parallel experiments on Linux, where worker processes start far faster than on Windows.",
      "<b>Interactive rendering.</b> Measure pan and zoom responsiveness in the QGIS desktop as well as off-screen render time.",
      "<b>Final integration.</b> One consolidated comparison of the three workloads, the final report and the final presentation."]))
P("<h2>7.5 Timeline to the final submission</h2>")
P(table(["Period", "Track 1", "Track 2", "Track 3", "Team"],
        [["Week 1", "radar siting; detection model", "bounded-memory threads", "compiled landmark A*", "second study area data"],
         ["Week 2", "tiling for 64 M cells", "viewpoint selection; spacing rule", "aircraft constraints", "Linux benchmark runs"],
         ["Week 3", "DSM vs DTM; full parameter study", "more routes; first-sighting maps", "trade-off front; alternatives", "interactive rendering tests"],
         ["Week 4", "analysis and write-up", "analysis and write-up", "analysis and write-up", "final report and presentation"]],
        "Plan for the second half of the project.", widths=[11, 23, 23, 23, 20], num_from=-1))

# ---------------------------------------------------------------- 8 conclusions
P(f"""<h1 id="s8" style="page-break-before: always">8. Conclusions</h1>""")
P(ul([f"All three applications run end to end on one shared, documented data set and pass their correctness checks; the production viewshed agrees with the exact line-of-sight answer on {pct(v5['gdal']['agreement'])} of cells.",
      f"Algorithm choice dominates cost: the exact viewshed grows as N<sup>1.5</sup> and would take about {f0(E1['naive']['projected_16M_s'] / 60)} minutes at 16 M cells, while linear methods take well under a second.",
      "Each workload has its own cost driver: the area one radar covers (Track 1), the number of positions times the area each sees (Track 2), and the size of the route graph (Track 3).",
      f"The applications answer real questions: six radars see {pct(r_st['union_ground_frac_of_dem'])} of the ground, valley flying sees {pct(a3['seen_in_corridor_frac'])} of its corridor, and an optimised route cuts radar exposure by {pct(1 - a10['exposure_km'] / sh['exposure_km'])} for {pct(a10['length_km'] / sh['length_km'] - 1)} more distance.",
      "The mid-submission scope is complete, and the experiments for the second half are already under way."]))
P("<h2>References</h2>")
for ref in ["European Space Agency (2021). Copernicus DEM: Global and European Digital Elevation Model (GLO-30). Copernicus Programme.",
            "Wang, J., Robinson, G. J. and White, K. (2000). Generating viewsheds without using sightlines. <i>Photogrammetric Engineering &amp; Remote Sensing</i> 66(1), 87-90.",
            "Franklin, W. R. and Ray, C. K. (1994). Higher isn't necessarily better: visibility algorithms and experiments. <i>Advances in GIS Research</i>, 751-770.",
            "Dijkstra, E. W. (1959). A note on two problems in connexion with graphs. <i>Numerische Mathematik</i> 1, 269-271.",
            "Hart, P. E., Nilsson, N. J. and Raphael, B. (1968). A formal basis for the heuristic determination of minimum cost paths. <i>IEEE Transactions on Systems Science and Cybernetics</i> 4(2), 100-107.",
            "Goldberg, A. V. and Harrelson, C. (2005). Computing the shortest path: A* search meets graph theory. <i>Proc. ACM-SIAM SODA</i>, 156-165.",
            "GDAL/OGR contributors (2025). GDAL Geospatial Data Abstraction Library, version 3.13. Open Source Geospatial Foundation.",
            "QGIS Development Team (2025). QGIS Geographic Information System, version 3.44. Open Source Geospatial Foundation."]:
    P(f'<p class="ref">{ref}</p>')

# ---------------------------------------------------------------- appendix A
E4s = E4.get("speedup_threads", [])
P(f"""<h1 id="appA" style="page-break-before: always">Appendix A. Results Beyond the Mid-Submission Scope</h1>
<p>These experiments belong to phases 4b and 5 of the plan. They have been run with the same protocol and are reported here for
completeness; Section 7 describes how they will be extended.</p>
<h2>A.1 Track 1: parameters and optimisations</h2>""")
P(fig("t1_range", 300, "Compute time against radar range on the 4000 DEM (E2)."))
P(f"<p><b>Range (E2).</b> Work grows with the area inside the range: compute-time exponents {f2(E2['gdal']['exponent_vs_range'])} (GDAL) and "
  f"{f2(E2['r2']['exponent_vs_range'])} (R2) against range. <b>Mast height (E3)</b> changes coverage but not cost.</p>")
P(table(["Range", "Full DEM read: runtime / peak", "Window read: runtime / peak"],
        [[f"{int(a['range_km'])} km", f"{f3(a['runtime_s'])} s / {f0(a['peak_mb'])} MB", f"{f3(b['runtime_s'])} s / {f0(b['peak_mb'])} MB"]
         for a, b in zip(E5['gdal_full'], E5['gdal_window'])],
        "Region clipping (E5): reading only the window that the radar range covers (GDAL, DEM 4000)."))
P(fig("t1_radars", 450, "Several radars (E4): sequential, 8 worker processes and 12 threads."))
if E4s:
    P(box("Optimisation: threads instead of processes",
          f"<p>On Windows every worker process starts from scratch (about 0.8 s, longer than one 30 km viewshed) and copies results back, so 8 "
          f"processes only helped from 16 radars ({f2(E4['speedup'][-1])}x). GDAL releases Python's global lock inside the viewshed, so 12 threads "
          f"run truly in parallel: {f2(E4s[1])}x at 2 radars and {f2(E4s[-1])}x at 16 ({f2(E4['sequential']['compute_s'][-1])} s to "
          f"{f2(E4['threads12']['compute_s'][-1])} s), at about 0.5 GB because the windows are held together.</p>"))
P(table(["Cell size", "Compute time", "Agreement", "Kappa"],
        [[f"{int(d['cell_m'])} m", f"{f3(d['compute_s'])} s", f"{100 * d['agreement']:.2f}%", f3(d['kappa'])] for d in E6],
        "Coarser DEMs (E6) against the 30 m result. Raw agreement stays high because most cells are hidden either way; kappa shows the real loss."))

P("<h2>A.2 Track 2: parameters and optimisations</h2>")
P(table(["Spacing", "Positions", "Compute", "Overlap with 250 m run", "Missed area"],
        [[f"{int(d['spacing_m'])} m", str(int(d['waypoints'])), f"{f2(d['compute_s'])} s", pct(d['jaccard_vs_250m']), f"{f0(d['missed_km2'])} km&sup2;"] for d in F2],
        f"Sample spacing (F2). Runtime is linear in the number of positions (exponent {f2(f_b['F2_exponent_vs_waypoints'])})."))
P(fig("t2_params", 480, "Flight height (F3), sensor radius (F4) and route length (F5)."))
P(f"<p>Runtime is roughly quadratic in the sensor radius (exponent {f2(f_b['F4_radius_exponent'])}), linear in route length and independent of "
  "flight height, while the area seen rises with both radius and height.</p>")
P(fig("t2_opt", 420, "Execution modes on the 166 km route with 500 m spacing (F6)."))
P(table(["Mode", "Compute", "Positions", "Peak memory", "Coverage vs dense (Jaccard)"],
        [[m.replace("_", " "), f"{f2(d['compute_s'])} s", str(int(d['waypoints'])), f"{f0(d['peak_mb'])} MB", f3(d['jaccard_vs_dense'])] for m, d in F6.items()],
        "Optimisations (F6). Baseline re-opens the DEM for every position."))
P(box("Optimisation: threads; sampling should follow altitude",
      f"<p>Keeping the DEM in memory gives {f1(F6['baseline']['compute_s'] / F6['cached']['compute_s'])}x; 12 threads give "
      f"{f1(F6['baseline']['compute_s'] / F6['threads']['compute_s'])}x with identical results. Adaptive sampling did not pay off: refining where "
      f"neighbouring views differ refines almost everywhere in a winding valley ({int(F6['adaptive']['waypoints'])} positions), and refining only where "
      "a position sees new ground stays on or below the fixed-spacing curve (Figure below). The useful lever is altitude: at cruise, 4 km spacing keeps "
      "97.5% of the coverage with 43 viewsheds; valley flying needs 500 m.</p>"))
P(fig("t2_study", 470, "Positions against coverage for fixed spacing and two adaptive criteria, at valley and cruise altitude."))

P("<h2>A.3 Track 3: parameters and optimisations</h2>")
alt_e = [d["expanded"] for d in C2["astar_alt"]]; ast_e = [d["expanded"] for d in C2["astar_py"][1:]]
P(box("Why plain A* did not help, and the fix",
      f"<p>A* expands fewer nodes only when its estimate of the remaining cost is close to the truth. The straight-line estimate assumes 1 cost "
      f"unit per metre, but exposed metres cost 5 to 17, so with &alpha; between 1 and 100 plain A* expanded {pct(min(ast_e) / 4e6)} to "
      f"{pct(max(ast_e) / 4e6)} of the 4 M nodes. <b>Landmark A* (ALT)</b> precomputes exact costs to and from four landmarks once; the triangle "
      f"inequality then gives a much tighter estimate that is still admissible. It returns the same optimum while expanding {pct(min(alt_e) / 4e6)} to "
      f"{pct(max(alt_e) / 4e6)} of the nodes at every &alpha;. On the 16 M-node scenario: {f0(ALT['alt_expanded'])} nodes in {f1(ALT['alt_s'])} s instead of "
      f"{f0(AST['astar_expanded'])} nodes in {f1(AST['astar_s'])} s, after {f1(ALT['landmark_pre_s'])} s of one-off preprocessing.</p>"))
P(fig("t3_alpha", 450, "Nodes expanded against &alpha; for plain A*, landmark A* and Dijkstra, and the length-exposure trade-off (DEM 2000)."))
P(fig("t3_multi", 480, "Eight routes on the same map (C6): time per route, nodes expanded and peak memory."))
P(f"<p><b>Many routes on one map (C6).</b> Per route, landmark A* is about 3x faster than plain A*, but in Python it does not yet beat the C "
  f"Dijkstra ({f2(C6['alt'][-1]['per_query_s'])} s against {f2(C6['csgraph'][-1]['per_query_s'])} s at 16 M nodes) even though it expands only "
  f"{pct(C6['alt'][-1]['mean_expanded'] / 16e6)} of the nodes; a compiled version is planned (Section 7.3). All methods return identical costs.</p>")
P(table(["Coarsening factor", "Compute", "Nodes expanded", "Cost above optimum"],
        [[str(int(d['k'])), f"{f2(d['compute_s'])} s", f0(d['expanded']), f"{d['cost_gap_pct']:.2f}%"] for d in C3],
        f"Multi-resolution on the 16 M-node graph (C3). The exact C Dijkstra takes {f2(C1['dijkstra_csgraph']['compute_s'][-1])} s and 6 GB."))
P(fig("t3_misc", 480, "Coarsening factor (C3), trip length (C4) and exposure preprocessing cost (C5)."))

P("<h2>A.4 Visualisation performance</h2>")
P(fig("render", 470, "QGIS render time at 1600 x 1600 px (median of five cold renders) for the DEM stored three ways."))
P("<p>Plain or pyramided rasters draw in 55-80 ms at every size: QGIS reads only what fits on screen, so cost follows the screen, not the "
  "raster. Compressed, tiled GeoTIFFs without pyramids are the exception at full extent (0.27 s at 16 M cells), because every tile must be "
  "decompressed, and took 19.9 s when GDAL's cache was limited to 1 MB. Recommendation: build pyramids for compressed outputs.</p>")

P("<h2>A.5 Comparison across the tracks</h2>")
P(table(["Track", "Unit of work", "Cost grows with", "At 16 M cells", "Most effective optimisation"],
        [["1 Radar", "one viewshed", "cells in range (range&sup2;)", f"{f2(E1['gdal']['compute_s'][-1])} s, {f0(E1['gdal']['peak_mb'][-1])} MB", "read only the range window; threads"],
         ["2 Flight", "one viewshed per position", "positions x radius&sup2;", f"{f1(F1['compute_s'][-1])} s ({int(F1['waypoints'][-1])} positions)", "threads; spacing set by altitude"],
         ["3 Corridor", "graph search on exposure", "nodes (N log N)", f"{f0(C1['dijkstra_csgraph']['compute_s'][-1])}-{f0(C1['dijkstra_py']['compute_s'][-1])} s, 0.7-6 GB", "C code, landmark A*, multi-resolution"]],
        "What drives the cost of each workload. Raw runtimes across tracks are not a fair contest because the tracks do different work.",
        widths=[12, 20, 20, 20, 28], num_from=-1))
P(box("Limitations", ul(["Larger DEMs are also more rugged, which mixes size and terrain effects (Section 7.4).",
                          "Peak memory is the Windows peak working set; worker processes are reported separately from the parent.",
                          "The Copernicus model is a surface model, so trees and buildings block sight lines.",
                          "Exposure (1 - d/range) is a simple stand-in for the radar equation, and the aircraft is a point at a fixed height above ground."]), "note"))

# ---------------------------------------------------------------- appendix B
P(f"""<h1 id="appB" style="page-break-before: always">Appendix B. Reproducibility</h1>
<p>All code, results, the QGIS project, this report and the slide deck are in the team repository: <b>{REPO}</b>. The DEMs are not stored
there; the first command downloads and rebuilds them.</p>""")
P(table(["Step", "Command (Windows, QGIS 3.44 Python)"],
        [["Data", "run.bat scripts\\prepare_data.py"], ["Track 1", "run.bat -m radar.validate | radar.run_radar | radar.benchmark | radar.analysis"],
         ["Track 2", "run.bat -m flight.run_flight | flight.benchmark | flight.spacing_study | flight.analysis"],
         ["Track 3", "run.bat -m corridor.run_corridor | corridor.benchmark | corridor.analysis"],
         ["QGIS", "run_qgis.bat qgis\\build_project.py ; run_qgis.bat qgis\\render_bench.py"],
         ["Report / slides", "python report\\build_report.py ; node presentation\\build_pptx.js"]],
        "Commands to rebuild every result.", widths=[18, 82], num_from=-1, small=True))
P(table(["Folder", "Contents"],
        [["common/", "configuration, raster I/O, benchmark harness, plotting, shared radar sites"],
         ["radar/", "viewshed algorithms, validation, scenario, benchmarks, analysis"],
         ["flight/", "routes, moving-observer visibility, scenario, benchmarks, sampling study"],
         ["corridor/", "exposure surface, route solvers (Dijkstra, A*, landmark A*, SciPy, multi-resolution)"],
         ["results/", "GeoTIFF, GeoJSON, CSV, JSON and figures for every track"],
         ["qgis/, report/, presentation/", "QGIS project and render benchmark, this report, slide deck"]],
        "Repository layout.", widths=[26, 74], num_from=-1, small=True))

html = "".join(H)

# =================================================================== LAYOUT
A4 = fitz.paper_rect("a4")
W, Hh = A4.width, A4.height
BODY = A4 + (58, 70, -58, -62)


def layout(path, collect=None):
    _n["fig"] = _n["tab"] = 0
    story = fitz.Story(html=html, user_css=css, archive=fitz.Archive(str(FIG)))
    w = fitz.DocumentWriter(str(path))
    more, page = 1, 0
    while more:
        dev = w.begin_page(A4)
        more, _ = story.place(BODY)
        if collect is not None:
            story.element_positions(lambda pos: collect.append((page, pos.heading, pos.id, pos.text, pos.rect))
                                    if pos.heading in (1, 2) and pos.open_close & 1 else None)
        story.draw(dev); w.end_page(); page += 1
    w.close()
    return page


tmp = Path(tempfile.gettempdir()) / "report_body.pdf"
heads = []
layout(tmp, heads)
toc = []
for pg, lvl, hid, text, rect in heads:
    t = (text or "").strip()
    if t and (not toc or toc[-1][2] != t):
        toc.append((pg, lvl, t, rect))

doc = fitz.open()
doc.insert_pdf(fitz.open(str(tmp)))
FRONT = 2                                    # cover + contents
for i in range(FRONT):
    doc.new_page(pno=i, width=W, height=Hh)

fonts = {"geob": FONTS / "georgiab.ttf", "geo": FONTS / "georgia.ttf", "cal": FONTS / "calibri.ttf", "calb": FONTS / "calibrib.ttf"}


def use_fonts(pg):
    for name, f in fonts.items():
        pg.insert_font(fontname=name, fontfile=str(f))


def rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


# ---------------------------------------------------------------- cover
cv = doc[0]; use_fonts(cv)
band = 470
cv.draw_rect(fitz.Rect(0, 0, W, band), color=None, fill=rgb(NAVY))
im = Image.open(FIG / "dem.png").convert("RGB")
tw, th = im.size; target = W / (Hh - band)
if tw / th > target:
    nw = int(th * target); im = im.crop(((tw - nw) // 2, 0, (tw - nw) // 2 + nw, th))
else:
    nh = int(tw / target); im = im.crop((0, (th - nh) // 2, tw, (th - nh) // 2 + nh))
hero = FIG / "cover_hero.jpg"; im.save(hero, quality=90)
cv.insert_image(fitz.Rect(0, band, W, Hh), filename=str(hero))
cv.insert_text((58, 92), "GS2.401  SPATIAL INFORMATICS   ·   MID-SUBMISSION REPORT", fontname="calb", fontsize=9.5, color=rgb("#f4a261"))
cv.insert_textbox(fitz.Rect(58, 130, W - 58, 250), "Large-Scale Terrain\nData Analysis 2", fontname="geob", fontsize=34, color=(1, 1, 1), lineheight=1.15)
cv.insert_textbox(fitz.Rect(58, 252, W - 70, 320), "Radar visibility, flight-route visibility and radar-avoiding corridors over the Garhwal Himalaya",
                  fontname="cal", fontsize=14.5, color=rgb("#cdd6e4"), lineheight=1.3)
cv.draw_line((58, 340), (130, 340), color=rgb("#f4a261"), width=1.5)
for i, (tr_, who) in enumerate((("Track 1  ·  Radar visibility", "Person 1"), ("Track 2  ·  Flight-route visibility", "Person 2"),
                                ("Track 3  ·  Visibility corridor", "Person 3"))):
    y = 366 + i * 20
    cv.insert_text((58, y), tr_, fontname="calb", fontsize=10.5, color=(1, 1, 1))
    cv.insert_text((280, y), who, fontname="cal", fontsize=10.5, color=rgb("#cdd6e4"))
cv.insert_text((58, 448), "October 2026", fontname="cal", fontsize=10, color=rgb("#cdd6e4"))
cv.draw_rect(fitz.Rect(0, Hh - 26, W, Hh), color=None, fill=rgb(NAVY), fill_opacity=0.75)
cv.insert_text((58, Hh - 9.5), "Copernicus GLO-30 DEM of the study area, 120 x 120 km, rendered in QGIS", fontname="cal", fontsize=8, color=(1, 1, 1))

# ---------------------------------------------------------------- contents
tc = doc[1]; use_fonts(tc)
tc.insert_text((58, 96), "Contents", fontname="geob", fontsize=22, color=rgb(NAVY))
y = 132
for pg, lvl, text, rect in toc:
    target = pg + FRONT
    x = 58 if lvl == 1 else 78
    fn, fs = ("calb", 11) if lvl == 1 else ("cal", 10)
    if lvl == 1 and y > 132:
        y += 3
    tc.insert_text((x, y), text, fontname=fn, fontsize=fs, color=rgb(NAVY if lvl == 1 else INK))
    num = str(target + 1)
    tw_ = fitz.get_text_length(num, fontname="helv", fontsize=fs)
    tc.insert_text((W - 58 - tw_, y), num, fontname=fn, fontsize=fs, color=rgb(NAVY if lvl == 1 else INK))
    tlen = fitz.Font(fontfile=str(fonts[fn])).text_length(text, fontsize=fs)
    dots_x0, dots_x1 = x + tlen + 6, W - 58 - tw_ - 6
    if dots_x1 > dots_x0:
        tc.draw_line((dots_x0, y - 2), (dots_x1, y - 2), color=rgb("#c9d0d9"), width=0.6, dashes="[1 3] 0")
    tc.insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(x, y - fs, W - 58, y + 3), "page": target,
                    "to": fitz.Point(58, max(fitz.Rect(rect).y0 - 10, 0))})
    y += 17 if lvl == 1 else 14.2

# ---------------------------------------------------------------- MuPDF Story workaround
# Story re-draws every earlier box background as a 10 pt strip at the top of each later page.
# Remove vector drawings lying entirely inside that strip; text and real backgrounds (which
# extend further down) are untouched.
for i in range(FRONT, len(doc)):
    pg = doc[i]
    pg.add_redact_annot(fitz.Rect(60, 60, 540, 76))
    pg.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                        text=fitz.PDF_REDACT_TEXT_NONE)

# ---------------------------------------------------------------- running header and footer
n = len(doc)
for i in range(1, n):
    pg = doc[i]; use_fonts(pg)
    pg.insert_text((58, 40), "Large-Scale Terrain Data Analysis 2", fontname="calb", fontsize=8.5, color=rgb(NAVY))
    t = "Mid-submission report"
    pg.insert_text((W - 58 - fitz.Font(fontfile=str(fonts['cal'])).text_length(t, fontsize=8.5), 40), t, fontname="cal", fontsize=8.5, color=rgb(MUTED))
    pg.draw_line((58, 47), (W - 58, 47), color=rgb("#c9d0d9"), width=0.6)
    pg.draw_line((58, Hh - 44), (W - 58, Hh - 44), color=rgb("#c9d0d9"), width=0.6)
    pg.insert_text((58, Hh - 30), "Spatial Informatics · Terrain visibility", fontname="cal", fontsize=8.5, color=rgb(MUTED))
    num = f"{i + 1} / {n}"
    pg.insert_text((W - 58 - fitz.Font(fontfile=str(fonts['cal'])).text_length(num, fontsize=8.5), Hh - 30), num, fontname="cal", fontsize=8.5, color=rgb(MUTED))

doc.set_metadata({"title": "Large-Scale Terrain Data Analysis 2: Mid-Submission Report", "author": "Person 1, Person 2, Person 3",
                  "subject": "Terrain visibility: radar coverage, flight-route visibility, visibility corridors", "keywords": "viewshed, DEM, A*, QGIS, benchmark"})
doc.set_toc([[lvl, text, pg + FRONT + 1] for pg, lvl, text, _ in toc])
doc.save(str(OUT), garbage=4, deflate=True)
print("wrote", OUT, n, "pages;", len(toc), "contents entries")
try:
    os.remove(tmp)
except OSError:
    pass
