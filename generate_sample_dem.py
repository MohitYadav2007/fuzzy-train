"""
Generates a small synthetic DEM (GeoTIFF) so the team can test the full
pipeline (breach_hydrograph -> dualsphysics_wrapper / delft3d_runner ->
analysis -> dashboard) TODAY, without waiting on the real Rishiganga DEM.

NOT real terrain data. Replace data/sample/sample_dem.tif usage with the
real DEM (from ingestion/dem_fetch.py) as soon as it's available -- this
is purely for unblocking integration testing across the team.

Run: python simulation/generate_sample_dem.py
Requires: rasterio, numpy
"""

import numpy as np
import rasterio
from rasterio.transform import Affine

OUT_PATH = "data/sample/sample_dem.tif"

NY, NX = 200, 300           # grid cells
CELL_SIZE_M = 10.0          # resolution
# Rough placeholder origin near Rishiganga/Chamoli, Uttarakhand (30.5N, 79.7E) --
# NOT the real DEM extent, just plausible enough for CRS/coordinate sanity checks.
ORIGIN_LON, ORIGIN_LAT = 79.73, 30.55
CRS = "EPSG:4326"  # swap to a projected CRS (e.g. UTM 44N / EPSG:32644) once real DEM lands


def generate():
    x = np.arange(NX) * CELL_SIZE_M
    y = np.arange(NY) * CELL_SIZE_M
    X, Y = np.meshgrid(x, y)

    # steep valley narrowing downstream, roughly mimicking a Himalayan gorge profile:
    # high elevation upstream (row 0) descending to lower elevation downstream
    valley_center = NX / 2 + 20 * np.sin(Y / 800.0)  # meandering channel centerline
    dist_from_channel = np.abs(X - valley_center * CELL_SIZE_M)
    channel_depth = 40.0 * np.exp(-dist_from_channel / 150.0)

    elevation = (
        3000.0
        - 0.08 * Y                       # overall downstream slope
        + 0.02 * dist_from_channel        # valley walls rise away from channel
        - channel_depth                   # channel incision
    )
    elevation = elevation.astype(np.float32)

    # rough deg/pixel conversion for lat/lon so the raster is at least
    # geographically plausible near Uttarakhand -- refine when real DEM lands
    deg_per_m_lat = 1 / 111_320.0
    deg_per_m_lon = 1 / (111_320.0 * np.cos(np.radians(ORIGIN_LAT)))
    transform = Affine.translation(ORIGIN_LON, ORIGIN_LAT) * Affine.scale(
        CELL_SIZE_M * deg_per_m_lon, -CELL_SIZE_M * deg_per_m_lat
    )

    import os
    os.makedirs("data/sample", exist_ok=True)
    with rasterio.open(
        OUT_PATH, "w", driver="GTiff", height=NY, width=NX, count=1,
        dtype=elevation.dtype, crs=CRS, transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(elevation, 1)

    print(f"Wrote synthetic sample DEM to {OUT_PATH} ({NY}x{NX} cells, {CELL_SIZE_M}m resolution)")
    print(f"Elevation range: {elevation.min():.1f} - {elevation.max():.1f} m (SYNTHETIC, not real terrain)")


if __name__ == "__main__":
    generate()
