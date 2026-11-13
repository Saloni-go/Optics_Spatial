# Live demo: Visibility Corridor plugin (about 6 minutes)

**Before the talk**
- Open QGIS with an empty project and check that the plugin is installed (toolbar icon: a red radar with a cyan route).
  If it isn't: Plugins → Manage and Install Plugins → Install from ZIP → `qgis_plugin/dist/visibility_corridor-0.1.0.zip`.
- Optional: load the 120 km scenario once beforehand, so its files are in the OS cache and the first load is fast.
- Fallback if anything breaks: the screenshots in `qgis_plugin/screenshots/` and the plugin slides.

| # | Do | Say |
|---|---|---|
| 1 | Click the toolbar icon. In the panel choose **Garhwal Himalaya demo: 4000 x 4000** and **Detection probability**, then **Load scenario and precompute**. | "16 million cells, 120 by 120 km. In about 6 seconds, in the background, it builds the radar threat from six viewsheds, the cost-to-go field on 12 cores, the multi-resolution pyramid and the alpha bank." |
| 2 | Point at the layers: hillshade, red threat, radars R1–R6, cyan route, start and goal. | "These are ordinary QGIS layers, so we can style, identify or export them." |
| 3 | **Move the mouse** over the map (no click). | "The pink line is the best route from the cursor, recomputed on every mouse move: a lookup in the cost-to-go field, well under a millisecond." |
| 4 | **Left click** a few places. | "New start: Level 2 lookup, no search. The log on the right says which structure answered and how long it took." |
| 5 | **Right click** a new goal. | "A new goal invalidates the field: a coarse-to-fine route appears at once, and the exact field is rebuilt in the background in about 0.4 s." |
| 6 | **Drag a radar** onto the route, then press **R** over the route and **X** near a radar. | "Only that radar's viewshed is recomputed, then the field is rebuilt in parallel: exact in under a second. The route bends away." |
| 7 | Drag the **alpha live** slider, then release; or press **+** / **−**. | "While dragging we read routes from the precomputed alpha bank, a millisecond each; on release the exact field. The bank now stores 1-byte directions: 4 times less memory, identical routes." |
| 8 | Press **B** (budget 50%). | "Shortest route with detection probability at most 50%: Lagrangian relaxation plus an exact label search, with a certificate of how close to optimal it is." |
| 9 | Untick the **Radar threat** layer. **Scroll to zoom** into a valley, **middle-drag** (or hold Space) to pan, zoom back out. | "Pan and zoom on the fly: every view change recomputes the six-radar coverage for just what is on screen, one cell per pixel. Zoomed in it is the exact 30 m coverage, identical to Track 1; zoomed out a coarser pyramid level. 10 to 45 ms per view, and the log shows the level used. Drag a radar and the view redraws too." |
| 10 | Processing Toolbox → **Visibility Corridor** → *Least-exposure route*, on another DEM layer. | "Every track's best algorithm is also a Processing tool, usable in the Model Designer and in batch." |
| 11 | Click **Export**. | "Route, radars and threat surface go out as GeoPackage and GeoTIFF." |

**If a question comes up**
- *Why is it fast?* Precompute per goal (any start is a lookup), a parallel C solver on the implicit grid, and recomputing only what an edit invalidates.
- *Is it exact?* Yes, except the instant first answers (coarse-to-fine, nearest banked α), which are replaced by the exact field within about 0.4 s. The risk budget reports its certified gap.
- *Other areas?* Any DEM layer works: a lat/lon DEM is reprojected to UTM automatically, and radars can come from a point layer.
- *Why not compute the coverage for the whole DEM once?* That is what Track 1 does (0.1 s for 6 radars here). The live view's cost depends on the screen, not the DEM or the radar count: with 48 radars the whole DEM takes 0.53 s, the live view about 50 ms.
