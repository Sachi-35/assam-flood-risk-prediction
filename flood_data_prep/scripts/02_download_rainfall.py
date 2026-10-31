#!/usr/bin/env python
"""Step 2 (OPTIONAL - skip it if you already have the rainfall files): download daily gridded rainfall for the study bounding box (one NetCDF per year).

--source chirps_erddap : CHIRPS v2.0, 0.05 deg, via NOAA CoastWatch ERDDAP subsetting (no login). DEFAULT.
--source imd           : IMD 0.25 deg gridded rainfall via the `imdlib` package (pip install imdlib).

Output: data/raw/rainfall/<source>_<year>.nc   (variable 'precip' or 'rain', mm/day)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from floodprep.common import add_config_arg, ensure_dir, get_logger, load_config

log = get_logger("02_rain")
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/chirps20GlobalDailyP05.nc"


def erddap_year(year, t0, t1, bbox, dest):
    import requests

    lon0, lat0, lon1, lat1 = bbox
    # ERDDAP wants ranges in the dataset's axis order; try ascending latitude first, then descending.
    for la, lb in ((lat0, lat1), (lat1, lat0)):
        q = (f"precip[({t0:%Y-%m-%d}T00:00:00Z):1:({t1:%Y-%m-%d}T00:00:00Z)]"
             f"[({la}):1:({lb})][({lon0}):1:({lon1})]")
        r = requests.get(ERDDAP + "?" + q, timeout=600, stream=True)
        if r.status_code == 200:
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
            return True
        log.warning(f"{year}: HTTP {r.status_code} (lat order {la}->{lb}): {r.text[:200].strip()}")
    return False


def imd_all(start, end, bbox, out_dir):
    import imdlib as imd  # noqa: WPS433

    data = imd.get_data("rain", start.year, end.year, fn_format="yearwise", file_dir=str(out_dir))
    ds = data.get_xarray()
    ds = ds.where(ds["rain"] != -999.0)
    lon0, lat0, lon1, lat1 = bbox
    ds = ds.sel(lat=slice(lat0, lat1), lon=slice(lon0, lon1))
    for y, g in ds.groupby("time.year"):
        g.to_netcdf(out_dir / f"imd_{y}.nc")
        log.info(f"saved imd_{y}.nc")


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    ap.add_argument("--source", default=None, choices=["chirps_erddap", "imd"])
    args = ap.parse_args()
    cfg = load_config(args.config)
    rc, pc = cfg["rainfall"], cfg["project"]
    source = args.source or rc.get("download_source", "chirps_erddap")
    start = pd.Timestamp(pc["start_date"]) - pd.Timedelta(days=rc["buffer_days"])
    end = pd.Timestamp(pc["end_date"])
    out_dir = ensure_dir(cfg["paths"]["raw"] / "rainfall")
    log.info(f"Source={source}  window={start.date()} -> {end.date()}  bbox={rc['bbox']}")

    if source == "imd":
        imd_all(start, end, rc["bbox"], out_dir)
        return

    for year in range(start.year, end.year + 1):
        t0, t1 = max(start, pd.Timestamp(year, 1, 1)), min(end, pd.Timestamp(year, 12, 31))
        dest = out_dir / f"chirps_erddap_{year}.nc"
        if dest.exists():
            log.info(f"{dest.name} exists, skipping")
            continue
        log.info(f"Downloading {year} ({t0.date()} -> {t1.date()}) ...")
        if not erddap_year(year, t0, t1, rc["bbox"], dest):
            dest.unlink(missing_ok=True)
            log.error(f"{year} failed. Check your internet access, or that CHIRPS is published that far "
                      "(there is a lag of a few weeks), or use --source imd.")
    log.info("Done.")


if __name__ == "__main__":
    main()
