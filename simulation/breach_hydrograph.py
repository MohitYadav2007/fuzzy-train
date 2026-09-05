"""
Generates the breach hydrograph (discharge vs. time) that feeds BOTH
simulation engines as the inflow boundary condition.

OUTPUT CONTRACT (this is what dualsphysics_wrapper.py and delft3d_runner.py
both expect as input):

    CSV with exactly two columns, header required:
        time_s,discharge_cms
        0,0
        60,120.5
        120,890.3
        ...

    - time_s: seconds since breach initiation
    - discharge_cms: peak discharge in cubic meters per second
    - Monotonically increasing time_s, no gaps required (engines will
      interpolate), but keep it reasonably dense near the peak.

See data/sample/sample_breach_hydrograph.csv for a synthetic placeholder
shaped like a typical GLOF hydrograph (fast rise, slower recession) --
NOT real Rishiganga discharge data. Whoever owns hydrology_fetch.py /
the breach modeling research should replace this with values derived from
published Feb 2021 Rishiganga GLOF estimates (see docs/breach_model.md).
"""

import csv
from pathlib import Path


def generate_synthetic_hydrograph(
    peak_discharge_cms: float,
    time_to_peak_s: float,
    total_duration_s: float,
    timestep_s: float = 10.0,
) -> list[tuple[float, float]]:
    """
    Placeholder breach hydrograph shape generator (simple triangular/
    exponential-decay curve) for testing the pipeline before real
    breach-model output (docs/breach_model.md) is ready.

    Returns list of (time_s, discharge_cms) tuples.
    """
    import math

    points = []
    t = 0.0
    while t <= total_duration_s:
        if t <= time_to_peak_s:
            q = peak_discharge_cms * (t / time_to_peak_s) if time_to_peak_s > 0 else peak_discharge_cms
        else:
            # exponential recession after peak
            decay_const = 3.0 / (total_duration_s - time_to_peak_s)
            q = peak_discharge_cms * math.exp(-decay_const * (t - time_to_peak_s))
        points.append((round(t, 1), round(q, 2)))
        t += timestep_s
    return points


def save_hydrograph_csv(points: list[tuple[float, float]], path: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "discharge_cms"])
        writer.writerows(points)


if __name__ == "__main__":
    # TODO: replace with real breach-model-derived values once docs/breach_model.md
    # analysis is done. These numbers are placeholders only.
    pts = generate_synthetic_hydrograph(
        peak_discharge_cms=1000.0,
        time_to_peak_s=300.0,
        total_duration_s=3600.0,
    )
    save_hydrograph_csv(pts, "data/sample/sample_breach_hydrograph.csv")
    print(f"Wrote {len(pts)} points to data/sample/sample_breach_hydrograph.csv")
