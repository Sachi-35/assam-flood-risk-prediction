#!/usr/bin/env python
"""Step 9: write the files the FastAPI backend reads (see config/export_map.yaml).

seasonal mode (default): districts.csv, rainfall_daily.csv, climatology.csv, normal_season_features.csv, season_features.csv,
                         hazard_config.json, label_thresholds.json, model_table_full.csv
daily mode: the original districts.csv + daily_features.csv described below.

Output (data/backend_export/):
    districts.csv           id,name,state,geometry,mean_elevation_m,elevation_std_m,mean_slope_deg,low_lying_frac,pop_density_km2
    daily_features.csv      district_id,date, 6 rainfall columns, split, risk_class_next_day, risk_class_today
    model_table_full.csv    the whole processed table (all features) for offline experiments
    export_report.txt

Copy districts.csv and daily_features.csv into the backend's data/ folder, then use
backend_scripts/train_model_real.py (shipped in this repo) instead of train_model.py.

--reference-dir (optional): the backend's data/ folder. District ids are reused from it by name,
so existing ids stay stable.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import geopandas as gpd
import pandas as pd
import yaml

from floodprep.common import add_config_arg, ensure_dir, get_logger, load_config, normalize_name

log = get_logger("09_export")
CLASS_NAMES = {0: "low", 1: "moderate", 2: "high", 3: "severe"}  # backend uses lowercase strings


def export_seasonal(cfg, emap, args):
    """Backend v3 (hybrid assessment) files, see config/export_map.yaml `seasonal`."""
    import shutil
    out_dir = ensure_dir(cfg["paths"]["export"])
    interim, proc = cfg["paths"]["interim"], cfg["paths"]["processed"]
    dist = pd.read_csv(interim / "districts.csv")
    static = pd.read_csv(interim / "static_features.csv")
    notes = []
    if args.reference_dir and (Path(args.reference_dir) / "districts.csv").exists():
        ref = pd.read_csv(Path(args.reference_dir) / "districts.csv")
        by_name = {normalize_name(n): int(i) for n, i in zip(ref["name"], ref["id"])}
        id_map = {r.district_id: by_name.get(normalize_name(r.district_name)) for r in dist.itertuples()}
        bad = [k for k, v in id_map.items() if v is None]
        if bad:
            sys.exit(f"Districts not in the reference districts.csv: {bad}. Omit --reference-dir and use seed_db.py --reset.")
        notes.append("District ids reused from the reference districts.csv.")
    else:
        id_map = {d: i + 1 for i, d in enumerate(sorted(dist["district_id"]))}
        notes.append("District ids 1..N alphabetical. Use seed_db.py --reset.")

    # districts.csv --------------------------------------------------------------------------------------------
    geo = gpd.read_file(interim / "districts.geojson")
    geom = dict(zip(geo["district_id"], geo.geometry))
    d = dist[["district_id", "district_name"]].merge(static, on="district_id", how="left")
    rows = []
    for r in d.to_dict("records"):
        o = {"id": id_map[r["district_id"]], "name": r["district_name"], "state": emap["state_name"],
             "geometry": json.dumps(geom[r["district_id"]].__geo_interface__)}
        for b, sc in emap["districts"].items():
            o[b] = r.get(sc, float("nan"))
        rows.append(o)
    d_out = pd.DataFrame(rows).sort_values("id")
    opt = set(emap.get("optional_static", []))
    bad = [c for c in d_out.columns[d_out.isna().any()] if c not in opt]
    if bad:
        sys.exit(f"districts.csv would have empty values in {bad}. Check reports/terrain_quality.csv.")
    d_out.to_csv(out_dir / "districts.csv", index=False)
    for c in opt & set(d_out.columns):
        if d_out[c].isna().any():
            notes.append(f"{c} is empty for some/all districts: the backend trainer will not use it.")

    # rainfall_daily.csv ---------------------------------------------------------------------------------------
    rain = pd.read_csv(interim / "rainfall_daily.csv", parse_dates=["date"]).rename(columns={"zone_id": "district_id"})
    start = pd.Timestamp(cfg["project"]["start_date"]) - pd.Timedelta(days=60)
    rain = rain[(rain["date"] >= start) & rain["district_id"].isin(id_map)]
    r_out = pd.DataFrame({"district_id": rain["district_id"].map(id_map), "date": rain["date"].dt.strftime("%Y-%m-%d"),
                          "rainfall_mm": rain["rain_mm"].round(2), "n_stations": rain["n_stations"].astype(int)})
    r_out.sort_values(["district_id", "date"]).to_csv(out_dir / "rainfall_daily.csv", index=False)

    # climatology.csv / normal season / season_features ------------------------------------------------------
    cl = pd.read_csv(interim / "climatology.csv")
    cl["district_id"] = cl["district_id"].map(id_map)
    cl.dropna(subset=["district_id"]).astype({"district_id": int}).to_csv(out_dir / "climatology.csv", index=False)
    ns = pd.read_csv(interim / "normal_season_features.csv")
    ns["district_id"] = ns["district_id"].map(id_map)
    ns.dropna(subset=["district_id"]).astype({"district_id": int}).to_csv(out_dir / "normal_season_features.csv", index=False)
    tab = pd.read_csv(proc / "model_table_seasonal.csv")
    names = {i: n.lower() for i, n in enumerate(cfg["labels"]["class_names"])}
    from floodprep.climatology import SEASON_FEATURES
    sf = tab[["district_id", "year", "split", "metric_value", "risk_class"] + SEASON_FEATURES].copy()
    sf["district_id"] = sf["district_id"].map(id_map)
    sf["risk_class"] = sf["risk_class"].map(names)
    sf.to_csv(out_dir / "season_features.csv", index=False)
    tab.to_csv(out_dir / "model_table_full.csv", index=False)
    shutil.copy(proc / "hazard_config.json", out_dir / "hazard_config.json")
    shutil.copy(interim / "label_thresholds.json", out_dir / "label_thresholds.json")

    report = (f"districts.csv: {len(d_out)} rows\nrainfall_daily.csv: {len(r_out):,} rows ({r_out['date'].min()} .. {r_out['date'].max()})\n"
              f"climatology.csv: {len(cl):,} rows\nnormal_season_features.csv: {len(ns)} districts\n"
              f"season_features.csv: {len(sf)} district-years, splits {sf['split'].value_counts().to_dict()}, classes {sf['risk_class'].value_counts().to_dict()}\n\n"
              + "\n".join(notes))
    (out_dir / "export_report.txt").write_text(report)
    log.info("\n" + report)


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    ap.add_argument("--reference-dir", default=None)
    ap.add_argument("--map", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    emap = yaml.safe_load(Path(args.map or Path(__file__).resolve().parents[1] / "config" / "export_map.yaml").read_text())
    if cfg["project"].get("mode", "seasonal") == "seasonal":
        return export_seasonal(cfg, emap, args)
    out_dir = ensure_dir(cfg["paths"]["export"])
    notes = []

    feats = pd.read_csv(cfg["paths"]["processed"] / "district_day_features.csv", parse_dates=["date"])      # labelled rows
    all_path = cfg["paths"]["processed"] / "district_day_features_all.csv"
    feats_all = pd.read_csv(all_path, parse_dates=["date"]) if all_path.exists() else feats                 # + unlabelled days
    dist = pd.read_csv(cfg["paths"]["interim"] / "districts.csv")

    # fail early with a useful message if the backend's required inputs are not available
    opt = set(emap.get("optional_static", []))
    needed = {b: p for b, p in {**emap["daily_features"], **emap["districts"]}.items() if b not in opt}
    missing = [p for p in needed.values() if p not in feats.columns and p not in dist.columns]
    if missing:
        sys.exit(f"The processed table lacks {missing}. The backend needs them (static columns come from step 05 and the DEM; "
                 "rainfall windows come from step 07 -- check features.rain_windows includes 1,3,7,15,30). Fix and rerun.")

    # --- ids ---------------------------------------------------------------------------------------
    id_map = None
    if args.reference_dir and (Path(args.reference_dir) / "districts.csv").exists():
        ref = pd.read_csv(Path(args.reference_dir) / "districts.csv")
        by_name = {normalize_name(n): int(i) for n, i in zip(ref["name"], ref["id"])}
        mapped = {r.district_id: by_name.get(normalize_name(r.district_name)) for r in dist.itertuples()}
        unmatched = [k for k, v in mapped.items() if v is None]
        if unmatched:
            sys.exit(f"Districts not present in the backend reference districts.csv: {unmatched}. "
                     "Either use --reset in the backend (new ids) or align districts.selected.")
        id_map = mapped
        notes.append("District ids reused from the backend's existing districts.csv.")
    if id_map is None:
        id_map = {d: i + 1 for i, d in enumerate(sorted(dist["district_id"]))}
        notes.append("District ids assigned 1..N alphabetically (no --reference-dir). Use seed_db.py --reset.")

    # --- districts.csv -----------------------------------------------------------------------------
    geo = gpd.read_file(cfg["paths"]["interim"] / "districts.geojson").merge(
        dist[["district_id"] + [c for c in emap["districts"].values() if c in dist.columns]], on="district_id", how="left",
        suffixes=("", "_d"))
    static = pd.read_csv(cfg["paths"]["interim"] / "static_features.csv")
    d = dist[["district_id", "district_name"]].merge(static, on="district_id", how="left")
    rows = []
    geom_by_id = dict(zip(geo["district_id"], geo.geometry))
    for r in d.itertuples(index=False):
        rec = r._asdict()
        out = {"id": id_map[rec["district_id"]], "name": rec["district_name"], "state": emap["state_name"],
               "geometry": json.dumps(geom_by_id[rec["district_id"]].__geo_interface__)}
        for bcol, scol in emap["districts"].items():
            out[bcol] = rec.get(scol, float("nan"))
        rows.append(out)
    d_out = pd.DataFrame(rows).sort_values("id")
    bad = [c for c in d_out.columns[d_out.isna().any()] if c not in opt]
    if bad:
        sys.exit(f"districts.csv would contain empty values in {bad}; the backend declares these NOT NULL. "
                 "Check reports/terrain_quality.csv (DEM coverage per district).")
    for c in opt & set(d_out.columns):
        if d_out[c].isna().all():
            notes.append(f"{c} is empty for every district (no population raster) -> the backend model will not use it.")
        elif d_out[c].isna().any():
            notes.append(f"WARNING: {c} is empty for some districts; the trainer will drop the feature.")
    d_out.to_csv(out_dir / emap["districts_file"], index=False)

    # --- daily_features.csv ------------------------------------------------------------------------
    f = feats_all.copy()
    f["district_id"] = f["district_id"].map(id_map)
    bf = pd.DataFrame({"district_id": f["district_id"], "date": f["date"].dt.strftime("%Y-%m-%d")})
    for bcol, pcol in emap["daily_features"].items():
        bf[bcol] = f[pcol].round(3) if pcol in f.columns else float("nan")
    bf["split"] = f["split"]
    bf["risk_class_next_day"] = f["target_class"].astype("float").map(CLASS_NAMES)   # empty where the next-day label is unknown
    bf["risk_class_today"] = f["risk_class"].astype("float").map(CLASS_NAMES)   # empty where today's label is unknown

    nulls = [c for c in emap["required_non_null"] if bf[c].isna().any()]
    if nulls:
        sys.exit(f"NaN in {nulls} but the backend declares them NOT NULL (seed_db.py would crash). "
                 "Check rainfall coverage in step 03 (missing years / NaN grid cells).")
    bf.to_csv(out_dir / emap["daily_features_file"], index=False)
    feats.to_csv(out_dir / "model_table_full.csv", index=False)

    notes.append(f"daily_features.csv has {len(bf):,} rows; {int(bf['risk_class_next_day'].notna().sum()):,} have a known next-day "
                 "label (the trainer uses only those; the rest are for dashboard replay).")
    notes.append("Features in model_table_full.csv that the backend does NOT use: "
                 + ", ".join(sorted(set(feats.columns) - set(emap['daily_features'].values()) - {'district_id', 'date', 'split'}))[:600])

    report = (f"districts.csv: {len(d_out)} rows\ndaily_features.csv: {len(bf):,} rows\n"
              f"splits: {bf['split'].value_counts().to_dict()}\n"
              f"label balance (next day, known only): {bf['risk_class_next_day'].value_counts().to_dict()}\n\n" + "\n".join(notes))
    (out_dir / "export_report.txt").write_text(report)
    log.info("\n" + report)


if __name__ == "__main__":
    main()
