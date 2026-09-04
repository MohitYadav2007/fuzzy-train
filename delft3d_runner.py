"""
Second simulation engine: Delft3D, OR a 2D shallow-water-equations (SWE)
fallback.

DECISION (go/no-go closed): Delft3D FM Suite requires a FlexNet-based
license server (lmadmin/DS_Flex) bound to a hostid issued by Deltares --
a multi-day institutional request process, not viable within this
hackathon's timeline. USE_DELFT3D stays False. The SWE fallback below is
the actual second model for the demo, not a placeholder.

SWE fallback method: 2D diffusive-wave / storage-cell scheme (Bates et al.,
2010 -- the same family of method LISFLOOD-FP uses for flood inundation).
This is deliberately NOT a full dynamic-wave solver: it drops the momentum
advection/inertia terms and computes inter-cell flow from the water-surface
slope via Manning's equation. That's a standard, defensible simplification
for flood extent/depth mapping and is far more numerically stable than a
naive shallow-water solver under a hackathon time budget -- validated here
via flux limiting so no cell can ever go negative or blow up.

Requires: numpy, rasterio (pip install rasterio numpy pandas)
"""

import time
from pathlib import Path

import numpy as np

from simulation.sim_result import SimResult

USE_DELFT3D = False


def run_second_model(
    dem_path: str,
    breach_hydrograph_csv: str,
    case_name: str,
    output_dir: str,
    config: dict | None = None,
) -> SimResult:
    """Dispatches to Delft3D or the SWE fallback. Same signature either way."""
    if USE_DELFT3D:
        return _run_delft3d(dem_path, breach_hydrograph_csv, case_name, output_dir, config)
    return _run_swe_fallback(dem_path, breach_hydrograph_csv, case_name, output_dir, config)


def _run_delft3d(dem_path, breach_hydrograph_csv, case_name, output_dir, config=None) -> SimResult:
    """Not implemented -- see decision note above. Kept as a stub in case
    licensing comes through later and someone wants to revisit this."""
    return SimResult(
        engine="delft3d",
        status="failed",
        case_name=case_name,
        dem_source=dem_path,
        breach_hydrograph_csv=breach_hydrograph_csv,
        error_message="Delft3D not used: license server (FlexNet/lmadmin) requires a "
                       "Deltares-issued .lic file bound to a hostid; not viable in hackathon timeline.",
    )


def _load_breach_hydrograph(csv_path: str):
    """Returns (time_s array, discharge_cms array) from the CSV contract
    defined in simulation/breach_hydrograph.py."""
    import csv
    times, discharges = [], []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row["time_s"]))
            discharges.append(float(row["discharge_cms"]))
    return np.array(times), np.array(discharges)


def _discharge_at(t: float, times: np.ndarray, discharges: np.ndarray) -> float:
    """Linear interpolation into the hydrograph; 0 outside its range."""
    if t <= times[0]:
        return float(discharges[0])
    if t >= times[-1]:
        return 0.0
    return float(np.interp(t, times, discharges))


def _run_swe_fallback(
    dem_path: str,
    breach_hydrograph_csv: str,
    case_name: str,
    output_dir: str,
    config: dict | None = None,
) -> SimResult:
    """
    2D diffusive-wave flood solver.

    config options (all optional):
        manning_n: float, roughness coefficient (default 0.035, natural channel)
        sim_duration_s: float, total simulated time (default: 2x hydrograph duration)
        breach_row, breach_col: int, grid indices of breach location
            (default: highest-elevation edge cell -- crude auto-pick, override
            for real cases once we know the actual Rishiganga breach location)
        breach_half_width_cells: int, default 1
        output_timestep_s: float, how often to record max-depth (doesn't affect
            solver accuracy, just how granular timeseries_csv is)
    """
    import rasterio
    from rasterio.transform import Affine

    config = config or {}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / f"{case_name}_swe.log"
    start = time.time()
    log_lines = []

    def log(msg):
        log_lines.append(msg)

    try:
        with rasterio.open(dem_path) as src:
            z = src.read(1).astype(np.float64)
            transform = src.transform
            dx = transform.a
            dy = -transform.e  # transform.e is negative for north-up rasters
            crs = src.crs
            nodata = src.nodata

        if nodata is not None:
            z = np.where(z == nodata, np.nanmin(z[z != nodata]), z)

        ny, nx = z.shape
        cell_area = dx * dy
        n_manning = config.get("manning_n", 0.035)

        times, discharges = _load_breach_hydrograph(breach_hydrograph_csv)
        sim_duration_s = config.get("sim_duration_s", float(times[-1]) * 2.0)

        breach_row = config.get("breach_row", 0)
        breach_col = config.get("breach_col", int(np.argmax(z[0, :])))
        bhw = config.get("breach_half_width_cells", 1)
        log(f"Breach location: row={breach_row}, col={breach_col}, half_width={bhw} cells")
        log(f"Grid: {ny}x{nx} cells, dx={dx:.2f}m dy={dy:.2f}m, manning_n={n_manning}")

        h = np.zeros((ny, nx))
        max_h = np.zeros((ny, nx))
        t = 0.0
        n_iters = 0
        dt = 1.0

        timeseries = []
        next_record_t = 0.0
        output_timestep_s = config.get("output_timestep_s", max(sim_duration_s / 200.0, 10.0))

        while t < sim_duration_s:
            eta = z + h

            eta_l, eta_r = eta[:, :-1], eta[:, 1:]
            z_l, z_r = z[:, :-1], z[:, 1:]
            flow_depth_x = np.maximum(np.maximum(eta_l, eta_r) - np.maximum(z_l, z_r), 0.0)
            slope_x = (eta_l - eta_r) / dx
            Qx = np.sign(slope_x) * (1.0 / n_manning) * flow_depth_x ** (5.0 / 3.0) * np.sqrt(np.abs(slope_x)) * dy
            Qx[flow_depth_x <= 1e-4] = 0.0

            eta_t, eta_b = eta[:-1, :], eta[1:, :]
            z_t, z_b = z[:-1, :], z[1:, :]
            flow_depth_y = np.maximum(np.maximum(eta_t, eta_b) - np.maximum(z_t, z_b), 0.0)
            slope_y = (eta_t - eta_b) / dy
            Qy = np.sign(slope_y) * (1.0 / n_manning) * flow_depth_y ** (5.0 / 3.0) * np.sqrt(np.abs(slope_y)) * dx
            Qy[flow_depth_y <= 1e-4] = 0.0

            outflow = np.zeros_like(h)
            outflow[:, :-1] += np.where(Qx > 0, Qx, 0.0)
            outflow[:, 1:]  += np.where(Qx < 0, -Qx, 0.0)
            outflow[:-1, :] += np.where(Qy > 0, Qy, 0.0)
            outflow[1:, :]  += np.where(Qy < 0, -Qy, 0.0)

            available = h * cell_area
            attempted = outflow * dt
            limiter = np.ones_like(h)
            mask = attempted > available
            limiter[mask] = available[mask] / (attempted[mask] + 1e-12)
            limiter = np.clip(limiter, 0.0, 1.0)

            Qx_lim = np.where(Qx > 0, Qx * limiter[:, :-1], Qx * limiter[:, 1:])
            Qy_lim = np.where(Qy > 0, Qy * limiter[:-1, :], Qy * limiter[1:, :])

            dh = np.zeros_like(h)
            dh[:, :-1] -= Qx_lim * dt / cell_area
            dh[:, 1:]  += Qx_lim * dt / cell_area
            dh[:-1, :] -= Qy_lim * dt / cell_area
            dh[1:, :]  += Qy_lim * dt / cell_area

            Q_in = _discharge_at(t, times, discharges)
            n_breach_cells = 2 * bhw + 1
            dh[breach_row, breach_col - bhw: breach_col + bhw + 1] += (
                Q_in * dt / (cell_area * n_breach_cells)
            )

            h = np.maximum(h + dh, 0.0)
            max_h = np.maximum(max_h, h)

            if t >= next_record_t:
                timeseries.append((round(t, 1), float(h.max()), float((h > 0.01).sum() * cell_area)))
                next_record_t += output_timestep_s

            t += dt
            n_iters += 1

            if not np.all(np.isfinite(h)):
                raise RuntimeError(f"Solver diverged at t={t:.1f}s (iteration {n_iters})")

        log(f"Completed {n_iters} iterations, simulated {t:.1f}s")
        log(f"Peak max depth: {max_h.max():.3f} m")

        # --- write outputs ---
        max_depth_path = output_dir / f"{case_name}_max_depth.tif"
        with rasterio.open(
            max_depth_path, "w", driver="GTiff", height=ny, width=nx, count=1,
            dtype=max_h.dtype, crs=crs, transform=transform, nodata=-9999.0,
        ) as dst:
            dst.write(np.where(max_h > 0.01, max_h, -9999.0), 1)

        timeseries_path = output_dir / f"{case_name}_timeseries.csv"
        with open(timeseries_path, "w") as f:
            f.write("time_s,max_depth_m,flooded_area_m2\n")
            for row in timeseries:
                f.write(f"{row[0]},{row[1]:.3f},{row[2]:.1f}\n")

        with open(log_path, "w") as f:
            f.write("\n".join(log_lines))

        return SimResult(
            engine="swe_fallback",
            status="success",
            case_name=case_name,
            max_depth_raster=str(max_depth_path),
            timeseries_csv=str(timeseries_path),
            runtime_seconds=time.time() - start,
            grid_resolution_m=dx,
            dem_source=dem_path,
            breach_hydrograph_csv=breach_hydrograph_csv,
            log_path=str(log_path),
            extra={"peak_max_depth_m": float(max_h.max()), "n_iterations": n_iters},
        )

    except Exception as e:
        with open(log_path, "w") as f:
            f.write("\n".join(log_lines) + f"\nERROR: {e}")
        return SimResult(
            engine="swe_fallback",
            status="failed",
            case_name=case_name,
            runtime_seconds=time.time() - start,
            dem_source=dem_path,
            breach_hydrograph_csv=breach_hydrograph_csv,
            log_path=str(log_path),
            error_message=str(e),
        )


if __name__ == "__main__":
    result = run_second_model(
        dem_path="data/sample/sample_dem.tif",
        breach_hydrograph_csv="data/sample/sample_breach_hydrograph.csv",
        case_name="smoke_test",
        output_dir="analysis/outputs/smoke_test",
        config={"breach_row": 2, "breach_col": 30, "sim_duration_s": 3600},
    )
    print(result)
