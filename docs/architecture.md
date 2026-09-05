# Architecture & Interfaces

## Status (updated by GPU/simulation owner)

- **DualSPHysics**: installed locally, GPU-verified on RTX 4060 (compute 8.9)
  against the official dam-break tutorial. Confirmed via CUDA device log
  and `nvidia-smi` showing the solver as a live Compute (`C`) process.
  `dualsphysics_wrapper.py` scripting still in progress (TODOs in file).
- **Delft3D: CLOSED, no-go.** Delft3D FM Suite 2026 installs and launches,
  but requires a FlexNet-based license server (`lmadmin`/`DS_Flex`) bound to
  a hostid that Deltares issues on request -- a multi-day institutional
  process, not viable in a 1-week hackathon. Not a setup mistake on our
  end; this is how Deltares' licensing model works for this suite.
- **Second model = Python shallow-water-equations (SWE) fallback, and it's
  implemented and working**, not just a stub. `simulation/delft3d/delft3d_runner.py`,
  `_run_swe_fallback()`. Method: 2D diffusive-wave / storage-cell scheme
  (Bates et al. 2010 -- same family as LISFLOOD-FP), with explicit flux
  limiting so the solver can't go unstable. Validated: 1800+ timestep runs,
  stable, volume-conserving, sub-second runtime on a 40x60 test grid.
  `USE_DELFT3D = False` is the active setting.

## Simulation output contract

Both `simulation/sph/dualsphysics_wrapper.py::run_sph_simulation()` and
`simulation/delft3d/delft3d_runner.py::run_second_model()` return a
`SimResult` (`simulation/sim_result.py`) -- same shape regardless of which
engine actually ran (`engine` field tells you: `"dualsphysics"` |
`"delft3d"` | `"swe_fallback"`).

```python
SimResult(
    engine, status, case_name,
    max_depth_raster,      # GeoTIFF path
    max_velocity_raster,   # GeoTIFF path, optional
    flood_extent_vector,   # .shp/.geojson path
    timeseries_csv,        # time_s, max_depth_m, flooded_area_m2
    runtime_seconds, grid_resolution_m, dem_source,
    breach_hydrograph_csv, log_path, error_message,
)
```

Consumers: `simulation/compare.py`, `analysis/raster_to_vector.py`,
`analysis/damage_estimation.py`, `dashboard/backend/tasks.py` + `routes/`.

## Test data available right now (before the real Rishiganga DEM lands)

- `simulation/generate_sample_dem.py` -> `data/sample/sample_dem.tif`
  (synthetic 200x300 grid, roughly Himalayan-gorge-shaped, placed near
  real Rishiganga/Chamoli coordinates for CRS sanity -- **not real terrain**)
- `data/sample/sample_breach_hydrograph.csv` (synthetic triangular-pulse
  hydrograph -- **not real discharge data**)
- Together these let anyone run `run_second_model()` end-to-end today and
  get a real `SimResult` with a real GeoTIFF and timeseries CSV back.

Swap both for real data (`ingestion/dem_fetch.py` output, and the real
breach-model-derived hydrograph per `docs/breach_model.md`) the moment
they're available -- no code changes needed, same file paths.

## Breach hydrograph input contract

```
time_s,discharge_cms
0,0
60,120.5
...
```

## Demo case

Rishiganga River, Uttarakhand -- replicating the Feb 2021 glacial lake
outburst flood as our documented ground-truth comparison case.
