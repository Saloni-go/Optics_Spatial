# Large-Scale Terrain Data Analysis – 2

## Project context and complete conversation handoff

**Project brief:** Evaluate terrain-driven applications for **radar visibility assessment**, **flight-route visibility analysis**, and **optimal visibility corridor generation**, focusing on computational complexity, memory efficiency, visualization performance, accuracy, and scalability.

This file consolidates the planning and technical decisions discussed in this chat. It is a project handoff rather than a verbatim transcript. Suggested approaches are marked as such; they are not yet implemented or experimentally verified.

## 1. Project objectives

1. Build three working terrain visibility applications using digital elevation models (DEMs).
2. Produce geospatial visualizations showing visible/blocked regions and flight/corridor routes.
3. Benchmark **execution time**, **peak memory**, **scalability**, **computational complexity**, **visualization/rendering performance**, and **accuracy/solution quality**.
4. Experiment with optimizations and compare them with baseline implementations.
5. Deliver a consolidated technical comparison and report.

**Central research contribution:** Explain *how and why* the computational demands of different terrain-visibility tasks grow with terrain size and problem parameters, and which implementation decisions improve efficiency.

## 2. Agreed three-person parallel division

| Person | Track | Main question | Core output |
|---|---|---|---|
| 1 | Radar Visibility Assessment | Which terrain cells are visible from a stationary radar site? | Radar coverage/viewshed raster and maps |
| 2 | Flight-Route Visibility Analysis | How does visibility change along a moving flight route? | Waypoint viewsheds, cumulative coverage, blind spots and route maps |
| 3 | Optimal Visibility Corridor Generation | Which feasible route best balances visibility and travel constraints? | Visibility-aware optimized route/corridor and alternatives |

**Independence rule:** Each track must be separately executable. Share conventions and utilities but avoid blocking one team member on another member's implementation. Track 3 may compute its own visibility costs or use a precomputed visibility raster.

### Shared setup — Phase 0 (all members)

- Choose one region and obtain a large DEM (e.g. SRTM or Copernicus DEM).
- Prepare raster subsets at multiple sizes, e.g. **500×500**, **1000×1000**, **2000×2000**, **4000×4000** cells (250k, 1m, 4m, 16m cells).
- Use a compatible **projected coordinate reference system**, with horizontal and vertical units documented; document no-data handling and DEM resolution.
- For a clean size-scaling experiment, grow geographic coverage at the **same cell resolution**, rather than only resampling the same geographic extent. Separately evaluate resolution effects if useful.
- Agree on observer/radar altitude, flight altitude reference (above ground or sea level), visibility radius, Earth-curvature/refraction assumptions, and what counts as blocked/visible.
- **Crucial unresolved conceptual choice:** Does corridor visibility mean visibility *from the aircraft to terrain* or *of the aircraft from ground radar stations*? Align objective functions and outputs accordingly.
- Decide common output formats: **GeoTIFF** for rasters, **GeoJSON** for routes, **CSV** for metrics, **PNG** for figures.
- Agree on Python/GDAL/Rasterio/QGIS stack and a shared benchmarking protocol, machine, experiment metadata and results schema.

## 3. Track 1 — Radar Visibility Assessment (Person 1)

**Goal:** Compute stationary radar viewsheds and assess algorithm efficiency.

| Phase | Tasks | Deliverable |
|---|---|---|
| 1. Research and setup | Read about viewshed/line-of-sight; evaluate GDAL `gdal_viewshed` and GRASS GIS; choose baseline | Algorithm choice, assumptions |
| 2. Core implementation | Load DEM; set radar coordinates, height and range; calculate visible/blocked cells; optionally implement naive line-of-sight baseline | Working radar module + raster |
| 3. Visualization | Overlay coverage and blocked areas on shaded terrain; create legends and maps in QGIS | Radar coverage figures |
| 4. Benchmarking | Vary DEM dimensions, radar heights/ranges and number of observers; capture runtime, peak RAM, correctness | Raw metrics CSV + graphs |
| 5. Optimization | Compare alternate viewshed implementations, tiling/region clipping, lower resolution where appropriate | Baseline-vs-optimized results |
| 6. Analysis and documentation | Discuss complexity, scaling patterns, accuracy and tradeoffs | Track report section |

**Track 1 output:** Executable radar viewshed workflow, coverage map(s), benchmark dataset, plots, optimization comparison and write-up.

## 4. Track 2 — Flight-Route Visibility Analysis (Person 2)

**Goal:** Measure terrain visibility from a changing sequence of flight locations.

| Phase | Tasks | Deliverable |
|---|---|---|
| 1. Research and setup | Study moving-observer viewsheds, route discretization and waypoint sampling | Flight visibility design |
| 2. Core implementation | Generate/import flight paths; interpolate altitude and sample waypoints; compute viewsheds/line-of-sight at each; aggregate coverage | Flight module + coverage outputs |
| 3. Visualization | Show path, altitudes, cumulative visible regions, gaps and obstructed portions | Flight maps and figures |
| 4. Benchmarking | Vary DEM size, flight altitude, route length, waypoint count, sampling interval, radius | Metrics CSV + performance plots |
| 5. Optimization | Test fewer/adaptive waypoint samples, caching repeated calculations and parallel execution | Accuracy/speed tradeoff comparison |
| 6. Analysis and documentation | Explain effects of waypoint density, altitude, terrain complexity and efficiency | Track report section |

**Track 2 output:** Flight visibility analysis, route visualizations, benchmark metrics and optimization analysis.

## 5. Track 3 — Optimal Visibility Corridor Generation (Person 3)

**Goal:** Find routes between endpoints that balance visibility against travel constraints.

| Phase | Tasks | Deliverable |
|---|---|---|
| 1. Research and setup | Define visibility objective, feasibility constraints and cost function; study Dijkstra/A* | Formal objective and design |
| 2. Core implementation | Build terrain grid/graph; assign visibility-aware edge/node costs; generate best route(s) | Working corridor solver |
| 3. Visualization | Draw optimized and baseline shortest paths over DEM and visibility score map | Route/corridor comparison maps |
| 4. Benchmarking | Vary DEM dimensions, graph resolution/node count, start/end points and constraints; record time/RAM/solution quality | Metrics CSV and plots |
| 5. Optimization | Compare Dijkstra vs A*, admissible heuristics where applicable, graph simplification/multiresolution | Solver comparison |
| 6. Analysis and documentation | Evaluate complexity, scaling, route lengths, visibility scores and efficiency tradeoffs | Track report section |

**Track 3 output:** Visibility-aware route optimizer, alternate routes, benchmark dataset, figures and write-up.

**Caution:** A* is optimal only under appropriate cost/heuristic conditions; graph resolution and visibility cost preprocessing must be counted when comparing methods. Physical flight constraints (clearance, turns, altitude) should be made explicit if the result is called a flight corridor.

## 6. Practical benchmarking protocol

### Dataset size experiment

| DEM grid | Number of cells |
|---|---:|
| 500 × 500 | 250,000 |
| 1000 × 1000 | 1,000,000 |
| 2000 × 2000 | 4,000,000 |
| 4000 × 4000 | 16,000,000 |

For each application, run the same defined workload at each dataset size, **repeat 5 times**, and report the **median** with individual measurements preserved. Keep computer hardware, algorithm, terrain resolution and other controlled parameters consistent. Larger rasters have different extents, so document how geography/terrain heterogeneity may influence results.

### Six evaluation dimensions

| Dimension | How to evaluate |
|---|---|
| Execution time | Wall-clock seconds per full run; clearly specify whether I/O and preprocessing are included |
| Peak memory | Max resident set size (RSS), and optionally overall system memory; report units |
| Scalability | Graph runtime/memory vs number of DEM cells and relevant application-specific parameters |
| Computational complexity | Derive expected big-O behavior from algorithm, then compare with measured growth; distinguish preprocessing and query costs |
| Visualization performance | Time to load/render result in QGIS; responsiveness while panning and zooming at defined settings |
| Accuracy / quality | Check line-of-sight against independently known/simple cases or trusted reference; for routes compare visibility score, distance and constraint satisfaction |

### Independent variables by track

- **Radar:** DEM size; radar range/height; number of radars.
- **Flight:** DEM size; path length; waypoint count/sampling interval; altitude/radius.
- **Corridor:** DEM size; graph node count/resolution; cost weights; endpoints; algorithm/constraints.

**Do not interpret raw runtimes across the three applications as a fair algorithm contest**: the three problems do different amounts and types of work. The core comparisons should be *within a track* across sizes, baselines and optimizations, followed by a careful cross-track resource-demand discussion.

### Instrumentation examples

Python runtime measurement for a command-line implementation:

```python
import subprocess
import time

start = time.perf_counter()
subprocess.run([
    "gdal_viewshed",
    "-b", "1",
    "-ox", "500000",  # Replace with in-bounds projected coordinates
    "-oy", "3000000",
    "-oz", "30",      # Observer height above terrain in DEM units
    "terrain.tif",
    "visibility.tif"
], check=True)
print(f"Runtime: {time.perf_counter() - start:.2f} s")
```

GDAL CLI availability/syntax and coordinates should be checked against the installed version and actual raster. On Linux, use `/usr/bin/time -v <command>` and record **Maximum resident set size**, normally in KB, as process peak RAM.

Recommended benchmark row fields:

```text
track,algorithm,dem_id,width,height,cell_size_m,scenario_id,
waypoints,radar_count,graph_nodes,repeat,runtime_s,peak_rss_kb,
render_time_s,accuracy_or_quality,notes
```

Use null/blank values for fields that do not apply to a track. Record CPU, RAM, QGIS/GDAL/Python versions and command/configuration for reproducibility.

### Validity checks

- Validate on simple synthetic terrain before large runs: **flat surface**, **single ridge**, **valley**.
- Check that the radar or flight point is inside the DEM; beware coordinate and vertical-unit mismatches.
- Treat no-data cells consistently; specify assumptions about earth curvature/refraction and altitude datum.
- Distinguish algorithm runtime from QGIS rendering time; measure the latter separately.
- State what optimization changes may sacrifice correctness or resolution.

## 7. Visualization deliverables

- Terrain base layer with elevation shading.
- Radar visible/blocked raster with clear legend.
- Flight path, sampled observer points, coverage mask and visibility gaps.
- Visibility-aware corridor against shortest-distance baseline and possibly multiple alternatives.
- Per-track **runtime vs cells** and **memory vs cells** plots; optionally quality vs time and render speed vs result size.
- One consolidated table of results, assumptions and limitations.

## 8. Suggested timeline (4–5 weeks)

| Period | All-track milestone |
|---|---|
| Days 1–2 | Phase 0: shared datasets, definitions, repository and benchmark standards |
| Days 3–5 | Phase 1: independent background research and designs |
| Week 2 | Phase 2: minimum working implementations and synthetic-terrain validation |
| Week 3 | Phase 3: mapping/visualization; begin Phase 4 benchmarking |
| Weeks 3–4 | Phase 4: controlled scaling and accuracy studies |
| Week 4 | Phase 5: implementation improvements and baseline comparisons |
| Week 5 | Phase 6: interpretation, combined report and final presentation |

Each member owns all six phases for their application; run integration checks during the project rather than only at the end.

## 9. Suggested repository layout

```text
terrain-visibility-project/
├── data/
│   ├── small.tif
│   ├── medium.tif
│   └── large.tif
├── radar/
│   ├── viewshed.py
│   └── benchmark.py
├── flight/
│   ├── visibility.py
│   └── benchmark.py
├── corridor/
│   ├── optimizer.py
│   └── benchmark.py
├── common/
│   ├── dem_utils.py
│   └── metrics.py
├── results/
│   ├── radar/
│   ├── flight/
│   └── corridor/
└── report/
```

## 10. Final project checklist

- [ ] Shared DEM data and reference parameters documented.
- [ ] Radar visibility program runs end-to-end.
- [ ] Flight-route visibility program runs end-to-end.
- [ ] Optimal corridor generator runs end-to-end.
- [ ] All programs pass synthetic-terrain sanity checks.
- [ ] All have clear visual outputs and geospatial exports.
- [ ] All have recorded timing and peak-memory experiments at several input sizes.
- [ ] All include a complexity discussion and a baseline-vs-optimization comparison.
- [ ] Visual rendering benchmarks use a consistent protocol.
- [ ] Report explains accuracy, limitations, and the difference between three workloads.
- [ ] Final integrated presentation demonstrates all three applications and their results.

## 11. Decisions still to make

1. Choose actual DEM dataset, region and projected CRS.
2. Finalize operational definition of visibility and corridor optimization objective.
3. Decide if the flight routes are hypothetical or sourced; specify altitude/clearance constraints.
4. Confirm software versions and machine available for benchmarks.
5. Decide minimum benchmark sizes feasible within time/memory budget.
6. Assign names to Person 1, Person 2, Person 3 and fix submission deadline.

## 12. One-sentence project summary

**Three team members independently implement radar, flight-route, and optimal corridor terrain-visibility applications over shared DEM data, then systematically benchmark runtime, memory, scaling, visualization, correctness, and optimization tradeoffs before integrating the results into one evaluation.**
