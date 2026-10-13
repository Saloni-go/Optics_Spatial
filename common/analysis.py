"""Reading benchmark CSVs: medians per configuration and power-law fits (empirical complexity)."""
import csv
import json
import statistics
from collections import defaultdict

import numpy as np


def load(csv_path):
    rows = list(csv.DictReader(open(csv_path)))
    for r in rows:
        for k in ("runtime_s", "compute_s", "peak_rss_kb", "base_rss_kb", "param_value", "dem_id"):
            try:
                r[k] = float(r[k])
            except (ValueError, TypeError, KeyError):
                r[k] = None
        r["extra"] = json.loads(r["notes"]) if r.get("notes") else {}
    return rows


def medians(rows, experiment):
    """{algorithm: [(param_value, median runtime, median compute, median peak MB, n, extra)]} sorted by param."""
    g = defaultdict(list)
    for r in rows:
        if r["experiment"] == experiment:
            g[(r["algorithm"], r["param_value"])].append(r)
    out = defaultdict(list)
    for (alg, pv), rs in g.items():
        med = lambda k: statistics.median([x[k] for x in rs if x[k] is not None]) if any(x[k] is not None for x in rs) else None
        ex = {}
        for k in ("waypoints", "graph_nodes", "radar_count"):      # numeric schema columns reported by jobs
            vals = []
            for x in rs:
                try:
                    vals.append(float(x.get(k)))
                except (TypeError, ValueError):
                    pass
            if vals:
                ex[k] = statistics.median(vals)
        for k in rs[0]["extra"]:
            vals = [x["extra"].get(k) for x in rs if isinstance(x["extra"].get(k), (int, float))]
            if vals:
                ex[k] = statistics.median(vals)
        out[alg].append({"param": pv, "runtime": med("runtime_s"), "compute": med("compute_s"),
                         "peak_mb": med("peak_rss_kb") / 1024, "base_mb": (med("base_rss_kb") or 0) / 1024,
                         "n": len(rs), "runs": [x["runtime_s"] for x in rs], **ex})
    for alg in out:
        out[alg].sort(key=lambda d: d["param"])
    return out


def power_fit(x, y):
    """Fit y = c * x^b on log-log axes; returns b (empirical exponent) and c."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = (x > 0) & (y > 0)
    if ok.sum() < 2:
        return None, None
    b, a = np.polyfit(np.log(x[ok]), np.log(y[ok]), 1)
    return float(b), float(np.exp(a))
