#!/usr/bin/env python
"""Step 3: daily rainfall per district (and optionally an upstream zone).

rainfall.source = station_csv   data/raw/rainfall/*.csv  -> Assam Water Dept / NWDP station gauges -> district mean (see floodprep/stations.py)
rainfall.source = netcdf        data/raw/rainfall/*.nc    -> area-weighted mean over each district polygon
rainfall.source = district_csv  data/raw/rainfall/*.csv   -> columns district,date,rain_mm (already district-level)

Output: data/interim/rainfall_daily.csv  (zone_id, date, rain_mm)   zone 'UPSTREAM' = upstream zone (if usable)
        reports/rainfall_qc.csv          per-district coverage / missing % / overlap conflicts

Checks performed (and reported, never silently ignored): variable + unit detection, grid coverage of every district,
date coverage versus the period + buffer the features need, duplicate days across files that disagree.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import box

from floodprep.common import (add_config_arg, build_name_lookup, ensure_dir, get_logger, load_config, match_series)
from floodprep import stations as ST
from floodprep.zonal import zonal_mean

log = get_logger("03_extract_rain")


def required_window(cfg):
    pc = cfg["project"]
    start = pd.Timestamp(pc["start_date"]) - pd.Timedelta(days=cfg["rainfall"]["buffer_days"])
    return start, pd.Timestamp(pc["end_date"])


def from_netcdf(cfg, districts):
    zones = {r.district_id: r.geometry for r in districts.itertuples()}
    up = cfg["rainfall"].get("upstream", {})
    if up.get("enabled", True):
        if up.get("geometry_file"):
            zones["UPSTREAM"] = gpd.read_file(up["geometry_file"]).to_crs("EPSG:4326").geometry.union_all()
        elif up.get("bbox"):
            zones["UPSTREAM"] = box(*up["bbox"])
    files = sorted((cfg["paths"]["raw"] / "rainfall").glob("*.nc"))
    if not files:
        sys.exit("No .nc files in data/raw/rainfall. (Use rainfall.source: district_csv for CSV rainfall.)")

    frames, info_all = [], {}
    for f in files:
        with xr.open_dataset(f) as ds:
            ds = ds.load()
        df, info, notes = zonal_mean(ds, zones, cfg["rainfall"].get("variable", "auto"), cfg["rainfall"].get("units", "auto"))
        frames.append(df.assign(source_file=f.name))
        for z, i in info.items():
            prev = info_all.get(z)
            if prev is None or i["coverage"] > prev["coverage"]:
                info_all[z] = i
        log.info(f"{f.name}: variable='{notes['variable']}', {notes['units']}; {df['date'].min().date()} -> {df['date'].max().date()}")
        if "UNRECOGNISED" in notes["units"]:
            log.warning(f"{f.name}: {notes['units']}")

    bad = {z: i for z, i in info_all.items() if i["status"] != "ok"}
    for z, i in bad.items():
        if z == "UPSTREAM":
            log.warning(f"Upstream zone is {i['status']} on your rainfall grid (grid covers {i['coverage']:.0%} of it) -> "
                        "upstream_* features will be skipped. (Normal if your NetCDFs were clipped to Assam.)")
        else:
            log.warning(f"District {z}: grid coverage {i['coverage']:.0%} ({i['status']}). Rainfall for it is unreliable.")
    return pd.concat(frames, ignore_index=True), info_all


def from_district_csv(cfg, districts):
    folder = cfg["paths"]["raw"] / "rainfall"
    files = sorted(folder.glob("*.csv"))
    if not files:
        sys.exit(f"rainfall.source = district_csv but there are no CSVs in {folder}")
    lookup = build_name_lookup(list(districts["district_name"]), cfg["districts"].get("aliases"))
    frames, unmatched_all = [], set()
    for f in files:
        df = pd.read_csv(f)
        df.columns = [c.strip().lower() for c in df.columns]
        rcol = next((c for c in ("rain_mm", "rainfall_mm", "rainfall", "precip", "precipitation", "rain") if c in df.columns), None)
        if not {"district", "date"} <= set(df.columns) or rcol is None:
            sys.exit(f"{f.name}: needs columns district, date and a rainfall column; found {list(df.columns)}")
        df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=False).dt.normalize()
        df["rain_mm"] = pd.to_numeric(df[rcol], errors="coerce")
        df.loc[df["rain_mm"] < 0, "rain_mm"] = float("nan")
        df["district_name"], unmatched = match_series(df["district"], lookup)
        unmatched_all |= set(unmatched)
        frames.append(df.dropna(subset=["district_name", "date"]).assign(source_file=f.name))
    if unmatched_all:
        log.warning(f"Rainfall district names with no match in the boundary file: {sorted(unmatched_all)}")
    allr = pd.concat(frames, ignore_index=True)
    name_to_id = dict(zip(districts["district_name"], districts["district_id"]))
    allr["zone_id"] = allr["district_name"].map(name_to_id)
    return allr[["date", "zone_id", "rain_mm", "source_file"]], {}


def from_stations(cfg, districts, interim, reports):
    sc = cfg["rainfall"]["station_csv"]
    raw, qc = ST.load_station_csvs(cfg["paths"]["raw"] / "rainfall", sc.get("files"), sc.get("columns"), sc.get("missing_values"),
                                   sc.get("date_dayfirst", True), int(sc.get("date_shift_days", 0)), float(sc.get("max_daily_mm", 1000)),
                                   float(sc.get("review_mm", 300)))
    dup_policy = sc.get("duplicate_policy", "missing")
    ST.duplicate_audit(raw).to_csv(reports / "rainfall_duplicate_audit.csv", index=False)
    raw[raw["flag"] != ""][["station", "district", "lat", "lon", "date", "source_file", "rain_raw", "flag"]].to_csv(
        reports / "rainfall_extreme_values.csv", index=False)
    clean = ST.collapse_duplicates(raw, dup_policy)
    st = ST.station_table(clean, districts, cfg["districts"].get("aliases"), sc.get("district_source", "polygon_then_column"))
    st.to_csv(interim / "stations.csv", index=False)
    clean.to_csv(interim / "rainfall_station_daily.csv", index=False)
    daily = ST.aggregate_to_districts(clean, st, int(sc.get("min_stations_per_district_day", 1)))

    served = set(daily["district_id"])
    nostation = [d for d in districts["district_id"] if d not in set(st["district_id"].dropna())]
    idw = sc.get("idw", {})
    idw_df = pd.DataFrame()
    if nostation and idw.get("enabled", False):
        idw_df = ST.idw_fill_districts(clean.merge(st[["station_id"]], on="station_id"), st, districts, nostation,
                                       float(idw.get("radius_km", 50)), float(idw.get("power", 2)), int(idw.get("max_stations", 4)))
        daily = pd.concat([daily, idw_df], ignore_index=True)
    unserved = [d for d in districts["district_id"] if d not in set(daily["district_id"])]

    # ---- per-district station coverage (all 33, nothing assumed) -------------------------------------------------
    yrs = clean.dropna(subset=["rain"]).merge(st[["station_id", "district_id"]], on="station_id")
    cov = districts[["district_id", "district_name"]].copy()
    g = st.dropna(subset=["district_id"]).groupby("district_id")
    cov["n_stations"] = cov["district_id"].map(g.size()).fillna(0).astype(int)
    cov["stations"] = cov["district_id"].map(g["station"].agg(lambda x: "; ".join(sorted(x)))).fillna("")
    cov["district_col_names"] = cov["district_id"].map(g["district_col"].agg(lambda x: "; ".join(sorted(set(map(str, x)))))).fillna("")
    cov["obs_days_by_year"] = cov["district_id"].map(yrs.groupby("district_id")["date"].agg(
        lambda d: str(d.dt.year.value_counts().sort_index().to_dict()))).fillna("{}")
    cov["status"] = np.where(cov["n_stations"] == 0, "NO STATION -> rainfall/hazard unknown", "has station(s)")
    cov.to_csv(reports / "station_coverage_by_district.csv", index=False)
    nostation_names = cov.loc[cov["n_stations"] == 0, "district_name"].tolist()

    # ---- report ---------------------------------------------------------------------------------------------
    nonmiss = clean.dropna(subset=["rain"])
    zero_share = nonmiss.groupby(nonmiss["date"].dt.year)["rain"].apply(lambda x: round(float((x == 0).mean()) * 100, 1))
    days_per_station = clean.groupby("station_id")["date"].nunique()
    span = clean.groupby("station_id")["date"].agg(lambda d: (d.max() - d.min()).days + 1)
    density = (days_per_station / span).describe().round(2).to_dict()
    L = ["# Station rainfall report\n", f"Rows read: {qc['rows_read']:,}. Stations: {len(st)}. Station-days kept after duplicate handling: {len(clean):,} "
         f"({len(nonmiss):,} with an observed value).\n",
         "## Per file\n"] + [f"- **{k}**: {v}" for k, v in qc["files"].items()]
    L += [f"\n## Duplicates\n\nRows involved in duplicate station-days: {qc['duplicate_rows']}; with conflicting values: "
          f"{qc['conflicting_duplicate_rows']}. Policy for conflicts: `{dup_policy}` ('missing' = the station-day becomes missing; nothing averaged). "
          f"Station-days made missing/resolved: {int(clean['conflict'].sum())}. Every duplicate row is in `reports/rainfall_duplicate_audit.csv`.\n",
          f"## Extreme values\n\nRows flagged for review (> {sc.get('review_mm', 300)} mm; > {sc.get('max_daily_mm', 1000)} mm are excluded from use): "
          f"{int((raw['flag'] != '').sum())}. Listed in `reports/rainfall_extreme_values.csv`; check each against the source.\n",
          "## Stations and districts\n",
          f"- stations assigned to a district: {int((st.assigned_by != 'none').sum())} / {len(st)} "
          f"(by polygon: {int((st.assigned_by == 'polygon').sum())}, by District column: {int((st.assigned_by == 'column').sum())}, none: {int((st.assigned_by == 'none').sum())})",
          f"- stations whose coordinates fall OUTSIDE every Assam polygon: {int(st.flag_outside_assam.sum())} "
          f"{st.loc[st.flag_outside_assam, 'station'].head(10).tolist()}",
          f"- stations whose District column disagrees with their coordinates: {int(st.flag_name_mismatch.sum())} "
          f"{st.loc[st.flag_name_mismatch, ['station', 'district_col']].head(10).values.tolist()}",
          f"- District-column names matching no boundary district: {sorted(st.loc[st.flag_unmatched_column_name, 'district_col'].dropna().unique())[:20]}",
          f"- {int((cov['n_stations'] > 0).sum())} of {len(cov)} districts have >= 1 station (by coordinates); distinct names in the District column: "
          f"{st['district_col'].nunique()}. Per-district table: `reports/station_coverage_by_district.csv`.",
          f"- districts with NO station: {nostation_names}",
          f"- IDW borrowing from neighbouring districts is {'ON' if idw.get('enabled', False) else 'OFF (rainfall stays unknown there)'}; districts with NO station: {nostation}; filled by IDW (<= {idw.get('radius_km', 50)} km): {sorted(set(idw_df['district_id'])) if len(idw_df) else []}; "
          f"still without any rainfall: {unserved}",
          "\n## Missing vs zero (check this)\n",
          f"Share of OBSERVED values that are exactly 0, by year (%): {zero_share.to_dict()}",
          f"Observed days per station / days between its first and last record: {density}. "
          "If stations are logged only on rainy days, dry days are missing rather than 0, and window/season totals would be biased LOW. "
          "A very low coverage ratio or an implausibly low zero share is the sign.\n"]
    (reports / "rainfall_station_report.md").write_text("\n".join(map(str, L)))

    for k, v in qc["files"].items():
        if v["bad_dates"] or v["negative"] or v["non_numeric_text"]:
            log.warning(f"{k}: {v['bad_dates']} unparseable dates, {v['negative']} negative values {v['negative_values_top']}, "
                        f"{v['non_numeric_text']} non-numeric texts (all treated as missing)")
    if len(st[st.assigned_by == 'none']):
        log.warning(f"{int((st.assigned_by == 'none').sum())} stations could not be assigned to any district (reports/rainfall_station_report.md)")
    if unserved:
        log.warning(f"Districts with no rainfall at all: {unserved}. They will be missing from the model table.")

    daily = daily.rename(columns={"district_id": "zone_id"}).sort_values(["zone_id", "date"])
    qcdf = (daily.assign(year=daily["date"].dt.year).groupby(["zone_id", "year"])
            .agg(days_observed=("rain_mm", "count"), mean_stations=("n_stations", "mean"), source=("source", "first")).reset_index())
    qcdf["days_in_year"] = qcdf["year"].map(lambda y: 366 if pd.Timestamp(y, 12, 31).dayofyear == 366 else 365)
    qcdf["observed_pct"] = (100 * qcdf["days_observed"] / qcdf["days_in_year"]).round(1)
    qcdf.to_csv(reports / "rainfall_qc.csv", index=False)
    daily.to_csv(interim / "rainfall_daily.csv", index=False)
    log.info(f"District-days with rainfall: {len(daily):,} ({daily['date'].min().date()} -> {daily['date'].max().date()}). "
             f"Report: {reports/'rainfall_station_report.md'}")


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    cfg = load_config(ap.parse_args().config)
    interim = ensure_dir(cfg["paths"]["interim"])
    reports = ensure_dir(cfg["paths"]["reports"])
    dpath = interim / "districts.geojson"
    if not dpath.exists():
        sys.exit("Run 01_prepare_boundaries.py first.")
    districts = gpd.read_file(dpath).to_crs("EPSG:4326")
    if cfg["rainfall"].get("source") == "station_csv":
        return from_stations(cfg, districts, interim, reports)

    src = cfg["rainfall"].get("source", "netcdf")
    allr, info = from_netcdf(cfg, districts) if src == "netcdf" else from_district_csv(cfg, districts)

    # ---- duplicates across files: same zone+date, different value ----------------------------------------------
    g = allr.dropna(subset=["rain_mm"]).groupby(["zone_id", "date"])["rain_mm"]
    spread = (g.max() - g.min())
    conflicts = spread[spread > 0.5]
    if len(conflicts):
        log.warning(f"{len(conflicts)} zone-days appear in several files with values differing by >0.5 mm "
                    f"(max {conflicts.max():.1f} mm). Overlapping sources disagree: check that files are one product/unit. "
                    "The first value in sorted file order is kept.")
    out = (allr.sort_values(["zone_id", "date", "source_file"]).drop_duplicates(["zone_id", "date"])
           .drop(columns="source_file").sort_values(["zone_id", "date"]))

    # ---- completeness over the window the features need ---------------------------------------------------------
    w0, w1 = required_window(cfg)
    full = pd.MultiIndex.from_product([sorted(out["zone_id"].dropna().unique()), pd.date_range(w0, w1)], names=["zone_id", "date"])
    out = out.set_index(["zone_id", "date"]).reindex(full).reset_index()
    qc = out.groupby("zone_id")["rain_mm"].agg(missing_pct=lambda s: round(s.isna().mean() * 100, 2),
                                               first_valid=lambda s: s.first_valid_index()).drop(columns="first_valid")
    qc["grid_coverage_pct"] = [round(100 * info.get(z, {}).get("coverage", float("nan")), 1) for z in qc.index]
    qc["conflicting_days"] = [int((conflicts.reset_index()["zone_id"] == z).sum()) for z in qc.index]
    qc.to_csv(reports / "rainfall_qc.csv")
    log.info(f"Window required by the features: {w0.date()} -> {w1.date()}")

    thr = cfg["rainfall"].get("min_coverage_pct", 90)
    districts_qc = qc.drop(index="UPSTREAM", errors="ignore")
    poor = districts_qc[districts_qc["missing_pct"] > 100 - thr]
    if len(poor):
        log.error(f"Districts with < {thr}% rainfall coverage in {w0.date()}..{w1.date()}:\n{poor.to_string()}")
        log.error("Likely causes: NetCDF files do not span the whole period (+45-day buffer), or the grid does not cover "
                  "the district. Fix the inputs; training on imputed rainfall would be misleading.")
        sys.exit(1)
    # An UPSTREAM zone the grid does not fully cover would give a misleading mean over a small corner: drop it.
    if "UPSTREAM" in qc.index and (qc.loc["UPSTREAM", "missing_pct"] > 100 - thr
                                   or info.get("UPSTREAM", {}).get("status", "ok") != "ok"):
        out = out[out["zone_id"] != "UPSTREAM"]
        log.warning("UPSTREAM series dropped (grid does not cover the whole upstream zone) -> no upstream_* features.")
    out.to_csv(interim / "rainfall_daily.csv", index=False)
    log.info("Rainfall QC:\n" + qc.to_string())
    log.info(f"Saved -> {interim/'rainfall_daily.csv'}")


if __name__ == "__main__":
    main()
