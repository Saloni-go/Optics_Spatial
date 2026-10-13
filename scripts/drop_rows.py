"""Remove the rows of given experiments from a benchmark CSV (before re-running them).
Usage: python scripts/drop_rows.py <csv> <experiment> [<experiment> ...]"""
import csv
import sys

path, drop = sys.argv[1], set(sys.argv[2:])
rows = list(csv.DictReader(open(path, newline="")))
fields = list(rows[0].keys()) if rows else []
keep = [r for r in rows if r["experiment"] not in drop]
with open(path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(keep)
print(f"{path}: removed {len(rows) - len(keep)} rows of {sorted(drop)}")
