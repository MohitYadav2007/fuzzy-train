"""
Generates a small synthetic DEM (GeoTIFF) so the team can test the full
pipeline (breach_hydrograph -> dualsphysics_wrapper / delft3d_runner ->
analysis -> dashboard) TODAY, without waiting on the real Rishiganga DEM.
NOT real terrain data. Replace data/sample/sample_dem.tif usage with the
real DEM (from ingestion/dem_fetch.py) as soon as it's available -- this
is purely for unblocking integration testing across the team.

IMPORTANT: written in a PROJECTED CRS (UTM 44N / EPSG:32644), meters,
not geographic lat/lon -- the SWE solver's Manning's-equation math assumes
dx/dy are in meters. A geographic CRS silently breaks the physics (pixel
size ends up ~0.0001 "meters" instead of ~10), so ALL DEMs used by either
simulation engine (SPH or SWE fallback) must be in a projected CRS.

Run: python simulation/generate_sample_dem.py
Requires: rasterio, numpy
"""
import numpy as np
import rasterio
from rasterio.transform import Affine

OUT_PATH = "data/sample/sample_dem.tif"
NY, NX = 200, 300           # grid cells
CELL_SIZE_M = 10.0          # resolution, meters

# Approximate UTM 44N coordinates near Rishiganga/Chamoli, Uttarakhand
# (roughly 30.55N, 79.73E) -- NOT the real DEM extent, just plausible
# enough for CRS/coordinate sanity checks.
ORIGIN_EASTING = 300000.0
ORIGIN_NORTHING = 3382000.0
CRS = "EPSG:32644"  # UTM zone 44N -- swap only if real DEM uses a different UTM zone


def generate():
    x = np.arange(NX) * CELL_SIZE_M
    y = np.arange(NY) * CELL_SIZE_M
    X, Y = np.meshgrid(x, y)

    valley_center = NX / 2 + 20 * np.sin(Y / 800.0)
    dist_from_channel = np.abs(X - valley_center * CELL_SIZE_M)
    channel_depth = 40.0 * np.exp(-dist_from_channel / 150.0)

    elevation = (
        3000.0
        - 0.08 * Y
        + 0.02 * dist_from_channel
        - channel_depth
    )
    elevation = elevation.astype(np.float32)

    transform = Affine.translation(ORIGIN_EASTING, ORIGIN_NORTHING) * Affine.scale(
        CELL_SIZE_M, -CELL_SIZE_M
    )

    import os
    os.makedirs("data/sample", exist_ok=True)
    with rasterio.open(
        OUT_PATH, "w", driver="GTiff", height=NY, width=NX, count=1,
        dtype=elevation.dtype, crs=CRS, transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(elevation, 1)

    print(f"Wrote synthetic sample DEM to {OUT_PATH} ({NY}x{NX} cells, {CELL_SIZE_M}m resolution, {CRS})")
    print(f"Elevation range: {elevation.min():.1f} - {elevation.max():.1f} m (SYNTHETIC, not real terrain)")


if __name__ == "__main__":
    generate()
