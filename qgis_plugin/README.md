# Visibility Corridor: QGIS plugin (Track 3)

The Track 3 interactive corridor demo as a QGIS plugin. QGIS's map canvas replaces the matplotlib window: the
DEM, radar threat surface, radars, start/goal and routes are ordinary map layers. Every action is answered by the
same engine as `corridor/interactive.py` (cost-to-go field, alpha bank, pyramid, parallel C solver, LARAC risk
budget), and a panel shows which structure answered and how long it took.

Not open source: the ZIP is shared privately (see `visibility_corridor/LICENSE.txt`) and is not published on
plugins.qgis.org. The C sources are not included, only the compiled solver.

## Build the ZIP

    run.bat qgis_plugin\build_plugin.py                # bundles the 1000, 2000 and 4000 DEMs (52 MB)
    run.bat qgis_plugin\build_plugin.py --sizes 1000   # small build (3 MB)

Output: `qgis_plugin/dist/visibility_corridor-<version>.zip`.

## Install

QGIS 3.28 or newer on 64-bit Windows: **Plugins → Manage and Install Plugins → Install from ZIP**, choose the ZIP,
then **Install Plugin**. A toolbar button and the menu **Plugins → Visibility Corridor** open the planner panel.

## Use

1. **Scenario.** Choose a bundled Garhwal DEM (1000, 2000 or 4000 cells per side), or *DEM raster layer from the
   project* for any DEM. A lat/lon DEM is reprojected to its UTM zone automatically. Radars: the scenario sites,
   automatic ridge-top sites (choose how many), or a point layer. Then choose the threat model (detection
   probability or exposure) and click **Load scenario and precompute** (about 6 s for 16 M cells; runs in the
   background).
2. **Map tool** (switched on after loading):

   | Input | Action | Answered by |
   |---|---|---|
   | left click | new start | Level 2 lookup, under 1 ms |
   | right click | new goal | coarse-to-fine route at once; exact field rebuilt in the background |
   | drag a radar | move it | threat window + parallel field rebuild (exact) |
   | R / X | add a radar at the cursor / remove the nearest | same |
   | + / − | alpha ×2 / ÷2 | alpha-bank lookup, then the exact field |
   | B | shortest route with P(detect) ≤ budget | LARAC + exact label search, certified gap |
   | mouse move | route from the cursor (pink) | Level 2 lookup, under 1 ms |
   | wheel / middle-drag / Space | zoom / pan | live radar coverage for the visible window (below) |

   The panel has the same controls as buttons (alpha ÷2 / ×2 / Set, P(detect) budget).
3. **Pan and zoom on the fly.** With *Live radar coverage for the visible window* ticked, every pan, zoom or
   radar edit recomputes how many radars see an aircraft 150 m above ground, for the visible cells only, at about
   one DEM cell per screen pixel (a DEM pyramid 30 m, 60 m, 120 m …). Zoomed in it is the full 30 m coverage, cell
   for cell identical to Track 1; zoomed out it is coarser, which the screen cannot show anyway. 10-45 ms per view
   on the 16 M-cell DEM (`run.bat -m corridor.panzoom_bench`); while panning fast, outdated views are skipped.
4. **Export** writes the route, radars and start/goal to a GeoPackage and the threat surface to a GeoTIFF.

## Layout

    visibility_corridor/      plugin source (GUI): plugin.py, dock.py (panel + controller), maptool.py, layers.py,
                              liveitem.py (pan / zoom overlay)
    build_plugin.py           assembles the ZIP: GUI + engine (corridor/, common/, gridsearch.dll) + DEMs + scenarios.json
    screenshots/              the plugin running in QGIS 3.44
