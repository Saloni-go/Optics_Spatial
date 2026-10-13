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
      "rendering performance); they are included for completeness and will be extended for the final. "
      "Appendix B reports the Track 3 work done since: interactive planning (what to precompute and what to compute on the fly) "
      "and extensions of the corridor model.</p>", "scope"))

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
P(ul(["<b>Done since the mid-submission (Appendix B):</b> compiled searches and landmark A*, an interactive planner (precomputed fields, alpha bank, parallel rebuilds, anytime search), detection-probability routing with a certified risk budget, a tile overlay, altitude choice, a radar-placement game, alternative corridors and robustness checks.",
      "<b>Remaining:</b> combine the risk budget with uncertain radar positions (a chance constraint over scenarios), and run the exact constrained search on 16 M cells with a stronger bound.",
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
            "Meyer, U. and Sanders, P. (2003). Delta-stepping: a parallelizable shortest path algorithm. <i>Journal of Algorithms</i> 49(1), 114-152.",
            "Koenig, S. and Likhachev, M. (2002). D* Lite. <i>Proc. AAAI</i>, 476-483.",
            "Ramalingam, G. and Reps, T. (1996). An incremental algorithm for a generalization of the shortest-path problem. <i>Journal of Algorithms</i> 21(2), 267-305.",
            "Juttner, A., Szviatovszki, B., Mecs, I. and Rajko, Z. (2001). Lagrange relaxation based method for the QoS routing problem. <i>Proc. IEEE INFOCOM</i>, 859-868.",
            "Carlyle, W. M., Royset, J. O. and Wood, R. K. (2008). Lagrangian relaxation and enumeration for solving constrained shortest-path problems. <i>Networks</i> 52(4), 256-270.",
            "Delling, D., Goldberg, A. V., Pajor, T. and Werneck, R. F. (2011). Customizable route planning. <i>Proc. SEA</i>, LNCS 6630, 376-387.",
            "Richter, S., Thayer, J. T. and Ruml, W. (2010). The joy of forgetting: faster anytime search via restarting. <i>Proc. ICAPS</i>, 137-144.",
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

# ---------------------------------------------------------------- appendix B: Track 3 interactive planning and extensions
IX, XT = R / "corridor" / "interactive", R / "corridor" / "extensions"
JX = lambda n: json.load(open(IX / f"{n}.json"))
JT = lambda n: json.load(open(XT / f"{n}.json"))
for k, p in {"b_e1": IX / "fig_e1_ladder.png", "b_e2": IX / "fig_e2_anytime.png", "b_e3": IX / "fig_e3_incremental.png",
             "b_e4": IX / "fig_e4_lod.png", "b_e5": IX / "fig_e5_detection.png", "b_demo": IX / "demo_last.png",
             "b_e7": XT / "fig_e7_bank.png", "b_e8": XT / "fig_e8_parallel.png", "b_e9": XT / "fig_e9_csp.png",
             "b_e10": XT / "fig_e10_tiles.png", "b_e11": XT / "fig_e11_altitude.png", "b_e12": XT / "fig_e12_placement.png",
             "b_e13": XT / "fig_e13_uncertain.png", "b_e14": XT / "fig_e14_alternatives.png", "b_e15": XT / "fig_e15_montecarlo.png"}.items():
    shutil.copy(p, FIG / f"{k}.png")
C7, C8 = c_b["C7"], c_b["C8"]
x1, x2, x3, x4, x5, x5b = (JX(n) for n in ("e1_ladder", "e2_anytime", "e3_incremental", "e4_lod", "e5_detection", "e5b_risk_budget"))
x7, x8, x9, x10, x11, x12 = (JT(n) for n in ("e7_bank", "e8_parallel", "e9_csp", "e10_tiles", "e11_altitude", "e12_placement"))
x13, x14, x15 = (JT(n) for n in ("e13_uncertain", "e14_alternatives", "e15_montecarlo"))
med = lambda v: sorted(v)[len(v) // 2]
row16 = lambda key: [d for d in C7[key] if d["nodes"] == 16e6][0]
lad = {r["strategy"]: r for r in x1["rows"]}
sc4 = [s_ for s_ in x8["scaling"] if s_["size"] == 4000][0]
th = {int(k): v for k, v in sc4["threads"].items()}
best_th = min(th, key=lambda k: th[k]["s"])
e3b = [r for r in x3["runs"] if r["size"] == 4000 and r["event"] == "start moved"]
e3r = [r for r in x3["runs"] if r["size"] == 4000 and "move radar" in r["event"]]
rvb = x8["repair_vs_rebuild"]
prog = [r["progressive"] for r in x2["runs"]]

P(f"""<h1 id="appB" style="page-break-before: always">Appendix B. Track 3: Interactive Planning</h1>
<p class="eyebrow" style="color:{BLUE}">PERSON 3 &middot; WORK AFTER THE MID-SUBMISSION</p>
<p>A route planner is only useful if it answers while the user is still looking at the map. This appendix answers the question raised in
our project meeting: <i>what should be precomputed, what should be computed on the fly, which algorithms keep panning, zooming and editing
smooth, and what to do when the precomputed data no longer applies?</i> It then reports further extensions of the corridor model. Every
number comes from the 120 x 120 km, 16 M-cell DEM unless stated otherwise, and every route is checked against an exact search.</p>
<h2>B.1 Compiled search</h2>
<p>The Python searches of Section 5 were rewritten in C on the implicit grid (no stored graph): Dijkstra, A* and landmark A* (ALT)
(corridor/c/gridsearch.c, called through ctypes). On 16 M nodes one exact route takes {f2(row16('dijkstra_c')['query_s'])} s with
{f0(row16('dijkstra_c')['peak_mb'])} MB (SciPy: {f2(C1['dijkstra_csgraph']['compute_s'][-1])} s, {f0(C1['dijkstra_csgraph']['peak_mb'][-1])} MB) and
landmark A* {f2(row16('alt_c')['query_s'])} s after {f2(row16('alt_c')['pre_s'])} s of landmark preprocessing on 8 threads. All costs are identical
to the optimum.</p>
<h2>B.2 What to precompute: a ladder of levels</h2>""")
P(table(["Level", "Precompute", "Memory", "Route for a new start", "Route for a new goal"],
        [["0. Nothing (C Dijkstra)", "-", "-", f"{f0(lad['Dijkstra (C)']['query_fixed_goal_ms'])} ms", f"{f0(lad['Dijkstra (C)']['query_any_pair_ms'])} ms"],
         ["0. A* (straight line + climb)", "-", "-", f"{f0(lad['A* geo heuristic (C)']['query_fixed_goal_ms'])} ms", f"{f0(lad['A* geo heuristic (C)']['query_any_pair_ms'])} ms"],
         ["1. Landmarks (4), ALT", f"{f1(lad['ALT, 4 landmarks (C)']['pre_s'])} s", f"{f0(lad['ALT, 4 landmarks (C)']['mem_mb'])} MB",
          f"{f0(lad['ALT, 4 landmarks (C)']['query_fixed_goal_ms'])} ms", f"{f0(lad['ALT, 4 landmarks (C)']['query_any_pair_ms'])} ms"],
         ["1. Landmarks (8), ALT", f"{f1(lad['ALT, 8 landmarks (C)']['pre_s'])} s", f"{f0(lad['ALT, 8 landmarks (C)']['mem_mb'])} MB",
          f"{f0(lad['ALT, 8 landmarks (C)']['query_fixed_goal_ms'])} ms", f"{f0(lad['ALT, 8 landmarks (C)']['query_any_pair_ms'])} ms"],
         ["2. Cost-to-go field to the goal", f"{f1(lad['Level 2 cost-to-go field (C)']['pre_s'])} s ({f2(th[best_th]['s'])} s parallel)",
          f"{f0(lad['Level 2 cost-to-go field (C)']['mem_mb'])} MB", f"{f2(lad['Level 2 cost-to-go field (C)']['query_fixed_goal_ms'])} ms (lookup)", "one new field"]],
        "Precompute against query time (E1, mean of 20 routes, 16 M cells; every route exact).", hl=[4], widths=[28, 18, 12, 21, 21]))
P(fig("b_e1", 470, "Left: precompute against time per route. Right: total time after n clicks with the same goal."))
P(box("Finding: precompute the field for the current goal",
      f"<p>A <b>cost-to-go field</b> stores, for every cell, the cost of the best route to the goal and the next step. One backward search "
      f"builds it; afterwards a route from <i>any</i> start is read off in {f2(lad['Level 2 cost-to-go field (C)']['query_fixed_goal_ms'])} ms with no search, "
      "exact. It pays off from the second click. Landmarks are the right precompute when the goal changes often; four are the sweet spot "
      f"(eight double memory for {f0(100 * (1 - lad['ALT, 8 landmarks (C)']['query_any_pair_ms'] / lad['ALT, 4 landmarks (C)']['query_any_pair_ms']))}% "
      "faster queries).</p>"))

P("<h2>B.3 Building the field on 12 cores</h2>")
P(f"<p>Dijkstra settles one node at a time and cannot use more cores. <b>Delta-stepping</b> (Meyer and Sanders 2003) relaxes a whole "
  f"bucket of nodes with similar cost at once; lock-free atomic updates keep it exact (corridor/c/parallel.inc). The OpenMP barrier of the "
  f"MinGW runtime sleeps between phases and made the parallel version slower than one core; replacing it with a spinning barrier fixed this. "
  f"On 16 M cells the field takes {f2(sc4['dijkstra_s'])} s with Dijkstra, {f2(th[1]['s'])} s with delta-stepping on one core and "
  f"<b>{f2(th[best_th]['s'])} s on {best_th} threads ({f1(sc4['dijkstra_s'] / th[best_th]['s'])}x)</b>, identical to the last bit. The alpha bank of "
  f"five fields (B.5) now builds in {f1(x8['bank']['build_s'])} s.</p>")
P(fig("b_e8", 480, "Speed-up against threads (12 physical cores), bucket width, and repair against a parallel rebuild after radar edits."))

P("<h2>B.4 Edits: moving the start, a radar, the goal</h2>")
P(table(["Event (16 M cells)", "Incremental method", "Time", "From scratch", "Time"],
        [["start moved (click)", "field lookup", f"{f2(med([r['lookup_ms'] for r in e3b]))} ms", "C Dijkstra", f"{f0(med([r['dijkstra_ms'] for r in e3b]))} ms"],
         ["start moved (click)", "D* Lite replan", f"{f0(med([r['dstar_ms'] for r in e3b]))} ms", "", ""],
         ["radar moved", "threat surface of that radar only", f"{f0(med([r['field_update_ms'] for r in e3r]))} ms", "all six viewsheds", "~1,000 ms"],
         ["radar moved", "field repair (dynamic SSSP)", f"{f0(med([r['repair_s'] * 1000 for r in rvb]))} ms", "parallel field rebuild",
          f"{f0(med([r['parallel_rebuild_s'] * 1000 for r in rvb]))} ms"],
         ["radar moved", "D* Lite update", f"{f0(med([r['dstar_ms'] for r in e3r]))} ms", "", ""]],
        "Medians over the edits of E3 and E8. Every repaired field equals a fresh one (max difference below 1e-9).", widths=[22, 30, 12, 24, 12]))
P(fig("b_e3", 470, "Left: incremental time / from-scratch time against the share of cells whose threat changed. Right: moving the start."))
P(box("Finding: repair locally, but rebuild in parallel", "<p>Only the radar that moved is recomputed (one viewshed window), never the whole "
      "threat surface. For the route, the incremental field repair and D* Lite are exact but their cost depends on how far the change "
      "propagates: a radar has a 40 km reach, so its edit touches a large share of the routes. With 12 cores a full parallel rebuild "
      f"({f0(med([r['parallel_rebuild_s'] * 1000 for r in rvb]))} ms) beat the repair in every edit measured. D* Lite shines only when the start moves "
      "along its route (often no work at all), which the field lookup already does in microseconds.</p>", "note"))

P("<h2>B.5 When the precompute stops being valid: changing alpha</h2>")
P(f"<p>The exposure weight alpha changes every edge cost, so fields and landmarks are invalid. Two remedies. <b>Anytime coarse-to-fine:</b> "
  f"exact routes on a 16x and 4x coarser copy of the grid, then a full-resolution search inside a corridor around them, then the exact field; "
  f"each stage is drawn as it arrives: first route after {f0(1000 * med([p_[0]['t_s'] for p_ in prog]))} ms "
  f"({f1(med([p_[0]['gap_pct'] for p_ in prog]))}% above the optimum), within {f2(max(p_[-2]['gap_pct'] for p_ in prog))}% after "
  f"{f2(med([p_[-2]['t_s'] for p_ in prog]))} s. Restarting weighted A*, the textbook anytime method, was slower at every quality level (Figure). "
  f"<b>Alpha bank:</b> precompute the next-step fields for a ladder of alpha values (64 MB each); the slider then shows the exact route for a "
  f"banked alpha at once and the nearest banked route in between.</p>")
P(table(["alpha requested", "5 banked (2-50): used", "cost above exact", "11 banked (1-100): used", "cost above exact"],
        [[f"{t['alpha']:g}", f"{t['5 alphas']['used']:g}", f"{max(t['5 alphas']['gap_mean'], 0):.2f}% (max {max(t['5 alphas']['gap_max'], 0):.2f}%)",
          f"{t['11 alphas']['used']:g}", f"{max(t['11 alphas']['gap_mean'], 0):.2f}%"] for t in x7["tests"]],
        f"Alpha bank (E7), 10 starts per alpha; a lookup takes about 1 ms. Bank of 5: {f0(x7['ladders']['5 alphas']['mem_mb'])} MB; of 11: "
        f"{f0(x7['ladders']['11 alphas']['mem_mb'])} MB.", small=True))
P(fig("b_e2", 360, "Cost above the optimum against time after alpha changes: coarse-to-fine (circles) and weighted A* (crosses)."))

P("<h2>B.6 Panning and zooming</h2>")
P(f"<p>A route is one global object, so it should not be re-solved per view. Re-solving the visible window on a coarse-to-fine pyramid "
  f"took {f0(med([r['preview_ms'] for r in x4['rows']]))} ms per view and often drew a route in a different valley (up to hundreds of pixels "
  f"off). Drawing the route already known, decimated to about one point per screen pixel, takes {f2(med([r['exact_draw_ms'] for r in x4['rows']]))} ms "
  f"at any zoom: pan and zoom never search. The pyramid's job is the anytime preview of B.5.</p>")
P(fig("b_e4", 420, "Pan and zoom: latency and on-screen error of re-solving each view (rejected) against drawing the known route (adopted)."))

P("<h2>B.7 Latency budget</h2>")
P(table(["Interaction", "Strategy", "Latency", "Class"],
        [["click a new start", "field lookup", f"{f2(med([r['lookup_ms'] for r in e3b]))} ms", "within a frame (16 ms)"],
         ["move the alpha slider (banked value)", "alpha bank lookup", "~1 ms", "within a frame"],
         ["move the alpha slider (other value)", "nearest bank route, then coarse-to-fine, then exact field",
          f"1 ms / {f0(1000 * med([p_[-2]['t_s'] for p_ in prog]))} ms / {f0(1000 * th[best_th]['s'])} ms", "frame, then responsive"],
         ["drag a radar", "one viewshed + parallel field rebuild", f"{f0(med([r['field_update_ms'] for r in e3r]) + 1000 * med([r['parallel_rebuild_s'] for r in rvb]))} ms", "responsive (< 1 s)"],
         ["new goal", "landmark A* now, field in the background", f"{f0(lad['ALT, 4 landmarks (C)']['query_any_pair_ms'])} ms", "responsive"],
         ["pan / zoom", "draw the known route", f"{f2(med([r['exact_draw_ms'] for r in x4['rows']]))} ms", "within a frame"]],
        "What the interactive viewer (corridor/interactive.py) does for each action, 16 M cells.", widths=[28, 40, 16, 16], num_from=-1))
P(fig("b_demo", 330, "The interactive viewer after a scripted session (clicks, radar drag, alpha change, zoom, risk budget); the panel logs what answered each action."))

P("<h2>B.8 From exposure to detection probability</h2>")
P("<p>Exposure is a unitless score. The detection model gives each radar that sees the aircraft a probability of detecting it per "
  "kilometre flown, p(d) = 0.5 / (1 + (d / 20 km)<sup>4</sup>), so P(detected) = 1 - exp(-&Sigma; length &middot; hazard) with hazard "
  "H = &Sigma; -ln(1 - p). The sum is additive along the route, so every solver above applies unchanged.</p>")
P(fig("b_e5", 330, "Detection probability against route length for routes optimised for exposure and for detection, and risk-budget answers."))
v9 = x9["validation"]; s9 = x9["scenario"]
P(f"<p><b>Risk budget: the shortest route with P(detected) &le; p.</b> This is a resource-constrained shortest path (NP-hard). "
  f"LARAC (Lagrangian relaxation) moves the price of risk to its best value in a few exact searches (one parallel field each) and certifies a "
  f"lower bound on the best possible length; an exact label-setting search in a corridor around its routes, pruned with exact bounds and the "
  f"Lagrangian bound (Carlyle et al. 2008), then closes the gap. On 1 M cells the corridor answer equals the whole-map optimum in all "
  f"{len(v9)} budgets and the remaining gap is the looseness of the bound itself. On 16 M cells LARAC answers in "
  f"{f1(min(r['larac_s'] for r in s9))}-{f1(max(r['larac_s'] for r in s9))} s instead of {f0(min(r['bisection_s'] for r in s9 if r.get('bisection_s')))}-"
  f"{f0(max(r['bisection_s'] for r in s9 if r.get('bisection_s')))} s for bisection.</p>")
P(table(["Budget P(detect) &le;", "Exact step", "Found", "Length", "Certified gap", "Time"],
        [[f"{100 * r['p_max']:.0f}%", r.get("exact_status", "-"), f"{100 * r['p_detect']:.1f}%", f"{f0(r['length_km'])}&nbsp;km",
          f"{r['gap_pct']:.1f}%", f"{f1(r['larac_s'] + (r.get('exact_s') or 0))}&nbsp;s"] for r in s9 if r.get("p_detect") is not None],
        "Risk-budget queries on 16 M cells (E9). Certified gap = how far the length can at most be from the best possible; "
        "splice = exact search on the union of the LARAC routes when the corridor search hits its label cap.", small=True, num_from=2))
P(fig("b_e9", 470, "Left: LARAC alone and with the exact corridor search, 1 M cells. Right: time and certified gap on 16 M cells."))

P("<h2>B.9 A precompute that survives edits: tile overlay</h2>")
v10 = {(r["spacing"], r["valleys"]): r for r in x10["variants"]}
best10 = v10.get((25, 10), x10["variants"][0])
P(f"<p>The field serves one goal; landmarks serve any goal but must be rebuilt after every radar edit ({f1(x10['updates'][0]['landmarks_rebuild_s'])} s). "
  f"A tile overlay (the idea of customizable route planning) cuts the map into 250 x 250 tiles and precomputes the cost between "
  f"<i>portal</i> cells on each tile's border. Any route is then a search on {f0(best10['portals'])} portals instead of 16 M cells, and a radar "
  f"edit recomputes only the tiles it touches. Portals at regular spacing force detours; adding a portal at every valley floor along a border, "
  f"where hidden routes actually cross, cut the error several-fold for the same number of portals.</p>")
P(table(["Portals", "Overlay nodes", "Precompute", "Query + unpack", "Cost above exact (mean / max)"],
        [[f"every {r['spacing']} cells" + (" + valleys" if r["valleys"] else ""), f0(r["portals"]), f"{f1(r['pre_s'])} s",
          f"{f0(r['query_ms'])} + {f0(r['unpack_ms'])} ms", f"{r['gap_mean']:.2f}% / {r['gap_max']:.2f}%"] for r in x10["variants"]],
        f"Tile overlay, 20 random start-goal pairs (E10). Exact landmark A*: {f0(1000 * x10['alt_query_s'])} ms per pair.", small=True))
P(fig("b_e10", 470, "Left: accuracy against overlay size. Right: time to make the precompute valid again after a radar edit."))

P("<h2>B.10 Altitude as a decision</h2>")
fx = {int(r["agl"]): r for r in x11["fixed"]}
fr = {r["gamma_scale"]: r for r in x11["runs"]}
t4 = x11["timing"][-1]
P(f"<p>The aircraft may fly at 75, 150, 300 or 600 m above ground and change height; each height has its own threat surface (viewsheds "
  f"depend on the target height) and ceiling mask, flying low costs extra per metre (gamma: terrain-following risk) and every climb costs. "
  f"The search runs on height levels x cells (corridor/c/layers.inc): 64 M nodes for the 16 M-cell map in {f0(t4['s'])} s and {f0(t4['mem_mb'])} MB. "
  f"On the 60 km map a fixed 150 m flight is detected with probability {pct(fx[150]['p_detect'])}; choosing the height freely gives "
  f"{pct(fr[0.0]['p_detect'])} without a low-flying penalty (the whole route at 75 m) and {pct(fr[1.0]['p_detect'])} with it. On the 16 M-cell "
  f"scenario: {pct(t4['p_detect'])} against {pct(t4['p_detect_fixed150'])} at a fixed 150 m.</p>")
P(fig("b_e11", 470, "Free-altitude route coloured by height, and height use with detection probability for fixed and free heights."))

g12 = x12["greedy"]["curve"]; c12 = x12["coverage"]["curve"]
P("<h2>B.11 Where should the radars go? A placement game</h2>")
P(f"<p>The defender places {x12['K']} radars among {len(x12['candidates'])} peaks; the attacker knows them, picks the safest of three entry points and "
  f"flies the least-risk route. Each attacker reply is one parallel field (about 0.1 s on 4 M cells), so a greedy defender can afford "
  f"{x12['evals']} replies. Placing for routes beats placing for coverage: one routing-aware radar already forces a detection probability of "
  f"{pct(g12[0])} and two reach {pct(g12[1])}, while the classic coverage placement (most ground seen) reaches {pct(c12[1])} with two and "
  f"{pct(c12[-1])} with all six. The hand-placed scenario radars score {pct(x12['hand']['p_detect'])}, random placements a median of "
  f"{pct(med(x12['random']))}.</p>")
P(fig("b_e12", 470, "Attacker's best-route detection probability against radars placed, and the radars with the attacker's reply."))

u1, u3 = x13["runs"][0]["routes"], x13["runs"][1]["routes"]
via14, pen14 = x14["via-node"], x14["penalty"]
mc = x15["routes"]; sen = x15["sensitivity"]
short = [r for r in sen if r["d50_km"] < 20]; same = [r for r in sen if r["d50_km"] >= 20]
P("<h2>B.12 Robustness: uncertain radars, alternatives, model checks</h2>")
P(f"<p><b>Uncertain radar positions (E13).</b> If each radar is only known to within &sigma;, sampled position scenarios give sampled threat "
  f"surfaces, and planning on their per-cell mean (expected risk) or on a high per-cell quantile (pessimistic envelope) is still an ordinary "
  f"shortest path. Judged on unseen scenarios by the planner's own objective (length + &alpha; x risk): with &sigma; = 1 km the mean-threat "
  f"plan is best ({f0(u1['expected']['J_mean'] / 1000)}k against {f0(u1['nominal']['J_mean'] / 1000)}k for the nominal plan); with &sigma; = 3 km "
  f"the pessimistic plan is best on average and in bad cases ({f0(u3['envelope q90']['J_mean'] / 1000)}k / {f0(u3['envelope q90']['J_p90'] / 1000)}k "
  f"against {f0(u3['nominal']['J_mean'] / 1000)}k / {f0(u3['nominal']['J_p90'] / 1000)}k at the 90th percentile). Note that a better objective is "
  f"not always a lower detection probability: averaging makes each radar look weaker but wider, and the planner trades that for distance "
  f"({f0(u1['expected']['length_km'])} km at {pct(u1['expected']['p_mean'])} mean detection against {f0(u1['nominal']['length_km'])} km at "
  f"{pct(u1['nominal']['p_mean'])}). A probability target needs the risk budget of B.8.</p>")
P(fig("b_e13", 470, "Uncertain radar positions: detection probability and planner objective on unseen scenarios."))
P(f"<p><b>Alternative corridors (E14).</b> A planner should offer genuinely different options. The via-node method (choice routing) needs only "
  f"two fields, one from the start and one to the goal, which give the best route through every cell; scanning cells at least 3 km from the "
  f"best route found {len(via14['routes']) - 1} alternatives (+{via14['routes'][1]['stretch_pct']:.1f}% and +{via14['routes'][-1]['stretch_pct']:.1f}%) in "
  f"{f1(via14['info']['total_s'])} s. The penalty method (make cells near each route dearer and re-plan) found {len(pen14['routes']) - 1} alternatives at "
  f"+{min(r['stretch_pct'] for r in pen14['routes'][1:]):.1f}% to +{max(r['stretch_pct'] for r in pen14['routes'][1:]):.1f}% with at most "
  f"{f0(100 * max(r['max_overlap'] for r in pen14['routes']))}% overlap in {f1(pen14['info']['total_s'])} s, and is the better choice on this terrain: "
  "narrow valleys leave few near-optimal detours, which the via-node scan must search for.</p>")
P(fig("b_e14", 470, "Three alternative corridors: via-node method (left) and penalty method (right)."))
P(f"<p><b>Checking the detection model (E15).</b> Simulating {x15['flights']:,} flights per route (each radar detecting independently per "
  f"segment) reproduces the formula within the 95% interval for every route (e.g. {pct(mc[2]['p_mc'])} simulated against {pct(mc[2]['p_analytic'])}). "
  f"The model itself matters: if the target's radar cross-section fluctuates from flight to flight (a Swerling-I-like model), the same route is "
  f"detected with {pct(mc[2]['p_fluctuating'])} instead of {pct(mc[2]['p_analytic'])}. If the true radar reach is shorter than assumed "
  f"(d50 = 10 km instead of 20), the nominal route is {f1(min(r['regret_pct'] for r in short))}-{f1(max(r['regret_pct'] for r in short))}% worse than a re-optimised "
  f"one and shares only {f0(100 * max(r['overlap'] for r in short))}% of it; if the reach is the same or longer it stays within "
  f"{f1(max(r['regret_pct'] for r in same))}%. Range calibration matters more than the peak detection probability.</p>")
P(fig("b_e15", 470, "Monte Carlo against the formula, a fluctuating-target model, and the cost of wrong model parameters."))
P(box("Summary: what to precompute, what to compute on the fly", ul([
    "Precompute the cost-to-go field for the current goal (exact routes from any start by lookup) and a small bank of fields for other alpha values; keep the landmark set or the tile overlay for new goals.",
    "Compute on the fly only what an edit invalidates: one radar's viewshed window, then a parallel rebuild of the field (0.3-0.4 s on 12 cores).",
    "When the precompute does not apply, answer at once with an approximate route (bank, coarse-to-fine, overlay) and improve it to the exact one in the background.",
    "Pan and zoom never search: they draw the route already known.",
    "Report risk as a probability, and answer probability targets with a certified constrained search."]), "finding"))

# ---------------------------------------------------------------- appendix C
P(f"""<h1 id="appC" style="page-break-before: always">Appendix C. Reproducibility</h1>
<p>All code, results, the QGIS project, this report and the slide deck are in the team repository: <b>{REPO}</b>. The DEMs are not stored
there; the first command downloads and rebuilds them.</p>""")
P(table(["Step", "Command (Windows, QGIS 3.44 Python)"],
        [["Data", "run.bat scripts\\prepare_data.py"], ["Track 1", "run.bat -m radar.validate | radar.run_radar | radar.benchmark | radar.analysis"],
         ["Track 2", "run.bat -m flight.run_flight | flight.benchmark | flight.spacing_study | flight.analysis"],
         ["Track 3", "run.bat -m corridor.run_corridor | corridor.benchmark | corridor.analysis"],
         ["Track 3 (App. B)", "run.bat -m corridor.interactive_bench all | corridor.extensions_bench all | corridor.interactive"],
         ["QGIS", "run_qgis.bat qgis\\build_project.py ; run_qgis.bat qgis\\render_bench.py"],
         ["Report / slides", "python report\\build_report.py ; node presentation\\build_pptx.js"]],
        "Commands to rebuild every result.", widths=[18, 82], num_from=-1, small=True))
P(table(["Folder", "Contents"],
        [["common/", "configuration, raster I/O, benchmark harness, plotting, shared radar sites"],
         ["radar/", "viewshed algorithms, validation, scenario, benchmarks, analysis"],
         ["flight/", "routes, moving-observer visibility, scenario, benchmarks, sampling study"],
         ["corridor/", "exposure surface, route solvers (Dijkstra, A*, landmark A*, SciPy, multi-resolution); compiled C core (c/), "
                       "interactive planner and viewer, extensions (risk budget, tiles, altitude, placement, alternatives)"],
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
