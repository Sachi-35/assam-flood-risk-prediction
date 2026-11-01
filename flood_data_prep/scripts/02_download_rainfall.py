#!/usr/bin/env python
"""Step 2: download daily CHIRPS v3.0 rainfall, subset to the Assam bounding box, one NetCDF per year.

Product (CHC, https://www.chc.ucsb.edu/data/chirps3 ; Earth Engine catalogue UCSB-CHC/CHIRPS/V3/DAILY_SAT):
  CHIRPS v3.0 daily, FINAL, 0.05 deg, mm/day, 1981-present, stored as GeoTIFF (COG) per day under
      <base_url>/final/<product>/<YYYY>/<one .tif per day>        base_url = https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily
  product 'sat' = pentad totals disaggregated with IMERG Late V07; 'rnl' = disaggregated with ERA5. Both are CHIRPS v3.0.
  YOU choose rainfall.chirps_v3.product; the script never switches product, never uses preliminary data and never uses CHIRPS v2.

How the subset works: each day's COG is opened over HTTP (GDAL /vsicurl/) and only the Assam window is read (range requests), so the
global raster is not downloaded. If that is impossible it downloads that day's whole GeoTIFF to a temp file instead.
File names inside a year folder are DISCOVERED from the directory listing (date found in the name); if the listing cannot be read, two
documented-by-convention names are tried and the manifest says so. `base_url` may also be a LOCAL folder with the same layout
(e.g. tifs you downloaded by hand) - then nothing is fetched.

Missing days stay missing (NaN in the NetCDF, listed in reports/chirps_v3_download_manifest.csv); the CHIRPS fill value (-9999) is NaN, never 0.
Output: data/raw/rainfall/chirps_v3_<product>_<year>.nc   variable 'precip' (mm/day), attrs product/version/stage/units/source.

    python scripts/02_download_rainfall.py [--start 1991-01-01] [--end 2023-12-31] [--workers 6] [--force]
"""
import argparse
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.windows import Window, from_bounds

from floodprep.common import add_config_arg, ensure_dir, get_logger, load_config

log = get_logger("02_chirps_v3")
DATE_RE = re.compile(r"(\d{4})[.\-_]?(\d{2})[.\-_]?(\d{2})")
FALLBACK_NAMES = ["chirps-v3.0.{product}.{y}.{m}.{d}.tif", "chirps-v3.0.{y}.{m}.{d}.tif"]
MAX_PLAUSIBLE_MM = 1500.0            # CHIRPS v3 daily maximum on record is ~1444 mm/day (Earth Engine catalogue)


def is_url(s: str) -> bool:
    return str(s).startswith(("http://", "https://"))


def list_year(base: str, stage: str, product: str, year: int, session) -> dict:
    """date -> full path/URL of that day's .tif, discovered from the listing."""
    loc = f"{base.rstrip('/')}/{stage}/{product}/{year}/"
    found = {}
    if is_url(base):
        try:
            r = session.get(loc, timeout=120)
            r.raise_for_status()
            names = re.findall(r'href="([^"?#]+\.tif)"', r.text, flags=re.I)
        except Exception as e:                                                       # listing unreadable
            log.warning(f"{year}: cannot read the directory listing ({type(e).__name__}: {e})")
            return {}
        for n in names:
            m = DATE_RE.search(Path(n).name)
            if m and m.group(1) == str(year):
                found[pd.Timestamp(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")] = loc + Path(n).name
    else:
        for p in Path(loc).glob("*.tif"):
            m = DATE_RE.search(p.name)
            if m and m.group(1) == str(year):
                found[pd.Timestamp(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")] = str(p)
    return found


def guess_urls(base, stage, product, day):
    return [f"{base.rstrip('/')}/{stage}/{product}/{day.year}/" + t.format(product=product, y=f"{day.year:04d}", m=f"{day.month:02d}", d=f"{day.day:02d}")
            for t in FALLBACK_NAMES]


def read_window(path: str, bbox, session=None):
    """(2-D float32 array north->south, lons, lats, meta) of the bbox from one daily GeoTIFF; fill/negative values -> NaN."""
    lon0, lat0, lon1, lat1 = bbox
    tmp = None
    src_path = ("/vsicurl/" + path) if is_url(path) else path
    try:
        try:
            src = rasterio.open(src_path)
        except Exception:
            if not is_url(path):
                raise
            tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
            with session.get(path, stream=True, timeout=600) as r:
                r.raise_for_status()
                for chunk in r.iter_content(1 << 20):
                    tmp.write(chunk)
            tmp.close()
            src = rasterio.open(tmp.name)
        with src:
            if src.crs is None or src.crs.to_epsg() != 4326:
                raise ValueError(f"{path}: CRS {src.crs} is not EPSG:4326")
            res = abs(src.transform.a)
            if not 0.045 < res < 0.055:
                raise ValueError(f"{path}: pixel size {res} deg is not the 0.05 deg of CHIRPS")
            win = from_bounds(lon0, lat0, lon1, lat1, src.transform).round_offsets().round_lengths()
            win = win.intersection(Window(0, 0, src.width, src.height))              # never read (or label) cells outside the raster
            if win.width < 1 or win.height < 1:
                raise ValueError(f"{path}: the bounding box {bbox} does not overlap the raster")
            arr = src.read(1, window=win, masked=False).astype("float32")
            if arr.shape != (int(win.height), int(win.width)):
                raise ValueError(f"{path}: read {arr.shape} for a window of {(win.height, win.width)}")
            nod = src.nodata
            tr = src.window_transform(win)
            if nod is not None:
                arr[arr == nod] = np.nan
            arr[(arr < 0) | (arr > MAX_PLAUSIBLE_MM)] = np.nan                       # -9999 style fills / absurd values: missing, not zero
            lons = tr.c + tr.a * (np.arange(arr.shape[1]) + 0.5)
            lats = tr.f + tr.e * (np.arange(arr.shape[0]) + 0.5)
            return arr, lons, lats, {"nodata": nod, "res": res, "dtype": src.dtypes[0], "tags": src.tags()}
    finally:
        if tmp is not None:
            Path(tmp.name).unlink(missing_ok=True)


def fetch_day(day, path, cfg_c, bbox, session, retries=3):
    last = None
    for k in range(retries):
        try:
            return day, path, read_window(path, bbox, session), None
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
    return day, path, None, last


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--force", action="store_true", help="re-download years that already exist")
    args = ap.parse_args()
    cfg = load_config(args.config)
    rc = cfg["rainfall"]
    cc = rc.get("chirps_v3")
    if not cc:
        sys.exit("config.yaml has no rainfall.chirps_v3 block.")
    if cc.get("stage", "final") != "final":
        sys.exit("Only the FINAL CHIRPS v3 stage is supported (no silent use of preliminary data).")
    product = cc["product"]
    if product not in ("sat", "rnl"):
        sys.exit("rainfall.chirps_v3.product must be 'sat' or 'rnl' (a deliberate choice; see docs/DATA_SOURCES.md).")
    start = pd.Timestamp(args.start or cc["start_date"])
    end = pd.Timestamp(args.end or cc["end_date"])
    bbox = cc.get("bbox") or rc["bbox"]
    base = cc["base_url"]
    out_dir = ensure_dir(cfg["paths"]["raw"] / "rainfall")
    reports = ensure_dir(cfg["paths"]["reports"])
    import requests
    session = requests.Session()
    log.info(f"CHIRPS v3.0 final/{product}: {start.date()} -> {end.date()}, bbox {bbox}, source {base}")
    manifest, problems = [], []

    for year in range(start.year, end.year + 1):
        dest = out_dir / f"chirps_v3_{product}_{year}.nc"
        t0, t1 = max(start, pd.Timestamp(year, 1, 1)), min(end, pd.Timestamp(year, 12, 31))
        days = pd.date_range(t0, t1)
        if dest.exists() and not args.force:
            with xr.open_dataset(dest) as d:
                have = pd.to_datetime(d["time"].values)
            if have.min() <= t0 and have.max() >= t1:
                log.info(f"{dest.name} exists and covers {t0.date()}..{t1.date()}; skipped (--force to redo)")
                continue
        listing = list_year(base, "final", product, year, session)
        guessed = False
        if not listing:
            guessed = True
            log.warning(f"{year}: no file list; trying conventional names (unverified): {FALLBACK_NAMES}")
        paths = {}
        for d in days:
            paths[d] = listing.get(d) if listing else None
            if paths[d] is None and guessed:
                for cand in guess_urls(base, "final", product, d):
                    try:
                        ok = session.head(cand, timeout=60).status_code == 200 if is_url(base) else Path(cand).exists()
                    except Exception:
                        ok = False
                    if ok:
                        paths[d] = cand
                        break
        res = {}
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(fetch_day, d, p, cc, bbox, session) for d, p in paths.items() if p]
            for f in futs:
                d, p, got, err = f.result()
                res[d] = (p, got, err)
        grid = next((g for _, g, _ in res.values() if g), None)
        if grid is None:
            log.error(f"{year}: no day could be read; nothing written.")
            problems.append(year)
            for d in days:
                manifest.append({"date": d.date(), "url": paths.get(d), "status": "no_file" if paths.get(d) is None else "failed",
                                 "error": res.get(d, (None, None, "no file found"))[2]})
            continue
        _, lons, lats, meta = grid
        cube = np.full((len(days), len(lats), len(lons)), np.nan, dtype="float32")
        for i, d in enumerate(days):
            p, got, err = res.get(d, (None, None, "no file found in the listing"))
            if got is not None and got[0].shape == cube.shape[1:]:
                cube[i] = got[0]
                manifest.append({"date": d.date(), "url": p, "status": "ok", "error": ""})
            else:
                manifest.append({"date": d.date(), "url": p, "status": "missing", "error": err or "grid shape differs"})
        order = np.argsort(lats)
        ds = xr.Dataset({"precip": (("time", "lat", "lon"), cube[:, order, :])},
                        coords={"time": days, "lat": lats[order], "lon": lons})
        ds["precip"].attrs.update(units="mm/day", long_name="CHIRPS v3.0 daily precipitation (final)", missing="NaN = no data")
        ds.attrs.update(product="CHIRPS-v3.0", version="3.0", stage="final", daily_product=product, units="mm/day",
                        source=base, bbox=str(bbox), file_names_discovered=str(not guessed), created=datetime.now(timezone.utc).isoformat(),
                        citation="Climate Hazards Center InfraRed Precipitation with Station version 3, doi:10.15780/G2JQ0P",
                        source_nodata=str(meta["nodata"]))
        ds.to_netcdf(dest)
        n_ok = sum(1 for m in manifest if m["status"] == "ok" and str(m["date"]).startswith(str(year)))
        log.info(f"{dest.name}: {n_ok}/{len(days)} days read, grid {len(lats)}x{len(lons)}")
        if n_ok < len(days):
            problems.append(year)
    pd.DataFrame(manifest).to_csv(reports / "chirps_v3_download_manifest.csv", index=False)
    if problems:
        log.warning(f"Years with missing days or failures: {problems}. See reports/chirps_v3_download_manifest.csv. "
                    "Missing days stay NaN (never zero); step 03 reports the coverage per district.")
    log.info("Done.")


if __name__ == "__main__":
    main()
