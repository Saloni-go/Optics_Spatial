"""Plot helpers: hillshade base maps in km coordinates, consistent styling across tracks."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from osgeo import gdal

from common.config import DATA

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.linewidth": 0.6,
                     "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 200,
                     "savefig.bbox": "tight"})

C_VIS = "#f2a541"     # visible
C_ROUTE = "#1d3557"
C_RADAR = "#e63946"


def extent_km(gt, shape):
    x0, y1 = gt[0], gt[3]
    x1, y0 = gt[0] + gt[1] * shape[1], gt[3] + gt[5] * shape[0]
    return [x0 / 1000, x1 / 1000, y0 / 1000, y1 / 1000]


def hillshade_for(dem, size=None):
    p = DATA / f"hillshade_{size}.tif" if size else None
    if p is not None and p.exists():
        return gdal.Open(str(p)).ReadAsArray()
    ds = gdal.DEMProcessing("", dem.path, "hillshade", format="MEM", zFactor=1.5, computeEdges=True)
    return ds.ReadAsArray()


def base_map(ax, dem, size=None, alpha=1.0, elev_tint=True):
    ext = extent_km(dem.gt, dem.shape)
    hs = hillshade_for(dem, size)
    ax.imshow(hs, cmap="gray", extent=ext, vmin=0, vmax=255, alpha=alpha, interpolation="bilinear")
    if elev_tint:
        ax.imshow(dem.z, cmap="terrain", extent=ext, alpha=0.35, interpolation="bilinear")
    ax.set_xlabel("Easting (km, UTM 44N)"); ax.set_ylabel("Northing (km)")
    ax.set_aspect("equal")
    return ext


def km(x):
    return np.asarray(x) / 1000.0


def save(fig, path):
    fig.savefig(path)
    plt.close(fig)
