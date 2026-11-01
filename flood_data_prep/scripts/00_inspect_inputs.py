#!/usr/bin/env python
"""Step 0: look at every raw input BEFORE running the pipeline, and print what it really contains.

    python scripts/00_inspect_inputs.py            # prints to screen and writes reports/input_inspection.md

Nothing is modified. Paste the output (or the .md file) when something looks wrong: it contains the variable names, units,
date ranges, column names and name mismatches that the other steps depend on.
"""
import argparse
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from floodprep.common import add_config_arg, build_name_lookup, ensure_dir, load_config, match_series


def section(t):
    print(f"\n## {t}\n")


def boundaries(cfg):
    section("Boundaries")
    import geopandas as gpd
    f = cfg["districts"]["boundary_file"]
    if not Path(f).exists():
        return print(f"MISSING: {f}")
    g = gpd.read_file(f)
    print(f"file: {f}\nrows: {len(g)}  crs: {g.crs}  columns: {list(g.columns)}")
    print(f"bounds (lon/lat): {[round(x, 4) for x in g.to_crs(4326).total_bounds]}")
    field = cfg["districts"].get("name_field")
    if field and field in g:
        names = sorted(g[field].astype(str).str.strip())
        print(f"{len(names)} names ({len(set(names))} distinct): {names}")
        bad = (~g.geometry.is_valid).sum()
        print(f"invalid geometries: {bad}")
    return g


def rainfall(cfg):
    section("Rainfall")
    folder = cfg["paths"]["raw"] / "rainfall"
    nc, csv = sorted(folder.glob("*.nc")), sorted(folder.glob("*.csv"))
    print(f"folder: {folder}  .nc files: {len(nc)}  .csv files: {len(csv)}")
    import xarray as xr
    from floodprep.zonal import LAT_NAMES, LON_NAMES, TIME_NAMES, _find, detect_variable, unit_scale
    spans = []
    for f in nc:
        try:
            with xr.open_dataset(f) as ds:
                var = detect_variable(ds)
                lat_n, lon_n, t_n = _find(ds, LAT_NAMES, "lat"), _find(ds, LON_NAMES, "lon"), _find(ds, TIME_NAMES, "time")
                t = pd.to_datetime(ds[t_n].values)
                da = ds[var]
                sc, note = unit_scale(da)
                vals = da.isel({t_n: slice(0, min(len(t), 60))}).values.astype("float64")
                print(f"- {f.name}: product={ds.attrs.get('product')} version={ds.attrs.get('version')} stage={ds.attrs.get('stage')} "
                      f"daily_product={ds.attrs.get('daily_product')} | var='{var}' dims={dict(da.sizes)} units='{da.attrs.get('units')}' -> {note}; "
                      f"time {t.min().date()}..{t.max().date()} ({len(t)} steps, step={pd.Series(t).diff().mode().iloc[0] if len(t) > 1 else 'n/a'}); "
                      f"lon {float(ds[lon_n].min()):.2f}..{float(ds[lon_n].max()):.2f} lat {float(ds[lat_n].min()):.2f}..{float(ds[lat_n].max()):.2f}; "
                      f"first-60-steps: min={np.nanmin(vals):.2f} max={np.nanmax(vals):.2f} nan%={100*np.isnan(vals).mean():.1f}")
                spans.append((t.min(), t.max()))
        except Exception as e:
            print(f"- {f.name}: COULD NOT READ ({type(e).__name__}: {e})")
    if spans:
        w0 = pd.Timestamp(cfg["project"]["start_date"]) - pd.Timedelta(days=cfg["rainfall"]["buffer_days"])
        w1 = pd.Timestamp(cfg["project"]["end_date"])
        print(f"need {w0.date()}..{w1.date()}; files cover {min(s[0] for s in spans).date()}..{max(s[1] for s in spans).date()}")
    for f in csv[:5]:
        df = pd.read_csv(f, nrows=5, dtype=str)
        print(f"- {f.name}: columns={list(df.columns)}\n{df.to_string(index=False)}")
    if cfg["rainfall"].get("source") in ("station_csv", "chirps_v3") and csv and cfg["rainfall"].get("station_csv", {}).get("files"):
        from floodprep import stations as ST
        sc = cfg["rainfall"]["station_csv"]
        try:
            raw, qc = ST.load_station_csvs(folder, sc.get("files"), sc.get("columns"), sc.get("missing_values"), sc.get("date_dayfirst", True),
                                           int(sc.get("date_shift_days", 0)), float(sc.get("max_daily_mm", 1000)))
            print(f"station CSV profile: {qc['rows_read']:,} rows; stations {raw['station_id'].nunique()}; "
                  f"observed values {int(raw['rain'].notna().sum()):,}; exactly 0: {100*float((raw['rain'] == 0).sum() / max(raw['rain'].notna().sum(), 1)):.1f}%")
            for k, v in qc["files"].items():
                print(f"  {k}: {v}")
            print(f"  duplicate station-day rows: {qc['duplicate_rows']} (conflicting values: {qc['conflicting_duplicate_rows']})")
            print("  observed rainfall rows per year:", raw.dropna(subset=["rain"]).groupby(raw["date"].dt.year).size().to_dict())
            print("  stations reporting per year:", raw.dropna(subset=["rain"]).groupby(raw["date"].dt.year)["station_id"].nunique().to_dict())
            print(f"  District column values: {sorted(raw['district'].astype(str).unique())[:60]}")
        except Exception as e:
            print(f"  COULD NOT PROFILE the station CSVs: {type(e).__name__}: {e}")


def labels(cfg, g):
    section("Labels")
    folder = Path(cfg["labels"]["input_dir"])
    print(f"folder: {folder}")
    files = sorted(folder.glob("*.csv")) if folder.exists() else []
    if not files:
        return print("MISSING / empty")
    if cfg["project"].get("mode", "seasonal") == "seasonal":
        from floodprep import annual_labels as AL
        lc = cfg["labels"]
        auth, others, excl = AL.discover_files(folder, lc.get("files"), lc.get("exclude_patterns", []))
        print(f"authoritative: {[p.name for p in auth]}\nother candidates (compared only): {[p.name for p in others]}\nexcluded: {[p.name for p in excl]}")
        for p in auth + others:
            try:
                head = pd.read_csv(p, nrows=5, dtype=str)
                rows, info = AL.load_annual_file(p, lc["annual"]["granularities"], int(lc["annual"].get("min_period_days", 60)))
                print(f"- {p.name}: columns={list(head.columns)}\n{head.to_string(index=False)}\n  info: {info}")
                print(f"  years: {rows['year'].value_counts().sort_index().to_dict()}; affected_population min/median/max: "
                      f"{rows['affected_population'].min()}/{rows['affected_population'].median()}/{rows['affected_population'].max()}")
                if "label_granularity" in head.columns:
                    full = pd.read_csv(p, dtype=str, usecols=["label_granularity"])
                    print("  label_granularity values:", full["label_granularity"].value_counts(dropna=False).to_dict())
                if "quality_flag" in head.columns:
                    print("  quality_flag values:", pd.read_csv(p, dtype=str, usecols=["quality_flag"])["quality_flag"].value_counts(dropna=False).to_dict())
                for c in ("period_start", "period_end"):
                    if c in rows:
                        print(f"  {c}: {rows[c].min()} .. {rows[c].max()}; month-day patterns: "
                              f"{rows[c].dropna().dt.strftime('%m-%d').value_counts().head(5).to_dict()}")
                dup = rows.groupby(["district", "year"]).size()
                print(f"  district-years with several rows: {int((dup > 1).sum())}")
                if g is not None:
                    from floodprep.common import build_name_lookup, match_series
                    field = cfg["districts"].get("name_field") or "district"
                    lk = build_name_lookup(list(g[field].astype(str).str.strip()), cfg["districts"].get("aliases"))
                    _, un = match_series(rows["district"], lk)
                    print(f"  names not in the boundary file (after aliases): {un} (merge_into_parent: {sorted(cfg['districts'].get('merge_into_parent') or {})})")
            except Exception as e:
                print(f"- {p.name}: COULD NOT READ as a label file ({type(e).__name__}: {e})")
        return
    from floodprep.labels import assign_granularity, load_label_csvs
    raw = load_label_csvs(folder)
    print(f"files: {[f.name for f in files]}\nrows: {len(raw)}  columns: {list(raw.columns)}")
    print(f"date range: {raw['date'].min().date()}..{raw['date'].max().date()}  distinct dates: {raw['date'].nunique()}")
    rg = assign_granularity(raw, cfg["labels"])
    print("interpreted kinds:", rg["kind"].value_counts().to_dict())


def rasters(cfg):
    section("Rasters")
    import rasterio
    for name, rel in (("DEM", "terrain/dem.tif"), ("population", "population/population.tif"), ("land cover", "landcover/landcover.tif")):
        p = cfg["paths"]["raw"] / rel
        if not p.exists():
            print(f"- {name}: not found ({p})")
            continue
        with rasterio.open(p) as s:
            print(f"- {name}: {s.width}x{s.height} crs={s.crs} nodata={s.nodata} dtype={s.dtypes[0]} res={s.res} bounds={tuple(round(b, 3) for b in s.bounds)}")
            if name == "population":
                ov = s.read(1, out_shape=(max(s.height // 8, 1), max(s.width // 8, 1)), masked=True)
                print(f"    coarse sample: min={ov.min()} max={ov.max()} mean={ov.mean():.3f}  "
                      "(people-per-pixel rasters have small values like 0-5000; densities can look similar -> verify the product name/units)")


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    cfg = load_config(ap.parse_args().config)
    buf = io.StringIO()

    class Tee:
        def write(self, x):
            sys.__stdout__.write(x); buf.write(x)

        def flush(self):
            sys.__stdout__.flush()

    import contextlib
    with contextlib.redirect_stdout(Tee()):
        print("# Input inspection")
        g = boundaries(cfg)
        rainfall(cfg)
        labels(cfg, g)
        rasters(cfg)
    out = ensure_dir(cfg["paths"]["reports"]) / "input_inspection.md"
    out.write_text(buf.getvalue())
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    main()
