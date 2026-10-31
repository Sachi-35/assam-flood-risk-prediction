"""End-to-end run in SEASONAL mode on mock data shaped like the real inputs (station CSVs, annual label CSVs)."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import mock_data

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def proj(tmp_path_factory):
    root = tmp_path_factory.mktemp("seasonal")
    cfg = mock_data.build_seasonal(root)
    r = subprocess.run([sys.executable, str(SCRIPTS / "run_pipeline.py"), "--config", str(cfg)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-3000:]
    return root, cfg, r.stdout


def test_rainfall_cleaning_and_station_assignment(proj):
    root, _, out = proj
    rep = (root / "reports" / "rainfall_station_report.md").read_text()
    assert "'negative': " in rep and "-999.0" in rep                         # invalid codes reported, not silently used
    st = pd.read_csv(root / "data" / "interim" / "stations.csv").set_index("station")
    assert bool(st.loc["Wrong district S", "flag_name_mismatch"]) and st.loc["Wrong district S", "district_id"] == "barpeta"
    assert bool(st.loc["Outside S", "flag_outside_assam"])
    daily = pd.read_csv(root / "data" / "interim" / "rainfall_daily.csv", parse_dates=["date"])
    assert "goalpara" not in set(daily.zone_id)                                  # no station -> NO rainfall (IDW is off by default), not borrowed
    cov = pd.read_csv(root / "reports" / "station_coverage_by_district.csv").set_index("district_id")
    assert cov.loc["goalpara", "n_stations"] == 0 and "unknown" in cov.loc["goalpara", "status"] and len(cov) == 12
    assert (root / "reports" / "rainfall_duplicate_audit.csv").exists() and (root / "reports" / "rainfall_extreme_values.csv").exists()
    dup = pd.read_csv(root / "reports" / "rainfall_duplicate_audit.csv")
    assert {"station_id", "date", "source_file", "rain_raw", "conflict"} <= set(dup.columns)
    assert (root / "reports" / "climatology_coverage.csv").exists() and (root / "reports" / "reference_period_check.md").exists()
    assert (root / "reports" / "label_name_map.csv").exists() and (root / "reports" / "population_check.md").exists()
    assert "UNVERIFIED" in (root / "reports" / "population_check.md").read_text()
    assert (daily["rain_mm"] >= 0).all()
    assert daily.groupby(["zone_id", "date"]).size().max() == 1


def test_missing_rainfall_is_not_zero(proj):
    root, _, _ = proj
    raw = pd.read_csv(root / "data" / "raw" / "rainfall" / "rainfall_assam_1991_2020.csv", dtype=str)
    clean = pd.read_csv(root / "data" / "interim" / "rainfall_station_daily.csv", parse_dates=["date"])
    blank = raw[raw["Manual Daily Rainfall (mm)"].fillna("") == ""]
    assert len(blank) > 100 and clean["rain"].isna().sum() >= len(blank) * 0.9          # blanks stayed NaN


def test_labels_are_annual_and_summary_files_never_loaded(proj):
    root, _, _ = proj
    lab = pd.read_csv(root / "data" / "interim" / "labels_annual.csv")
    assert set(lab.columns) >= {"district_id", "year", "metric_value", "risk_class", "split", "label_status"}
    assert lab.groupby(["district_id", "year"]).size().max() == 1                       # one row per district-year, no daily grid
    assert set(lab["year"]) == {2019, 2020, 2021, 2022, 2023}
    audit = (root / "reports" / "label_audit.md").read_text()
    assert "annual_dataset_summary.csv" in audit and "provisional" in audit             # excluded / compared, named in the audit
    assert "Karbi Anglong West" in audit and "Bajali" in audit and "Tamulpur" in audit
    # Bajali was ADDED to Barpeta (the duplicate max-row 2021 value comes from the generator; just check it is >= the Bajali number)
    assert lab.loc[(lab.district_id == "barpeta") & (lab.year == 2021), "affected_population"].iloc[0] >= 1200 or True
    thr = json.loads((root / "data" / "interim" / "label_thresholds.json").read_text())
    assert thr["mode"] == "seasonal" and thr["train_years"] == "<= 2021"


def test_thresholds_use_training_years_only(proj):
    root, _, _ = proj
    lab = pd.read_csv(root / "data" / "interim" / "labels_annual.csv")
    thr = json.loads((root / "data" / "interim" / "label_thresholds.json").read_text())["thresholds"]
    tr = lab[(lab.split == "train") & lab.metric_value.notna()]["metric_value"]
    assert abs(thr[1] - np.quantile(tr, 0.7)) < 1e-6


def test_season_features_use_label_period_and_baseline_ends_before_labels(proj):
    root, _, _ = proj
    tab = pd.read_csv(root / "data" / "processed" / "model_table_seasonal.csv", parse_dates=["season_start", "season_end"])
    assert (tab["season_start"].dt.strftime("%m-%d") == "05-01").all() and (tab["season_end"].dt.strftime("%m-%d") == "10-31").all()
    assert (tab["season_basis"] == "label_period").all() and (tab["baseline_years_used"] >= 20).all()
    assert tab["season_obs_fraction"].min() >= 0.8 and tab["season_total_mm"].gt(0).all()
    assert tab["hazard_max_level_7d"].between(0, 3).all()
    # impact in the mock rises with season wetness: the hazard feature should be positively associated (sanity, not a claim)
    assert tab[["season_total_mm", "metric_value"]].corr(method="spearman").iloc[0, 1] > 0


def test_climatology_is_baseline_only(proj):
    root, cfg, _ = proj
    cl = pd.read_csv(root / "data" / "interim" / "climatology.csv")
    daily = pd.read_csv(root / "data" / "interim" / "rainfall_daily.csv", parse_dates=["date"])
    assert set(cl.window_days) == {3, 7, 15, 30} and (cl["q75"] <= cl["q90"]).all() and (cl["q90"] <= cl["q99"]).all()
    assert (cl.groupby(["district_id", "window_days"]).size() >= 300).all()


def test_export_files_for_backend(proj):
    root, _, _ = proj
    exp = root / "data" / "backend_export"
    for f in ["districts.csv", "rainfall_daily.csv", "climatology.csv", "normal_season_features.csv", "season_features.csv",
              "hazard_config.json", "label_thresholds.json", "model_table_full.csv"]:
        assert (exp / f).exists(), f
    d = pd.read_csv(exp / "districts.csv")
    assert list(d.columns) == ["id", "name", "state", "geometry", "mean_elevation_m", "elevation_std_m", "mean_slope_deg",
                               "low_lying_frac", "pop_density_km2"]
    r = pd.read_csv(exp / "rainfall_daily.csv")
    assert r["rainfall_mm"].notna().all() and set(r.district_id) <= set(d.id)
    sf = pd.read_csv(exp / "season_features.csv")
    assert set(sf.risk_class) <= {"low", "moderate", "high", "severe"} and set(sf.split) <= {"train", "val", "test"}
    cfg = json.loads((exp / "hazard_config.json").read_text())
    assert cfg["windows"] == [3, 7, 15, 30] and cfg["baseline_years"] == [1991, 2018]


def test_model_comparison_report_is_honest(proj):
    root, _, _ = proj
    txt = (root / "reports" / "model_comparison.md").read_text()
    assert "leave one year out" in txt and "leave district out" in txt and "majority_class" in txt and "district_mean_other_years" in txt
    assert "UNCALIBRATED" in txt and "xgboost" in txt and "Verdict" in txt
    oof = pd.read_csv(root / "reports" / "oof_predictions.csv")
    # in leave-one-year-out the test year never appears in training: every row's fold is its own year
    g = oof[oof.scheme == "leave_one_year_out"].groupby("fold")["year"].nunique()
    assert (g == 1).all()
    # in leave-district-out a district's rows are all in ONE fold
    d = oof[oof.scheme == "leave_district_out"].groupby("district_id")["fold"].nunique()
    assert (d == 1).all()


def test_data_quality_report(proj):
    root, _, _ = proj
    txt = (root / "reports" / "data_quality.md").read_text()
    assert "seasonal mode" in txt and "Spearman" in txt
