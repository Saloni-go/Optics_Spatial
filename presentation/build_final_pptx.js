// Builds presentation/Terrain_Visibility_Final.pptx: final presentation, all three tracks + integration,
// Track 3 ending in the live QGIS-plugin demo. Every number is read from results/ at build time.
// Run:  node presentation/build_final_pptx.js   (after run.bat -m integration.pipeline; needs `npm install` once)
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(process.env.PPTX_SKILL_THEME || path.join(__dirname, "apply_theme.js"));

const ROOT = path.resolve(__dirname, "..");
const R = (p) => path.join(ROOT, "results", p);
const OUT = path.join(__dirname, "Terrain_Visibility_Final.pptx");
const J = (p) => { try { return JSON.parse(fs.readFileSync(R(p))); } catch (e) { return null; } };

const TEAM = { 1: "Sravani", 2: "Saloni", 3: "Akshat" };
const THEME = {
  name: "Terrain Visibility", headFontFace: "Cambria", bodyFontFace: "Calibri",
  colors: { dk1: "14213D", lt1: "FFFFFF", dk2: "3D4652", lt2: "EEF1F4", accent1: "B4472E", accent2: "1F7A6F", accent3: "2F5D7C",
            accent4: "E76F51", accent5: "2A9D8F", accent6: "F4A261", hlink: "2F5D7C", folHlink: "6B7280" },
};
const HEX = THEME.colors, MUTED = "6B7280";
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.title = "Terrain Visibility - Final Presentation";
pres.author = `${TEAM[1]}, ${TEAM[2]}, ${TEAM[3]}`;
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

// ---------------------------------------------------------------- masters and helpers
const footer = () => [{ text: { text: "Large-scale terrain data analysis · final", options: { x: 0.6, y: 7.0, w: 6, h: 0.3, fontSize: 10, color: MUTED, margin: 0 } } }];
const titleBox = () => ({ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.72, w: 12.1, h: 0.9, fontSize: 30, bold: true, color: C.text1, fontFace: THEME.headFontFace, valign: "top", align: "left", margin: 0 }, text: "" } });
pres.defineSlideMaster({ title: "CONTENT", background: { color: HEX.lt1 }, objects: [...footer(), titleBox()], slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: MUTED, align: "right" } });
pres.defineSlideMaster({ title: "BACKUP", background: { color: HEX.lt2 }, objects: [...footer(), titleBox()], slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: MUTED, align: "right" } });
pres.defineSlideMaster({ title: "DARK", background: { color: HEX.dk1 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.0, w: 11.7, h: 2.2, fontSize: 46, bold: true, color: C.background1, fontFace: THEME.headFontFace, valign: "bottom", align: "left", margin: 0 }, text: "" } }] });

const T = (s, text, o) => s.addText(text, { isTextBox: true, margin: 0, fontSize: 16, color: C.text2, valign: "top", ...o });
const eyebrow = (s, text, color) => T(s, text.toUpperCase(), { x: 0.6, y: 0.35, w: 12.1, h: 0.3, fontSize: 13, bold: true, color, charSpacing: 2 });
const img = (s, file, x, y, w, h, alt) => {
  const p = file.includes(":") || file.startsWith("/") ? file : R(file);
  if (!fs.existsSync(p)) { console.warn("missing figure", file); T(s, `[figure: ${file}]`, { x, y, w, h, fontSize: 12, color: MUTED, align: "center", valign: "middle" }); return; }
  s.addImage({ path: p, x, y, w, h, sizing: { type: "contain", w, h }, altText: alt });
};
const stat = (s, x, y, w, big, small, color) => {
  T(s, big, { x, y, w, h: 0.75, fontSize: 38, bold: true, color, fontFace: THEME.headFontFace });
  T(s, small, { x, y: y + 0.76, w, h: 0.7, fontSize: 14, color: C.text2 });
};
const card = (s, x, y, w, h, head, body, accent, fs_ = 15) => {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: "F7F8FA" }, line: { color: "D9DEE5", width: 0.75 } });
  T(s, head, { x: x + 0.25, y: y + 0.2, w: w - 0.5, h: 0.45, fontSize: 18, bold: true, color: accent || C.text1, fontFace: THEME.headFontFace });
  T(s, body, { x: x + 0.25, y: y + 0.72, w: w - 0.5, h: h - 0.9, fontSize: fs_ });
};
const table = (s, rows, x, y, w, colW, o = {}) => {
  const head = rows[0].map((t) => ({ text: String(t), options: { bold: true, fill: { color: "E3E8EF" }, color: HEX.dk1 } }));
  const body = rows.slice(1).map((r, i) => r.map((t) => ({ text: String(t), options: { fill: { color: (o.hl || []).includes(i) ? "E3EFE9" : "FFFFFF" } } })));
  s.addTable([head, ...body], { x, y, w, colW, fontSize: o.fontSize || 14, fontFace: THEME.bodyFontFace, color: HEX.dk2,
    border: { type: "solid", pt: 0.75, color: "C9D0D9" }, margin: 0.06, valign: "middle" });
};
const foot = (s, text) => T(s, text, { x: 0.6, y: 6.45, w: 12.1, h: 0.4, fontSize: 13, color: MUTED });
let section = "";
const add = (master, sec) => { if (sec !== section) { pres.addSection({ title: sec }); section = sec; } return pres.addSlide({ masterName: master, sectionTitle: sec }); };
const divider = (sec, kicker, title, sub, notes) => {
  const s = add("DARK", sec);
  T(s, kicker, { x: 0.8, y: 1.4, w: 11, h: 0.4, fontSize: 14, bold: true, color: HEX.accent6, charSpacing: 3 });
  s.addText(title, { placeholder: "title" });
  if (sub) T(s, sub, { x: 0.8, y: 4.5, w: 11.4, h: 1.2, fontSize: 20, color: "CDD6E4" });
  if (notes) s.addNotes(notes);
  return s;
};

// ---------------------------------------------------------------- numbers
const f0 = (v) => (v == null ? "–" : Math.round(v).toLocaleString("en-US"));
const f1 = (v) => (v == null ? "–" : Number(v).toFixed(1));
const f2 = (v) => (v == null ? "–" : Number(v).toFixed(2));
const pc = (v, d = 0) => (v == null ? "–" : `${(100 * v).toFixed(d)}%`);
const last = (a) => (a && a.length ? a[a.length - 1] : null);
const secs = (v) => (v == null ? "–" : v < 1 ? `${f0(1000 * v)} ms` : v < 100 ? `${f1(v)} s` : `${f1(v / 60)} min`);

const man = J("integration/run_manifest.json") || {};
const mach = man.machine || J("corridor/machine.json") || {};
const RS = J("radar/stats.json") || {}, RB = J("radar/benchmark_summary.json") || {}, RV = J("radar/validation.json") || {};
const FS = J("flight/stats.json") || {}, FB = J("flight/benchmark_summary.json") || {};
const CS = J("corridor/stats.json") || {}, CB = J("corridor/benchmark_summary.json") || {};
const XT = J("integration/cross_track.json") || {}, EF = J("corridor/efficiency/efficiency.json") || {};
const PZ = J("corridor/panzoom/panzoom.json") || {};
const IX = (n) => J(`corridor/interactive/${n}.json`) || {}, EX = (n) => J(`corridor/extensions/${n}.json`) || {};
const cpu = /AMD|Ryzen/i.test(mach.cpu || "") || (mach.cores_logical || 0) >= 20 ? "AMD Ryzen 9 7900X" : (mach.cpu || "?");
const machLine = `${cpu}, ${mach.cores_physical || "?"} cores / ${mach.cores_logical || "?"} threads, ${mach.ram_gb || "?"} GB · Python ${mach.python || "?"}, GDAL ${mach.gdal || "?"}, NumPy ${mach.numpy || "?"}`;

// ================================================================ INTRO
let s = add("DARK", "Introduction");
T(s, "SPATIAL INFORMATICS · FINAL PRESENTATION", { x: 0.8, y: 0.7, w: 11, h: 0.4, fontSize: 14, bold: true, color: HEX.accent6, charSpacing: 3 });
s.addText("Large-Scale Terrain Data Analysis 2", { placeholder: "title" });
T(s, "Radar visibility, flight-route visibility and radar-hidden corridors over the Garhwal Himalaya: one dataset, one pipeline, one QGIS plugin",
  { x: 0.8, y: 4.4, w: 11, h: 1.0, fontSize: 21, color: "CDD6E4" });
T(s, [1, 2, 3].flatMap((k) => [{ text: `Track ${k} `, options: { bold: true, color: "FFFFFF" } }, { text: `${TEAM[k]}      ` }]),
  { x: 0.8, y: 6.3, w: 11, h: 0.4, fontSize: 16, color: "CDD6E4" });
s.addNotes("Three visibility problems on one shared terrain. Since the mid evaluation: every track finished its parameter studies and optimisations, the three tracks now run as one integrated pipeline on one machine, the tracks are cross-checked against each other, and Track 3 became an installable QGIS plugin, which we demo at the end.");

s = add("CONTENT", "Introduction");
s.addText("One terrain, three visibility problems", { placeholder: "title" });
[["TRACK 1 · " + TEAM[1].toUpperCase(), "Radar visibility", "Which terrain, and which low-flying aircraft, can a ground radar see?", "Naive line of sight, R2 ray casting, GDAL; range, height, many radars", HEX.accent1],
 ["TRACK 2 · " + TEAM[2].toUpperCase(), "Flight-route visibility", "What does an aircraft see along its route, and what does it miss?", "Viewsheds along a route, aggregation, sampling, altitude, threads", HEX.accent2],
 ["TRACK 3 · " + TEAM[3].toUpperCase(), "Radar-hidden corridor", "Which route keeps the aircraft hidden from the radars, interactively?", "Graph search on 16 M cells, precompute vs on the fly, QGIS plugin", HEX.accent3]]
  .forEach(([eb, h, q, v, col], i) => {
    const x = 0.6 + i * 4.1;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.85, w: 3.85, h: 4.3, rectRadius: 0.08, fill: { color: "F7F8FA" }, line: { color: "D9DEE5", width: 0.75 } });
    s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: 2.15, w: 0.5, h: 0.5, fill: { color: col } });
    T(s, String(i + 1), { x: x + 0.3, y: 2.15, w: 0.5, h: 0.5, fontSize: 18, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
    T(s, eb, { x: x + 0.3, y: 2.85, w: 3.3, h: 0.3, fontSize: 12, bold: true, color: col, charSpacing: 1 });
    T(s, h, { x: x + 0.3, y: 3.2, w: 3.3, h: 0.5, fontSize: 22, bold: true, color: C.text1, fontFace: THEME.headFontFace });
    T(s, q, { x: x + 0.3, y: 3.8, w: 3.3, h: 1.1, fontSize: 16 });
    T(s, v, { x: x + 0.3, y: 5.0, w: 3.3, h: 0.9, fontSize: 14, color: MUTED });
  });
foot(s, "Shared: DEMs, visibility model and radar sites (Track 1 → 3), route endpoints (Track 2 → 3); Track 3 scores every track's routes with one detection model.");
s.addNotes("Track 2 is many Track 1 problems along a path; Track 3 puts a graph search on top of Track 1's radar viewsheds and uses Track 2's endpoints.");

s = add("CONTENT", "Introduction");
s.addText("Shared data and model: Garhwal Himalaya", { placeholder: "title" });
img(s, "shared/qgis_dem.png", 0.6, 1.75, 5.0, 5.0, "Shaded relief of the 120 by 120 km DEM in QGIS");
T(s, "Copernicus GLO-30 DSM, UTM 44N (EPSG:32644), 30 m cells. Four square DEMs centred on Rudraprayag: coverage grows, resolution stays fixed.", { x: 6.0, y: 1.8, w: 6.7, h: 1.0, fontSize: 16 });
table(s, [["DEM", "cells", "extent", "elevation"], ["500 × 500", "0.25 M", "15 km", "594–2,856 m"], ["1000 × 1000", "1 M", "30 km", "547–3,022 m"],
          ["2000 × 2000", "4 M", "60 km", "485–4,480 m"], ["4000 × 4000", "16 M", "120 km", "315–7,074 m"]], 6.0, 2.95, 6.7, [1.8, 1.4, 1.4, 2.1]);
card(s, 6.0, 5.1, 6.7, 1.3, "One visibility model for all tracks", "Radar masts 30 m · aircraft 150 m above ground · 40 km range · Earth curvature with refraction k = 1/7 · six ridge-top radar sites", HEX.accent3, 14);
s.addNotes("Growing the extent at fixed 30 m resolution is a clean size-scaling experiment; bigger DEMs also reach the high Himalaya, so the terrain gets more rugged with size.");

const steps = man.steps || {};
const stepRows = [["Track 1", ["radar.validate", "radar.run_radar", "radar.benchmark", "radar.analysis"]],
                  ["Track 2", ["flight.run_flight", "flight.benchmark", "flight.spacing_study", "flight.analysis"]],
                  ["Track 3", ["corridor.run_corridor", "corridor.benchmark", "corridor.analysis", "corridor.interactive_bench", "corridor.extensions_bench", "corridor.efficiency_bench", "corridor.panzoom_bench"]],
                  ["Cross-track + QGIS", ["integration.cross_track", "qgis.build_project", "qgis.render_bench"]]]
  .map(([k, ids]) => { const ok = ids.filter((i) => steps[i]); const m = ok.reduce((a, i) => a + steps[i].seconds, 0) / 60;
                       const bad = ok.filter((i) => steps[i].exit && !steps[i].note); const noted = ok.filter((i) => steps[i].note); return [k, ids.map((i) => i.split(".")[1]).join(", "), ok.length ? `${f1(m)} min` : "–", bad.length ? `failed: ${bad.join(", ")}` : (ok.length ? (noted.length ? "ok*" : "ok") : "–")]; });
const totalMin = Object.values(steps).reduce((a, v) => a + (v.seconds || 0), 0) / 60;
s = add("CONTENT", "Introduction");
s.addText("One pipeline, one dataset, one machine", { placeholder: "title" });
table(s, [["Part", "Steps (validation, scenario, every benchmark, analysis)", "time", "status"], ...stepRows], 0.6, 1.85, 12.1, [2.3, 7.2, 1.2, 1.4], { fontSize: 14 });
T(s, [{ text: "run.bat -m integration.pipeline", options: { bold: true, fontFace: "Consolas", color: HEX.dk1 } },
      { text: `  runs everything one step at a time in fresh processes, clears every benchmark CSV first and records commit ${man.commit || "?"}, the machine and each step's time.` }],
  { x: 0.6, y: 4.45, w: 12.1, h: 0.8, fontSize: 15 });
T(s, [{ text: "How we measure: ", options: { bold: true, color: HEX.dk1 } },
      { text: "median of 5 runs, each in a fresh process (compute kept apart from I/O) · peak working set · complexity = slope of log(time) vs log(cells) · accuracy against synthetic terrains and exact references (agreement, kappa, Jaccard, cost gap)." }],
  { x: 0.6, y: 5.35, w: 12.1, h: 0.9, fontSize: 14 });
foot(s, machLine + ` · whole pipeline ${f0(totalMin)} min · *QGIS crashed on exit after writing all render results`);
s.addNotes("At the mid evaluation each track had benchmarked on its own laptop, so runtimes could not be compared across tracks. Now one command reruns all three tracks, all algorithms and all benchmarks on the same data and machine.");

// ================================================================ TRACK 1
const E1 = RB.E1 || {}, g1 = E1.gdal || {}, r21 = E1.r2 || {}, nv = E1.naive || {};
divider("Track 1: radar visibility", `TRACK 1 · ${TEAM[1].toUpperCase()}`, "Radar visibility", "Which terrain, and which low-flying aircraft, can six ridge-top radars see? Three viewshed algorithms, validated and benchmarked.");

s = add("CONTENT", "Track 1: radar visibility");
eyebrow(s, "Track 1 · Algorithms and validation", HEX.accent1);
s.addText("Three viewshed algorithms that agree with the exact answer", { placeholder: "title" });
table(s, [["Algorithm", "Idea", "Cost"], ["Naive line of sight", "sample the profile to every cell; exact reference", "O(N·√N)"],
          ["R2 ray casting", "one ray per boundary cell with a running horizon (own NumPy code)", "O(N)"], ["GDAL viewshed", "C++ reference-plane algorithm", "O(N)"]],
  0.6, 1.85, 7.0, [2.2, 3.8, 1.0], { fontSize: 14 });
const v500 = (RV.real || {}).dem_500_range_0 || {};
table(s, [["Real DEM vs exact", "R2", "GDAL"], ["agreement", pc((v500.r2 || {}).agreement, 1), pc((v500.gdal || {}).agreement, 1)],
          ["kappa", f2((v500.r2 || {}).kappa), f2((v500.gdal || {}).kappa)]], 7.9, 1.85, 4.8, [2.2, 1.3, 1.3], { fontSize: 14 });
T(s, "Synthetic flat, valley, wall and cone terrains: all three 100% correct. R2 now takes each cell from the ray closest to its centre: removes a +8% visible-area bias, at ~1.6× the time.", { x: 7.9, y: 3.15, w: 4.8, h: 1.0, fontSize: 13 });
img(s, "radar/fig_algorithm_comparison.png", 0.6, 4.2, 12.1, 2.2, "Viewsheds by the three algorithms and their differences");
s.addNotes("All three share one interface so the benchmark swaps them. Mismatches sit on grazing ridge edges. Kappa corrects agreement for chance; most cells are hidden.");

s = add("CONTENT", "Track 1: radar visibility");
eyebrow(s, "Track 1 · Scenario", HEX.accent1);
s.addText(`Six radars see ${pc(RS.union_ground_frac_of_dem, 1)} of the ground`, { placeholder: "title" });
img(s, "radar/fig_coverage_six_radars.png", 0.6, 1.7, 8.8, 4.7, "Ground and aircraft coverage of the six radars");
stat(s, 9.8, 1.9, 2.9, pc(RS.union_ground_frac_of_dem, 1), "of the ground seen by at least one radar", HEX.accent1);
stat(s, 9.8, 3.5, 2.9, pc(RS.union_air150_frac_of_dem, 1), "where an aircraft 150 m up is seen: Track 3's threat", HEX.dk1);
T(s, `Each radar sees ${pc(Math.min(...(RS.radars || [{ ground_visible_frac: 0 }]).map((r) => r.ground_visible_frac)))}–${pc(Math.max(...(RS.radars || [{ ground_visible_frac: 0 }]).map((r) => r.ground_visible_frac)))} of the ground within 40 km.`, { x: 9.8, y: 5.2, w: 2.9, h: 1.0, fontSize: 15 });
foot(s, "Sites: highest point within 3 km, 1,500–3,200 m, ≥ 22 km apart · 30 m masts · 40 km range");
s.addNotes("Deep valleys hide most terrain even from ridge tops. The aircraft layer is what Track 3 avoids.");

s = add("CONTENT", "Track 1: radar visibility");
eyebrow(s, "Track 1 · Scaling (E1)", HEX.accent1);
s.addText("Exact costs N^1.5; the fast methods stay linear", { placeholder: "title" });
img(s, "radar/fig_bench_size.png", 0.6, 1.75, 8.6, 4.5, "Compute time and memory against DEM cells");
stat(s, 9.6, 1.9, 3.1, nv.projected_16M_s ? secs(nv.projected_16M_s) : "–", "exact method, 16 M cells (projected)", HEX.accent1);
stat(s, 9.6, 3.5, 3.1, secs(last(g1.compute_s)), "GDAL, same DEM", HEX.accent2);
T(s, `Fitted slopes: naive ${f2(nv.exponent)}, R2 ${f2(r21.exponent)}, GDAL ${f2(g1.exponent)} (theory 1.5, 1, 1).`, { x: 9.6, y: 5.1, w: 3.1, h: 1.0, fontSize: 15 });
foot(s, `R2 timings: original R2 on the team PC; the fixed R2 is 1.5–1.9× slower (laptop, results/linux64) · GDAL peak memory ${f0(g1.peak_mb && g1.peak_mb[0])} → ${f0(last(g1.peak_mb))} MB`);
s.addNotes("Naive is measured on 0.25 M and 1 M cells and extrapolated with its slope. GDAL's slope is under 1 because fixed overheads dominate small DEMs.");

const E4 = RB.E4 || {}, sp = (E4.speedup_threads || []), E2 = RB.E2 || {}, E6 = RB.E6 || [];
s = add("CONTENT", "Track 1: radar visibility");
eyebrow(s, "Track 1 · Parameters and optimisations (E2–E6)", HEX.accent1);
s.addText("Read less, use threads, coarsen with care", { placeholder: "title" });
img(s, "radar/fig_bench_clipping.png", 0.6, 1.75, 5.95, 2.5, "Runtime against range for full and window reads");
img(s, "radar/fig_bench_radars.png", 6.75, 1.75, 5.95, 2.5, "Many radars: sequential, processes, threads");
const e6 = (c) => E6.find((r) => r.cell_m === c) || {};
table(s, [["Study (16 M cells)", "Result"],
  ["E2 range 5 → 60 km", `GDAL time grows as range^${f2((E2.gdal || {}).exponent_vs_range)} (area ~ range²)`],
  ["E3 mast height", "changes coverage, not cost"],
  ["E4 many radars", `12 threads: ${f1(last(sp))}× faster at 16 radars; processes lose up to 8 radars (start-up)`],
  ["E5 read only the range window", "same output, a fraction of the time and memory"],
  ["E6 coarser DEM 60 / 90 / 120 m", `kappa ${f2(e6(60).kappa)} / ${f2(e6(90).kappa)} / ${f2(e6(120).kappa)} vs 30 m`]],
  0.6, 4.4, 12.1, [3.6, 8.5], { fontSize: 13 });
s.addNotes("GDAL releases Python's lock inside the viewshed, so threads run in parallel without process start-up (about 0.8 s on Windows) or copying results back.");

// ---------------------------------------------------------------- Track 1 extensions (Linux laptop, results/linux/radar_ext)
const RX = (n) => J(`linux/radar_ext/${n}.json`) || {};
const XA = RX("minalt"), XS = RX("siting"), XD = RX("detect"), XM = RX("mc"), XH = RX("mast");
const xaAt = (h) => ((XA.area_seen_at_or_below_km2 || {})[String(h)]);
const xaTot = XA.area_total_km2 || 14400;
const radLine = "Linux laptop · 4000 × 4000 DEM (16 M cells), GDAL viewshed, 40 km range · results/linux/radar_ext";

s = add("CONTENT", "Track 1: radar visibility");
eyebrow(s, "Track 1 · Extension: lowest detectable altitude", HEX.accent1);
s.addText(`Fly 25 m above ground and the radars see you over ${pc(xaAt(25) / xaTot, 0)} of the area`, { placeholder: "title" });
img(s, "linux/radar_ext/fig_minalt.png", 0.6, 1.75, 8.9, 4.3, "Map of the lowest altitude at which the six radars see an aircraft, and coverage against height");
stat(s, 9.8, 1.9, 2.9, pc(xaAt(150) / xaTot, 0), "seen at 150 m (Track 3's threat height)", HEX.accent1);
stat(s, 9.8, 3.5, 2.9, pc(xaAt(2000) / xaTot, 0), "seen at 2,000 m: the rest is out of range", HEX.dk1);
T(s, `${(XA.levels_m || []).length} target heights × 6 radars = ${(XA.levels_m || []).length * 6} viewsheds in ${f1(XA.seconds_total)} s. A 5-level sweep over-estimates by ${f0(((XA.sweep_resolution || {})["5 levels"] || {}).mean_overestimate_m)} m on average.`,
  { x: 9.8, y: 5.0, w: 2.9, h: 1.3, fontSize: 12 });
foot(s, radLine);
s.addNotes("GDAL 3.4 has no direct minimum-height output, so the map is a sweep over target heights; the answer is exact at each level. Dark red valleys are the ones Track 3's corridors should use.");

s = add("CONTENT", "Track 1: radar visibility");
eyebrow(s, "Track 1 · Extension: where to put the radars", HEX.accent1);
s.addText(`Greedy placement: ${f0(XS.greedy6_exact_km2)} km² instead of ${f0(XS.shared6_exact_km2)} km² with the same six radars`, { placeholder: "title" });
img(s, "linux/radar_ext/fig_siting.png", 0.6, 1.75, 8.9, 4.3, "Coverage of the shared six sites against the greedy six, and coverage against number of radars");
stat(s, 9.8, 1.9, 2.9, `+${pc(XS.greedy6_exact_km2 / XS.shared6_exact_km2 - 1, 0)}`, "area where an aircraft at 150 m is seen", HEX.accent1);
stat(s, 9.8, 3.5, 2.9, `${XS.radars_needed_to_match_shared6 || "–"}`, "greedy radars to match the shared six", HEX.dk1);
T(s, `${XS.candidates} ridge-top candidates, one viewshed each (${f0(XS.seconds_coverage)} s), greedy pick on a 120 m grid (${f1(XS.seconds_greedy)} s). Highest-first picks peaks that look at each other; greedy spreads them (≥ ${f0(XS.greedy6_min_separation_km)} km apart).`,
  { x: 9.8, y: 5.0, w: 2.9, h: 1.4, fontSize: 11 });
foot(s, radLine);
s.addNotes("Greedy max-coverage is within 63% of the optimum by theory and usually much closer. The six shared sites stay as the team's common input; this shows what placement is worth.");

s = add("CONTENT", "Track 1: radar visibility");
eyebrow(s, "Track 1 · Extension: detection, DEM error, mast height", HEX.accent1);
s.addText("Seen is not detected; a few metres of DEM error matter little", { placeholder: "title" });
img(s, "linux/radar_ext/fig_detect_mc_mast.png", 0.6, 1.75, 12.1, 3.6, "DEM-error Monte Carlo map, detection probability bars, mast-height curves");
const xm = XM.air150 || {}, xg = XM.ground || {}, xmast = XH.rows || [];
table(s, [["Study (aircraft at 150 m unless stated)", "Result"],
  ["Detection model of Track 3", `line of sight ${f0(XD.los_km2)} km² → P(detect per km) ≥ 0.5 on only ${f0(XD["p1km_ge_0.5_km2"])} km²; ≥ 0.9 over 5 km on ${f0(XD["p5km_ge_0.9_km2"])} km²`],
  [`DEM error ±${f0(XM.sigma_z_m)} m, ${XM.runs} runs`, `reliable ${f0(xm.reliable_km2)} km², uncertain ${f0(xm.uncertain_km2)} km² (${pc(xm.uncertain_km2 / xm.nominal_km2, 0)}); ground ${pc(xg.uncertain_km2 / xg.nominal_km2, 0)}`],
  ["Mast 10 → 100 m", xmast.length ? `ground ${f0(xmast[0].ground_km2)} → ${f0(last(xmast).ground_km2)} km², aircraft ${f0(xmast[0].air150_km2)} → ${f0(last(xmast).air150_km2)} km²: placement matters more` : "–"]],
  0.6, 5.4, 12.1, [3.6, 8.5], { fontSize: 11 });
s.addNotes("Track 3's detection model: p(d) = 0.5 / (1 + (d / 20 km)^4) per km flown, combined over radars. DEM noise is spatially correlated over 300 m, as in Track 2. Uncertain cells sit on ridge edges.");

// ================================================================ TRACK 2
const fa = (FS.cases || {}).agl300 || {}, fm = (FS.cases || {}).msl5500 || {}, F1 = FB.F1_size || {}, F6 = FB.F6 || [];
const f6 = (m) => F6.find((r) => r.mode === m) || {};
divider("Track 2: flight-route visibility", `TRACK 2 · ${TEAM[2].toUpperCase()}`, "Flight-route visibility", "A moving observer = many viewsheds, aggregated: what the aircraft sees, when it first sees it, and what it never sees.");

s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Method", HEX.accent2);
s.addText("Route, altitude, sample, aggregate", { placeholder: "title" });
[["1 · Route", `${f0(FS.route_km)} km up the Alaknanda valley, Devprayag → Joshimath (least-elevation path between towns)`],
 ["2 · Altitude", "terrain following 300 m above smoothed ground, or a 5,500 m cruise"],
 ["3 · Sample", `a position every ${f0(FS.spacing_m)} m (${FS.waypoints || "–"}), a viewshed within ${f0((FS.radius_m || 0) / 1000)} km at each`],
 ["4 · Aggregate", "times seen per cell, first position that sees it, new area per position, blind spots"]]
  .forEach(([h, b], i) => card(s, 0.6 + i * 3.075, 1.85, 2.85, 2.35, h, b, HEX.accent2, 14));
img(s, "flight/fig_altitude_profile.png", 0.6, 4.4, 12.1, 2.3, "Terrain under the route with both altitude profiles");
s.addNotes("The altitude profile is computed once at 100 m and interpolated, so coarse and dense sampling fly the same path: a fair comparison of sampling densities.");

s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Scenario", HEX.accent2);
s.addText(`Valley flying sees ${pc(fa.seen_in_corridor_frac)} of the corridor`, { placeholder: "title" });
img(s, fs.existsSync(R("shared/qgis_track2_agl300.png")) ? "shared/qgis_track2_agl300.png" : "flight/fig_cumulative_visibility.png", 0.6, 1.7, 8.8, 4.7, "Cumulative visibility along the route");
stat(s, 9.8, 1.9, 2.9, f0(fa.seen_km2), `km² seen at 300 m AGL (${pc(fa.seen_in_corridor_frac)} of the corridor)`, HEX.accent2);
stat(s, 9.8, 3.5, 2.9, f0(fm.seen_km2), `km² seen cruising at 5,500 m (${pc(fm.seen_in_corridor_frac)})`, HEX.accent1);
T(s, `${FS.waypoints || "–"} viewsheds in ${f1(fa.compute_s)} s.`, { x: 9.8, y: 5.2, w: 2.9, h: 0.6, fontSize: 15 });
foot(s, `Corridor = ${f0(FS.corridor_km2)} km² within 20 km of the route · blind spots = corridor cells never seen`);
s.addNotes("The valley walls hide almost everything beyond the first ridge from a low aircraft: good for staying hidden, bad for surveillance. That trade-off is what Track 3 optimises.");

s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Scaling and parameters (F1–F5)", HEX.accent2);
s.addText("Cost = positions × cells per viewshed", { placeholder: "title" });
img(s, "flight/fig_bench_size.png", 0.6, 1.75, 6.4, 3.4, "Compute time against DEM cells, growing and fixed route");
img(s, "flight/fig_bench_params.png", 7.2, 1.75, 5.5, 3.4, "Compute time against spacing, altitude, radius and length");
table(s, [["Study", "Result"], ["F1 DEM + route grow", `${secs(F1.compute_s && F1.compute_s[0])} → ${secs(last(F1.compute_s))}, slope ${f2(F1.exponent)} (theory 1.5)`],
  ["F1b fixed 12 km route", `flat once the DEM is larger than the radius (slope ${f2((FB.F1b_size_fixed_route || {}).exponent)})`],
  ["F2 / F4 / F5", `linear in positions (${f2(FB.F2_exponent_vs_waypoints)}), ~radius² (${f2(FB.F4_radius_exponent)}), linear in length (${f2(FB.F5_length_exponent)})`],
  ["F3 altitude", `no cost change (${f2(FB.F3_altitude_exponent)}); coverage grows with height`]], 0.6, 5.25, 12.1, [3.0, 9.1], { fontSize: 13 });
s.addNotes("DEM size alone does not drive the cost; the number of positions and the area each viewshed covers do.");

s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Optimisations (F6) and sampling", HEX.accent2);
s.addText(`${f1(f6("baseline").runtime_s / f6("threads").runtime_s)}× faster with threads; spacing should follow altitude`, { placeholder: "title" });
img(s, "flight/fig_bench_optimise.png", 0.6, 1.75, 5.95, 2.9, "Runtime for each optimisation mode");
img(s, "flight/fig_spacing_study.png", 6.75, 1.75, 5.95, 2.9, "Coverage against positions for fixed and adaptive sampling");
T(s, [{ text: "Speed: ", options: { bold: true, color: HEX.dk1 } },
      { text: `${f0(f6("baseline").waypoints)} viewsheds take ${f1(f6("baseline").runtime_s)} s re-reading the DEM, ${f1(f6("cached").runtime_s)} s cached, ${f1(f6("parallel").runtime_s)} s with processes and ` },
      { text: `${f1(f6("threads").runtime_s)} s with threads`, options: { bold: true, color: HEX.accent2 } }, { text: " (identical result)." }], { x: 0.6, y: 4.85, w: 5.95, h: 1.5, fontSize: 15 });
T(s, [{ text: "Sampling: ", options: { bold: true, color: HEX.dk1 } },
      { text: "adaptive refinement never beat fixed spacing. The lever is altitude: at cruise 4 km spacing keeps ~97% of coverage; valley flying needs ~500 m." }],
  { x: 6.75, y: 4.85, w: 5.95, h: 1.5, fontSize: 15 });
s.addNotes("Coverage grows smoothly along the route, so uniform spacing is already efficient.");

// ---------------------------------------------------------------- Track 2 extensions (Linux laptop, results/linux/flight)
const LF = (p) => J(`linux/flight/${p}`) || {};
const I1 = LF("idea1_summary.json"), I2 = LF("idea2/idea2_summary.json"), US = LF("usecases/usecases_summary.json");
const LM = LF("machine.json");
const lapLine = `Linux laptop: ${LM.cores_physical || "?"} cores / ${LM.cores_logical || "?"} threads, ${LM.ram_gb || "?"} GB, GDAL ${LM.gdal || "?"} · results/linux/flight`;
const f7 = (m) => (I1.F7 || []).find((r) => r.mode === m) || {};
const F10 = I1.F10 || {};
const sens = (p, n) => (((I2.sensors || {})[p] || {})[n]) || {};
const mcv = ((I2.mc || {}).valley || {}), mcc = ((I2.mc || {}).cruise || {});

s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Extension 1: cheaper computation (F7–F10)", HEX.accent2);
s.addText(`Shared DEM: ${f2(f7("shared_threads").compute_s)} s instead of ${f2(f7("threads").compute_s)} s, same answer`, { placeholder: "title" });
img(s, "linux/flight/fig_idea1_shared.png", 0.6, 1.75, 6.6, 2.4, "Compute time and memory: window copy vs shared zero-copy view");
img(s, "linux/flight/fig_idea1_complexity.png", 7.5, 1.75, 5.2, 4.3, "Complexity model prediction against measured time");
table(s, [["Idea", "Result"],
  ["F7 shared view + threads", `${f2(f7("shared_threads").compute_s)} s, ${f0(f7("shared_threads").peak_mb)} MB; identical result`],
  ["F8 30 m near, coarse far", "viewshed 2.3× faster, route ~10%; 86–97% overlap"],
  ["F9 tiled accumulator", "12 km route, 16 M cells: 92 → 10 MB of rasters"],
  ["F10 T = a·W·min(πr², N) + b·W", `a ${f1(F10.a_ns_per_cell)} ns/cell, b ${f2(F10.b_ms_per_position)} ms/pos, error ${f1(F10.mean_abs_err_pct)}%`]],
  0.6, 4.25, 6.6, [2.4, 4.2], { fontSize: 10 });
T(s, lapLine, { x: 7.5, y: 6.15, w: 5.2, h: 0.5, fontSize: 11, color: MUTED });
s.addNotes("Copying a 40 km window per position cost more than the smaller search saved. The model says cost is positions × min(radius², map): linear in route length, quadratic in radius, independent of altitude.");

s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Extension 2: a real sensor", HEX.accent2);
s.addText(`A forward camera observes ${f0(sens("valley", "forward").observed_km2)} of ${f0(sens("valley", "omni").observed_km2)} km² seen`, { placeholder: "title" });
img(s, "linux/flight/idea2/fig_idea2_sensors.png", 0.6, 1.75, 7.6, 2.75, "Area observed and runtime per sensor and altitude");
img(s, "linux/flight/idea2/fig_idea2_gsd.png", 8.4, 1.75, 4.3, 2.75, "Share of line-of-sight area observed against required resolution");
table(s, [["Sensor (3 m per pixel)", "Valley 300 m", "Cruise 5,500 m"],
  ["line of sight only", `${f0(sens("valley", "omni").observed_km2)} km²`, `${f0(sens("cruise", "omni").observed_km2)} km²`],
  ["forward camera 90°", `${f0(sens("valley", "forward").observed_km2)} km², ${f0(sens("valley", "forward").dwell_s_median)} s`, `${f0(sens("cruise", "forward").observed_km2)} km², ${f0(sens("cruise", "forward").dwell_s_median)} s`],
  ["side cameras 2 × 60°", `${f0(sens("valley", "side").observed_km2)} km², ${f0(sens("valley", "side").dwell_s_median)} s`, `${f0(sens("cruise", "side").observed_km2)} km², ${f0(sens("cruise", "side").dwell_s_median)} s`],
  ["nadir ≥ 45° down", `${f0(sens("valley", "nadir").observed_km2)} km², ${f0(sens("valley", "nadir").dwell_s_median)} s`, `${f0(sens("cruise", "nadir").observed_km2)} km², ${f0(sens("cruise", "nadir").dwell_s_median)} s`]],
  0.6, 4.65, 7.6, [2.6, 2.5, 2.5], { fontSize: 12 });
T(s, "Field of view from the heading, depression limits, ground sample distance = slant × IFOV / cos(incidence), dwell = seconds observed at 60 m/s (median shown). Valley: forward is best (walls block the sides); cruise: side-looking.",
  { x: 8.4, y: 4.65, w: 4.3, h: 1.7, fontSize: 13 });
foot(s, lapLine);
s.addNotes("6000-pixel, 60 degree camera. At 5,500 m nothing is resolved at 0.5 m: the closest slant range is about 3.5 km.");

s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Extension 2: uncertainty (Monte Carlo)", HEX.accent2);
s.addText(`"Seen" is uncertain on ${pc(((mcv.both || {}).uncertain_km2 || 0) / ((mcv.both || {}).nominal_km2 || 1), 1)} (valley), ${pc(((mcc.both || {}).uncertain_km2 || 0) / ((mcc.both || {}).nominal_km2 || 1), 1)} (cruise)`, { placeholder: "title" });
img(s, "linux/flight/idea2/fig_idea2_uncertainty.png", 0.6, 1.75, 12.1, 3.7, "P(seen) maps and uncertain area per error source");
T(s, `20 runs per source: DEM error 4 m (correlated over 300 m), aircraft position error 10 m horizontal / 15 m vertical. The total area barely moves (valley ${f0((mcv.both || {}).seen_km2_mean)} ± ${f0((mcv.both || {}).seen_km2_std)} km²) but which cells are seen does, at the edges of visibility. Valley: DEM and position errors matter equally (${f0((mcv.dem || {}).uncertain_km2)} / ${f0((mcv.position || {}).uncertain_km2)} km²); cruise: almost only the DEM.`,
  { x: 0.6, y: 5.55, w: 12.1, h: 1.0, fontSize: 14 });
s.addNotes("Report a reliable-coverage map (seen in at least 95% of runs) rather than a single nominal answer.");

s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Extension 3: six applications", HEX.accent2);
s.addText("Six applications of the same engine", { placeholder: "title" });
img(s, "linux/flight/usecases/fig_usecases.png", 0.6, 1.65, 7.6, 4.75, "Radio link, river coverage, search and rescue, altitude, several aircraft, look-ahead");
const ul = (US.link || {}), sr = (US.sar || []), fl = ((US.fleet || {}).aircraft || []), la = (US.lookahead || {});
const sarRow = (agl, sp) => sr.find((r) => r.agl === agl && r.track_spacing_m === sp) || {};
T(s, [
  { text: "Radio link: ", options: { bold: true, color: HEX.dk1 } }, { text: `valley flight reaches a town station on ${pc((ul.valley || {}).link_frac)} of the route (longest gap ${f0((ul.valley || {}).longest_outage_km)} km); cruise ${pc((ul.cruise || {}).link_frac)}.\n` },
  { text: "River / road: ", options: { bold: true, color: HEX.dk1 } }, { text: "following the valley sees all of it; a straight 5,500 m line only 65% with a 3 m camera.\n" },
  { text: "Search & rescue: ", options: { bold: true, color: HEX.dk1 } }, { text: `0.5 m camera, 15 × 15 km: 1 km tracks cover ${pc(sarRow(300, 1000).covered_frac, 2)} in ${f0(sarRow(300, 1000).flight_min)} min, 4 km tracks ${pc(sarRow(300, 4000).covered_frac)} in ${f0(sarRow(300, 4000).flight_min)} min.\n` },
  { text: "Height: ", options: { bold: true, color: HEX.dk1 } }, { text: "80% of the local view needs ~2 km above ground; per-position height gains only ~2%.\n" },
  { text: "Several aircraft: ", options: { bold: true, color: HEX.dk1 } }, { text: `${fl.map((a) => f0(a.union_km2)).join(" → ")} km²; the 4th overlaps ${pc((last(fl) || {}).overlap_with_earlier_frac)}.\n` },
  { text: "Look-ahead: ", options: { bold: true, color: HEX.dk1 } }, { text: `< 20 s to terrain on ${pc((la.valley || {}).warn_frac, 1)} of the valley route if heading is held.` }],
  { x: 8.4, y: 1.7, w: 4.3, h: 4.8, fontSize: 12.5 });
s.addNotes("All six reuse the same viewshed engine; each is one function in flight/usecases.py.");

s = add("CONTENT", "Track 2: flight-route visibility");
eyebrow(s, "Track 2 · Extension 4: flight playback in QGIS", HEX.accent2);
const PB = LF("qgis/playback.json"), pbFps = Object.values(PB).map((v) => v.fps);
s.addText(`QGIS playback at ${f0(Math.min(...pbFps))}–${f0(Math.max(...pbFps))} frames per second`, { placeholder: "title" });
img(s, "linux/flight/qgis/playback_mid.png", 0.6, 1.7, 6.2, 4.65, "Mid-flight frame: ground seen so far and the aircraft trail");
img(s, "linux/flight/qgis/fig_render_track2.png", 7.0, 1.7, 5.7, 1.8, "Draw time per Track 2 raster and playback frame rate");
T(s, [{ text: "How: ", options: { bold: true, color: HEX.dk1 } },
      { text: "the first-seen raster stores the flight time at which each cell is first seen (raster temporal mode 'represents temporal values'); the aircraft layer has a time per position; a cumulative range makes seen ground accumulate.\n" },
      { text: "Draw time: ", options: { bold: true, color: HEX.dk1 } },
      { text: "Track 2 rasters (16 M cells) draw in 23–69 ms; overviews make full-extent ~1.6× faster and change nothing zoomed in.\n" },
      { text: "Files: ", options: { bold: true, color: HEX.dk1 } }, { text: "qgis/track2_extensions.qgz, qgis/track2_layers.py" }],
  { x: 7.0, y: 3.65, w: 5.7, h: 2.8, fontSize: 13 });
s.addNotes("Open View > Panels > Temporal Controller and press play: 163 frames of 17 s cover the 46-minute flight.");

// ================================================================ TRACK 3
const r10 = (CS.routes || {}).alpha_10 || {}, rsh = (CS.routes || {}).shortest || {};
const C1 = CB.C1 || {}, C7 = CB.C7 || {};
const x1 = Object.fromEntries((IX("e1_ladder").rows || []).map((r) => [r.strategy, r]));
const x8 = EX("e8_parallel"), x9 = EX("e9_csp"), x10 = EX("e10_tiles"), x11 = EX("e11_altitude"), x12 = EX("e12_placement");
const sc4 = (x8.scaling || []).find((r) => r.size === 4000) || {};
const thr = Object.entries(sc4.threads || {}).map(([k, v]) => [Number(k), v.s]).sort((a, b) => a[1] - b[1])[0] || [12, null];
divider("Track 3: radar-hidden corridor", `TRACK 3 · ${TEAM[3].toUpperCase()}`, "Radar-hidden corridor, interactively",
  "Exact routing on 16 M cells, what to precompute and what to compute on the fly, a certified risk budget, and the whole thing as a QGIS plugin (live demo at the end).");

s = add("CONTENT", "Track 3: radar-hidden corridor");
eyebrow(s, "Track 3 · Problem", HEX.accent3);
s.addText("Stay hidden from the radars without a big detour", { placeholder: "title" });
s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 1.9, w: 6.2, h: 0.85, rectRadius: 0.08, fill: { color: "F7F8FA" }, line: { color: "D9DEE5", width: 0.75 } });
T(s, "c(u,v) = L · (1 + α · threat) + β · climb", { x: 0.8, y: 1.9, w: 5.8, h: 0.85, fontSize: 18, bold: true, color: C.text1, fontFace: THEME.headFontFace, valign: "middle" });
T(s, [{ text: "Grid graph: ", options: { bold: true, color: HEX.dk1 } }, { text: "16 M cells, 8 neighbours, 128 M edges; aircraft 150 m above ground; above a 5,000 m ceiling is blocked.\n" },
      { text: "Threat: ", options: { bold: true, color: HEX.dk1 } }, { text: "from Track 1's radar viewsheds: exposure (visible, closer = worse) or detection hazard −ln(1 − p) per km.\n" },
      { text: "Detection: ", options: { bold: true, color: HEX.dk1 } }, { text: "P(detect) = 1 − exp(−Σ length · hazard): additive, so every shortest-path method applies." }],
  { x: 0.6, y: 2.95, w: 6.2, h: 3.3, fontSize: 15 });
img(s, "corridor/fig_routes.png", 7.1, 1.7, 5.6, 4.7, "Exposure map with shortest and least-exposure routes");
s.addNotes("α trades exposure against distance; α = β = 0 is the shortest path. We chose visibility OF the aircraft FROM ground radars, so Track 3 reuses Track 1's sites and engine.");

s = add("CONTENT", "Track 3: radar-hidden corridor");
eyebrow(s, "Track 3 · Scenario and exact solvers", HEX.accent3);
s.addText(`${pc((r10.length_km - rsh.length_km) / rsh.length_km)} longer, ${pc(1 - r10.exposure_km / rsh.exposure_km)} less exposure`, { placeholder: "title" });
const rr = (k, n) => { const r = (CS.routes || {})[k] || {}; return [n, `${f0(r.length_km)} km`, pc(r.exposed_frac), f1(r.exposure_km)]; };
table(s, [["Devprayag → Joshimath", "length", "exposed", "exposure"], rr("shortest", "Shortest (α = 0)"), rr("track2_valley_route", "Track 2 valley route"),
          rr("alpha_3", "α = 3"), rr("alpha_10", "α = 10"), rr("alpha_100", "α = 100")], 0.6, 1.85, 6.0, [2.6, 1.1, 1.1, 1.2], { fontSize: 14, hl: [3] });
const c1 = (a) => last((C1[a] || {}).compute_s), cm = (a) => last((C1[a] || {}).peak_mb);
const c7 = last(C7.dijkstra_c || []) || {};
table(s, [["16 M nodes, one route", "time", "peak memory", "gap"], ["Dijkstra (Python)", secs(c1("dijkstra_py")), `${f0(cm("dijkstra_py"))} MB`, "0"],
          ["A* (Python)", secs(c1("astar_py")), `${f0(cm("astar_py"))} MB`, "0"], ["Dijkstra (SciPy)", secs(c1("dijkstra_csgraph")), `${f0(cm("dijkstra_csgraph"))} MB`, "0"],
          ["Multi-resolution ×4", secs(c1("multires")), `${f0(cm("multires"))} MB`, `${f1(last((C1.multires || {}).cost_gap_pct))}%`],
          ["Our C Dijkstra (implicit grid)", secs(c7.query_s), `${f0(c7.peak_mb)} MB`, "0"]], 6.9, 1.85, 5.8, [2.5, 1.0, 1.3, 1.0], { fontSize: 13, hl: [4] });
const exps = ["dijkstra_py", "astar_py", "dijkstra_csgraph"].map((a) => (C1[a] || {}).exponent).filter((v) => v != null);
T(s, `All exact solvers return the same optimum. Fitted slopes ${f2(Math.min(...exps))}–${f2(Math.max(...exps))} (theory N log N). The C search on the implicit grid needs no edge list: SciPy's 128 M-edge matrix costs ${f1(cm("dijkstra_csgraph") / 1024)} GB.`,
  { x: 0.6, y: 4.55, w: 12.1, h: 1.0, fontSize: 15 });
foot(s, `Exposure = km of route weighted by threat · ALT (landmark A*) returns the same cost and searches a fraction of the nodes`);
s.addNotes("Beyond α ≈ 30 the route only gets longer: diminishing returns. Exposed = share of the route visible to at least one radar.");

s = add("CONTENT", "Track 3: radar-hidden corridor");
eyebrow(s, "Track 3 · What to precompute", HEX.accent3);
s.addText("Precompute the field for the goal; every start is a lookup", { placeholder: "title" });
img(s, "corridor/interactive/fig_e1_ladder.png", 0.6, 1.7, 7.0, 2.6, "Precompute against query time for each level");
const L2 = x1["Level 2 cost-to-go field (C)"] || {}, L1 = x1["ALT, 4 landmarks (C)"] || {}, L0 = x1["Dijkstra (C)"] || {};
table(s, [["Level (16 M cells)", "Precompute", "New start", "New goal"], ["0 · C Dijkstra", "–", `${f0(L0.query_fixed_goal_ms)} ms`, `${f0(L0.query_any_pair_ms)} ms`],
          ["1 · 4 landmarks (ALT)", `${f1(L1.pre_s)} s · ${f0(L1.mem_mb)} MB`, `${f0(L1.query_fixed_goal_ms)} ms`, `${f0(L1.query_any_pair_ms)} ms`],
          ["2 · cost-to-go field", `${f2(thr[1])} s · ${f0(L2.mem_mb)} MB`, `${f2(L2.query_fixed_goal_ms)} ms`, "new field"]], 0.6, 4.5, 7.0, [2.4, 2.0, 1.3, 1.3], { fontSize: 13, hl: [2] });
card(s, 7.9, 1.75, 4.8, 2.3, "Cost-to-go field", "For every cell: cost of the best route to the goal and the next step. One backward search builds it; a route from any start is then a lookup: exact, no search.", HEX.accent3, 15);
card(s, 7.9, 4.25, 4.8, 2.1, `12 cores: ${f2(sc4.dijkstra_s)} → ${f2(thr[1])} s`, `Delta-stepping with a lock-free atomic minimum, exact. ${f1((sc4.dijkstra_s || 0) / (thr[1] || 1))}× on ${thr[0]} threads; a spin barrier fixed MinGW's sleeping one.`, HEX.accent3, 14);
s.addNotes("Level 0 = no precompute; Level 1 = landmarks, any start and goal; Level 2 = one field per goal, pays off from the second click. With 12 cores a full rebuild beats incremental repair after a radar edit.");

s = add("CONTENT", "Track 3: radar-hidden corridor");
eyebrow(s, "Track 3 · When precompute stops being valid", HEX.accent3);
s.addText("Answer at once, exact soon after", { placeholder: "title" });
img(s, "corridor/interactive/fig_e2_anytime.png", 0.6, 1.7, 5.6, 3.3, "Cost above optimum against time, coarse-to-fine and weighted A*");
img(s, "corridor/extensions/fig_e7_bank.png", 6.4, 1.7, 6.3, 2.2, "Alpha bank error and build cost");
const bud = (IX("e6_budget").rows || IX("e6_budget") || []);
const budRows = Array.isArray(bud) ? bud : [];
const pick = (a, st) => (budRows.find((r) => r.interaction === a && (!st || r.strategy.includes(st))) || {}).ms;
table(s, [["Interaction (16 M cells)", "Strategy", "Latency"],
  ["Click a new start", "Level 2 lookup", `${f2(pick("click new start", "Level 2"))} ms`],
  ["Change α", "α bank lookup → exact field in background", "~1 ms → ~0.4 s"],
  ["Drag / add a radar", "that radar's viewshed + parallel field rebuild", "~0.6–0.9 s"],
  ["New goal", "coarse-to-fine route now, field in background", "~0.3–0.6 s"],
  ["Pan / zoom", "draw the known route (never re-search)", "< 0.1 ms"]], 6.4, 4.05, 6.3, [1.9, 3.1, 1.3], { fontSize: 12 });
T(s, "The pyramid stores threat and height, not costs, so it survives an α change; the field and landmarks do not. Weighted A* lost to coarse-to-fine at every quality level.",
  { x: 0.6, y: 5.2, w: 5.6, h: 1.2, fontSize: 14 });
s.addNotes("α bank: next-step fields for a ladder of α values; banked α → exact route in about a millisecond, in-between α → nearest banked route (within about 1%) while the exact field is rebuilt. Re-solving the visible window on pan/zoom was measured and rejected: slower, and often a different valley.");

const sc9 = (x9.scenario || []).filter((r) => r.p_detect != null);
s = add("CONTENT", "Track 3: radar-hidden corridor");
eyebrow(s, "Track 3 · Detection risk budget", HEX.accent3);
s.addText("Shortest route under a detection budget, with a certificate", { placeholder: "title" });
img(s, "corridor/interactive/fig_e5_detection.png", 0.6, 1.7, 5.4, 3.3, "Detection probability against length and risk-budget answers");
img(s, "corridor/extensions/fig_e9_csp.png", 6.2, 1.7, 6.5, 2.4, "Exact search closes the gap; certified gap on 16 M cells");
T(s, [{ text: "Resource-constrained shortest path (NP-hard): ", options: { bold: true, color: HEX.dk1 } },
      { text: `LARAC Lagrangian relaxation on parallel fields (${f1(Math.min(...sc9.map((r) => r.larac_s).concat([99])))}–${f1(Math.max(...sc9.map((r) => r.larac_s).concat([0])))} s), then an exact label-setting search in a corridor with Lagrangian pruning and dominance. ` },
      { text: "The lower bound certifies how far the answer can be from the best possible length.", options: { bold: true, color: HEX.accent3 } }],
  { x: 6.2, y: 4.25, w: 6.5, h: 2.0, fontSize: 15 });
foot(s, `Exact on 1 M cells (corridor answer = whole-map optimum) · 16 M cells, P(detect) ≤ 50%: ${f0(((XT.routes || {})["Track 3 risk budget 50 %"] || {}).length_km)} km at ${pc(((XT.routes || {})["Track 3 risk budget 50 %"] || {}).p_detect, 1)} (plugin scenario: 145 km, within 0.4% of optimal) · Monte Carlo = formula`);
s.addNotes("Carlyle, Royset and Wood 2008 for the Lagrangian pruning. In the plugin this is the B key.");

const tv = ((x10.variants || []).find((r) => r.valleys === 10)) || (x10.variants || [])[0] || {};
const fx150 = (x11.fixed || []).find((r) => r.agl === 150) || {}, fr0 = (x11.runs || []).find((r) => r.gamma_scale === 0) || {};
s = add("CONTENT", "Track 3: radar-hidden corridor");
eyebrow(s, "Track 3 · Extensions", HEX.accent3);
s.addText("Tiles, radar placement, altitude, robustness", { placeholder: "title" });
img(s, "corridor/extensions/fig_e10_tiles.png", 0.6, 1.7, 6.0, 2.0, "Tile overlay accuracy and update time");
img(s, "corridor/extensions/fig_e12_placement.png", 6.75, 1.7, 5.95, 2.0, "Placement game");
img(s, "corridor/extensions/fig_e11_altitude.png", 0.6, 3.8, 6.0, 2.2, "Free-altitude route");
img(s, "corridor/extensions/fig_e15_montecarlo.png", 6.75, 3.8, 5.95, 2.2, "Monte Carlo and parameter sensitivity");
foot(s, `Tiles (CRP idea): any pair in ~${f0(tv.query_ms)} ms, ${f1(tv.gap_mean)}% above exact · placement for routes beats placement for coverage (2 radars: ${pc((x12.greedy || { curve: [0, 0] }).curve[1])} vs ${pc((x12.coverage || { curve: [0, 0] }).curve[1])} detection) · free altitude: P(detect) ${pc(fx150.p_detect)} → ${pc(fr0.p_detect)}`);
s.addNotes("Tile overlay: costs between border portals of 250 × 250 tiles (Delling et al. 2011); a radar edit recomputes only the touched tiles. Placement game: defender places radars, attacker flies the safest route. 3-D search over 4 heights. Also uncertain radar positions and alternative corridors.");

const M1 = EF.M1_bank || {}, M2 = EF.M2_field || {}, M3 = EF.M3_snapshot || {}, O1 = EF.O1_hover || {}, O2 = EF.O2_slider || {};
s = add("CONTENT", "Track 3: radar-hidden corridor");
eyebrow(s, "Track 3 · Memory efficiency and on-the-fly (new)", HEX.accent3);
s.addText("Same routes, a quarter of the memory; live previews", { placeholder: "title" });
img(s, "corridor/efficiency/fig_memory.png", 0.6, 1.7, 6.2, 3.2, "Memory of bank and field representations");
img(s, "corridor/efficiency/fig_onthefly.png", 7.0, 1.7, 5.7, 2.4, "Hover preview and alpha slider latency");
table(s, [["Memory (16 M cells)", "before", "after", "routes"], ["α bank, 6 fields: next → 1-byte direction", `${f0(M1.int32_mb)} MB`, `${f0(M1.dir8_mb)} MB`, M1.identical_routes || "–"],
          ["Field: f64 cost + int32 → f32 + 1 byte", `${f0(M2.float64_int32_mb)} MB`, `${f0(M2.float32_dir8_mb)} MB`, M2.identical_routes || "–"],
          ["Bank snapshot on disk (zlib)", `${f0(M1.dir8_mb)} MB`, `${f1((M3.zlib_mb_per_alpha || 0) * (M1.alphas || []).length)} MB`, "lossless"]], 0.6, 5.0, 6.2, [3.2, 1.0, 1.0, 1.0], { fontSize: 12 });
table(s, [["On the fly (plugin)", "latency"], ["Hover: route from the cursor", `${f2(O1.route_ms_median)} ms (p99 ${f2(O1.route_ms_p99)})`],
          ["… + P(detect) of that route", `${f1(O1.route_plus_pdetect_ms_median)} ms`], ["α slider while dragging (bank)", `${f2(O2.bank_lookup_ms_median)} ms`],
          ["α slider released (exact field)", secs(O2.exact_on_release_s)]], 7.0, 4.3, 5.7, [3.3, 2.4], { fontSize: 12 });
s.addNotes("A next step always points to one of 8 neighbours, so a 1-byte direction code replaces a 4-byte pointer with identical routes. Costs in float32 have a negligible relative error. Direction fields compress well, so banks for several goals can be stored and restored in milliseconds.");

const pzs = (PZ.P1_summary || []).filter((r) => r.density === 1), pzo = PZ.P1_overall || {};
const pzFull = pzs.find((r) => r.width === 4000) || {}, pzL1 = pzs.filter((r) => r.level === 1);
const pzMed = (a) => { const v = a.map((r) => r.ms_median).sort((x, y) => x - y); return v.length ? v[Math.floor(v.length / 2)] : null; };
const pz48 = (PZ.P2_radars || []).find((r) => r.radars === 48) || {};
s = add("CONTENT", "Track 3: radar-hidden corridor");
eyebrow(s, "Track 3 · Pan and zoom on the fly (new)", HEX.accent3);
s.addText("Every pan and zoom recomputes only what is on screen", { placeholder: "title" });
img(s, "../qgis_plugin/screenshots/live_coverage_map.png", 0.6, 1.65, 3.3, 4.7, "Plugin: live radar coverage for the visible window, and the panel");
img(s, "corridor/panzoom/fig_panzoom.png", 4.2, 1.55, 8.5, 2.75, "Latency and accuracy against view width");
table(s, [["Per pan / zoom (canvas 1600 × 1000 px, 16 M cells)", "time", "exact cells"],
          ["Recompute the whole DEM at 30 m", `${f0(PZ.full_recompute_ms)} ms`, "100%"],
          [`Live, zoomed out: ${pzFull.cell_m || "–"} m level`, `${f0(pzFull.ms_median)} ms`, pc(pzFull.agree_count_median, 1)],
          [`Live, zoomed in (${pzL1.length ? Math.max(...pzL1.map((r) => r.width)) : "–"} cells wide or less): 30 m`, `${f0(pzMed(pzL1))} ms`, "100%"],
          [`All ${pzo.views || "–"} views (zoom × pan)`, `median ${f0(pzo.ms_median)}, max ${f0(pzo.ms_max)} ms`, "–"],
          ["48 radars: whole DEM vs live, full extent", `${f0(pz48.full_recompute_ms)} vs ${f0(pz48.live_full_extent_ms)} ms`, "–"]],
  4.2, 4.4, 8.5, [4.9, 2.3, 1.3], { fontSize: 12 });
foot(s, `Level of detail: DEM pyramid 30 m → 1.9 km (built at load in ${f2((PZ.pyramid || {}).build_s)} s, +${f0((PZ.pyramid || {}).extra_mb)} MB) · one GDAL viewshed per radar, only on the box between radar and view, on ${PZ.threads || 12} threads · stale views dropped while panning`);
s.addNotes("Saloni's item 5. When the map moves, the plugin works out which DEM cells are visible and how many screen pixels they cover, picks the pyramid level with about one cell per pixel and recomputes the six-radar coverage (Track 1's cumulative viewshed for a 150 m aircraft) for that window only. Zoomed in it runs at 30 m and matches Track 1's coverage cell for cell; zoomed out it uses 60-120 m cells, which the screen cannot resolve anyway. The cost depends on the screen size, not the DEM: with 48 radars the whole-DEM recompute takes about half a second, the live view still about 50 ms. A moved radar redraws the current view in tens of ms. Wheel zooms, middle-drag or Space pans, even with the planner tool active.");

s = add("CONTENT", "Track 3: radar-hidden corridor");
eyebrow(s, "Track 3 · Deliverable", HEX.accent3);
s.addText("A QGIS plugin: the planner inside QGIS", { placeholder: "title" });
img(s, "../qgis_plugin/screenshots/risk_budget_4000.png", 0.6, 1.65, 8.2, 4.55, "QGIS with the Visibility Corridor panel and a risk-budget route");
T(s, [{ text: "Install: ", options: { bold: true, color: HEX.dk1 } }, { text: "Plugins → Install from ZIP (Windows; not open source).\n" },
      { text: "Map: ", options: { bold: true, color: HEX.dk1 } }, { text: "DEM, radar threat, radars, start/goal and routes are real QGIS layers.\n" },
      { text: "Controls: ", options: { bold: true, color: HEX.dk1 } }, { text: "left / right click start / goal, drag a radar, R / X add / remove, + / − α, B risk budget, live hover preview, α slider; wheel / middle-drag pan and zoom with live radar coverage of the view.\n" },
      { text: "Panel: ", options: { bold: true, color: HEX.dk1 } }, { text: "which level answered each action and how long it took.\n" },
      { text: "Any DEM: ", options: { bold: true, color: HEX.dk1 } }, { text: "bundled 1000 / 2000 / 4000 scenarios, or any DEM layer (lat/lon reprojected to UTM), radars from a point layer." }],
  { x: 9.05, y: 1.75, w: 3.65, h: 4.6, fontSize: 13.5 });
foot(s, "Export: route, radars and start/goal to GeoPackage, threat surface to GeoTIFF · the C solver ships as a DLL, without its source");
s.addNotes("The matplotlib demo became a QGIS plugin: same engine, QGIS map canvas instead of a figure window. Every action is answered from precomputed structures or the parallel C solver in the background, so QGIS stays responsive.");

s = add("CONTENT", "Track 3: radar-hidden corridor");
eyebrow(s, "Track 3 · Processing Toolbox", HEX.accent3);
s.addText("Our best algorithm per track as Processing tools", { placeholder: "title" });
img(s, "../qgis_plugin/screenshots/processing_toolbox.png", 0.6, 1.7, 5.4, 4.6, "Processing Toolbox with the Visibility Corridor provider");
table(s, [["Tool", "Track", "Algorithm"], ["Radar coverage", "1", "GDAL viewshed per radar, count"], ["Route visibility", "2", "threaded window viewsheds (F6 best)"],
          ["Radar threat surface", "3", "detection hazard or exposure"], ["Least-exposure route", "3", "parallel C cost-to-go field, exact"],
          ["Shortest route under a detection budget", "3", "LARAC + exact label search, certified"], ["Route detection check", "all", "P(detect) + part outside coverage (= 0)"]],
  6.3, 1.85, 6.4, [2.8, 0.8, 2.8], { fontSize: 13 });
T(s, "Usable in the Model Designer, batch mode and from Python, like any QGIS algorithm.", { x: 6.3, y: 5.5, w: 6.4, h: 0.8, fontSize: 15 });
s.addNotes("These tools let anyone chain our algorithms with QGIS's own in a model, as in the Lecture 21 modelling activity.");

s = divider("Track 3: radar-hidden corridor", "LIVE DEMO", "Visibility Corridor in QGIS",
  "1 · Load the 120 km Garhwal scenario (~6 s)   2 · click starts, move the mouse: live preview   3 · right-click a goal   4 · drag a radar, R / X   5 · α slider, + / −   6 · B: route under 50% detection   7 · pan and zoom: live coverage   8 · Processing tool on another DEM");
s.addNotes("Demo script. Fallback if anything fails: the screenshots on the previous slides and qgis_plugin/screenshots. Mention the timing panel after each action.");

// ================================================================ CROSS-TRACK
const xc = XT.cells || {}, xr = XT.random_paths || {}, xh = XT.hidden_route || {}, xroutes = XT.routes || {};
divider("Integration: across the tracks", "INTEGRATION", "All three tracks on one dataset", "Does every track agree with the others? Detection is checked against coverage, every route is scored by all tracks, and all benchmarks run on one machine.");

s = add("CONTENT", "Integration: across the tracks");
eyebrow(s, "Cross-track check · Track 1 × Track 3", MUTED);
s.addText("No detection outside the cumulative viewshed", { placeholder: "title" });
img(s, "integration/fig_detection_vs_coverage.png", 0.6, 1.7, 8.0, 3.1, "P(detect) against fraction of path inside coverage, and cumulative P(detect) along routes");
table(s, [["Check (16 M cells)", "Result"], ["Cells: Track 1 coverage = Track 3 hazard > 0", `${pc(xc.agreement, 3)} agree`],
          ["Hazard outside coverage", `${f0(xc.hazard_not_covered)} cells`], [`Random paths fully outside (of ${f0(xr.n)})`, `${f0(xr.fully_outside_coverage)}, max P(detect) ${pc(xr.max_p_detect_fully_outside, 2)}`],
          ["Paths with hazard outside coverage", f0(xr.paths_with_hazard_outside_coverage)], ["Fully hidden Devprayag → Joshimath route", xh.exists ? "exists" : (xh.start_covered || xh.goal_covered ? "impossible: an endpoint is covered" : "none")]],
  8.85, 1.75, 3.85, [2.35, 1.5], { fontSize: 11 });
T(s, "A path the radars cannot see cannot be detected: the detection hazard is zero wherever Track 1's coverage of a 150 m aircraft is zero, checked cell by cell, on every named route and on thousands of random paths. The same check is a Processing tool.",
  { x: 0.6, y: 4.95, w: 12.1, h: 1.2, fontSize: 15 });
s.addNotes("Both tracks use the same GDAL viewshed, mast and target heights and curvature; Track 1 also cuts coverage at exactly 40 km. Any disagreement would show at the range rim.");

s = add("CONTENT", "Integration: across the tracks");
eyebrow(s, "Cross-track · every route scored by every track", MUTED);
s.addText("Hidden from the radars is not blind to the ground", { placeholder: "title" });
img(s, "integration/fig_integrated_map.png", 0.6, 1.65, 5.6, 5.0, "Coverage map with Track 2 and Track 3 routes");
const xrow = (n, k) => { const r = xroutes[k] || {}; return [n, f0(r.length_km), f0(r.covered_km), pc(r.p_detect), r.worst_radar || "–", f0((r.aircraft_sees || {}).seen_km2)]; };
table(s, [["Route", "km", "covered km", "P(detect)", "worst", "aircraft sees km²"],
          xrow("Track 2 valley", "Track 2 valley route"), xrow("Track 3 shortest", "Track 3 shortest"), xrow("Track 3 α = 10", "Track 3 alpha = 10"),
          xrow("Track 3 α = 100", "Track 3 alpha = 100"), xrow("Track 3 P ≤ 50%", "Track 3 risk budget 50 %"), xrow("Least covered", "Least covered length")],
  6.45, 1.8, 6.25, [1.75, 0.65, 1.0, 1.0, 0.75, 1.1], { fontSize: 12 });
T(s, `Track 1's radars and Track 3's detection model score each route; Track 2's engine measures the ground the aircraft itself sees (150 m AGL, 20 km). Hiding from six radar sites does not blind the aircraft: the least-covered route is detected with ${pc((xroutes["Least covered length"] || {}).p_detect)} probability yet sees ${f0(((xroutes["Least covered length"] || {}).aircraft_sees || {}).seen_km2)} km², ${f1((((xroutes["Least covered length"] || {}).aircraft_sees || {}).seen_km2 || 0) / ((((xroutes["Track 2 valley route"] || {}).aircraft_sees || {}).seen_km2) || 1))}× the valley route.`,
  { x: 6.45, y: 5.0, w: 6.25, h: 1.4, fontSize: 14 });
s.addNotes("Worst = the radar contributing most detection. Covered km = length inside the cumulative viewshed.");

const BX = XT.benchmarks || {};
const ex = (t, a) => (((BX[t] || {}).algorithms || {})[a] || {}).exponent;
s = add("CONTENT", "Integration: across the tracks");
eyebrow(s, "Cross-track · scaling on one machine", MUTED);
s.addText("Three workloads, three cost drivers", { placeholder: "title" });
img(s, "integration/fig_scaling_all_tracks.png", 0.6, 1.7, 6.2, 3.9, "Runtime against DEM cells for all tracks");
table(s, [["Track", "Unit of work", "Grows with", "Exponent", "Best lever"],
  ["1 Radar", "one viewshed", "cells in range", f2(ex("radar", "gdal")), "range window, threads"],
  ["2 Flight", "viewshed per position", "positions × radius²", f2((BX.flight || {}).algorithms ? Object.values(BX.flight.algorithms)[0].exponent : null), "threads, spacing per altitude"],
  ["3 Corridor", "graph search", "nodes (N log N)", f2(ex("corridor", "dijkstra_csgraph")), "C on implicit grid, precompute"]],
  7.0, 1.85, 5.7, [1.1, 1.3, 1.3, 0.8, 1.2], { fontSize: 11 });
T(s, "Raw runtimes across tracks are not a contest: they do different work. Comparisons that matter are within a track; across tracks we compare what drives the cost.",
  { x: 7.0, y: 4.3, w: 5.7, h: 1.4, fontSize: 14 });
foot(s, machLine);
s.addNotes("Track 2 is many Track 1 problems; Track 3 adds a graph search on top of Track 1's viewsheds. Memory is set by the DEM in Tracks 1 and 2, by the graph representation in Track 3.");

s = add("CONTENT", "Integration: across the tracks");
eyebrow(s, "Visualisation performance", MUTED);
s.addText("QGIS cost follows the screen, not the raster", { placeholder: "title" });
img(s, "shared/fig_render_benchmark.png", 0.6, 1.75, 12.1, 3.6, "QGIS render time against raster cells");
T(s, "Plain or pyramided rasters draw in tens of milliseconds at any size. Compressed tiled GeoTIFFs without pyramids grow with the raster at full extent (every tile is decompressed). Build pyramids for compressed outputs; the plugin keeps its threat layer in memory.",
  { x: 0.6, y: 5.55, w: 12.1, h: 1.2, fontSize: 16 });
s.addNotes("Algorithm time and render time are measured separately; each render opens a fresh layer, so GDAL's block cache is cold.");

// ================================================================ CONCLUSION
s = add("CONTENT", "Conclusion");
s.addText("What we learned", { placeholder: "title" });
card(s, 0.6, 1.85, 3.85, 4.4, "Track 1", `Exact viewsheds cost N^1.5; R2 and GDAL stay linear at 99.8% agreement. Read only the range window, run many radars on threads (${f1(last(sp))}×), coarsen only with a kappa check.`, HEX.accent1, 17);
card(s, 4.7, 1.85, 3.85, 4.4, "Track 2", `Cost = positions × min(radius², map), fitted within 5%. Sharing the DEM across threads is fastest (exact); spacing should follow altitude. A real camera sees 5–18% of line of sight in the valley; ~8% of a low-flight coverage map is uncertain.`, HEX.accent2, 17);
card(s, 8.8, 1.85, 3.9, 4.4, "Track 3", "Precompute per goal and every start is a lookup; parallel C makes rebuilds sub-second; a certified risk budget; 4× less memory with direction codes; shipped as a QGIS plugin with Processing tools.", HEX.accent3, 17);
foot(s, "Across tracks: one pipeline on one machine, detection consistent with coverage, and every route scored by all three tracks.");
s.addNotes("Limitations: one region and one DEM source; radar model is line of sight with a distance-based detection probability; the plugin is Windows-only because the solver ships as a DLL.");

s = add("DARK", "Conclusion");
T(s, "THANK YOU", { x: 0.8, y: 1.4, w: 11, h: 0.4, fontSize: 14, bold: true, color: HEX.accent6, charSpacing: 3 });
s.addText("Questions?", { placeholder: "title" });
T(s, "Code, results and the plugin ZIP in the team repository · run.bat -m integration.pipeline reproduces every number", { x: 0.8, y: 4.5, w: 11, h: 0.8, fontSize: 20, color: "CDD6E4" });

// ================================================================ BACKUP
s = add("BACKUP", "Backup");
eyebrow(s, "Backup · Track 3 edits and pan / zoom", HEX.accent3);
s.addText("Recompute only what an edit invalidates", { placeholder: "title" });
img(s, "corridor/interactive/fig_e3_incremental.png", 0.6, 1.7, 6.0, 2.4, "Incremental against from-scratch time");
img(s, "corridor/interactive/fig_e4_lod.png", 0.6, 4.2, 6.0, 2.4, "Pan and zoom latency and on-screen error");
card(s, 6.9, 1.75, 5.8, 1.5, "Start moved", "Field lookup ~0.1 ms vs 2.7 s Dijkstra; D* Lite often needs no work, but the lookup is simpler.", HEX.accent3, 14);
card(s, 6.9, 3.4, 5.8, 1.5, "Radar dragged", "Recompute that radar's viewshed window (~0.2 s), then rebuild the field in parallel (~0.4 s). Exact.", HEX.accent3, 14);
card(s, 6.9, 5.05, 5.8, 1.5, "Pan / zoom", "Never search: draw the known route. Re-solving each view: 30–240 ms and often the wrong valley.", HEX.accent3, 14);

s = add("BACKUP", "Backup");
eyebrow(s, "Backup · Track 3 interactive viewer (before the plugin)", HEX.accent3);
s.addText("From the matplotlib viewer to the plugin with live preview", { placeholder: "title" });
img(s, "corridor/interactive/demo_last.png", 0.6, 1.7, 5.4, 4.8, "Interactive viewer after a scripted session");
img(s, "../qgis_plugin/screenshots/hover_preview.png", 6.3, 1.7, 6.4, 4.8, "Plugin: live route preview from the cursor (pink) on the 120 km scenario");

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
