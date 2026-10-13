"""Builds report/mid_submission_report.pdf from the result JSONs and figures.

Part A = the 50% mid-submission scope (setup, design, implementation, validation, maps, first
scaling benchmark per track).  Part B = completed work beyond 50% (parameter studies,
optimisations, rendering, cross-track discussion), clearly marked so the team can choose.
Run:  python report\\build_report.py   (system Python with PyMuPDF; it only reads JSON and PNG files)
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

import fitz  # PyMuPDF (pip-installed in the system Python; see README)

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"
FIG = ROOT / "report" / "figs"
OUT = ROOT / "report" / "mid_submission_report.pdf"

J = lambda p: json.load(open(R / p))
meta = json.load(open(ROOT / "data" / "dem_metadata.json"))
mach = J("radar/machine.json")
val = J("radar/validation.json")
r_st, r_b = J("radar/stats.json"), J("radar/benchmark_summary.json")
f_st, f_b = J("flight/stats.json"), J("flight/benchmark_summary.json")
c_st, c_b = J("corridor/stats.json"), J("corridor/benchmark_summary.json")

FIG.mkdir(parents=True, exist_ok=True)
FIGS = {"dem": R / "shared/qgis_dem.png", "t1_alg": R / "radar/fig_algorithm_comparison.png",
        "t1_cov": R / "radar/fig_coverage_six_radars.png", "t1_one": R / "radar/fig_single_radar.png",
        "t1_size": R / "radar/fig_bench_size.png", "t1_range": R / "radar/fig_bench_range.png",
        "t1_radars": R / "radar/fig_bench_radars.png", "t1_clip": R / "radar/fig_bench_clipping.png",
        "t1_res": R / "radar/fig_bench_resolution.png", "t1_h": R / "radar/fig_bench_height.png",
        "t2_cum": R / "flight/fig_cumulative_visibility.png", "t2_alt": R / "flight/fig_altitude_profile.png",
        "t2_along": R / "flight/fig_coverage_along_route.png", "t2_size": R / "flight/fig_bench_size.png",
        "t2_spacing": R / "flight/fig_bench_spacing.png", "t2_params": R / "flight/fig_bench_params.png",
        "t2_opt": R / "flight/fig_bench_optimise.png",
        "t3_routes": R / "corridor/fig_routes.png", "t3_trade": R / "corridor/fig_tradeoff.png",
        "t3_size": R / "corridor/fig_bench_size.png", "t3_alpha": R / "corridor/fig_bench_alpha.png",
        "t3_misc": R / "corridor/fig_bench_misc.png", "t3_multi": R / "corridor/fig_bench_multiquery.png",
        "t2_spacing_study": R / "flight/fig_spacing_study.png", "render": R / "shared/fig_render_benchmark.png"}
for k, p in FIGS.items():
    if p.exists():
        shutil.copy(p, FIG / f"{k}.png")

f0 = lambda v: f"{v:,.0f}"
f1 = lambda v: f"{v:,.1f}"
f2 = lambda v: f"{v:,.2f}"
f3 = lambda v: f"{v:.3f}"
pct = lambda v: f"{100 * v:.1f}%"


def img(k, w=470, cap=None):
    s = f'<p align="center"><img src="{k}.png" width="{w}"></p>'
    if cap:
        s += f'<p class="cap" align="center">{cap}</p>'
    return s


def table(header, rows, widths=None):
    h = "".join(f"<th>{x}</th>" for x in header)
    b = "".join("<tr>" + "".join(f'<td class="r">{c}</td>' if i else f"<td>{c}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<table class="g" width="100%"><tr>{h}</tr>{b}</table>'


css = """
body { font-family: sans-serif; font-size: 9.6pt; line-height: 1.32; }
h1 { font-size: 17pt; margin-bottom: 2pt; color: #14213d; }
h2 { font-size: 13pt; margin-top: 12pt; margin-bottom: 3pt; color: #14213d; border-bottom: 1px solid #c9ced6; }
h3 { font-size: 10.6pt; margin-top: 8pt; margin-bottom: 2pt; color: #2a6f97; }
p { margin-top: 2pt; margin-bottom: 4pt; }
li { margin-bottom: 2pt; }
table { border-collapse: collapse; }
table.g td, table.g th { border: 1px solid #9aa3ad; padding: 2pt 4pt; font-size: 8.8pt; }
th { font-weight: bold; background-color: #eef1f4; }
.cap { font-size: 8.2pt; color: #3d4652; margin-top: 1pt; margin-bottom: 7pt; }
.r { text-align: right; }
.note { font-size: 9pt; color: #3d4652; }
.part { font-size: 9pt; color: #9d0208; font-weight: bold; }
"""

E1 = r_b["E1"]
sz = meta["sizes"]
html = f"""
<h1>Large-Scale Terrain Data Analysis 2: terrain visibility</h1>
<p><b>Mid-submission report.</b> Team: Person 1 (Track 1, radar visibility), Person 2 (Track 2, flight-route visibility), Person 3 (Track 3, optimal visibility corridor).</p>
<p>We build three terrain-visibility applications on one shared set of DEMs and measure how their cost grows with terrain size and problem parameters: runtime, peak memory, scalability, complexity, rendering performance and accuracy. Every number in this report comes from the code and result files in the project folder (<i>results/</i>).</p>
<p class="part">Part A (sections 1-5) is the mid-submission scope (about 50% of the project). Part B (sections 6-9) is additional completed work for the final submission.</p>

<h2>1. Shared setup (Phase 0)</h2>
<p><b>Data.</b> Copernicus GLO-30 DSM, Garhwal Himalaya (Uttarakhand), reprojected with bilinear resampling to WGS 84 / UTM 44N (EPSG:32644) at 30 m. Four square DEMs share the same centre (Rudraprayag) and the same 30 m cells, so a bigger DEM means more <i>area</i>, not finer cells. No no-data cells.</p>
{table(["DEM", "cells", "extent", "min (m)", "max (m)", "relief (m)", "std (m)"],
       [[f"{s} x {s}", f0(int(s) ** 2), f"{v['extent_km']:.0f} x {v['extent_km']:.0f} km", f0(v['z_min']), f0(v['z_max']), f0(v['relief_m']), f0(v['z_std'])]
        for s, v in sz.items()])}
<p class="cap">Table 1. The four benchmark DEMs. Larger DEMs reach the high Himalaya (up to 7,074 m), so terrain also gets more rugged with size; the results are read with that in mind.</p>
{img("dem", 330, "Figure 1. The 4000 x 4000 DEM (120 x 120 km), hillshade over elevation, rendered in QGIS.")}
<p><b>Visibility model (all tracks).</b> A cell is visible if the point <i>target height</i> above it is in line of sight from the observer, whose eye is <i>observer height</i> above its cell. Earth curvature with standard refraction is applied (drop = (1 - k) d<sup>2</sup> / 2R, k = 1/7). Radars stand on 30 m masts; terrain targets are at 0 m; aircraft targets for Track 3 are 150 m above ground. Rasters are GeoTIFF (1 visible, 0 blocked, 255 out of range), routes GeoJSON, metrics CSV.</p>
<p><b>Benchmark protocol.</b> Each measured run is a fresh Python process (<i>common/bench.py</i>), repeated 5 times (3 or 1 for the slowest configurations); we report the median and keep every run in the CSV. <i>compute</i> = algorithm only; <i>runtime</i> also includes reading the DEM; <i>peak memory</i> = peak working set of the process (about 60 MB is Python, NumPy and GDAL themselves). Machine: AMD Ryzen 9 7900X ({mach['cores_physical']} cores / {mach['cores_logical']} threads), {mach['ram_gb']} GB RAM, Windows 11, Python {mach['python']}, GDAL {mach['gdal']}, NumPy {mach['numpy']}.</p>

<h2>2. Track 1: radar visibility assessment (Person 1)</h2>
<h3>Design and implementation</h3>
<p>Three viewshed algorithms behind one interface (<i>radar/viewshed.py</i>), same physical model and output:</p>
<ul>
<li><b>Naive line of sight</b>: for every cell, sample the terrain profile to the observer every half cell (bilinear) and test whether anything rises above the sight line. O(N &middot; R) for N cells and R cells of radius. Exact; used as the accuracy reference.</li>
<li><b>R2 ray casting</b> (Franklin and Ray): one ray to every cell on the boundary square, each ray keeps a running horizon. O(N). Our own implementation, vectorised over rays in NumPy.</li>
<li><b>GDAL viewshed</b> (C++, Wang et al. reference planes), O(N). The trusted production implementation.</li>
</ul>
<h3>Validation</h3>
{table(["Test", "naive", "R2", "GDAL"],
       [["flat plane: all visible", pct(val['synthetic']['flat']['naive']['correct_frac']), pct(val['synthetic']['flat']['r2']['correct_frac']), pct(val['synthetic']['flat']['gdal']['correct_frac'])],
        ["V-shaped valley: all visible", pct(val['synthetic']['valley']['naive']['correct_frac']), pct(val['synthetic']['valley']['r2']['correct_frac']), pct(val['synthetic']['valley']['gdal']['correct_frac'])],
        ["200 m wall: everything behind hidden", pct(val['synthetic']['ridge']['naive']['correct_frac']), pct(val['synthetic']['ridge']['r2']['correct_frac']), pct(val['synthetic']['ridge']['gdal']['correct_frac'])],
        ["real DEM 500, agreement with exact LOS", "reference", pct(val['real']['dem_500_range_0']['r2']['agreement']) + f" (kappa {f3(val['real']['dem_500_range_0']['r2']['kappa'])})", pct(val['real']['dem_500_range_0']['gdal']['agreement']) + f" (kappa {f3(val['real']['dem_500_range_0']['gdal']['kappa'])})"],
        ["real DEM 1000, 10 km range", "reference", pct(val['real']['dem_1000_range_10000']['r2']['agreement']), pct(val['real']['dem_1000_range_10000']['gdal']['agreement'])]])}
<p class="cap">Table 2. Correctness on synthetic terrains with known answers and against the exact line-of-sight reference on real terrain. An early R2 version scored 84.7% on the valley because it tested the cell centre against a horizon built from interpolated ray points; testing the ray point itself fixed it.</p>
{img("t1_alg", 500, "Figure 2. Same radar, three algorithms (DEM 500). Right: where GDAL differs from the exact answer; the few mismatches sit on grazing ridge edges.")}
<h3>Scenario: six radar sites</h3>
<p>Six ridge-top sites (highest point within 3 km, 1500-3200 m, at least 22 km apart; <i>common/sites.py</i>), range 40 km. Together they see <b>{pct(r_st['union_ground_frac_of_dem'])}</b> of the ground in the 120 x 120 km area, but would detect an aircraft 150 m above the ground over <b>{pct(r_st['union_air150_frac_of_dem'])}</b> of it. Individual radars see {pct(min(x['ground_visible_frac'] for x in r_st['radars']))} to {pct(max(x['ground_visible_frac'] for x in r_st['radars']))} of the ground inside their range: deep valleys hide most terrain.</p>
{img("t1_cov", 500, "Figure 3. Number of radars that see each ground cell (left) and each aircraft position 150 m above ground (right). Dashed: 40 km range.")}
<h3>First benchmark: runtime and memory vs DEM size (E1)</h3>
{table(["DEM cells", "naive (s)", "R2 (s)", "GDAL (s)", "GDAL peak MB"],
       [[f0(c), f2(E1['naive']['compute_s'][i]) if i < len(E1['naive']['compute_s']) else f"~{f0(E1['naive']['projected_16M_s'])} (projected)" if c == 16e6 else "not run",
         f3(E1['r2']['compute_s'][i]), f3(E1['gdal']['compute_s'][i]), f0(E1['gdal']['peak_mb'][i])] for i, c in enumerate(E1['gdal']['cells'])])}
<p class="cap">Table 3. Radar at the centre, unlimited range (the whole DEM is processed), median compute time.</p>
{img("t1_size", 480, "Figure 4. Log-log runtime and memory vs number of cells; the slope is the empirical complexity exponent.")}
<p>The fitted exponents match the theory: naive LOS grows as N<sup>{f2(E1['naive']['exponent'])}</sup> (theory N<sup>1.5</sup>), R2 as N<sup>{f2(E1['r2']['exponent'])}</sup> and GDAL as N<sup>{f2(E1['gdal']['exponent'])}</sup> (theory N; fixed overheads flatten the small sizes). Extrapolated, the exact method would need about <b>{f0(E1['naive']['projected_16M_s'] / 60)} minutes</b> for the 16 M-cell DEM, against {f2(E1['gdal']['compute_s'][-1])} s for GDAL, while agreeing to within about 0.3%. Memory is dominated by the DEM array and the output (4 + 1 bytes per cell).</p>
"""

# ------------------------------------------------------------------ Track 2
F1 = f_b["F1_size"]; F1b = f_b["F1b_size_fixed_route"]
a3, m55 = f_st["cases"]["agl300"], f_st["cases"]["msl5500"]
html += f"""
<h2>3. Track 2: flight-route visibility (Person 2)</h2>
<h3>Design and implementation</h3>
<ul>
<li><b>Route.</b> A {f0(f_st['route_km'])} km valley route along the Alaknanda (Devprayag, Srinagar, Rudraprayag, Karnaprayag, Chamoli, Joshimath), found as the least-elevation path between the towns and simplified to 300 m (<i>flight/route.py</i>).</li>
<li><b>Altitude.</b> Terrain following at 300 m above a smoothed ground (running maximum over 3 km, since an aircraft cannot follow every bump), or a constant cruise altitude. The profile is computed once at 100 m spacing, so every sampling density flies the same path.</li>
<li><b>Visibility.</b> The route is sampled every {f0(f_st['spacing_m'])} m ({f_st['waypoints']} positions); at each, a viewshed within a {f0(f_st['radius_m'] / 1000)} km sensor radius (GDAL engine, same curvature model). Results are aggregated into: how many positions see each cell, the first position that sees it, per-position and newly seen area, and <b>blind spots</b> (cells within the radius of the route that are never seen).</li>
</ul>
<h3>Scenario results</h3>
{table(["Profile", "area seen", "corridor seen", "blind in corridor", "mean visible per position"],
       [[a3['label'], f0(a3['seen_km2']) + " km2", pct(a3['seen_in_corridor_frac']), f0(a3['blind_km2']) + " km2", f0(a3['mean_visible_km2_per_wp']) + " km2"],
        [m55['label'], f0(m55['seen_km2']) + " km2", pct(m55['seen_in_corridor_frac']), f0(m55['blind_km2']) + " km2", f0(m55['mean_visible_km2_per_wp']) + " km2"]])}
<p class="cap">Table 4. The corridor is the {f0(f_st['corridor_km2'])} km<sup>2</sup> within 20 km of the route.</p>
{img("t2_cum", 500, "Figure 5. Number of positions that see each cell (colour) and blind spots in the corridor (blue). Low valley flying sees only the valley walls.")}
{img("t2_alt", 440, "Figure 6. Terrain under the route and the two flight profiles.")}
<p>Flying low in the valley is the stealthy option: the aircraft sees (and is seen from) only {pct(a3['seen_in_corridor_frac'])} of the corridor; at 5,500 m it sees {pct(m55['seen_in_corridor_frac'])}. Each scenario takes about {f1(a3['compute_s'])} s for {f_st['waypoints']} viewsheds.</p>
<h3>First benchmark: runtime vs DEM size (F1)</h3>
{table(["DEM cells", "F1: route = 0.8 x DEM width, unlimited radius (s)", "positions", "F1b: fixed 12 km route, 20 km radius (s)"],
       [[f0(c), f2(F1['compute_s'][i]), str(int(F1['waypoints'][i])) if F1['waypoints'][i] else "", f2(F1b['compute_s'][i])] for i, c in enumerate(F1['cells'])])}
{img("t2_size", 470, "Figure 7. Two ways to grow the problem with DEM size.")}
<p>When the route and the sensor radius grow with the terrain (F1), each viewshed covers the whole DEM and the number of positions grows with its width, so cost grows like N &middot; &radic;N: measured exponent {f2(F1['exponent'])}. With a fixed route and radius (F1b) only reading the larger DEM grows, exponent {f2(F1b['exponent'])}. The work is set by <i>positions x cells per viewshed</i>, not by DEM size itself.</p>
"""

# ------------------------------------------------------------------ Track 3
C1 = c_b["C1"]
rt = c_st["routes"]
sh, a10, t2r = rt["shortest"], rt["alpha_10"], rt["track2_valley_route"]
html += f"""
<h2>4. Track 3: optimal visibility corridor (Person 3)</h2>
<h3>Objective and design</h3>
<p><b>Visibility meaning.</b> Track 3 uses <i>visibility of the aircraft from ground radars</i>: find a route between two points that keeps the aircraft hidden from the six Track 1 radars without making it much longer. The aircraft flies 150 m above the ground; terrain where that is above a 5,000 m ceiling is blocked.</p>
<p><b>Exposure</b> E(cell) = sum over radars that can see an aircraft there of (1 - d / range), range 40 km (closer radars count more). <b>Edge cost</b> between neighbouring cells u, v on the 8-connected grid:<br>
&nbsp;&nbsp;&nbsp;c(u, v) = L<sub>uv</sub> (1 + &alpha; (E<sub>u</sub> + E<sub>v</sub>)/2) + &beta; max(0, z<sub>v</sub> - z<sub>u</sub>)<br>
L = 30 or 42.4 m; &alpha; trades exposure against distance; &beta; = 2 penalises climbing. &alpha; = &beta; = 0 is the shortest-distance baseline.</p>
<p><b>Solvers</b> (<i>corridor/optimizer.py</i>): Dijkstra in pure Python with a binary heap (baseline); A* with h(u) = straight-line distance + &beta; max(0, z<sub>goal</sub> - z<sub>u</sub>), admissible and consistent because every metre costs at least 1 and any path must climb at least the height difference; SciPy's C Dijkstra on an explicit sparse graph; and a coarse-to-fine multi-resolution search (approximate). All exact solvers return identical optimal costs (checked on every size).</p>
<h3>Scenario: Devprayag to Joshimath</h3>
{table(["Route", "length", "exposure (weighted km)", "length exposed", "climb"],
       [["shortest distance (alpha 0)", f1(sh['length_km']) + " km", f1(sh['exposure_km']), pct(sh['exposed_frac']), f0(sh['climb_m']) + " m"],
        ["least exposure (alpha 10, beta 2)", f1(a10['length_km']) + " km", f1(a10['exposure_km']), pct(a10['exposed_frac']), f0(a10['climb_m']) + " m"],
        ["Track 2 valley route", f1(t2r['length_km']) + " km", f1(t2r['exposure_km']), pct(t2r['exposed_frac']), f0(t2r['climb_m']) + " m"]])}
<p class="cap">Table 5. Same endpoints as the Track 2 route. Exposure integral = sum of segment length x exposure.</p>
{img("t3_routes", 430, "Figure 8. Exposure surface, blocked terrain and routes for several alpha.")}
<p>The least-exposure route is {pct(a10['length_km'] / sh['length_km'] - 1)} longer than the shortest one but cuts the exposure integral by {pct(1 - a10['exposure_km'] / max(sh['exposure_km'], 1e-9))}.</p>
<h3>First benchmark: search time vs graph size (C1)</h3>
{table(["nodes", "Dijkstra (Python) s", "A* (Python) s", "SciPy C Dijkstra s", "multi-res s", "multi-res cost gap"],
       [[f0(n), f2(C1['dijkstra_py']['compute_s'][i]), f2(C1['astar_py']['compute_s'][i]), f2(C1['dijkstra_csgraph']['compute_s'][i]),
         f2(C1['multires']['compute_s'][i]), f"{C1['multires']['cost_gap_pct'][i]:.2f}%"] for i, n in enumerate(C1['dijkstra_csgraph']['nodes'])])}
{img("t3_size", 500, "Figure 9. Search time (incl. graph build), memory and cost above the optimum vs graph size.")}
<p>Exponents: Python Dijkstra {f2(C1['dijkstra_py']['exponent'])}, A* {f2(C1['astar_py']['exponent'])}, SciPy {f2(C1['dijkstra_csgraph']['exponent'])} (theory O(N log N) for an N-node grid). Moving the same algorithm from Python to C gains about {f0(C1['dijkstra_py']['compute_s'][-1] / C1['dijkstra_csgraph']['compute_s'][-1])}x at 16 M nodes, but the explicit graph costs memory ({f0(C1['dijkstra_csgraph']['peak_mb'][-1])} MB vs {f0(C1['dijkstra_py']['peak_mb'][-1])} MB).</p>

<h2>5. Status and plan</h2>
<p>All three applications run end to end, pass their correctness checks, export GeoTIFF/GeoJSON/CSV, and have a first scaling benchmark. A styled QGIS project (<i>qgis/terrain_visibility.qgz</i>) holds every output. Remaining phases for the final submission: parameter studies, optimisation comparisons, rendering performance and the cross-track analysis. Part B shows that these have already been run.</p>
"""

# ------------------------------------------------------------------ Part B
E5 = r_b["E5"]; E6 = r_b["E6"]; E4 = r_b["E4"]
F2 = f_b["F2"]; F6 = {d["mode"]: d for d in f_b["F6"]}
html += f"""
<h2 style="page-break-before: always">6. Part B. Track 1: parameters and optimisation</h2>
<p class="part">Part B: completed work beyond the 50% scope.</p>
{img("t1_range", 300, "Figure 10. Runtime vs radar range on the 4000 DEM.")}
<p><b>Range (E2).</b> Work grows with the area inside the range: compute time slope {f2(r_b['E2']['gdal']['exponent_vs_range'])} (GDAL) and {f2(r_b['E2']['r2']['exponent_vs_range'])} (R2) against range (theory 2 for the area; GDAL's fixed costs dominate at short range). <b>Height (E3)</b> changes coverage, not cost.</p>
{img("t1_clip", 470, "Figure 11. Region clipping: reading only the window that the range covers.")}
{table(["range", "full read: runtime / peak", "window read: runtime / peak"],
       [[f"{int(a['range_km'])} km", f"{f3(a['runtime_s'])} s / {f0(a['peak_mb'])} MB", f"{f3(b['runtime_s'])} s / {f0(b['peak_mb'])} MB"]
        for a, b in zip(E5['gdal_full'], E5['gdal_window'])])}
<p class="cap">Table 6. GDAL with and without region clipping (E5), DEM 4000.</p>
{img("t1_radars", 470, "Figure 12. Several radars: sequential vs 8 worker processes (E4).")}
<p><b>Parallel radars (E4).</b> The first attempt used 8 worker processes: on Windows each starts from scratch (about 0.8 s, longer than one 30 km viewshed) and results are copied back, so it only won from 16 radars ({f2(E4['speedup'][-1])}x). GDAL releases Python's global lock inside the viewshed, so 12 threads in one process run truly in parallel: {f2(E4['speedup_threads'][1])}x at 2 radars and {f2(E4['speedup_threads'][-1])}x at 16 ({f2(E4['sequential']['compute_s'][-1])} s to {f2(E4['threads12']['compute_s'][-1])} s), at about 0.5 GB because the windows are held together.</p>
{img("t1_res", 300, "Figure 13. Coarser DEM: faster but less accurate (E6).")}
{table(["cell size", "compute", "agreement", "kappa"], [[f"{int(d['cell_m'])} m", f3(d['compute_s']) + " s", f"{100 * d['agreement']:.2f}%", f3(d['kappa'])] for d in E6])}
<p class="cap">Table 7. Agreement with the 30 m result. Raw agreement stays high because most cells are hidden either way; kappa (chance-corrected) shows the real loss.</p>

<h2>7. Part B. Track 2: parameters and optimisation</h2>
{img("t2_spacing", 470, "Figure 14. Number of positions vs time, and coverage lost by sparser sampling (F2).")}
{table(["spacing", "positions", "compute", "overlap with 250 m run", "missed area"],
       [[f"{int(d['spacing_m'])} m", str(int(d['waypoints'])), f2(d['compute_s']) + " s", pct(d['jaccard_vs_250m']), f0(d['missed_km2']) + " km2"] for d in F2])}
<p class="cap">Table 8. Runtime is linear in the number of positions (slope {f2(f_b['F2_exponent_vs_waypoints'])}).</p>
{img("t2_params", 500, "Figure 15. Flight height, sensor radius and route length (F3-F5).")}
{img("t2_opt", 360, "Figure 16. Optimisations on the 166 km route, 500 m spacing (F6).")}
{table(["mode", "compute", "positions", "peak memory", "same coverage as dense (Jaccard)"],
       [[m, f2(d['compute_s']) + " s", str(int(d['waypoints'])), f0(d['peak_mb']) + " MB", f3(d['jaccard_vs_dense'])] for m, d in F6.items()])}
<p class="cap">Table 9. Optimisations (F6). Baseline re-opens the DEM file for every position.</p>
<p><b>Findings.</b> Runtime is linear in the number of positions and route length, roughly quadratic in the sensor radius (slope {f2(f_b['F4_radius_exponent'])}) and independent of flight height (slope {f2(f_b['F3_altitude_exponent'])}), while the area seen rises with both. Keeping the DEM in memory gives {f1(F6['baseline']['compute_s'] / F6['cached']['compute_s'])}x; copying a range window per position adds overhead because GDAL already limits itself to the radius. Worker processes give {f1(F6['baseline']['compute_s'] / F6['parallel']['compute_s'])}x, but <b>threads</b> (GDAL releases the global lock) give {f1(F6['baseline']['compute_s'] / F6['threads']['compute_s'])}x with identical results. Adaptive sampling did not pay off. The first criterion (refine where neighbouring viewsheds differ) refines almost everywhere in a winding valley ({int(F6['adaptive']['waypoints'])} positions). The second (refine only where the midpoint sees new ground) uses {int(F6['adaptive_gain']['waypoints'])} positions at Jaccard {f3(F6['adaptive_gain']['jaccard_vs_dense'])}, which is no better than fixed spacing (Figure 16b): coverage grows smoothly along the route, so uniform spacing is already efficient. The useful lever is to match the spacing to the altitude: at cruise, 4 km spacing keeps 97.5% of the coverage with 43 viewsheds; valley flying needs 500 m.</p>
{img("t2_spacing_study", 470, "Figure 16b. Positions vs coverage for fixed spacing and both adaptive criteria, valley flying and cruise.")}

<h2>8. Part B. Track 3: parameters and optimisation</h2>
{img("t3_alpha", 470, "Figure 17. Effect of the exposure weight alpha (DEM 2000): nodes expanded and the length vs exposure trade-off.")}
<p><b>Exposure weight (C2) and the A* fix.</b> Plain A* uses straight-line distance as its estimate of the remaining cost, assuming 1 cost unit per metre, but exposed metres cost 5-17 units. With alpha 1 to 100 it therefore expands {pct(min(d['expanded'] for d in c_b['C2']['astar_py'][1:]) / 4e6)} to {pct(max(d['expanded'] for d in c_b['C2']['astar_py'][1:]) / 4e6)} of the 4 M nodes. <b>Landmark A* (ALT)</b> fixes this: exact costs to and from 4 landmarks are precomputed once (one forward and one backward C Dijkstra each), and by the triangle inequality give a much tighter estimate that is still admissible and consistent. It returns the same optimum while expanding only {pct(min(d['expanded'] for d in c_b['C2']['astar_alt']) / 4e6)} to {pct(max(d['expanded'] for d in c_b['C2']['astar_alt']) / 4e6)} of the nodes at every alpha, and answers in {f2(min(d['compute_s'] for d in c_b['C2']['astar_alt']))}-{f2(max(d['compute_s'] for d in c_b['C2']['astar_alt']))} s instead of {f1(min(d['compute_s'] for d in c_b['C2']['astar_py']))}-{f1(max(d['compute_s'] for d in c_b['C2']['astar_py']))} s. On the 16 M-node scenario: {f0(c_st['alt_check_alpha10']['alt_expanded'])} nodes and {f1(c_st['alt_check_alpha10']['alt_s'])} s instead of {f0(c_st['astar_check_alpha10']['astar_expanded'])} nodes and {f1(c_st['astar_check_alpha10']['astar_s'])} s, after {f1(c_st['alt_check_alpha10']['landmark_pre_s'])} s and {f0(c_st['alt_check_alpha10']['landmark_mb'])} MB of one-off preprocessing. The trade-off curve flattens after alpha = 10: the route length goes from {f1(c_b['C2']['dijkstra_csgraph'][0]['length_km'])} to {f1(c_b['C2']['dijkstra_csgraph'][3]['length_km'])} km while exposure falls from {f1(c_b['C2']['dijkstra_csgraph'][0]['exposure_km'])} to {f1(c_b['C2']['dijkstra_csgraph'][3]['exposure_km'])}.</p>
{img("t3_multi", 500, "Figure 17b. Eight routes on the same map (C6): time per route, nodes expanded and memory.")}
<p><b>Many routes on one map (C6).</b> Per route, landmark A* is about 3x faster than plain A*, but in Python it does not beat the C Dijkstra ({f2(c_b['C6']['alt'][-1]['per_query_s'])} s vs {f2(c_b['C6']['csgraph'][-1]['per_query_s'])} s at 16 M nodes) even though it expands only {pct(c_b['C6']['alt'][-1]['mean_expanded'] / 16e6)} of the nodes: Python costs far more per node. Implementing it in compiled code is the next step. All methods return identical route costs.</p>
{img("t3_misc", 500, "Figure 18. Multi-resolution factor (C3), trip length (C4) and exposure preprocessing cost (C5).")}
{table(["coarsening k", "compute", "nodes expanded", "cost above optimum"], [[str(int(d['k'])), f2(d['compute_s']) + " s", f0(d['expanded']), f"{d['cost_gap_pct']:.2f}%"] for d in c_b['C3']])}
<p class="cap">Table 10. Multi-resolution on the 16 M-node graph (C3); exact SciPy Dijkstra takes {f2(C1['dijkstra_csgraph']['compute_s'][-1])} s and 6 GB.</p>
<p><b>Trip length (C4).</b> A* pays off on short trips ({f0(c_b['C4']['astar_py'][0]['expanded'])} vs {f0(c_b['C4']['dijkstra_py'][0]['expanded'])} nodes at a quarter of the diagonal) and much less on long ones. <b>Exposure preprocessing (C5)</b> is linear in the number of radars, about {f2(c_b['C5'][-1]['compute_s'] / c_b['C5'][-1]['radars'])} s per radar on the 16 M-cell DEM, and is done once per scenario.</p>
{img("t3_trade", 280, "Figure 19. Scenario trade-off between distance and exposure.")}

<h2>9. Part B. Visualisation performance and cross-track comparison</h2>
{img("render", 470, "Figure 20. QGIS render time (1600 x 1600 px, median of 5 cold renders) for the DEM stored three ways.")}
<p><b>Rendering.</b> QGIS draws plain or pyramided rasters in 55-80 ms at every size: the cost follows the screen (1600 x 1600 px), because GDAL reads only the rows or overview level it needs. Compressed, tiled GeoTIFFs without pyramids are the exception at full extent (0.06 s at 0.25 M cells, 0.27 s at 16 M), since every tile must be decompressed; with GDAL's cache starved to 1 MB the same render took 19.9 s. Each render opens a fresh layer, so GDAL's block cache is cold; the operating-system file cache stays warm. Recommendation: build pyramids for compressed outputs.</p>
{table(["Track", "unit of work", "cost grows with", "16 M cells", "best lever"],
       [["1 Radar", "one viewshed", "cells in range (~range^2)", f"{f2(E1['gdal']['compute_s'][-1])} s, {f0(E1['gdal']['peak_mb'][-1])} MB", "read only the range window"],
        ["2 Flight", "one viewshed per position", "positions x radius^2", f"{f1(F1['compute_s'][-1])} s ({int(F1['waypoints'][-1])} positions)", "keep DEM in memory; fewer positions"],
        ["3 Corridor", "graph search on exposure", "nodes (N log N)", f"{f0(C1['dijkstra_csgraph']['compute_s'][-1])}-{f0(C1['dijkstra_py']['compute_s'][-1])} s, 0.7-6 GB", "C solver or multi-resolution"]])}
<p class="cap">Table 11. Cross-track comparison of what drives the cost. Raw runtimes across tracks are not a fair contest because the tracks do different work.</p>
<p><b>Limitations.</b> Bigger DEMs are also more rugged (they reach the high Himalaya), which mixes size and terrain effects. Peak memory is the process peak working set on Windows; parallel runs report parent and workers separately. The Copernicus model is a surface model (trees and buildings included). The exposure weight (1 - d/range) is a simple stand-in for the radar equation, and the aircraft is a point at a fixed height above ground.</p>
"""

story = fitz.Story(html=html, user_css=css, archive=fitz.Archive(str(FIG)))
tmp = os.path.join(tempfile.gettempdir(), "mid_report_nofooter.pdf")
w = fitz.DocumentWriter(tmp)
mb = fitz.paper_rect("a4")
where = mb + (48, 48, -48, -54)
more = 1
while more:
    dev = w.begin_page(mb); more, _ = story.place(where); story.draw(dev); w.end_page()
w.close()
doc = fitz.open(tmp)
n = len(doc)
for i, pg in enumerate(doc, 1):
    pg.insert_text((48, mb.height - 28), "Terrain visibility - mid-submission report", fontsize=7.5, color=(0.4, 0.4, 0.4))
    pg.insert_text((mb.width - 80, mb.height - 28), f"{i} / {n}", fontsize=7.5, color=(0.4, 0.4, 0.4))
doc.save(OUT, garbage=3, deflate=True)
print("wrote", OUT, n, "pages")
