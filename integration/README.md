# Integration: all three tracks on one dataset and one machine

    run.bat -m integration.pipeline              # everything, about 2 h on the Ryzen 9 7900X (12 cores)
    run.bat -m integration.pipeline --list       # step names
    run.bat -m integration.pipeline --from corridor.run_corridor
    run.bat -m integration.pipeline --only integration.cross_track

**Same dataset.** Every step uses the Copernicus GLO-30 DEMs in `data/` (500, 1000, 2000 and 4000 cells per side,
30 m, EPSG:32644), the six shared radar sites (`common/sites.py`, `results/shared/radars.geojson`) and the
visibility model in `common/config.py`: 30 m masts, aircraft 150 m above ground, 40 km range, curvature with
refraction k = 1/7.

**Same machine.** Steps run one after another in fresh processes, so benchmarks never overlap. Each track's
`benchmark_raw.csv` is cleared before its benchmark, so every runtime in `results/` comes from the machine and
commit recorded in `results/integration/run_manifest.json`. The per-step output is in
`results/integration/logs/<step>.txt`.

| Step | Track | What it does |
|---|---|---|
| radar.validate, radar.run_radar, radar.benchmark, radar.analysis | 1 | viewshed validation, six-radar coverage, E1-E6, fits |
| flight.run_flight, flight.benchmark, flight.spacing_study, flight.analysis | 2 | valley route visibility, F1-F6, spacing study |
| corridor.run_corridor, corridor.benchmark, corridor.analysis | 3 | least-exposure routes, C1-C8 |
| corridor.interactive_bench, corridor.extensions_bench | 3 | interactive levels, alpha bank, risk budget, tiles, altitude, placement, robustness |
| corridor.efficiency_bench | 3 | memory-efficient fields and on-the-fly operations |
| corridor.panzoom_bench | 1 × 3 | pan and zoom on the fly: radar coverage for the visible window at screen resolution |
| integration.cross_track | all | the checks below |
| qgis.build_project, qgis.render_bench | all | QGIS project with every layer, render benchmark |

## Cross-track checks (`integration/cross_track.py`)

1. **No detection outside the cumulative viewshed.** Track 1's coverage of a 150 m AGL aircraft is compared cell
   by cell with the cells where Track 3's detection hazard is non-zero. Every named route, 5000 random paths and
   the best fully hidden route are then scored. The detection probability accumulated outside the coverage must be
   exactly 0, and the paths with no covered length must have P(detect) = 0.
2. **Every route scored by all three tracks.** Track 2's valley route, Track 3's routes (shortest and alpha 1, 10,
   100), the risk-budget route (P(detect) ≤ 50%) and the least-covered route, each with: length, length inside
   radar coverage, P(detect), which radar contributes most, the distance at which P(detect) reaches 10% and 50%,
   and the ground area the aircraft itself sees along the route (Track 2's engine at 150 m AGL).
3. **One machine for all benchmarks.** E1, F1 and C1 runtime against DEM size with empirical exponents, on the
   machine in the manifest.

Outputs: `results/integration/cross_track.json`, `fig_integrated_map.png`, `fig_detection_vs_coverage.png`,
`fig_scaling_all_tracks.png`, `routes_scored.geojson`.
