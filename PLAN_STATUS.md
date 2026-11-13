# Plan, status and the 50% line

Everything below is implemented. For the mid-submission only the **first half** is meant to be
shown; the second half is ready for the final submission (and for any changes suggested at the
mid evaluation).

## What counts as 50% (show at mid-submission)

Per track, phases 1-3 of the plan plus the first scaling experiment:

| Part | Track 1 Radar | Track 2 Flight | Track 3 Corridor |
|---|---|---|---|
| Phase 0 (shared) | DEM, CRS, sizes, visibility model, benchmark harness | same | same |
| 1 Research / design | viewshed algorithms, curvature model | route sampling, altitude model, aggregation | cost function, constraints, Dijkstra/A* |
| 2 Core implementation | naive LOS + R2 + GDAL, one interface | per-position viewsheds, count / first-seen / blind spots | exposure surface, Dijkstra, A*, SciPy |
| Validation | synthetic flat/ridge/valley/cone + exact LOS on real DEM | (uses Track 1 engine) identical results across modes | all exact solvers give the same optimum |
| 3 Visualisation | six-radar coverage maps, single-radar map | cumulative visibility, blind spots, altitude profile | exposure map, routes vs shortest path |
| First benchmark | **E1** runtime/memory vs DEM size | **F1** runtime/memory vs DEM size | **C1** runtime/memory vs graph size |

Slides/report sections for the mid version: problem and shared setup, one slide per track
(design, map, validation, E1/F1/C1 plot), and the plan for the rest.

## The other 50% (keep for the final)

| Part | Track 1 | Track 2 | Track 3 |
|---|---|---|---|
| 4 Parameter benchmarks | E2 range, E3 height, E4 number of radars | F2 spacing, F3 altitude, F4 radius, F5 length | C2 alpha, C4 distance, C5 exposure cost |
| 5 Optimisation | E4 parallel radars, E5 region clipping, E6 coarser DEM | F6 cached / window / parallel / adaptive | C3 multi-resolution, A* vs Dijkstra, C vs Python |
| Accuracy of optimisations | E6 agreement vs 30 m | F2/F6 Jaccard vs dense sampling | cost gap vs optimum |
| Visualisation performance | QGIS render benchmark (pyramids vs none, full vs zoomed) | same | same |
| 6 Analysis | complexity fits and discussion | same | same |
| Integration | cross-track comparison, radar sites shared with Track 3, Track 2 route scored by Track 3 | | |

## Status

- [x] Phase 0: DEM (Copernicus GLO-30), CRS, sizes, synthetic terrains, conventions
- [x] Track 1 implementation, validation, scenario, benchmarks E1-E6, analysis
- [x] Track 2 implementation, scenario, benchmarks F1-F6, analysis
- [x] Track 3 implementation, scenario, benchmarks C1-C5, analysis
- [x] QGIS project and QGIS render benchmark
- [x] Mid-submission report and slide deck
- [x] Integrated run of all tracks on one machine, QGIS plugin, final deck (`presentation/Terrain_Visibility_Final.pptx`)
- [x] Track 2 extensions (Linux laptop, `results/linux/`; write-up `flight/TRACK2_EXTENSIONS.md`):
      shared-DEM threads and complexity model (F7-F10), sensor model and Monte Carlo uncertainty (F11-F12),
      six applications (U1-U6), QGIS flight playback and render benchmark; five slides in the final deck

## Decisions made (from context.md section 11)

1. DEM: Copernicus GLO-30 DSM, Garhwal Himalaya; EPSG:32644; 30 m; sizes 500-4000 cells.
2. Visibility: a cell is visible if the point `target_h` above it is in line of sight; radars 30 m
   masts; terrain targets at 0 m; aircraft targets 150 m above ground. Corridor objective = hide the
   aircraft from ground radars (distance + exposure + climb).
3. Flight routes: hypothetical but realistic (Alaknanda valley, Devprayag -> Joshimath); terrain
   following at 300 m AGL vs constant 5500 m MSL.
4. Machine: AMD Ryzen 9 7900X (12 cores / 24 threads), 31 GB RAM, Windows 11, QGIS 3.44.12,
   GDAL 3.13.1, Python 3.12.
5. Benchmark sizes: 0.25M, 1M, 4M, 16M cells; slow baselines run only where feasible and are
   projected beyond.
6. Owners: Track 1 Sravani, Track 2 Saloni, Track 3 Akshat.
7. Second machine: Track 2 extensions ran on a Linux laptop (10 cores / 12 threads, 15.3 GB, GDAL 3.4.1);
   its results are kept apart in `results/linux/` (set `OPTICS_RESULTS`), never mixed with the Ryzen runs.
