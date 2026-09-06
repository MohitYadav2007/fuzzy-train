"""
Programmatic wrapper around the DualSPHysics GPU solver — CHANNEL-PROXY
geometry approach (not full DEM->STL terrain import).

SCOPE DECISION: DualSPHysics does not natively ingest raster DEMs -- it
needs geometry as an STL mesh or built-in primitive shapes. A full
DEM->STL terrain pipeline is real but high-risk this close to deadline
(STL geometry from real terrain commonly needs multiple iterations to
avoid holes/bad normals/stepped surfaces -- a known pain point even for
experienced DualSPHysics users). Given no local GPU access to iterate
blind, we use a SIMPLIFIED CHANNEL PROXY instead: a straight, sloped
trapezoidal channel whose slope/width/depth are derived from the real
DEM's summary statistics, built entirely from GenCase's built-in box
primitives (no STL, no external mesh tooling). This is a standard,
defensible simplification for idealized dam-break/flume SPH studies,
NOT a shortcut taken carelessly -- document this in the demo narrative
alongside the Delft3D->SWE-fallback decision.

Water enters via an Inlet/Outlet (InOut) zone at the upstream end, driven
by the SAME breach hydrograph CSV the SWE fallback consumes -- no initial
standing water block, for a fair, consistent comparison between engines.

======================== VERIFY-BEFORE-TRUSTING CHECKLIST ========================
(For Ayush, first real run on the RTX 4060 -- these are the specific
assumptions in this file that need confirming against the real toolchain,
since this was written without GPU/GenCase access to test against.)

  1. Binary paths/names below (GENCASE_EXE, DUALSPHYSICS_EXE, MEASURETOOL_EXE)
     -- confirm exact filenames in your DualSPHysics_v5.4/bin/windows folder.
  2. <mkconfig boundcount=... fluidcount=...> values in _build_gencase_xml()
     are generous placeholders. If GenCase errors about exceeding these,
     increase them (check the GenCase log for the actual counts it wants).
  3. MeasureTool's exact variable name for water-surface elevation / depth
     -- run `MeasureTool -h` (or `MeasureTool_win64.exe -h`) to confirm the
     correct -vars: flag. `_extract_max_depth_via_measuretool()` currently
     assumes `+zsurf`; this is the most likely wrong guess in this file.
  4. The discharge->velocity conversion in `_hydrograph_to_velocity_time()`
     assumes a FIXED inlet cross-sectional area (channel_width *
     channel_depth). This is a simplification -- real inlet area changes
     as flow depth rises. Fine for a proxy demo comparison; flag it in the
     write-up.
  5. `dp` (particle spacing, config["dp"]) directly controls particle count
     and GPU memory. Start coarse (e.g. dp=1.0 or 2.0, meaning 1-2m spacing)
     and only go finer if the RTX 4060's 8GB VRAM has headroom -- an 8GB
     card will run out of memory fast on a real-scale channel at fine dp.

Requires: numpy, rasterio (already in simulation/requirements.txt)
"""

import csv
import subprocess
import time
from pathlib import Path

import numpy as np

from simulation.sim_result import SimResult

# TODO: move to simulation/sph/config/paths.yaml once we have a shared config loader
DUALSPHYSICS_BIN_DIR = Path(r"C:\DualSPHysics\DualSPHysics_v5.4\bin\windows")
GENCASE_EXE = DUALSPHYSICS_BIN_DIR / "GenCase4_win64.exe"
DUALSPHYSICS_EXE = DUALSPHYSICS_BIN_DIR / "DualSPHysics5.4_win64.exe"
MEASURETOOL_EXE = DUALSPHYSICS_BIN_DIR / "MeasureTool_win64.exe"  # VERIFY exact filename


def run_sph_simulation(
    dem_path: str,
    breach_hydrograph_csv: str,
    case_name: str,
    output_dir: str,
    config: dict | None = None,
) -> SimResult:
    """
    Run a DualSPHysics dam-break/GLOF simulation using a channel-proxy
    geometry derived from dem_path's summary statistics (NOT the full
    raster terrain -- see module docstring for why).

    Args:
        dem_path: path to a DEM (.tif), used only to derive channel slope/
            width/depth statistics and to georeference the output raster --
            NOT imported as full terrain geometry.
        breach_hydrograph_csv: CSV with columns [time_s, discharge_cms],
            same contract as simulation/breach_hydrograph.py produces.
        case_name: short id, e.g. "rishiganga_glof_2021"
        output_dir: where to write raster/log outputs (analysis/outputs/<case_name>/)
        config: optional overrides -- see _derive_channel_params_from_dem()
            and _build_gencase_xml() for available keys (dp, manning-like
            wall roughness is not modeled in SPH the same way; channel_width_m,
            channel_depth_m, n_channel_segments, sim_duration_s, etc.)

    Returns:
        SimResult with engine="dualsphysics"
    """
    config = config or {}
    output_dir = Path(output_dir)
    case_dir = output_dir / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / f"{case_name}_dualsphysics.log"
    start = time.time()
    log_lines = []

    def log(msg):
        log_lines.append(msg)
        print(msg)

    try:
        for exe, label in [
            (GENCASE_EXE, "GenCase"),
            (DUALSPHYSICS_EXE, "DualSPHysics"),
        ]:
            if not exe.exists():
                raise FileNotFoundError(
                    f"{label} executable not found at {exe} -- check "
                    f"DUALSPHYSICS_BIN_DIR at the top of this file."
                )

        # --- Step 1: derive channel-proxy geometry params from the real DEM ---
        dem_meta, channel = _derive_channel_params_from_dem(dem_path, config)
        log(f"Channel proxy: slope={channel['slope']:.4f}, "
            f"width={channel['channel_width_m']:.1f}m, "
            f"depth={channel['channel_depth_m']:.1f}m, "
            f"length={channel['length_m']:.1f}m")

        # --- Step 2: load breach hydrograph, convert discharge -> inlet velocity ---
        times, discharges = _load_breach_hydrograph(breach_hydrograph_csv)
        velocity_time_points = _hydrograph_to_velocity_time(
            times, discharges, channel, config
        )
        sim_duration_s = config.get("sim_duration_s", float(times[-1]) * 1.5)
        log(f"Inlet velocity range: {min(v for _, v in velocity_time_points):.2f} - "
            f"{max(v for _, v in velocity_time_points):.2f} m/s, "
            f"sim_duration_s={sim_duration_s:.0f}")

        # --- Step 3: build GenCase XML ---
        case_def_path = case_dir / f"{case_name}_Def.xml"
        dp = config.get("dp", 1.0)  # particle spacing, metres -- VERIFY item #5
        xml_content = _build_gencase_xml(
            case_name=case_name,
            channel=channel,
            velocity_time_points=velocity_time_points,
            dp=dp,
            sim_duration_s=sim_duration_s,
            config=config,
        )
        case_def_path.write_text(xml_content)
        log(f"Wrote GenCase definition: {case_def_path}")

        # --- Step 4: run GenCase ---
        gencase_out_prefix = case_dir / case_name  # GenCase appends .xml/.bi4
        gencase_cmd = [str(GENCASE_EXE), str(case_def_path.with_suffix("")),
                        str(gencase_out_prefix), "-save:all"]
        log(f"Running GenCase: {' '.join(gencase_cmd)}")
        _run_subprocess(gencase_cmd, log)

        # --- Step 5: run DualSPHysics on GPU ---
        sim_out_dir = case_dir / f"{case_name}_out"
        dualsph_cmd = [
            str(DUALSPHYSICS_EXE),
            str(gencase_out_prefix),
            str(sim_out_dir),
            "-gpu",
            "-svres",
        ]
        log(f"Running DualSPHysics -gpu: {' '.join(dualsph_cmd)}")
        _run_subprocess(dualsph_cmd, log)

        # --- Step 6: extract max water depth on a grid, write GeoTIFF ---
        max_depth_path = case_dir / f"{case_name}_max_depth.tif"
        _extract_max_depth_via_measuretool(
            sim_out_dir=sim_out_dir,
            channel=channel,
            dem_meta=dem_meta,
            out_tif_path=max_depth_path,
            log=log,
        )

        with open(log_path, "w") as f:
            f.write("\n".join(log_lines))

        return SimResult(
            engine="dualsphysics",
            status="success",
            case_name=case_name,
            max_depth_raster=str(max_depth_path),
            runtime_seconds=time.time() - start,
            grid_resolution_m=dp,
            dem_source=dem_path,
            breach_hydrograph_csv=breach_hydrograph_csv,
            log_path=str(log_path),
            extra={
                "geometry_type": "channel_proxy",
                "channel_params": channel,
            },
        )

    except Exception as e:
        log(f"ERROR: {e}")
        with open(log_path, "w") as f:
            f.write("\n".join(log_lines))
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


def _run_subprocess(cmd: list[str], log) -> None:
    """Runs a subprocess, streams output into the log list, raises on nonzero exit."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    log(result.stdout)
    if result.returncode != 0:
        log(result.stderr)
        raise RuntimeError(f"Command failed (exit {result.returncode}): {' '.join(cmd)}")


def _derive_channel_params_from_dem(dem_path: str, config: dict) -> tuple[dict, dict]:
    """
    Reads summary statistics from the real DEM to shape the channel-proxy
    geometry -- NOT a full terrain import, just slope/width/depth.

    Returns (dem_meta, channel_params). dem_meta carries the DEM's CRS/
    transform so the OUTPUT raster can be georeferenced consistently with
    the real DEM, even though the SPH geometry itself is a simplified proxy.

    channel_params keys:
        slope: dimensionless (rise/run) -- estimated from mean elevation
            drop between the DEM's first and last N rows.
        length_m, channel_width_m, channel_depth_m: derived or config-overridden.
        n_segments: number of stepped box segments approximating the slope
            (GenCase geometry is axis-aligned boxes, so any slope is a
            staircase approximation -- this is also how GenCase rasterizes
            ANY boundary internally, so it's not an unusual simplification).
    """
    import rasterio

    with rasterio.open(dem_path) as src:
        z = src.read(1).astype(np.float64)
        transform = src.transform
        crs = src.crs
        nodata = src.nodata
        dx = transform.a
        dy = -transform.e

    if nodata is not None:
        z = np.where(z == nodata, np.nanmedian(z[z != nodata]), z)

    ny, nx = z.shape
    length_m = ny * dy
    domain_width_m = nx * dx

    n_edge_rows = max(1, ny // 20)
    elev_top = float(np.mean(z[:n_edge_rows, :]))
    elev_bottom = float(np.mean(z[-n_edge_rows:, :]))
    slope = config.get("slope_override", abs(elev_top - elev_bottom) / length_m)

    elev_range = float(np.max(z) - np.min(z))

    dem_meta = {"crs": crs, "transform": transform, "shape": (ny, nx)}
    channel = {
        "slope": slope,
        "length_m": config.get("channel_length_m", min(length_m, 500.0)),
        "channel_width_m": config.get("channel_width_m", max(domain_width_m * 0.15, 10.0)),
        "channel_depth_m": config.get("channel_depth_m", max(elev_range * 0.3, 5.0)),
        "wall_height_m": config.get("wall_height_m", max(elev_range * 0.5, 10.0)),
        "n_segments": config.get("n_channel_segments", 15),
        "elev_top": elev_top,
    }
    return dem_meta, channel


def _load_breach_hydrograph(csv_path: str):
    """Same contract/logic as delft3d_runner.py's loader -- kept identical
    on purpose so both engines interpret the hydrograph CSV the same way."""
    times, discharges = [], []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row["time_s"]))
            discharges.append(float(row["discharge_cms"]))
    return np.array(times), np.array(discharges)


def _hydrograph_to_velocity_time(
    times: np.ndarray, discharges: np.ndarray, channel: dict, config: dict,
    max_points: int = 60,
) -> list[tuple[float, float]]:
    """
    Converts discharge (m3/s) -> inlet velocity (m/s) using a FIXED inlet
    cross-sectional area (channel_width * channel_depth) -- see VERIFY
    item #4 in the module docstring. Downsamples to max_points entries
    since GenCase's <velocitytime> table doesn't need every original row
    and a huge table just bloats the XML.
    """
    inlet_area = channel["channel_width_m"] * channel["channel_depth_m"]
    if len(times) > max_points:
        sample_idx = np.linspace(0, len(times) - 1, max_points).astype(int)
        times, discharges = times[sample_idx], discharges[sample_idx]

    velocities = discharges / inlet_area
    return list(zip(times.tolist(), velocities.tolist()))


def _build_gencase_xml(
    case_name: str,
    channel: dict,
    velocity_time_points: list[tuple[float, float]],
    dp: float,
    sim_duration_s: float,
    config: dict,
) -> str:
    """
    Builds a GenCase case-definition XML: a staircase-approximated sloped
    channel (bed + two side walls) as boundary particles, plus one InOut
    zone at the upstream end driven by velocity_time_points.

    Schema confirmed against DualSPHysics' official examples (01_DamBreak,
    inletoutlet examples) -- see module docstring VERIFY items for the
    specific pieces that still need confirming against a real GenCase run.
    """
    length = channel["length_m"]
    width = channel["channel_width_m"]
    depth = channel["channel_depth_m"]
    wall_h = channel["wall_height_m"]
    slope = channel["slope"]
    n_seg = channel["n_segments"]
    seg_len = length / n_seg

    domain_pointmin = f'x="-1" y="-1" z="-1"'
    domain_pointmax = f'x="{length + 1:.2f}" y="{width + 1:.2f}" z="{wall_h + depth + 1:.2f}"'

    bed_segments_xml = []
    for i in range(n_seg):
        x0 = i * seg_len
        x1 = (i + 1) * seg_len
        z_bed = -slope * x0  # descending downstream, staircase step per segment
        bed_segments_xml.append(f"""
                    <drawbox>
                        <point x="{x0:.3f}" y="0" z="{z_bed:.3f}" />
                        <size x="{seg_len:.3f}" y="{width:.3f}" z="0.3" />
                    </drawbox>""")

    walls_xml = f"""
                    <drawbox>
                        <point x="0" y="0" z="{-slope * length:.3f}" />
                        <size x="{length:.3f}" y="0.3" z="{wall_h:.3f}" />
                    </drawbox>
                    <drawbox>
                        <point x="0" y="{width:.3f}" z="{-slope * length:.3f}" />
                        <size x="{length:.3f}" y="0.3" z="{wall_h:.3f}" />
                    </drawbox>"""

    velocitytime_entries = "\n".join(
        f'                        <timevalue time="{t:.2f}" v="{v:.4f}" />'
        for t, v in velocity_time_points
    )

    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<case>
    <casedef>
        <constantsdef>
            <gravity x="0" y="0" z="-9.81" comment="Gravitational acceleration" units_comment="m/s^2" />
            <rhop0 value="1000" comment="Reference density of water" units_comment="kg/m^3" />
            <hswl value="0" auto="true" />
            <gamma value="7" />
            <speedsystem value="0" auto="true" />
            <coefsound value="20" />
            <speedsound value="0" auto="true" />
            <coefh value="1.0" />
            <cflnumber value="0.2" />
        </constantsdef>
        <mkconfig boundcount="240" fluidcount="240" comment="VERIFY: raise if GenCase log reports exceeding these" />
        <geometry>
            <definition dp="{dp}" units_comment="metres (m)">
                <pointmin {domain_pointmin} />
                <pointmax {domain_pointmax} />
            </definition>
            <commands>
                <mainlist>
                    <setshapemode>dp | bound</setshapemode>
                    <setdrawmode mode="full" />
                    <setmkbound mk="0" />
                    {''.join(bed_segments_xml)}
                    {walls_xml}
                </mainlist>
            </commands>
        </geometry>
        <inout>
            <zone comment="Breach inflow, upstream end of channel">
                <zone2d>
                    <point x="0" y="0" />
                    <size x="0.5" y="{width:.3f}" />
                    <direction x="1" y="0" />
                </zone2d>
                <imposevelocity mode="1" comment="0:Fixed,1:Variable in time,2:Extrapolated">
                    <velocitytime>
{velocitytime_entries}
                    </velocitytime>
                </imposevelocity>
                <imposezsurf mode="0">
                    <zsurf value="{depth:.2f}" />
                </imposezsurf>
            </zone>
        </inout>
    </casedef>
    <execution>
        <parameters>
            <parameter key="StepAlgorithm" value="2" />
            <parameter key="Boundary" value="2" comment="1:DBC, 2:mDBC" />
            <parameter key="TimeMax" value="{sim_duration_s:.1f}" />
            <parameter key="TimeOut" value="{max(sim_duration_s / 100.0, 1.0):.2f}" />
        </parameters>
    </execution>
</case>
"""


def _extract_max_depth_via_measuretool(
    sim_out_dir: Path, channel: dict, dem_meta: dict, out_tif_path: Path, log,
) -> None:
    """
    Samples water surface elevation on a grid across all output timesteps
    using DualSPHysics' MeasureTool, takes the max, writes a GeoTIFF
    georeferenced to the ORIGINAL real DEM's CRS/transform (even though
    the SPH geometry itself is the channel proxy) so downstream
    raster_to_vector.py can treat this the same as the SWE fallback's output.

    VERIFY item #3: the -vars: flag below assumes `+zsurf` is the correct
    MeasureTool variable name for free-surface elevation. Run
    `MeasureTool_win64.exe -h` first to confirm before trusting this.
    """
    import rasterio

    ny, nx = dem_meta["shape"]
    length, width = channel["length_m"], channel["channel_width_m"]
    step_x, step_y = length / nx, width / ny

    points_file = sim_out_dir / "measure_points.txt"
    with open(points_file, "w") as f:
        f.write("POINTSLIST\n")
        f.write(f"BeginX 0 BeginY 0 BeginZ 0 StepX {step_x:.4f} StepY {step_y:.4f} "
                f"StepZ 0 CountX {nx} CountY {ny} CountZ 1\n")

    measure_csv = sim_out_dir / "measure_out.csv"
    cmd = [
        str(MEASURETOOL_EXE),
        "-dirin", str(sim_out_dir / "data"),
        "-points", str(points_file),
        "-onlytype:-all,+fluid",
        "-vars:-all,+zsurf",  # VERIFY item #3
        "-savecsv", str(measure_csv),
    ]
    log(f"Running MeasureTool: {' '.join(cmd)}")
    _run_subprocess(cmd, log)

    # Parse MeasureTool's CSV, take max zsurf per point across all timesteps,
    # reshape to the DEM's grid, write as GeoTIFF.
    import pandas as pd
    df = pd.read_csv(measure_csv, sep=";")  # VERIFY separator -- MeasureTool often uses ';'
    max_depth = df.groupby(["PointX", "PointY"])["zsurf"].max().values.reshape(ny, nx)
    max_depth = np.clip(max_depth, 0, None).astype(np.float32)

    with rasterio.open(
        out_tif_path, "w", driver="GTiff", height=ny, width=nx, count=1,
        dtype=max_depth.dtype, crs=dem_meta["crs"], transform=dem_meta["transform"],
        nodata=-9999.0,
    ) as dst:
        dst.write(np.where(max_depth > 0.01, max_depth, -9999.0), 1)

    log(f"Wrote max-depth raster: {out_tif_path}")


if __name__ == "__main__":
    result = run_sph_simulation(
        dem_path="data/sample/sample_dem.tif",
        breach_hydrograph_csv="data/sample/sample_breach_hydrograph.csv",
        case_name="smoke_test",
        output_dir="analysis/outputs",
        config={"dp": 2.0, "sim_duration_s": 1800},
    )
    print(result)
