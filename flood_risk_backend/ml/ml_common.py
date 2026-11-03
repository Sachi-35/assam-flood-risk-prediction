"""Shared definitions for the seasonal-vulnerability ML experiment (isolated from the rest of the backend).

Everything that decides WHAT is a feature, WHAT is a row and WHAT is the target lives here, so that the dataset
builder, the evaluation script, the trainer and the prediction service cannot drift apart.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ML_DIR = Path(__file__).resolve().parent
INPUT_DIR = ML_DIR / "inputs"
ARTIFACT_DIR = ML_DIR / "artifacts"
REPORT_DIR = ML_DIR / "reports"

SEED = 42
CLASSES = ["Low", "Moderate", "High", "Severe"]
CLASS_TO_INT = {c: i for i, c in enumerate(CLASSES)}

# --- fixed seasonal window used for rainfall features (month/day, inclusive). Labels cover different reporting periods
# per year (2019: 5 days, 2020: 159, 2021: 109, 2022: 205, 2023: 183), so rainfall is NOT aggregated over each row's own
# period; it always uses the same monsoon window, which keeps the features comparable between years.
SEASON_START = (6, 1)
SEASON_END = (9, 30)
MIN_OBS_DAYS = 30          # a district-season needs at least this many reported rainfall days in the window
HEAVY_MM = 64.5            # IMD "heavy rain" lower bound (mm/day); applied to station-mean values, so approximate
TRAIN_YEARS = (2020, 2021, 2022, 2023)   # 2019 labels are 5-day snapshots (27 Oct-1 Nov), not seasons -> excluded

RAIN_FEATURES = ["rain_mean_mm", "rain_p90_mm", "rain_max_mm", "heavy_day_frac", "rain_cv"]
# Terrain only. pop_total and pop_density_km2 are deliberately excluded: the label is affected_population / pop_total,
# so they are the denominator of the target (leakage). Centroid lat/lon are excluded: they identify the district.
STATIC_FEATURES = ["elev_mean_m", "elev_std_m", "slope_mean_deg", "low_lying_frac", "area_km2"]
FEATURE_SETS = {
    "rain_only": RAIN_FEATURES,
    "static_only": STATIC_FEATURES,
    "static_plus_rain": STATIC_FEATURES + RAIN_FEATURES,
}


def season_rain_features(rain: pd.DataFrame, zone_id: str, year: int) -> dict:
    """Rainfall features for one district-season from *reported* days only. Missing days are never treated as zero.

    rain: columns zone_id, date (datetime), rain_mm.
    Returns NaN features and n_obs_days < MIN_OBS_DAYS when coverage is inadequate.
    """
    start = pd.Timestamp(year=year, month=SEASON_START[0], day=SEASON_START[1])
    end = pd.Timestamp(year=year, month=SEASON_END[0], day=SEASON_END[1])
    x = rain[(rain.zone_id == zone_id) & (rain.date >= start) & (rain.date <= end)].rain_mm.dropna()
    out = {"n_obs_days": int(len(x))}
    if len(x) < MIN_OBS_DAYS:
        out.update({k: np.nan for k in RAIN_FEATURES})
        return out
    out.update({
        "rain_mean_mm": float(x.mean()),
        "rain_p90_mm": float(x.quantile(0.9)),
        "rain_max_mm": float(x.max()),
        "heavy_day_frac": float((x >= HEAVY_MM).mean()),
        "rain_cv": float(x.std(ddof=1) / x.mean()),
    })
    return out


def load_inputs(input_dir: Path = INPUT_DIR):
    labels = pd.read_csv(input_dir / "labels_annual.csv")
    rain = pd.read_csv(input_dir / "rainfall_daily.csv", parse_dates=["date"])
    static = pd.read_csv(input_dir / "static_features.csv")
    return labels, rain, static


def build_model_table(input_dir: Path = INPUT_DIR) -> tuple[pd.DataFrame, dict]:
    """One row per labelled district-year that has adequate rainfall coverage. Also returns an attrition log."""
    labels, rain, static = load_inputs(input_dir)
    lab = labels[labels.label_status == "reported"].copy()
    log = {"labelled_district_years": int(len(lab))}
    lab = lab[lab.year.isin(TRAIN_YEARS)]
    log["after_excluding_2019_snapshots"] = int(len(lab))
    rows = []
    for _, r in lab.iterrows():
        f = season_rain_features(rain, r.district_id, int(r.year))
        rows.append({"district_id": r.district_id, "year": int(r.year), "risk_label": r.risk_label,
                     "risk_class": int(r.risk_class), "affected_pct": r.metric_value,
                     "affected_population": r.affected_population, **f})
    df = pd.DataFrame(rows)
    log["with_any_rainfall_station"] = int((df.n_obs_days > 0).sum())
    df = df[df.n_obs_days >= MIN_OBS_DAYS].copy()
    log[f"with_at_least_{MIN_OBS_DAYS}_rain_days"] = int(len(df))
    df = df.merge(static[["district_id"] + STATIC_FEATURES], on="district_id", how="left")
    log["rows_missing_static"] = int(df[STATIC_FEATURES].isna().any(axis=1).sum())
    return df.sort_values(["year", "district_id"]).reset_index(drop=True), log
