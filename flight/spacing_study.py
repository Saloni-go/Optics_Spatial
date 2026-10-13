"""Track 2 - how many positions does a route need?  Positions vs coverage accuracy for fixed
spacing and for adaptive sampling (both criteria), at valley-flying and cruise altitude.
Accuracy = Jaccard overlap of the area seen with a dense 250 m sampling of the same flight.

Results: results/flight/spacing_study.json, results/flight/fig_spacing_study.png
Run:  run.bat -m flight.spacing_study
"""
import json
import time

from common.config import RESULTS, dem_path
from common.dem_utils import DEM
from common.plots import plt, save
from flight.route import load_route, resample
from flight.visibility import AltitudeModel, run_route, run_adaptive

OUT = RESULTS / "flight"


def main():
    dem = DEM(dem_path(4000)); v = load_route()
    cases = {"valley": ("Terrain following, 300 m AGL", AltitudeModel(dem, v)),
             "cruise": ("Cruise, 5500 m MSL", AltitudeModel(dem, v, "msl", 300.0, 5500.0))}
    res = {}
    for key, (label, am) in cases.items():
        ref, _ = run_route(dem, resample(v, 250.0), am, 20000, mode="threads", workers=12)
        ref = ref.count > 0
        J = lambda u: float((ref & u).sum() / (ref | u).sum())
        rows = []
        for sp in (500, 1000, 2000, 4000, 8000):
            t = time.perf_counter(); acc, info = run_route(dem, resample(v, sp), am, 20000, mode="threads", workers=12)
            rows.append({"method": "fixed", "param": sp, "positions": info["viewsheds"], "jaccard": J(acc.count > 0),
                         "seconds": time.perf_counter() - t})
        for crit, pars in (("similarity", (0.5, 0.7, 0.85)), ("gain", (0.02, 0.05, 0.1, 0.2))):
            for par in pars:
                kw = {"tau": par} if crit == "similarity" else {"eps": par}
                t = time.perf_counter(); acc, _, info = run_adaptive(dem, v, am, 20000, criterion=crit, **kw)
                rows.append({"method": f"adaptive_{crit}", "param": par, "positions": info["viewsheds"],
                             "jaccard": J(acc.count > 0), "seconds": time.perf_counter() - t})
        res[key] = {"label": label, "rows": rows}
        for r in rows:
            print(key, r)
    json.dump(res, open(OUT / "spacing_study.json", "w"), indent=1)

    fig, axs = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    sty = {"fixed": ("o-", "#14213d", "fixed spacing"), "adaptive_similarity": ("s--", "#e76f51", "adaptive: views differ"),
           "adaptive_gain": ("^--", "#2a9d8f", "adaptive: new ground")}
    for ax, (key, d) in zip(axs, res.items()):
        for m, (mk, c, lab) in sty.items():
            rr = sorted([r for r in d["rows"] if r["method"] == m], key=lambda r: r["positions"])
            ax.plot([r["positions"] for r in rr], [100 * r["jaccard"] for r in rr], mk, c=c, label=lab, ms=5)
        for r in d["rows"]:
            if r["method"] == "fixed":
                ax.annotate(f"{r['param'] / 1000:g} km", (r["positions"], 100 * r["jaccard"]), textcoords="offset points",
                            xytext=(4, -10), fontsize=7)
        ax.set_xscale("log"); ax.set_xlabel("viewsheds computed (positions)"); ax.set_title(d["label"], fontsize=9)
    axs[0].set_ylabel("coverage overlap with 250 m sampling (%)"); axs[0].legend(fontsize=8, frameon=False)
    save(fig, OUT / "fig_spacing_study.png")


if __name__ == "__main__":
    main()
