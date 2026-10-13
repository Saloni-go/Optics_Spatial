// Builds presentation/Terrain_Visibility_Mid_Evaluation.pptx from the result figures.
// 15 mid-evaluation slides + backup sections (beyond 50%; Track 3 interactive planning after the mid-submission).
// Run:  node presentation/build_pptx.js   (needs `npm install` in presentation/ once)
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(process.env.PPTX_SKILL_THEME || path.join(__dirname, "apply_theme.js"));

const ROOT = path.resolve(__dirname, "..");
const R = (p) => path.join(ROOT, "results", p);
const OUT = path.join(__dirname, "Terrain_Visibility_Mid_Evaluation.pptx");

const THEME = {
  name: "Terrain Visibility",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "14213D", lt1: "FFFFFF", dk2: "3D4652", lt2: "EEF1F4",
    accent1: "B4472E", accent2: "1F7A6F", accent3: "2F5D7C", accent4: "E76F51",
    accent5: "2A9D8F", accent6: "F4A261", hlink: "2F5D7C", folHlink: "6B7280",
  },
};
const HEX = THEME.colors;
const MUTED = "6B7280";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5 in
pres.title = "Terrain Visibility - Mid Evaluation";
pres.author = "Person 1, Person 2, Person 3";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

// ---------------------------------------------------------------- layouts
const footer = (dark) => [
  { text: { text: "Terrain visibility · mid evaluation", options: { x: 0.6, y: 7.0, w: 6, h: 0.3, fontSize: 10, color: dark ? "CDD6E4" : MUTED, margin: 0 } } },
];
pres.defineSlideMaster({
  title: "CONTENT", background: { color: HEX.lt1 },
  objects: [...footer(false),
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.72, w: 12.1, h: 0.9, fontSize: 30, bold: true, color: C.text1, fontFace: THEME.headFontFace, valign: "top", align: "left", margin: 0 }, text: "" } }],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: MUTED, align: "right" },
});
pres.defineSlideMaster({
  title: "BACKUP", background: { color: HEX.lt2 },
  objects: [...footer(false),
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.72, w: 12.1, h: 0.9, fontSize: 30, bold: true, color: C.text1, fontFace: THEME.headFontFace, valign: "top", align: "left", margin: 0 }, text: "" } }],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: MUTED, align: "right" },
});
pres.defineSlideMaster({
  title: "DARK", background: { color: HEX.dk1 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.0, w: 11.7, h: 2.2, fontSize: 48, bold: true, color: C.background1, fontFace: THEME.headFontFace, valign: "bottom", align: "left", margin: 0 }, text: "" } }],
});

// ---------------------------------------------------------------- helpers
const T = (slide, text, o) => slide.addText(text, { isTextBox: true, margin: 0, fontSize: 16, color: C.text2, valign: "top", ...o });
const eyebrow = (slide, text, color) => T(slide, text.toUpperCase(), { x: 0.6, y: 0.35, w: 12.1, h: 0.3, fontSize: 13, bold: true, color, charSpacing: 2, objectName: "eyebrow" });
const img = (slide, file, x, y, w, h, alt) => slide.addImage({ path: R(file), x, y, w, h, sizing: { type: "contain", w, h }, altText: alt });
const stat = (slide, x, y, w, big, small, color) => {
  T(slide, big, { x, y, w, h: 0.75, fontSize: 40, bold: true, color, fontFace: THEME.headFontFace });
  T(slide, small, { x, y: y + 0.78, w, h: 0.6, fontSize: 14, color: C.text2 });
};
const card = (slide, x, y, w, h, head, body, accent) => {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: "F7F8FA" }, line: { color: "D9DEE5", width: 0.75 } });
  T(slide, head, { x: x + 0.25, y: y + 0.22, w: w - 0.5, h: 0.45, fontSize: 18, bold: true, color: accent || C.text1, fontFace: THEME.headFontFace });
  T(slide, body, { x: x + 0.25, y: y + 0.75, w: w - 0.5, h: h - 0.95, fontSize: 15 });
};
const table = (slide, rows, x, y, w, colW, o = {}) => {
  const head = rows[0].map((t) => ({ text: t, options: { bold: true, fill: { color: "E3E8EF" }, color: HEX.dk1 } }));
  const body = rows.slice(1).map((r, i) => r.map((t) => ({ text: t, options: { fill: { color: (o.hl || []).includes(i) ? "E3EFE9" : "FFFFFF" } } })));
  slide.addTable([head, ...body], { x, y, w, colW, fontSize: o.fontSize || 14, fontFace: THEME.bodyFontFace, color: HEX.dk2,
    border: { type: "solid", pt: 0.75, color: "C9D0D9" }, margin: 0.06, valign: "middle" });
};
let section = "";
const add = (master, sec) => { if (sec !== section) { pres.addSection({ title: sec }); section = sec; } return pres.addSlide({ masterName: master, sectionTitle: sec }); };

// ================================================================ INTRO
let s = add("DARK", "Introduction");
T(s, "SPATIAL INFORMATICS · MID EVALUATION", { x: 0.8, y: 0.7, w: 11, h: 0.4, fontSize: 14, bold: true, color: HEX.accent6, charSpacing: 3 });
s.addText("Large-Scale Terrain Data Analysis 2", { placeholder: "title" });
T(s, "Radar visibility, flight-route visibility and optimal visibility corridors over the Garhwal Himalaya",
  { x: 0.8, y: 4.4, w: 10.5, h: 0.9, fontSize: 22, color: "CDD6E4" });
T(s, [{ text: "Track 1 ", options: { bold: true, color: "FFFFFF" } }, { text: "Person 1      " },
      { text: "Track 2 ", options: { bold: true, color: "FFFFFF" } }, { text: "Person 2      " },
      { text: "Track 3 ", options: { bold: true, color: "FFFFFF" } }, { text: "Person 3" }],
  { x: 0.8, y: 6.4, w: 11, h: 0.4, fontSize: 16, color: "CDD6E4" });
s.addNotes("Three team members, three terrain-visibility applications on one shared set of DEMs. The question across all three: how does the computational cost grow with terrain size and problem parameters, and which implementation choices help.");

s = add("CONTENT", "Introduction");
s.addText("One terrain, three visibility problems", { placeholder: "title" });
const tr = [["TRACK 1 · PERSON 1", "Radar visibility", "Which terrain can a stationary radar see?", "Varies: DEM size, range, mast height, number of radars", HEX.accent1],
            ["TRACK 2 · PERSON 2", "Flight-route visibility", "What does an aircraft see along its route, and what does it miss?", "Varies: DEM size, sample spacing, altitude, radius, route length", HEX.accent2],
            ["TRACK 3 · PERSON 3", "Visibility corridor", "Which route keeps an aircraft hidden from the radars without a big detour?", "Varies: graph size, exposure weight, solver, trip length", HEX.accent3]];
tr.forEach(([eb, h, q, v, col], i) => {
  const x = 0.6 + i * 4.1;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.9, w: 3.85, h: 4.3, rectRadius: 0.08, fill: { color: "F7F8FA" }, line: { color: "D9DEE5", width: 0.75 } });
  s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: 2.2, w: 0.5, h: 0.5, fill: { color: col } });
  T(s, String(i + 1), { x: x + 0.3, y: 2.2, w: 0.5, h: 0.5, fontSize: 18, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
  T(s, eb, { x: x + 0.3, y: 2.9, w: 3.3, h: 0.3, fontSize: 12, bold: true, color: col, charSpacing: 1 });
  T(s, h, { x: x + 0.3, y: 3.25, w: 3.3, h: 0.5, fontSize: 22, bold: true, color: C.text1, fontFace: THEME.headFontFace });
  T(s, q, { x: x + 0.3, y: 3.85, w: 3.3, h: 1.0, fontSize: 16 });
  T(s, v, { x: x + 0.3, y: 5.0, w: 3.3, h: 0.9, fontSize: 14, color: MUTED });
});
T(s, "Each track runs on its own; they share data and conventions, the radar sites (Track 1 → 3) and the route endpoints (Track 2 → 3).", { x: 0.6, y: 6.45, w: 12.1, h: 0.4, fontSize: 14, color: MUTED });
s.addNotes("Each person owns all six phases for their track. Comparisons are made within a track; the three tracks do different work, so raw runtimes across tracks are not an algorithm contest.");

s = add("CONTENT", "Introduction");
s.addText("Shared data: Garhwal Himalaya", { placeholder: "title" });
img(s, "shared/qgis_dem.png", 0.6, 1.75, 5.0, 5.0, "Shaded relief of the 120 by 120 km DEM, rendered in QGIS");
T(s, "Copernicus GLO-30 DSM, UTM 44N (EPSG:32644), 30 m cells. Four square DEMs centred on Rudraprayag: coverage grows, resolution stays fixed.", { x: 6.0, y: 1.8, w: 6.7, h: 1.0, fontSize: 16 });
table(s, [["DEM", "cells", "extent", "elevation range"], ["500 × 500", "0.25 M", "15 km", "594–2,856 m"], ["1000 × 1000", "1 M", "30 km", "547–3,022 m"],
          ["2000 × 2000", "4 M", "60 km", "485–4,480 m"], ["4000 × 4000", "16 M", "120 km", "315–7,074 m"]], 6.0, 3.0, 6.7, [1.8, 1.4, 1.4, 2.1]);
T(s, "Plus flat, ridge, valley and cone synthetic terrains with known answers.", { x: 6.0, y: 5.8, w: 6.7, h: 0.5, fontSize: 15 });
s.addNotes("Growing the extent at a fixed 30 m resolution is a clean size-scaling experiment, but bigger DEMs also reach the high Himalaya, so terrain gets more rugged with size.");

s = add("CONTENT", "Introduction");
s.addText("How we measure", { placeholder: "title" });
table(s, [["Dimension", "Method"],
  ["Execution time", "Median of 5 runs, each in a fresh process; compute (algorithm only) kept apart from DEM reading"],
  ["Peak memory", "Peak working set of the process (Python + NumPy + GDAL alone is about 60 MB)"],
  ["Scalability", "DEM 500 → 4000 cells per side (0.25 M → 16 M cells), same 30 m cells, plus track parameters"],
  ["Complexity", "Slope of log(time) vs log(size), compared with the theoretical big-O"],
  ["Visualisation", "QGIS load and render time at 1600 × 1600 px, full extent and zoomed, with and without pyramids"],
  ["Accuracy", "Synthetic terrains with known answers, an exact reference, and agreement / kappa / Jaccard / cost gap"]],
  0.6, 1.95, 12.1, [2.6, 9.5], { fontSize: 18 });
T(s, "AMD Ryzen 9 7900X (12 cores), 31 GB RAM, Windows 11 · QGIS 3.44.12, GDAL 3.13.1, Python 3.12, NumPy 2.4 · every raw run kept in CSV",
  { x: 0.6, y: 6.35, w: 12.1, h: 0.4, fontSize: 13, color: MUTED });
s.addNotes("Each benchmark run is a new Python process so memory from an earlier run does not leak into the next. Slowest baselines run 1 to 3 times and are extrapolated with the fitted exponent.");

// ================================================================ TRACK 1
s = add("CONTENT", "Track 1: radar visibility");
eyebrow(s, "Track 1 · Radar visibility", HEX.accent1);
s.addText("Three ways to compute a viewshed", { placeholder: "title" });
table(s, [["Algorithm", "Idea", "Cost", "Role"],
  ["Naive line of sight", "Sample the profile to every cell every half cell; blocked if anything rises above the sight line", "O(N·√N)", "exact reference"],
  ["R2 ray casting", "One ray to each boundary cell, each keeps a running horizon (our NumPy code)", "O(N)", "own fast method"],
  ["GDAL viewshed", "C++ reference-plane algorithm (Wang et al.)", "O(N)", "production engine"]], 0.6, 1.9, 12.1, [2.6, 6.3, 1.4, 1.8], { fontSize: 15 });
card(s, 0.6, 4.6, 12.1, 1.6, "Same model for all three",
  "Radar on a 30 m mast; a cell is visible if its surface (or an aircraft 150 m above it) is in line of sight; Earth curvature with refraction k = 1/7; output 1 visible / 0 blocked / 255 out of range.", HEX.accent1);
s.addNotes("All three share one interface (radar/viewshed.py) so the benchmark can swap them. The naive method is slow but exact, so it is our truth for accuracy.");

s = add("CONTENT", "Track 1: radar visibility");
eyebrow(s, "Track 1 · Validation", HEX.accent1);
s.addText("All three agree with the exact answer", { placeholder: "title" });
table(s, [["Test", "Naive", "R2", "GDAL"], ["Flat plane: all visible", "100%", "100%", "100%"], ["V valley: all visible", "100%", "100%", "100%"],
  ["200 m wall: hidden behind", "100%", "100%", "100%"], ["Real DEM, agreement with exact", "ref.", "99.7%", "99.8%"], ["Kappa vs exact", "ref.", "0.957", "0.965"]],
  0.6, 1.85, 6.4, [3.1, 1.1, 1.1, 1.1], { fontSize: 14 });
T(s, "The few mismatches sit on grazing ridge edges. A bug caught by the valley test: the first R2 scored 84.7% because it tested the cell centre against a horizon built from interpolated ray points; testing the ray point itself fixed it.",
  { x: 7.4, y: 1.9, w: 5.3, h: 2.4, fontSize: 16 });
img(s, "radar/fig_algorithm_comparison.png", 0.6, 4.75, 12.1, 2.1, "Viewsheds by naive LOS, R2 and GDAL, and where GDAL differs from the exact answer");
s.addNotes("Synthetic terrains have analytical answers; on the real 500 x 500 DEM the exact line-of-sight method is the reference. Kappa corrects agreement for chance, which matters because most cells are hidden.");

s = add("CONTENT", "Track 1: radar visibility");
eyebrow(s, "Track 1 · Scenario", HEX.accent1);
s.addText("Six ridge-top radars see one sixth of the ground", { placeholder: "title" });
img(s, "radar/fig_coverage_six_radars.png", 0.6, 1.75, 8.9, 4.6, "Ground cells visible and aircraft detectable, coloured by number of radars");
stat(s, 9.9, 2.0, 2.8, "16.7%", "of the ground visible to at least one radar", HEX.accent1);
stat(s, 9.9, 3.7, 2.8, "35.6%", "where an aircraft 150 m up would be seen", HEX.dk1);
T(s, "Each radar sees 4–14% of the ground within its 40 km range.", { x: 9.9, y: 5.4, w: 2.8, h: 0.9, fontSize: 15 });
T(s, "Sites: highest point within 3 km, 1,500–3,200 m, at least 22 km apart · 30 m masts · 40 km range", { x: 0.6, y: 6.45, w: 12.1, h: 0.35, fontSize: 13, color: MUTED });
s.addNotes("Deep valleys hide most of the terrain even from ridge tops. The aircraft layer is what Track 3 tries to avoid.");

s = add("CONTENT", "Track 1: radar visibility");
eyebrow(s, "Track 1 · Scaling (E1)", HEX.accent1);
s.addText("Exact costs N^1.5; the fast methods stay linear", { placeholder: "title" });
img(s, "radar/fig_bench_size.png", 0.6, 1.8, 8.6, 4.4, "Compute time and memory against DEM cells for naive, R2 and GDAL");
stat(s, 9.6, 2.0, 3.1, "~68 min", "exact method, 16 M cells (projected)", HEX.accent1);
stat(s, 9.6, 3.6, 3.1, "0.10 s", "GDAL, same DEM, 99.8% agreement", HEX.accent2);
T(s, "Fitted slopes: naive 1.54, R2 0.97, GDAL 0.79 (theory 1.5, 1, 1).", { x: 9.6, y: 5.2, w: 3.1, h: 0.9, fontSize: 15 });
T(s, "Radar at the DEM centre, unlimited range · median of 5 runs (naive: 3) · GDAL peak memory 68 → 242 MB", { x: 0.6, y: 6.45, w: 12.1, h: 0.35, fontSize: 13, color: MUTED });
s.addNotes("Naive ran on 0.25 M and 1 M cells (6.6 s and 56 s); beyond that we extrapolate with its fitted slope. GDAL's slope is under 1 because fixed overheads dominate the smallest DEMs.");

// ================================================================ TRACK 2
s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Flight-route visibility", HEX.accent2);
s.addText("A moving observer = many viewsheds, aggregated", { placeholder: "title" });
[["1 · Route", "166 km up the Alaknanda valley, Devprayag → Joshimath: least-elevation path between the towns"],
 ["2 · Altitude", "Terrain following 300 m above a smoothed ground, or a constant 5,500 m cruise"],
 ["3 · Sample", "A position every 1 km (167), a viewshed within a 20 km sensor radius at each"],
 ["4 · Aggregate", "Times seen per cell, first position that sees it, new area per position, blind spots"]]
  .forEach(([h, b], i) => card(s, 0.6 + i * 3.075, 1.85, 2.85, 2.35, h, b, HEX.accent2));
img(s, "flight/fig_altitude_profile.png", 0.6, 4.4, 12.1, 2.35, "Terrain profile under the route with the two flight altitude profiles");
s.addNotes("The altitude profile is computed once at 100 m spacing and interpolated, so coarse and dense sampling fly exactly the same path; that makes the comparison of sampling densities fair. Same GDAL engine and curvature model as Track 1.");

s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Scenario", HEX.accent2);
s.addText("Valley flying sees a quarter of the corridor", { placeholder: "title" });
img(s, "flight/fig_cumulative_visibility.png", 0.6, 1.75, 8.9, 4.6, "Cells seen along the route and blind spots, for valley flying and cruise");
stat(s, 9.9, 2.0, 2.8, "26%", "of the corridor seen at 300 m above ground (1,537 km²)", HEX.accent2);
stat(s, 9.9, 3.7, 2.8, "79%", "seen cruising at 5,500 m (4,732 km²)", HEX.accent1);
T(s, "167 viewsheds in about 4.5 s.", { x: 9.9, y: 5.4, w: 2.8, h: 0.5, fontSize: 15 });
T(s, "Corridor = 6,024 km² within 20 km of the route · blue = blind spots (in the corridor, never seen)", { x: 0.6, y: 6.45, w: 12.1, h: 0.35, fontSize: 13, color: MUTED });
s.addNotes("The valley walls hide almost everything beyond the first ridge from a low aircraft: good for staying hidden, bad for surveillance. That trade-off is what Track 3 optimises.");

s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Scaling (F1)", HEX.accent2);
s.addText("Cost = positions × cells per viewshed", { placeholder: "title" });
img(s, "flight/fig_bench_size.png", 0.6, 1.8, 8.6, 4.4, "Compute time and memory against DEM cells for a growing route and a fixed route");
T(s, [{ text: "Route and radius grow with the DEM: ", options: { bold: true, color: HEX.accent1 } },
      { text: "13 → 97 positions, each covering the whole DEM; 0.07 → 18.8 s, slope 1.35 (theory 1.5)." }], { x: 9.6, y: 2.0, w: 3.1, h: 2.0, fontSize: 16 });
T(s, [{ text: "Fixed 12 km route, 20 km radius: ", options: { bold: true, color: HEX.accent2 } },
      { text: "0.07 → 0.31 s, flat once the DEM is bigger than the radius." }], { x: 9.6, y: 4.2, w: 3.1, h: 1.6, fontSize: 16 });
T(s, "Median of 5 runs (3 at 16 M cells) · 1 km spacing · peak memory 71 → 356 MB", { x: 0.6, y: 6.45, w: 12.1, h: 0.35, fontSize: 13, color: MUTED });
s.addNotes("DEM size alone does not drive the cost; the number of positions and the area each viewshed covers do.");

// ================================================================ TRACK 3
s = add("CONTENT", "Track 3: visibility corridor");
eyebrow(s, "Track 3 · Optimal visibility corridor", HEX.accent3);
s.addText("Stay hidden from the radars, without a big detour", { placeholder: "title" });
T(s, [{ text: "Exposure ", options: { bold: true, color: HEX.dk1 } },
      { text: "of an aircraft 150 m above each cell: sum over the six Track 1 radars that can see it of (1 − distance / 40 km)." }],
  { x: 0.6, y: 1.9, w: 6.0, h: 1.1, fontSize: 16 });
s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 3.15, w: 6.0, h: 0.85, rectRadius: 0.08, fill: { color: "F7F8FA" }, line: { color: "D9DEE5", width: 0.75 } });
T(s, "c(u,v) = L · (1 + α · mean exposure) + β · climb", { x: 0.8, y: 3.15, w: 5.6, h: 0.85, fontSize: 17, bold: true, color: C.text1, fontFace: THEME.headFontFace, valign: "middle" });
T(s, "8-connected 30 m grid. α trades exposure for distance; β = 2 penalises climbing; ground + 150 m above a 5,000 m ceiling is blocked. α = β = 0 is the shortest path.",
  { x: 0.6, y: 4.2, w: 6.0, h: 1.6, fontSize: 16 });
table(s, [["Solver", "Notes"], ["Dijkstra (Python)", "binary heap, stops at goal; baseline"],
  ["A* (Python)", "straight-line distance + β·height still to climb: admissible and consistent"],
  ["Dijkstra (SciPy, C)", "explicit sparse graph, build timed"], ["Multi-resolution", "4× coarser search, then A* in a buffer around it; approximate"]],
  7.0, 1.9, 5.7, [2.0, 3.7], { fontSize: 14 });
s.addNotes("We chose visibility OF the aircraft FROM ground radars, so Track 3 reuses Track 1's radar sites and engine. All exact solvers return identical costs at every size.");

s = add("CONTENT", "Track 3: visibility corridor");
eyebrow(s, "Track 3 · Scenario", HEX.accent3);
s.addText("30% longer, 93% less exposure", { placeholder: "title" });
img(s, "corridor/fig_routes.png", 0.6, 1.7, 5.3, 5.1, "Radar exposure with the shortest route and least-exposure routes");
table(s, [["Devprayag → Joshimath", "length", "exposed", "exposure"], ["Shortest (α = 0)", "131 km", "39%", "31.5"], ["Track 2 valley route", "178 km", "26%", "26.5"],
  ["α = 3", "139 km", "14%", "8.1"], ["α = 10", "170 km", "3%", "2.2"], ["α = 100", "216 km", "1%", "0.5"]], 6.3, 1.9, 6.4, [2.8, 1.2, 1.2, 1.2], { fontSize: 15, hl: [3] });
T(s, "A* and Dijkstra return the identical optimum (234,906 cost units). Exposed = share of the route visible to at least one radar.", { x: 6.3, y: 5.0, w: 6.4, h: 1.0, fontSize: 15 });
s.addNotes("Exposure = segment length times weighted exposure, in km. The shortest route is an L because on an 8-connected grid many paths tie on length. Beyond alpha 30 the route only gets longer: diminishing returns.");

s = add("CONTENT", "Track 3: visibility corridor");
eyebrow(s, "Track 3 · Scaling (C1)", HEX.accent3);
s.addText("C is 8× faster, but needs 9× the memory", { placeholder: "title" });
img(s, "corridor/fig_bench_size.png", 0.6, 1.7, 12.1, 3.5, "Search time, peak memory and cost above optimum against graph nodes for four solvers");
table(s, [["16 M nodes", "Dijkstra (Python)", "A* (Python)", "SciPy (C)", "Multi-resolution"], ["Time · peak memory", "70.2 s · 683 MB", "55.0 s · 685 MB", "9.0 s · 6.0 GB", "3.0 s · 863 MB"],
  ["Cost above optimum", "0", "0", "0", "1.4%"]], 0.6, 5.4, 12.1, [2.9, 2.3, 2.3, 2.3, 2.3], { fontSize: 15 });
s.addNotes("All exact solvers scale close to linearly (slopes 1.04 to 1.12, theory N log N). The C solver needs the whole graph as a sparse matrix: 128 M edges.");

// ================================================================ STATUS
s = add("CONTENT", "Status");
s.addText("Where we are", { placeholder: "title" });
table(s, [["Phase", "Track 1", "Track 2", "Track 3"], ["0 · Shared data and protocol", "done", "done", "done"], ["1 · Research and design", "done", "done", "done"],
  ["2 · Implementation + checks", "done", "done", "done"], ["3 · Visualisation (maps, QGIS)", "done", "done", "done"], ["4a · Scaling vs DEM size", "E1 done", "F1 done", "C1 done"],
  ["4b · Parameter studies", "range, height, radars", "spacing, altitude, radius", "α, trip length"], ["5 · Optimisations", "clipping, threads, resolution", "caching, threads, sampling", "landmark A*, C, multi-res"],
  ["6 · Analysis, rendering, report", "final", "final", "final"]], 0.6, 1.85, 12.1, [3.4, 2.9, 2.9, 2.9], { fontSize: 17, hl: [0, 1, 2, 3, 4] });
T(s, "Green rows = this mid-submission (about 50%). The rest is planned for the final; first results are in the backup slides.", { x: 0.6, y: 6.2, w: 12.1, h: 0.5, fontSize: 16 });
s.addNotes("Mid-submission scope: phases 0 to 3 and the first scaling benchmark for every track. Phases 4b, 5 and 6 are the second half.");

// ================================================================ BACKUP
s = add("DARK", "Backup: beyond the mid-submission");
T(s, "BACKUP · BEYOND THE MID-SUBMISSION", { x: 0.8, y: 1.4, w: 11, h: 0.4, fontSize: 14, bold: true, color: HEX.accent6, charSpacing: 3 });
s.addText("Parameter studies, optimisations and rendering", { placeholder: "title" });
T(s, "Already run; shown only if asked. These belong to the final submission.", { x: 0.8, y: 4.5, w: 11, h: 0.6, fontSize: 20, color: "CDD6E4" });
s.addNotes("Skip these in the mid presentation unless the evaluators ask what comes next.");

s = add("BACKUP", "Backup: beyond the mid-submission");
eyebrow(s, "Backup · Track 1 optimisations", HEX.accent1);
s.addText("Read less, and use threads, not processes", { placeholder: "title" });
img(s, "radar/fig_bench_clipping.png", 0.6, 1.75, 5.95, 2.6, "Runtime and memory against range for full and window reads");
img(s, "radar/fig_bench_radars.png", 6.75, 1.75, 5.95, 2.6, "Compute time and memory against number of radars: sequential, processes, threads");
table(s, [["Optimisation (DEM 4000)", "Result", "Cost"], ["Read only the range window", "10 km: 0.35 → 0.05 s, 242 → 73 MB", "none; identical output"],
  ["12 threads, many radars", "16 radars: 1.68 → 0.40 s (4.2×); wins from 2 radars", "~0.5 GB, windows held together"],
  ["8 processes (first try)", "slower up to 8 radars; 1.4× at 16", "~0.8 s start-up, 1.2 GB"],
  ["Coarser DEM (60/90/120 m)", "compute 0.10 → 0.03 / 0.016 / 0.010 s", "kappa 0.90 / 0.83 / 0.78"]], 0.6, 4.55, 12.1, [3.2, 5.1, 3.8], { fontSize: 14 });
s.addNotes("On Windows each worker process starts from scratch and re-imports NumPy and GDAL (about 0.8 s) and copies results back. GDAL releases Python's lock inside the viewshed, so threads run in parallel with neither cost. Range: compute time slope 1.38 (GDAL) and 1.12 (R2). Mast height changes coverage, not cost.");

s = add("BACKUP", "Backup: beyond the mid-submission");
eyebrow(s, "Backup · Track 2 optimisations", HEX.accent2);
s.addText("8× faster with threads; spacing should follow altitude", { placeholder: "title" });
img(s, "flight/fig_bench_optimise.png", 0.6, 1.75, 5.95, 2.9, "Compute time for baseline, cached, window, processes, threads and adaptive modes");
img(s, "flight/fig_spacing_study.png", 6.75, 1.75, 5.95, 2.9, "Coverage against number of positions for fixed and adaptive sampling at two altitudes");
T(s, [{ text: "Speed: ", options: { bold: true, color: HEX.dk1 } },
      { text: "333 viewsheds on the 166 km route take 17.7 s re-reading the DEM, 6.5 s cached, 4.3 s with 8 processes and " },
      { text: "2.1 s with 12 threads", options: { bold: true, color: HEX.accent2 } }, { text: " (identical result)." }], { x: 0.6, y: 4.9, w: 5.95, h: 1.5, fontSize: 16 });
T(s, [{ text: "Sampling: ", options: { bold: true, color: HEX.dk1 } },
      { text: "adaptive refinement never beat fixed spacing. The real lever is altitude: at cruise, 4 km spacing keeps 97.5% of the coverage with 43 viewsheds; valley flying needs 500 m (333)." }],
  { x: 6.75, y: 4.9, w: 5.95, h: 1.5, fontSize: 16 });
s.addNotes("Adaptive v1 refined where neighbouring viewsheds look different; in a winding valley they always do (621 positions). v2 refines only where the midpoint sees new ground: 251 positions at 94.7% overlap, still on or below the fixed-spacing curve. Coverage grows smoothly along the route, so uniform spacing is already efficient.");

s = add("BACKUP", "Backup: beyond the mid-submission");
eyebrow(s, "Backup · Track 3 optimisations", HEX.accent3);
s.addText("Fixing A*: a heuristic that knows about the radars", { placeholder: "title" });
img(s, "corridor/fig_bench_alpha.png", 0.6, 1.75, 6.6, 2.75, "Nodes expanded against alpha for plain A*, landmark A* and Dijkstra");
T(s, [{ text: "Problem: ", options: { bold: true, color: HEX.dk1 } },
      { text: "straight-line distance assumes 1 cost unit per metre; exposed metres cost 5–17. The guess is far too low, so A* searched 64–86% of the map." }],
  { x: 7.5, y: 1.85, w: 5.2, h: 1.3, fontSize: 16 });
T(s, [{ text: "Fix (ALT): ", options: { bold: true, color: HEX.dk1 } },
      { text: "exact costs to 4 landmarks, precomputed once; the triangle inequality gives a much tighter guess that is still admissible." }],
  { x: 7.5, y: 3.2, w: 5.2, h: 1.2, fontSize: 16 });
table(s, [["Same optimal route", "Plain A*", "Landmark A*", "C Dijkstra"], ["4 M nodes, α = 1–100", "2.6–3.4 M nodes, 8–12 s", "0.14–0.58 M, 0.8–2.0 s", "all 4 M, 1.7–1.9 s"],
  ["16 M nodes, scenario", "14.3 M nodes, 67 s", "4.6 M, 22 s (+37 s once)", "all, 9 s · 6 GB"]], 0.6, 4.75, 12.1, [3.1, 3.0, 3.0, 3.0], { fontSize: 15 });
s.addNotes("Landmark A* returns the same cost as Dijkstra in every case and searches 3.5 to 15% of the nodes, yet in Python it only matches the C Dijkstra per route (8 routes on 16 M nodes: 6.1 s vs 4.4 s each) because Python costs far more per node. Next step: the same algorithm in compiled code. Multi-resolution stays the fastest approximate option (16 M nodes: k = 4, 2.1 s, 1.4% above optimum).");

// ================================================================ BACKUP: TRACK 3 INTERACTIVE PLANNING (after the mid-submission)
const IXJ = (n) => JSON.parse(require("fs").readFileSync(R(`corridor/interactive/${n}.json`)));
const EXJ = (n) => JSON.parse(require("fs").readFileSync(R(`corridor/extensions/${n}.json`)));
const SEC3 = "Backup: Track 3 interactive planning";
const x1 = Object.fromEntries(IXJ("e1_ladder").rows.map((r) => [r.strategy, r]));
const x8 = EXJ("e8_parallel"), x9 = EXJ("e9_csp"), x10 = EXJ("e10_tiles"), x11 = EXJ("e11_altitude"), x12 = EXJ("e12_placement");
const sc4 = x8.scaling.find((r) => r.size === 4000);
const thr = Object.entries(sc4.threads).map(([k, v]) => [Number(k), v.s]).sort((a, b) => a[1] - b[1])[0];
const f1 = (v) => v.toFixed(1), f2 = (v) => v.toFixed(2), f0 = (v) => Math.round(v).toLocaleString("en-US");
const pc = (v) => `${(100 * v).toFixed(0)}%`;

s = add("DARK", SEC3);
T(s, "BACKUP · TRACK 3 AFTER THE MID-SUBMISSION", { x: 0.8, y: 1.4, w: 11, h: 0.4, fontSize: 14, bold: true, color: HEX.accent6, charSpacing: 3 });
s.addText("Interactive planning: what to precompute, what to compute on the fly", { placeholder: "title" });
T(s, "Precompute vs on-the-fly, smooth pan / zoom / edits, what to do when precompute stops being valid, and extensions of the corridor model.",
  { x: 0.8, y: 4.5, w: 11, h: 0.9, fontSize: 20, color: "CDD6E4" });
s.addNotes("This answers the question raised in our meeting with the professor. All numbers are on the 16 M-cell map unless stated; every route is checked against an exact search.");

s = add("BACKUP", SEC3);
eyebrow(s, "Track 3 · What to precompute", HEX.accent3);
s.addText("Precompute the field for the current goal", { placeholder: "title" });
img(s, "corridor/interactive/fig_e1_ladder.png", 0.6, 1.7, 7.0, 2.45, "Precompute against query time for each level, and total time after n clicks");
table(s, [["Level (16 M cells)", "Precompute", "New start", "New goal"],
  ["0 · C Dijkstra", "-", `${f0(x1["Dijkstra (C)"].query_fixed_goal_ms)} ms`, `${f0(x1["Dijkstra (C)"].query_any_pair_ms)} ms`],
  ["1 · 4 landmarks (ALT)", `${f1(x1["ALT, 4 landmarks (C)"].pre_s)} s · ${f0(x1["ALT, 4 landmarks (C)"].mem_mb)} MB`, `${f0(x1["ALT, 4 landmarks (C)"].query_fixed_goal_ms)} ms`, `${f0(x1["ALT, 4 landmarks (C)"].query_any_pair_ms)} ms`],
  ["2 · cost-to-go field", `${f2(thr[1])} s · ${f0(x1["Level 2 cost-to-go field (C)"].mem_mb)} MB`, `${f2(x1["Level 2 cost-to-go field (C)"].query_fixed_goal_ms)} ms`, "new field"]],
  0.6, 4.4, 7.0, [2.4, 2.0, 1.3, 1.3], { fontSize: 13, hl: [2] });
T(s, [{ text: "Cost-to-go field: ", options: { bold: true, color: HEX.dk1 } },
      { text: "for every cell, the cost of the best route to the goal and the next step. One backward search builds it; then a route from any start is a lookup: exact, no search." }],
  { x: 8.0, y: 1.8, w: 4.7, h: 2.0, fontSize: 16 });
T(s, [{ text: "Landmarks ", options: { bold: true, color: HEX.dk1 } },
      { text: "when the goal changes often; 4 is the sweet spot (8 doubles memory for ~10% faster queries)." }], { x: 8.0, y: 4.0, w: 4.7, h: 1.2, fontSize: 16 });
T(s, "All solvers in C on the implicit grid (corridor/c/gridsearch.c); every route identical to the exact optimum.", { x: 0.6, y: 6.45, w: 12.1, h: 0.35, fontSize: 13, color: MUTED });
s.addNotes("Level 0 = no precompute; level 1 = landmarks for any start and goal; level 2 = a cost-to-go field per goal. The field pays off from the second click.");

s = add("BACKUP", SEC3);
eyebrow(s, "Track 3 · 12 cores for one field", HEX.accent3);
s.addText(`Field rebuild: ${f2(sc4.dijkstra_s)} s → ${f2(thr[1])} s, exact`, { placeholder: "title" });
img(s, "corridor/extensions/fig_e8_parallel.png", 0.6, 1.7, 12.1, 3.6, "Speed-up against threads, bucket width trade-off, repair against parallel rebuild");
T(s, [{ text: "Delta-stepping: ", options: { bold: true, color: HEX.dk1 } },
      { text: `relax a whole bucket of similar-cost nodes in parallel; lock-free atomic minimum keeps it exact. ${f1(sc4.dijkstra_s / thr[1])}× on ${thr[0]} threads. ` },
      { text: "Lesson: ", options: { bold: true, color: HEX.accent1 } },
      { text: "the MinGW OpenMP barrier sleeps between phases (slower than 1 core); a spinning barrier fixed it." }],
  { x: 0.6, y: 5.45, w: 12.1, h: 1.0, fontSize: 16 });
T(s, "With 12 cores a full rebuild (~0.4 s) beats incremental repair (0.9-3.9 s) after every radar edit measured.", { x: 0.6, y: 6.45, w: 12.1, h: 0.35, fontSize: 13, color: MUTED });
s.addNotes("Meyer and Sanders 2003. Next-step pointers are set in a final parallel pass from the final costs, so racing writers cannot leave them inconsistent.");

s = add("BACKUP", SEC3);
eyebrow(s, "Track 3 · When precompute stops being valid", HEX.accent3);
s.addText("Changing α: answer now, exact soon", { placeholder: "title" });
img(s, "corridor/interactive/fig_e2_anytime.png", 0.6, 1.7, 6.0, 3.6, "Cost above optimum against time for coarse-to-fine and weighted A*");
img(s, "corridor/extensions/fig_e7_bank.png", 6.75, 1.7, 5.95, 2.1, "Alpha bank: cost of nearest banked route, and bank build cost");
T(s, [{ text: "α bank: ", options: { bold: true, color: HEX.dk1 } },
      { text: "next-step fields for α = 2, 5, 10, 20, 50 (305 MB, 1.9 s on 12 cores). Banked α: exact route in ~1 ms; in between: nearest banked route, ≤1.2% above on average." }],
  { x: 6.75, y: 3.95, w: 5.95, h: 1.4, fontSize: 15 });
T(s, [{ text: "Coarse-to-fine anytime: ", options: { bold: true, color: HEX.dk1 } },
      { text: "16× and 4× coarser grids, then full resolution in a corridor, then the exact field: first route in ~10 ms, within 0.2% at ~0.5 s. Weighted A* lost at every quality level." }],
  { x: 0.6, y: 5.5, w: 12.1, h: 0.95, fontSize: 15 });
s.addNotes("The pyramid stores exposure and height, not costs, so it stays valid when alpha changes; the field and landmarks do not.");

s = add("BACKUP", SEC3);
eyebrow(s, "Track 3 · Edits, pan and zoom", HEX.accent3);
s.addText("Recompute only what an edit invalidates", { placeholder: "title" });
img(s, "corridor/interactive/fig_e3_incremental.png", 0.6, 1.7, 6.6, 2.4, "Incremental against from-scratch time for radar edits, and start moves");
img(s, "corridor/interactive/fig_e4_lod.png", 0.6, 4.2, 6.6, 2.4, "Pan and zoom latency and on-screen error");
card(s, 7.5, 1.75, 5.2, 1.5, "Start moved", "Field lookup 0.1 ms vs 2.7 s Dijkstra. D* Lite often needs no work, but the lookup is simpler.", HEX.accent3);
card(s, 7.5, 3.4, 5.2, 1.5, "Radar dragged", "Recompute that radar's viewshed window (~0.2 s), then rebuild the field in parallel (~0.4 s). Exact.", HEX.accent3);
card(s, 7.5, 5.05, 5.2, 1.5, "Pan / zoom", "Never search: draw the known route (0.03 ms). Re-solving each view: 30-240 ms and often the wrong valley.", HEX.accent3);
s.addNotes("A radar reaches 40 km, so an edit changes many routes: dynamic shortest-path repair and D* Lite are exact but often no faster than a rebuild. A route is a global object: solving the visible window separately gives inconsistent pieces.");

s = add("BACKUP", SEC3);
eyebrow(s, "Track 3 · Latency budget", HEX.accent3);
s.addText("Every interaction within a frame or under a second", { placeholder: "title" });
table(s, [["Interaction (16 M cells)", "Strategy", "Latency"],
  ["Click a new start", "field lookup", "0.1 ms"], ["α slider, banked value", "α bank lookup", "~1 ms"],
  ["α slider, other value", "nearest bank route → corridor → exact field", "1 ms / 0.5 s / 0.35 s"],
  ["Drag a radar", "one viewshed window + parallel field rebuild", "~0.6 s"],
  ["New goal", "landmark A* now, field in the background", "0.27 s"], ["Pan / zoom", "draw the known route", "0.03 ms"]],
  0.6, 1.85, 7.3, [2.3, 3.6, 1.4], { fontSize: 14 });
img(s, "corridor/interactive/demo_last.png", 8.2, 1.7, 4.5, 4.9, "Interactive viewer after a scripted session");
T(s, "Viewer: run.bat -m corridor.interactive · scripted demo GIF: --demo", { x: 0.6, y: 6.45, w: 12.1, h: 0.35, fontSize: 13, color: MUTED });
s.addNotes("The viewer logs, for every action, which level answered it and how long it took. Click = start, right click = goal, drag = move a radar, +/- = alpha, b = risk budget.");

const sc9 = x9.scenario.filter((r) => r.p_detect != null);
s = add("BACKUP", SEC3);
eyebrow(s, "Track 3 · Detection probability", HEX.accent3);
s.addText("A risk budget with a certificate", { placeholder: "title" });
img(s, "corridor/interactive/fig_e5_detection.png", 0.6, 1.7, 5.4, 3.2, "Detection probability against length, and risk-budget answers");
img(s, "corridor/extensions/fig_e9_csp.png", 6.2, 1.7, 6.5, 2.3, "Exact search closes the gap on 1 M cells; time and certified gap on 16 M cells");
T(s, [{ text: "Model: ", options: { bold: true, color: HEX.dk1 } },
      { text: "each radar that sees the aircraft detects it with p(d) per km; P(detected) = 1 − exp(−Σ length·hazard) is additive, so all solvers apply." }],
  { x: 6.2, y: 4.15, w: 6.5, h: 1.0, fontSize: 15 });
T(s, [{ text: "Shortest route with P(detect) ≤ p: ", options: { bold: true, color: HEX.dk1 } },
      { text: `LARAC (Lagrangian) in ${f1(Math.min(...sc9.map((r) => r.larac_s)))}-${f1(Math.max(...sc9.map((r) => r.larac_s)))} s instead of ~25 s bisection, then an exact label search in a corridor. ` },
      { text: `≤ 25%: ${f0(sc9[sc9.length - 1].length_km)} km (bisection: 261 km), certified within ${f1(sc9[sc9.length - 1].gap_pct)}%.`, options: { bold: true, color: HEX.accent3 } }],
  { x: 0.6, y: 5.25, w: 12.1, h: 1.1, fontSize: 15 });
T(s, "Exact on 1 M cells (corridor answer = whole-map optimum); on 16 M cells the gap is certified, not always closed.", { x: 0.6, y: 6.45, w: 12.1, h: 0.35, fontSize: 13, color: MUTED });
s.addNotes("Resource-constrained shortest path is NP-hard. The Lagrangian lower bound certifies how far the answer can be from the best possible length. Monte Carlo with 200,000 simulated flights per route matches the formula.");

s = add("BACKUP", SEC3);
eyebrow(s, "Track 3 · Extensions", HEX.accent3);
s.addText("Tile overlay and a radar-placement game", { placeholder: "title" });
img(s, "corridor/extensions/fig_e10_tiles.png", 0.6, 1.7, 6.0, 2.1, "Tile overlay accuracy and update time");
img(s, "corridor/extensions/fig_e12_placement.png", 6.75, 1.7, 5.95, 2.6, "Placement game scores and radar sites with attacker routes");
const tv = x10.variants.find((r) => r.valleys === 10) || x10.variants[0];
T(s, [{ text: "Tile overlay (CRP idea): ", options: { bold: true, color: HEX.dk1 } },
      { text: `costs between border portals of 250×250 tiles; any start and goal in ~${f0(tv.query_ms)} ms, ${f1(tv.gap_mean)}% above exact. Portals at valley floors cut the error several-fold. A radar edit recomputes only the tiles it touches (${x10.updates[x10.updates.length - 1].tiles}-${x10.updates[0].tiles} of 256).` }],
  { x: 0.6, y: 4.0, w: 6.0, h: 2.3, fontSize: 15 });
T(s, [{ text: "Placement: ", options: { bold: true, color: HEX.dk1 } },
      { text: `defender places radars, attacker flies the safest route (one field per reply, ${x12.evals} replies). Routing-aware greedy: 2 radars force ${pc(x12.greedy.curve[1])} detection; coverage greedy: ${pc(x12.coverage.curve[1])}.` }],
  { x: 6.75, y: 4.45, w: 5.95, h: 1.9, fontSize: 15 });
s.addNotes("Delling et al. 2011 customizable route planning: the partition never changes, only tile costs are recomputed. Placing radars for routes beats placing them for coverage.");

const fx150 = x11.fixed.find((r) => r.agl === 150), fr0 = x11.runs.find((r) => r.gamma_scale === 0), t4 = x11.timing[x11.timing.length - 1];
s = add("BACKUP", SEC3);
eyebrow(s, "Track 3 · Extensions", HEX.accent3);
s.addText("Altitude as a decision; robustness checks", { placeholder: "title" });
img(s, "corridor/extensions/fig_e11_altitude.png", 0.6, 1.7, 6.3, 3.2, "Free-altitude route coloured by height and height use per setting");
img(s, "corridor/extensions/fig_e15_montecarlo.png", 7.1, 1.7, 5.6, 2.0, "Monte Carlo check and sensitivity to model parameters");
img(s, "corridor/extensions/fig_e14_alternatives.png", 7.1, 3.8, 5.6, 2.5, "Alternative corridors: via-node and penalty methods");
T(s, [{ text: "3-D search ", options: { bold: true, color: HEX.dk1 } },
      { text: `over 4 heights × cells (64 M nodes, ${f0(t4.s)} s): free height cuts P(detect) from ${pc(fx150.p_detect)} (fixed 150 m) to ${pc(fr0.p_detect)} on the 60 km map.` }],
  { x: 0.6, y: 5.05, w: 6.3, h: 1.3, fontSize: 15 });
T(s, "Also: uncertain radar positions (plan on mean or pessimistic threat), alternative corridors, Monte Carlo = formula; wrong radar range costs up to 14%.", { x: 0.6, y: 6.45, w: 12.1, h: 0.35, fontSize: 13, color: MUTED });
s.addNotes("Each flight level has its own viewsheds and ceiling; flying low has a per-km penalty, otherwise the answer is always to hug the ground.");


s = add("BACKUP", "Backup: across the tracks");
eyebrow(s, "Backup · Visualisation performance", MUTED);
s.addText("QGIS cost follows the screen, not the raster", { placeholder: "title" });
img(s, "shared/fig_render_benchmark.png", 0.6, 1.75, 12.1, 3.6, "QGIS render time against raster cells for three storage formats and three views");
T(s, "Plain or pyramided rasters draw in 55–80 ms at any size. Compressed, tiled GeoTIFFs without pyramids grow to 0.27 s at full extent (every tile is decompressed), and to 20 s if GDAL's cache is starved to 1 MB. Build pyramids for compressed outputs.",
  { x: 0.6, y: 5.55, w: 12.1, h: 1.2, fontSize: 16 });
s.addNotes("Each render opens a fresh layer, so GDAL's block cache is cold; the operating-system file cache stays warm. Algorithm time and render time are measured separately.");

s = add("BACKUP", "Backup: across the tracks");
eyebrow(s, "Backup · Across the tracks", MUTED);
s.addText("Three workloads, three different cost drivers", { placeholder: "title" });
table(s, [["Track", "Unit of work", "Grows with", "16 M cells", "Best lever"],
  ["1 Radar", "one viewshed", "cells in range (~R²)", "0.10 s, 242 MB", "read only the window; threads"],
  ["2 Flight", "one viewshed per position", "positions × radius²", "18.8 s (97 positions)", "threads; spacing per altitude"],
  ["3 Corridor", "graph search + exposure", "nodes (N log N)", "9–70 s, 0.7–6 GB", "C code, landmark A*, multi-res"]], 0.6, 1.95, 12.1, [1.7, 2.7, 2.4, 2.4, 2.9], { fontSize: 18 });
T(s, "Raw runtimes across tracks are not a fair contest: the tracks do different amounts of work. The comparisons that matter are within a track (sizes, baselines, optimisations); across tracks we compare what drives the cost.",
  { x: 0.6, y: 5.35, w: 12.1, h: 1.2, fontSize: 18 });
s.addNotes("Track 2 is many Track 1 problems; Track 3 adds a graph search on top of Track 1's viewsheds. Memory is set by the DEM in Tracks 1 and 2, but by the explicit graph in Track 3's C solver.");

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
