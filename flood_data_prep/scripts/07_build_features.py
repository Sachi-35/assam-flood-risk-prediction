#!/usr/bin/env python
"""Step 7: assemble the modelling table.

project.mode = seasonal (your data): one row per district-YEAR: seasonal rainfall features (over the label's own period) + terrain/population
   + the annual severity class. Also builds the rainfall climatology (baseline years) used by the window hazard.
   Output data/processed/model_table_seasonal.csv, data/interim/climatology.csv, normal_season_features.csv, hazard_config.json
project.mode = daily: the original district x day table described below.

Input : data/interim/{districts,rainfall_daily,gauge_daily,static_features,labels_daily}.csv
Output: data/processed/district_day_features.csv      TRAINING table: only rows whose next-day label is known
        data/processed/district_day_features_all.csv  every district-day with features (label may be empty) - for the dashboard
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

import json

import numpy as np

from floodprep import climatology as C
from floodprep import features as F
from floodprep.common import add_config_arg, ensure_dir, get_logger, load_config

log = get_logger("07_features")


def main_seasonal(cfg):
    interim, proc = cfg["paths"]["interim"], ensure_dir(cfg["paths"]["processed"])
    reports = ensure_dir(cfg["paths"]["reports"])
    hz, sc = cfg["hazard"], cfg["season"]
    min_frac = float(cfg["rainfall"].get("min_obs_fraction", 0.8))
    grid, lq = hz["quantile_grid"], hz["level_quantiles"]
    if not set(lq) <= set(grid):
        sys.exit("hazard.level_quantiles must be a subset of hazard.quantile_grid")

    districts = pd.read_csv(interim / "districts.csv")
    rain = pd.read_csv(interim / "rainfall_daily.csv", parse_dates=["date"]).rename(columns={"zone_id": "district_id"})
    static = pd.read_csv(interim / "static_features.csv")
    labels = pd.read_csv(interim / "labels_annual.csv", parse_dates=["period_start", "period_end"], low_memory=False)
    labels = labels[labels["metric_value"].notna()].copy()

    d0, d1 = rain["date"].min(), rain["date"].max()
    series = {d: C.full_series(rain, d, d0, d1) for d in districts["district_id"] if (rain["district_id"] == d).any()}
    no_rain = sorted(set(districts["district_id"]) - set(series))
    if no_rain:
        log.warning(f"No rainfall at all for {no_rain}: they cannot get features or hazard.")
    log.info(f"Rainfall {d0.date()} -> {d1.date()} for {len(series)} districts; baseline years {hz['baseline_years']}")

    qtable = C.build_quantile_table(series, hz["windows"], hz["baseline_years"], grid, hz["doy_halfwidth"], min_frac,
                                    hz["min_baseline_values"], int(hz.get("min_baseline_years", 1)))
    if qtable.empty:
        sys.exit("The baseline climatology is empty: rainfall does not cover hazard.baseline_years well enough "
                 f"(need >= {hz['min_baseline_values']} window totals from >= {hz.get('min_baseline_years', 1)} years per district, window and day-of-year). "
                 "Run scripts/11_reference_period_check.py to compare candidate reference periods; nothing was substituted.")
    # coverage by district x window, and the reference years that actually contributed (never substituted silently)
    y0, y1 = hz["baseline_years"]
    cov_rows = []
    for did, s_ in series.items():
        for w in hz["windows"]:
            sums = C.window_sum(s_, w, min_frac)
            sums = sums[(sums.index.year >= y0) & (sums.index.year <= y1)].dropna()
            q = qtable[(qtable["district_id"] == did) & (qtable["window_days"] == w)]
            cov_rows.append({"district_id": did, "window_days": w, "reference_years_requested": f"{y0}-{y1}",
                             "years_with_window_totals": ",".join(map(str, sorted(set(sums.index.year)))),
                             "doy_usable": len(q), "doy_usable_pct": round(100 * len(q) / 366, 1),
                             "median_n_values": float(q["n_values"].median()) if len(q) else 0.0,
                             "min_n_years": int(q["n_years"].min()) if len(q) else 0,
                             "status": "ok" if len(q) >= 0.9 * 366 else ("partial: hazard unknown on other days" if len(q) else "NO CLIMATOLOGY: hazard unknown")})
    pd.DataFrame(cov_rows).to_csv(reports / "climatology_coverage.csv", index=False)
    cover = qtable.groupby(["district_id", "window_days"]).size().unstack()
    thin = sorted(set(series) - set(qtable["district_id"]))
    if thin:
        log.warning(f"No usable baseline climatology (hazard unavailable) for: {thin}")
    qtable.round(3).to_csv(interim / "climatology.csv", index=False)
    haz = C.hazard_table(series, qtable, hz["windows"], lq, min_frac)

    # ---- seasonal features for every labelled district-year -------------------------------------------------------
    fixed = sc["fixed"]
    cache = {}

    def base_stats(did, ms, me):
        k = (did, ms, me)
        if k not in cache:
            cache[k] = C.baseline_season_stats(series[did], ms, me, hz["baseline_years"], min_frac, sc["heavy_day_quantile"])
        return cache[k]

    rows, dropped = [], []
    for r in labels.itertuples():
        if r.district_id not in series:
            dropped.append((r.district_id, r.year, "no rainfall for district"))
            continue
        if sc["source"] == "label_period" and pd.notna(r.period_start) and pd.notna(r.period_end):
            a, b = r.period_start, r.period_end
            used = "label_period"
        else:
            a, b = C.span_for_year(fixed["start"], fixed["end"], int(r.year))
            used = "fixed_season"
        ms, me = a.strftime("%m-%d"), b.strftime("%m-%d")
        mean_total, heavy, n_base = base_stats(r.district_id, ms, me)
        f, why = C.season_features(series[r.district_id], a, b, haz, r.district_id, mean_total, heavy, min_frac)
        if f is None:
            dropped.append((r.district_id, r.year, why))
            continue
        rows.append({"district_id": r.district_id, "year": int(r.year), "season_start": a, "season_end": b, "season_basis": used,
                     "baseline_years_used": n_base, **f})
    feats = pd.DataFrame(rows)
    unavailable = pd.DataFrame(dropped, columns=["district_id", "year", "reason"])
    unavailable.to_csv(reports / "season_rows_dropped.csv", index=False)         # name kept for compatibility: these rows are FLAGGED, not removed
    if dropped:
        log.warning(f"{len(dropped)} of {len(labels)} labelled district-years have UNAVAILABLE rainfall features (kept in the table, flagged "
                    f"`rainfall_status`, features unknown; model steps exclude them and say so): see reports/season_rows_dropped.csv")
    if feats.empty:
        log.error("No district-year has enough rainfall coverage in its season: every season feature is unknown. The table is still written "
                  "with rainfall_status explaining why; no model can be trained until the rainfall input is fixed.")
        feats = pd.DataFrame(columns=["district_id", "year"] + C.SEASON_FEATURES)

    # ---- 'normal season' per district (for the vulnerability component): median season features over baseline years ----
    spans = labels.dropna(subset=["period_start", "period_end"])
    if sc["source"] == "label_period" and len(spans):
        ms, me = (spans.assign(ms=spans.period_start.dt.strftime("%m-%d"), me=spans.period_end.dt.strftime("%m-%d"))
                  .groupby(["ms", "me"]).size().sort_values(ascending=False).index[0])
    else:
        ms, me = fixed["start"], fixed["end"]
    log.info(f"'Normal season' reference span: {ms} .. {me}")
    normal = []
    for did, s_ in series.items():
        mean_total, heavy, n_base = base_stats(did, ms, me)
        per_year = []
        for y in range(hz["baseline_years"][0], hz["baseline_years"][1] + 1):
            a, b = C.span_for_year(ms, me, y)
            f, _ = C.season_features(s_, a, b, haz, did, mean_total, heavy, min_frac)
            if f:
                per_year.append(f)
        if len(per_year) >= int(hz.get("min_normal_years", 3)):
            m = pd.DataFrame(per_year)[C.SEASON_FEATURES].median()
            normal.append({"district_id": did, "n_years": len(per_year), "span": f"{ms}..{me}", **m.to_dict()})
    normal = pd.DataFrame(normal)
    normal.round(4).to_csv(interim / "normal_season_features.csv", index=False)
    if normal.empty:
        log.warning("No 'normal season' could be computed (fewer than hazard.min_normal_years usable baseline years per district): vulnerability baseline unavailable.")

    # ---- model table -------------------------------------------------------------------------------------------------
    keep_static = ["district_id", "area_km2"] + [c for c in C.STATIC_FEATURES + ["pop_total"] if c in static.columns]
    tab = labels[["district_id", "year", "split", "period_start", "period_end", "affected_population", "metric_value", "risk_class",
                  "risk_label", "label_status", "n_source_rows"] + (["quality_flags"] if "quality_flags" in labels else [])]
    tab = tab.merge(feats, on=["district_id", "year"], how="left").merge(static[keep_static], on="district_id", how="left")
    reasons = {(r.district_id, int(r.year)): r.reason for r in unavailable.itertuples()}
    tab["rainfall_status"] = [("ok" if pd.notna(f) else reasons.get((d, int(y)), "season features unavailable"))
                              for d, y, f in zip(tab["district_id"], tab["year"], tab["season_total_mm"] if "season_total_mm" in tab else [np.nan] * len(tab))]
    tab = tab.merge(districts[["district_id", "district_name"]], on="district_id", how="left")
    tab["risk_class"] = tab["risk_class"].astype(int)
    tab = tab.sort_values(["year", "district_id"]).reset_index(drop=True)
    tab.to_csv(proc / "model_table_seasonal.csv", index=False)
    (proc / "hazard_config.json").write_text(json.dumps({
        "windows": hz["windows"], "level_quantiles": lq, "quantile_grid": grid, "min_obs_fraction": min_frac,
        "baseline_years": hz["baseline_years"], "doy_halfwidth": hz["doy_halfwidth"], "level_names": C.LEVEL_NAMES,
        "min_baseline_values": hz["min_baseline_values"], "min_baseline_years": int(hz.get("min_baseline_years", 1)),
        "reference_note": "baseline_years are the REQUESTED reference years; see reports/climatology_coverage.csv for what each district contributed"}, indent=2))
    log.info(f"Model table: {len(tab)} district-years x {tab.shape[1]} columns -> {proc/'model_table_seasonal.csv'}")
    log.info("Split sizes:\n" + tab["split"].value_counts().to_string())


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    cfg = load_config(ap.parse_args().config)
    if cfg["project"].get("mode", "seasonal") == "seasonal":
        return main_seasonal(cfg)
    interim, proc = cfg["paths"]["interim"], ensure_dir(cfg["paths"]["processed"])
    pc, fc = cfg["project"], cfg["features"]

    districts = pd.read_csv(interim / "districts.csv")
    ids = list(districts["district_id"])
    rain = pd.read_csv(interim / "rainfall_daily.csv", parse_dates=["date"])
    panel = F.make_panel(ids, pc["start_date"], pc["end_date"])

    local = rain[rain["zone_id"] != "UPSTREAM"].rename(columns={"zone_id": "district_id"})
    panel = F.add_local_rain_features(panel, local, fc["rain_windows"], fc["api_decay"])

    panel = F.add_rain_deviation(panel, cfg["splits"]["train_end"])

    up = rain[rain["zone_id"] == "UPSTREAM"]
    if len(up):
        panel = F.add_upstream_features(panel, up, fc["upstream_windows"], fc["upstream_lags"])
    else:
        log.warning("No upstream rainfall -> upstream_* features omitted")

    gpath = interim / "gauge_daily.csv"
    gauge = pd.read_csv(gpath, parse_dates=["date"]) if gpath.exists() else pd.DataFrame()
    if len(gauge):
        panel = F.add_gauge_features(panel, gauge, set(gauge["district_id"].unique()))
    else:
        log.info("No gauge data: gauge features are not created (not zero-filled, not NaN-filled).")

    static = pd.read_csv(interim / "static_features.csv")
    panel = panel.merge(static, on="district_id", how="left")
    panel = panel.merge(districts[["district_id", "district_name"]], on="district_id", how="left")
    panel = F.add_calendar(panel)

    labels = pd.read_csv(interim / "labels_daily.csv", parse_dates=["date"])
    keep = ["district_id", "date", "metric_value", "risk_class", "risk_label", "label_observed", "label_quality"]
    panel = F.add_targets(panel, labels[[c for c in keep if c in labels.columns]], pc["target_lead_days"])

    s = cfg["splits"]
    panel["split"] = "test"
    panel.loc[panel["date"] <= pd.Timestamp(s["val_end"]), "split"] = "val"
    panel.loc[panel["date"] <= pd.Timestamp(s["train_end"]), "split"] = "train"

    rain_cols = [c for c in panel.columns if c.startswith("rain_") and c[5:-1].isdigit()]
    n_nan_rain = int(panel[rain_cols].isna().any(axis=1).sum())
    if n_nan_rain:
        log.warning(f"{n_nan_rain:,} district-days have a missing rainfall feature (gaps in the rainfall series). "
                    "They are dropped below; check reports/rainfall_qc.csv.")
        panel = panel.dropna(subset=rain_cols + ["rainfall_deviation_pct"])

    # Every day with complete rainfall features (also days whose label is unknown) is kept for the dashboard replay.
    panel_all = panel.sort_values(["district_id", "date"]).reset_index(drop=True)
    panel_all.to_csv(proc / "district_day_features_all.csv", index=False)

    n0 = len(panel)
    if fc.get("drop_rows_without_target", True):
        # Unknown next-day label (no report that day, or district not listed under absence_policy=unknown) -> row removed.
        panel = panel.dropna(subset=["target_class"])
    log.info(f"Rows: {n0:,} -> {len(panel):,} (dropped {n0-len(panel):,} whose next-day label is unknown)")
    if len(panel) == 0:
        sys.exit("No rows with a known target. See reports/label_audit.md (are there daily labels inside the project dates?).")
    panel["target_class"] = panel["target_class"].astype(int)
    panel["risk_class"] = panel["risk_class"].astype("Int64")   # today's class may be unknown; stays <NA>

    panel = panel.sort_values(["district_id", "date"]).reset_index(drop=True)
    panel.to_csv(proc / "district_day_features.csv", index=False)
    log.info(f"Saved {len(panel):,} rows x {panel.shape[1]} columns -> {proc/'district_day_features.csv'}")
    log.info("Split sizes:\n" + panel["split"].value_counts().to_string())


if __name__ == "__main__":
    main()
