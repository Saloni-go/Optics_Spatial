# Track 1 extensions

All on the Linux laptop: the 4000 × 4000 DEM (16M cells), GDAL viewshed, 40 km range, the team's six radar sites (`results/shared/radars.geojson`).
Results are in `results/linux/radar_ext/`. To reproduce:

```bash
OPTICS_RESULTS=results/linux PYTHONNOUSERSITE=1 PYTHONPATH="$PWD" python3 -m radar.extensions
```

## 0. R2 accuracy fix (`radar/viewshed.py`)

**Problem.** Several rays cross each cell. The old rule called a cell visible if *any* of them saw it, so errors went only one way: about 20× more falsely visible cells than falsely hidden ones, and a visible area about 8% too high.

**Fix.** Each cell now takes the answer of the ray that passes closest to its centre.

**Effect.**
- Agreement with the exact reference (kappa): 0.959 → 0.984 on the 500 map, 0.954 → 0.985 on the 1000 map. GDAL is 0.965.
- Visible area is now within 1% of the exact result.
- R2 is 1.5–1.9× slower than before (laptop re-run in `results/linux64/radar`; the old timings are in `benchmark_raw_r2_old.csv`).

## 1. Lowest detectable altitude (`minalt`)

**What it computes.** For every cell, the lowest height above ground at which at least one radar sees an aircraft. GDAL 3.4 has no direct mode for this, so it is a sweep over 15 target heights (90 viewsheds, 7.6 s). The answer is exact at each height in the sweep.

**Coverage against flying height:**

| Aircraft height above ground | Share of the 120 × 120 km area where it is seen |
|---|---|
| 0 m (ground) | 17% |
| 25 m | 22% |
| 150 m | 36% |
| 2,000 m | 79% (the rest is beyond the 40 km range) |

**Cost of coarser sweeps.** A 5-level sweep costs a third of the time but over-estimates the lowest altitude by about 160 m on average.

## 2. Radar placement (`siting`)

**Method.** Greedy maximum coverage over 193 ridge-top candidates (same rule as the shared sites, without the 22 km spacing). The goal is the largest area where an aircraft at 150 m is seen.

**Result.**
- With six radars, greedy placement covers 6,624 km², against 5,122 km² for the shared sites (+29%).
- Five greedy radars already match the six shared sites.
- The shared sites were picked highest-first, so several of them overlook the same valleys.

## 3. Detection model (`detect`)

This uses Track 3's detection model: p(d) = 0.5 / (1 + (d / 20 km)^4) per km flown, combined over the radars that see the cell.

**Result.** An aircraft at 150 m is in line of sight over 5,122 km². But only:
- 576 km² gives a detection chance of at least 50% per km flown;
- 2,127 km² gives at least 90% over 5 km flown.

## 4. DEM error (`mc`)

**Method.** 20 runs, each with correlated DEM noise of ±4 m (correlated over 300 m), the same noise model as Track 2.

**Result.**
- The covered area hardly moves from run to run: standard deviation 5–11 km².
- About 5% (aircraft at 150 m) and 8% (ground) of the covered area depends on the DEM error. These cells are on ridge edges.

## 5. Mast height (`mast`)

**Result.** Raising the masts from 10 m to 100 m adds 15% ground coverage (2,301 → 2,639 km²) and 10% aircraft coverage (4,965 → 5,480 km²). Choosing better sites (+29%) matters more than taller masts.
