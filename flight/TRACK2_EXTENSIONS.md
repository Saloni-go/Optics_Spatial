# Track 2 - flight-route visibility: extensions

Branch `track2-extensions`. Everything below was run on one machine (Linux laptop: 10 cores / 12 threads,
15.3 GB RAM, Python 3.10, GDAL 3.4.1; `results/linux/flight/machine.json`). Results are in
`results/linux/flight/`, separate from the team's Windows results in `results/flight/`.

Scenario throughout: the 166 km Alaknanda valley route (Devprayag to Joshimath) on the 4000 x 4000 DEM
(16 M cells, 30 m), terrain following at 300 m above ground ("valley") or constant 5500 m above sea level
("cruise"), 20 km visibility radius, positions every 500 m (333 positions) unless stated.

## 0. Baseline on this machine and two measurement fixes

The scenario and F1-F6 were re-run and agree with the team's run to within 0.1% in area seen
(`stats.json`, `benchmark_summary.json`); threads mode takes 2.25 s (team machine 1.95 s).

* **GDAL 3.4** rejects an empty option list in `ViewshedGenerate`; `None` is used instead (six files).
* **Peak memory on Linux.** psutil has no peak there, so the harness reported the memory in use at
  the end of a run. It now reads the kernel high-water mark `VmHWM`. (`ru_maxrss` was tried first, but
  on Linux it survives `exec`, so a child started by a big parent reported the parent's peak.)
* Radar validation on GDAL 3.4: 99.75% / 99.82% agreement with exact line of sight, as on the team
  machine (`results/linux/radar_validation.json`).

## 1. Cheaper computation (F7-F10)

Figures: `fig_idea1_shared.png`, `fig_idea1_multires.png`, `fig_idea1_memory.png`, `fig_idea1_complexity.png`.

**F7 - share the DEM instead of copying it (exact).** The old window mode copied a 40 x 40 km piece
of the DEM for every position. Each thread now gets a zero-copy GDAL view of the one in-memory array;
GDAL clips the work to the radius itself. Identical counts in every cell.

| Mode | Compute | Peak memory |
|---|---|---|
| window copy per position | 5.49 s | 307 MB |
| window copy + 12 threads (previous best) | 1.92 s | 919 MB |
| shared view, serial | 4.33 s | 362 MB |
| **shared view + 12 threads** | **1.38 s** | 841 MB |

28% faster than the previous best and less memory. With unlimited radius on 16 M cells the route
takes 3.8 s instead of 18 s (F1, window mode).

**F8 - fine near, coarse far (approximate).** Exact 30 m viewshed within r_near, k-times coarser DEM
beyond. One viewshed: 10.7 ms -> 4.6 ms at k = 3. A whole route gains little (1.41 s -> 1.27-1.52 s),
because once viewsheds are cheap, adding each result into the coverage rasters (serial) dominates
(Amdahl). Accuracy 86-97% (Jaccard); errors are mostly *extra* visible cells, because block means lower
ridge tops. **Not worth it at 20 km radius**; a candidate for much larger radii.

**F9 - tiled accumulator.** Count / first-seen rasters stored only for 256 x 256 tiles the route
touches. Fixed 12 km route on the 16 M-cell map: accumulator 91.6 -> 9.8 MB, process peak 415 -> 343 MB.
Memory now scales with the area seen, not the map; little gain when the route spans the whole map.

**F10 - complexity model.** One viewshed sweeps every cell of its disc once, so

    T = a * W * min(pi r^2 / cell^2, N) + b * W        (W positions, radius r, N map cells)

Fitted to every F1-F5 median: a = 11.4 ns per cell, b = 0.10 ms per position; mean error 4.9%
(max 16%), R^2 (log) = 0.998. Cost is O(W * min(r^2, N)): linear in positions and route length,
quadratic in radius, independent of altitude, and independent of map size once the map is larger
than the radius disc (F1b flat beyond 4 M cells).

## 2. Realistic sensor and uncertainty (F11, F12)

Figures in `idea2/`: `fig_idea2_sensors.png`, `fig_idea2_gsd.png`, `fig_idea2_dwell.png`, `fig_idea2_uncertainty.png`.

A cell counts as observed only if it is in line of sight, inside the sensor's horizontal field of
view (relative to heading), inside its depression-angle limits, and imaged at a ground sample
distance GSD = slant range x IFOV / cos(incidence) <= limit (6000 px, 60 deg camera: 0.175 mrad).
Dwell time = positions seeing the cell x spacing / speed (60 m/s).

| Sensor (3 m limit except plain omni) | Valley area | Valley median dwell | Cruise area | Cruise median dwell |
|---|---|---|---|---|
| omni, line of sight only | 1,600 km^2 | 67 s | 4,747 km^2 | 408 s |
| omni, <= 3 m | 969 | 58 s | 2,499 | 242 s |
| forward camera, 90 deg | 220 | 25 s | 1,963 | 50 s |
| side cameras, 2 x 60 deg | 175 | 8 s | 2,272 | 67 s |
| nadir, >= 45 deg down | 87 | 8 s | 1,249 | 125 s |

* Line of sight overstates what a real sensor observes: 5-18% of it in the valley.
* The best mounting depends on height: forward in a valley (walls block the sides), side-looking at cruise.
* Resolution requirement: at cruise nothing is seen at 0.5 m (closest slant range ~3.5 km gives 0.6 m);
  1 m keeps 17% of the line-of-sight area, 10 m keeps 89%.
* Cost (fresh process): valley 1.8 s -> 2.1-2.2 s with a sensor, ~0.9 GB; cruise 5-8 s, ~1-1.3 GB
  (ten times more cells in view, each tested). Masks are evaluated only on line-of-sight cells, cheapest
  test first; terrain slopes are computed once (computing them per thread had cost 12 s and 2.5 GB).

**Monte Carlo** (20 runs per source): DEM error 4 m, correlated over 300 m; aircraft position error
10 m horizontal, 15 m vertical.

| | Valley | Cruise |
|---|---|---|
| area seen per run | 1,604 +/- 3 km^2 | 4,748 +/- 1 km^2 |
| overlap of each run with the error-free run | 97.7% | 99.5% |
| uncertain (seen in 5-95% of runs) | 126 km^2 (7.9%) | 80 km^2 (1.7%) |
| uncertain from DEM error only / position error only | 85 / 81 km^2 | 75 / 17 km^2 |

The total area barely changes, but which cells are seen does, at the edges of visibility. Low valley
flight is about five times more sensitive than cruise; in the valley DEM and position errors matter
equally, at cruise almost only the DEM. Rasters `p_seen_valley.tif`, `p_seen_cruise.tif`.

## 3. Applications (U1-U6)

Figure `usecases/fig_usecases.png`; per-case JSON in `usecases/`.

* **U1 radio link** to town stations (10 m mast, 60 km): valley flight is in contact on only 33% of the
  route (111 km without, longest gap 30 km); cruise 100% (Srinagar alone covers 82%).
* **U2 line target** (valley floor as river / road proxy): following the valley sees 100%; a straight
  line at 5500 m sees 92% in line of sight but only 65% with a 3 m camera (gaps up to 18 km); 7500 m
  barely helps (69%). To survey a winding valley, follow it.
* **U3 search and rescue**, 15 x 15 km box, camera must resolve 0.5 m (a person): track spacing 1 km
  covers 99.9-100% in 66 min; 2 km covers 92-95% in 33 min; 4 km covers 61-72% in 20 min. Height
  matters only at wide spacing.
* **U4 height vs coverage** within 5 km of the route: seeing 80% of the best local view needs about
  2000 m above ground nearly everywhere (deep valleys). Choosing the height per position gains only
  about 2% over a constant height of the same mean (e.g. 60% target: mean 1023 m, 1,301 km^2 vs
  constant 1000 m, 1,287 km^2).
* **U5 several aircraft** on parallel routes 8 km apart at 300 m: 1,600 -> 3,499 -> 4,702 -> 5,644 km^2;
  the 4th adds 942 km^2 and 62% of what it sees was already covered.
* **U6 terrain look-ahead**: holding heading and altitude, 3.4% of the valley route gives less than 20 s
  to terrain (median 48 s); never at cruise.

## 4. Visualisation in QGIS

`qgis/track2_layers.py` adds a styled group (baseline, sensors and uncertainty, use cases) to a
running QGIS or writes `qgis/track2_extensions.qgz`. **Playback**: the first-seen raster stores the
flight time (s) at which each cell is first seen and uses the raster temporal mode "represents temporal
values"; the aircraft layer has a time per position; the Temporal Controller range is cumulative, so seen
cells accumulate and the aircraft leaves a trail (163 frames of 17 s, 46 min of flight).

Draw time (`qgis/track2_render_bench.py`, 1600 x 1600 px, fresh layer each render, median of 5):

| Track 2 raster (16 M cells) | full extent | full, with overviews | zoomed / 1:1 |
|---|---|---|---|
| times seen | 51 ms | 31 ms | 27-29 ms |
| first seen (s) | 69 ms | 42 ms | 31-35 ms |
| P(seen) | 55 ms | 38 ms | 31-33 ms |
| dwell, forward camera | 50 ms | 28 ms | 23-27 ms |

Overviews make full-extent drawing ~1.6x faster and change nothing when zoomed in; the files are small
(0.2-0.7 MB, mostly empty cells), so overviews add ~50% size for little absolute gain. Playback runs at
17-23 frames per second (hillshade + seen-so-far + aircraft), so the animation is smooth.

## Reproduce

See the README sections "Linux" and "Track 2 extensions" for the commands.
