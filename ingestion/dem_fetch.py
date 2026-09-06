"""
ingestion/dem_fetch.py

Fetches an open-source DEM covering the Rishiganga / Dhauliganga catchment,
Chamoli district, Uttarakhand -- site of the 7 Feb 2021 disaster chain
(Ronti Gad rock-ice avalanche -> Rishiganga -> Raini confluence ->
Dhauliganga -> Tapovan).

Primary source : Copernicus GLO-30 DSM ("COP30"), 30 m, via OpenTopography
Fallback source: NASADEM (reprocessed, void-filled SRTM), 30 m, via OpenTopography

Both are served through the same OpenTopography REST endpoint, so switching
sources is just a --dem-type flag.

SETUP (one-time, ~5 min):
  1. Create a free account at https://portal.opentopography.org
  2. Go to "myOpenTopo" -> "Request API key"
  3. Put the key in your shell, do NOT commit it:
       export OPENTOPOGRAPHY_API_KEY=your_key_here

USAGE:
  python ingestion/dem_fetch.py
  python ingestion/dem_fetch.py --dem-type NASADEM --out data/raw/rishiganga_nasadem.tif
  python ingestion/dem_fetch.py --south 30.20 --north 30.48 --west 79.50 --east 79.90

MANUAL FALLBACK (if the API is unreachable from the hackathon venue):
  Go to https://portal.opentopography.org -> "Data" -> "Global Raster Datasets and
  Derivatives" -> pick "Copernicus GLO-30" -> draw/enter the same bbox below ->
  download GeoTIFF -> save it as data/raw/rishiganga_dem_raw.tif manually.
"""
import argparse
import os
import sys
from pathlib import Path

import requests

OPENTOPO_URL = "https://portal.opentopography.org/API/globaldem"

# First-pass bounding box around the documented GLOF flow path:
#   - Ronti Gad avalanche source:      ~30.375 N, 79.732 E
#   - Raini village / Dhauliganga confluence: ~30.30-30.32 N, 79.56-79.58 E
#   - Tapovan Vishnugad HEP:           ~30.28 N, 79.57 E
# with a buffer margin so we don't clip the ridgelines that bound the
# sub-catchment. This is a DOWNLOAD box, not the final simulation extent --
# the real sub-catchment boundary should be delineated hydrologically from
# the DEM itself once we have data (see preprocess.py, task 2).
DEFAULT_BBOX = {
    "south": 30.20,
    "north": 30.48,
    "west": 79.50,
    "east": 79.90,
}

SUPPORTED_DEMS = ["COP30", "COP90", "NASADEM", "SRTMGL1", "SRTMGL3"]


def fetch_dem(dem_type: str, bbox: dict, out_path: Path, api_key: str) -> Path:
    if dem_type not in SUPPORTED_DEMS:
        raise ValueError(f"dem_type must be one of {SUPPORTED_DEMS}")

    params = {
        "demtype": dem_type,
        "south": bbox["south"],
        "north": bbox["north"],
        "west": bbox["west"],
        "east": bbox["east"],
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Requesting {dem_type} for bbox={bbox} ...")
    resp = requests.get(OPENTOPO_URL, params=params, timeout=120)
    resp.raise_for_status()

    # OpenTopography sometimes returns a 200 with a JSON error body instead
    # of a real GeoTIFF (e.g. bad bbox, rate limit) -- catch that early.
    content_type = resp.headers.get("content-type", "")
    if "json" in content_type or resp.content[:4] != b"II*\x00" and resp.content[:4] != b"MM\x00*":
        raise RuntimeError(
            f"Expected a GeoTIFF but got content-type={content_type!r}. "
            f"Response begins: {resp.text[:300]!r}"
        )

    with open(out_path, "wb") as f:
        f.write(resp.content)

    size_mb = out_path.stat().st_size / 1e6
    print(f"Saved DEM to {out_path} ({size_mb:.1f} MB)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dem-type", default="COP30", choices=SUPPORTED_DEMS,
                         help="COP30 = Copernicus GLO-30 (recommended). NASADEM = SRTM-based fallback.")
    parser.add_argument("--out", default="data/raw/rishiganga_dem_raw.tif")
    parser.add_argument("--south", type=float, default=DEFAULT_BBOX["south"])
    parser.add_argument("--north", type=float, default=DEFAULT_BBOX["north"])
    parser.add_argument("--west", type=float, default=DEFAULT_BBOX["west"])
    parser.add_argument("--east", type=float, default=DEFAULT_BBOX["east"])
    args = parser.parse_args()

    api_key = os.environ.get("OPENTOPOGRAPHY_API_KEY")
    if not api_key:
        sys.exit(
            "ERROR: OPENTOPOGRAPHY_API_KEY is not set.\n"
            "Get a free key at https://portal.opentopography.org "
            "(myOpenTopo -> Request API key), then:\n"
            "  export OPENTOPOGRAPHY_API_KEY=your_key_here"
        )

    bbox = {"south": args.south, "north": args.north, "west": args.west, "east": args.east}
    fetch_dem(args.dem_type, bbox, Path(args.out), api_key)


if __name__ == "__main__":
    main()
