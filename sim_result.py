"""
Shared contract for simulation engine outputs.

BOTH simulation/sph/dualsphysics_wrapper.py and simulation/delft3d/delft3d_runner.py
(including the SWE fallback, if we go that route) MUST return a SimResult with this
shape. This is the one thing everyone else on the team can build against starting
today, even before either engine is fully wired up.

Consumers of this contract:
- simulation/compare.py        -> diffs two SimResults (SPH vs Delft3D/SWE)
- analysis/raster_to_vector.py -> reads max_depth_raster, converts to .shp/.kml
- analysis/damage_estimation.py-> reads max_depth_raster + flood_extent_vector
- dashboard/backend/tasks.py   -> stores this dict, exposes it via routes/ to frontend
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import json


@dataclass
class SimResult:
    engine: str                      # "dualsphysics" | "delft3d" | "swe_fallback"
    status: str                      # "success" | "failed" | "running"
    case_name: str                   # e.g. "rishiganga_glof_2021"

    # Primary outputs (paths, not the data itself -- keep results out of git,
    # data/processed/ and analysis/outputs/ are gitignored for a reason)
    max_depth_raster: Optional[str] = None      # GeoTIFF, flood depth in meters
    max_velocity_raster: Optional[str] = None   # GeoTIFF, optional
    flood_extent_vector: Optional[str] = None   # .shp or .geojson polygon of max extent
    timeseries_csv: Optional[str] = None        # depth/velocity at gauge points over time

    # Metadata every engine must report, for the comparison dashboard
    runtime_seconds: Optional[float] = None
    grid_resolution_m: Optional[float] = None
    dem_source: Optional[str] = None
    breach_hydrograph_csv: Optional[str] = None  # input used, for traceability
    log_path: Optional[str] = None
    error_message: Optional[str] = None
    extra: dict = field(default_factory=dict)   # engine-specific info, don't rely on this

    def to_json(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @staticmethod
    def from_json(path: str) -> "SimResult":
        with open(path) as f:
            return SimResult(**json.load(f))
