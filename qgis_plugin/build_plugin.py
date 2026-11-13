"""Assemble the installable QGIS plugin ZIP (Plugins > Manage and Install Plugins > Install from ZIP).

    run.bat qgis_plugin\\build_plugin.py [--sizes 1000 2000 4000]

Copies the plugin GUI (qgis_plugin/visibility_corridor), the Track 3 engine it runs on (corridor/, common/
and the compiled C solver, without the C sources), the bundled DEMs and a scenario file with the project's
radar sites and endpoints, then zips everything to qgis_plugin/dist/visibility_corridor-<version>.zip.
"""
import argparse
import configparser
import json
import py_compile
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SRC = ROOT / "qgis_plugin" / "visibility_corridor"
BUILD = ROOT / "qgis_plugin" / "build" / "visibility_corridor"
DIST = ROOT / "qgis_plugin" / "dist"

ENGINE = {"common": ["__init__.py", "config.py", "dem_utils.py", "sites.py"],
          "corridor": ["__init__.py", "cgrid.py", "optimizer.py", "exposure.py", "prep.py", "radarfield.py",
                       "interactive_core.py", "riskcsp.py", "liveview.py"],
          "flight": ["__init__.py", "route.py", "visibility.py"]}
KM = {500: 15, 1000: 30, 2000: 60, 4000: 120}


def scenario(size):
    """Radar sites and endpoints exactly as the project's interactive demo uses them."""
    from common.config import dem_path
    from common.dem_utils import DEM
    from corridor.exposure import blocked_mask
    from corridor.interactive_core import scenario_endpoints
    from corridor.prep import sites_for
    dem = DEM(dem_path(size))
    sites = [list(map(float, s)) for s in sites_for(dem, size, 6)]
    s, g = scenario_endpoints(dem, size, blocked_mask(dem))
    return {"dem": f"dem_{size}.tif", "sites": sites,
            "start": list(dem.to_world(s[1], s[0])), "goal": list(dem.to_world(g[1], g[0])),
            "title": f"Garhwal Himalaya demo: {size} x {size} cells ({KM.get(size, size * 0.03):g} km, {size * size / 1e6:g} M cells)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000, 2000, 4000])
    a = ap.parse_args()
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    for f in SRC.iterdir():
        if f.suffix in (".py", ".txt", ".svg"):
            shutil.copy2(f, BUILD / f.name)
    eng = BUILD / "engine"
    for pkg, files in ENGINE.items():
        (eng / pkg).mkdir(parents=True)
        for name in files:
            shutil.copy2(ROOT / pkg / name, eng / pkg / name)
    (eng / "corridor" / "c").mkdir()
    shutil.copy2(ROOT / "corridor" / "c" / "gridsearch.dll", eng / "corridor" / "c" / "gridsearch.dll")
    (eng / "data").mkdir()
    scen = {}
    for size in a.sizes:
        shutil.copy2(ROOT / "data" / f"dem_{size}.tif", eng / "data" / f"dem_{size}.tif")
        scen[str(size)] = scenario(size)
        print("scenario", size, scen[str(size)]["title"])
    json.dump(scen, open(eng / "data" / "scenarios.json", "w"), indent=1)
    for f in BUILD.rglob("*.py"):
        py_compile.compile(str(f), doraise=True, cfile=str(f) + ".check")
        Path(str(f) + ".check").unlink()
    meta = configparser.ConfigParser(); meta.read(SRC / "metadata.txt")
    version = meta["general"]["version"]
    DIST.mkdir(exist_ok=True)
    out = DIST / f"visibility_corridor-{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(BUILD.rglob("*")):
            if f.is_file():
                z.write(f, Path("visibility_corridor") / f.relative_to(BUILD))
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
