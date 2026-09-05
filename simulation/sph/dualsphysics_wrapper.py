"""
Programmatic wrapper around the DualSPHysics GPU solver.

STATUS: DualSPHysics installed and GPU-verified locally (RTX 4060, sm 8.9,
official dam-break tutorial confirmed running on GPU). This wrapper is the
next piece -- implementation in progress. Signature below is stable; build
against it.

Pipeline this wraps (currently done by hand via the tutorial, being scripted):
  1. Take a DEM + breach hydrograph CSV
  2. Generate a GenCase XML case definition from a config template
  3. Run GenCase4_win64.exe to build particles
  4. Run DualSPHysics5.4_win64.exe -gpu on the generated case
  5. Post-process .bi4 particle output -> max depth raster + extent polygon
  6. Return a SimResult (see simulation/sim_result.py)
"""

import subprocess
import time
from pathlib import Path

from simulation.sim_result import SimResult

# TODO: move to simulation/sph/config/paths.yaml once we have a shared config loader
DUALSPHYSICS_BIN_DIR = Path(r"C:\DualSPHysics\DualSPHysics_v5.4\bin\windows")
GENCASE_EXE = DUALSPHYSICS_BIN_DIR / "GenCase4_win64.exe"
DUALSPHYSICS_EXE = DUALSPHYSICS_BIN_DIR / "DualSPHysics5.4_win64.exe"


def run_sph_simulation(
    dem_path: str,
    breach_hydrograph_csv: str,
    case_name: str,
    output_dir: str,
    config: dict | None = None,
) -> SimResult:
    """
    Run a DualSPHysics dam-break/GLOF simulation.

    Args:
        dem_path: path to a DEM (.tif) defining terrain for the case
        breach_hydrograph_csv: CSV with columns [time_s, discharge_cms],
            produced by simulation/breach_hydrograph.py
        case_name: short id, e.g. "rishiganga_glof_2021"
        output_dir: where to write raster/vector outputs (analysis/outputs/<case_name>/)
        config: overrides for simulation/sph/config/ template (particle size,
            duration, viscosity model, etc). None = use defaults.

    Returns:
        SimResult with engine="dualsphysics"
    """
    config = config or {}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / f"{case_name}_dualsphysics.log"
    start = time.time()

    try:
        # TODO Step 1: generate GenCase XML from DEM + config template
        #   -> simulation/sph/config/case_template.xml, filled in with dem_path,
        #      particle spacing (config.get("dp", 0.02)), domain bounds, etc.
        # TODO Step 2: inject breach hydrograph as an inflow/moving-boundary condition
        #   -> DualSPHysics supports inlet zones driven by a flow-rate function;
        #      need to map breach_hydrograph_csv -> inlet velocity/flow XML block.
        # TODO Step 3: run GenCase, then DualSPHysics -gpu, capture stdout to log_path
        #   subprocess.run([str(GENCASE_EXE), ...], check=True, ...)
        #   subprocess.run([str(DUALSPHYSICS_EXE), "-gpu", ...], check=True, ...)
        # TODO Step 4: post-process .bi4 output with DualSPHysics' PartVTK/BoundaryVTK
        #   tools -> derive max water depth per grid cell -> write GeoTIFF
        #   (analysis/raster_to_vector.py will consume this raster)
        raise NotImplementedError("dualsphysics_wrapper: simulation run not yet implemented")

    except Exception as e:
        return SimResult(
            engine="dualsphysics",
            status="failed",
            case_name=case_name,
            runtime_seconds=time.time() - start,
            dem_source=dem_path,
            breach_hydrograph_csv=breach_hydrograph_csv,
            log_path=str(log_path),
            error_message=str(e),
        )


if __name__ == "__main__":
    # Quick manual smoke test once implemented:
    result = run_sph_simulation(
        dem_path="data/sample/rishiganga_dem_sample.tif",
        breach_hydrograph_csv="data/sample/sample_breach_hydrograph.csv",
        case_name="smoke_test",
        output_dir="analysis/outputs/smoke_test",
    )
    print(result)
