"""Feature engineering on the district x day panel.

RULE: a feature on day t may only use information available at the END of day t.
All rolling windows are trailing (never centred) and the target is shifted *backwards*,
so features(t) never see label(t+lead). tests/test_features.py checks this.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_panel(district_ids: list[str], start, end) -> pd.DataFrame:
    dates = pd.date_range(start, end, freq="D")
    idx = pd.MultiIndex.from_product([sorted(district_ids), dates], names=["district_id", "date"])
    return idx.to_frame(index=False)


def _trailing_sum(s: pd.Series, w: int) -> pd.Series:
    return s.rolling(w, min_periods=w).sum()


def add_local_rain_features(panel: pd.DataFrame, rain: pd.DataFrame, windows, api_decay: float) -> pd.DataFrame:
    """rain: [district_id, date, rain_mm] (must include the buffer days before the panel start)."""
    r = rain.sort_values(["district_id", "date"]).copy()
    out = []
    for did, g in r.groupby("district_id"):
        g = g.set_index("date").asfreq("D")
        s = g["rain_mm"]
        f = pd.DataFrame(index=g.index)
        for w in windows:
            f[f"rain_{w}d"] = _trailing_sum(s, w)
        f["rain_max_3d"] = s.rolling(3, min_periods=3).max()
        alpha = 1.0 - api_decay
        f["antecedent_precip_index"] = s.ewm(alpha=alpha, adjust=False).mean() / alpha
        f["district_id"] = did
        out.append(f.reset_index().rename(columns={"index": "date"}))
    feats = pd.concat(out, ignore_index=True)
    return panel.merge(feats, on=["district_id", "date"], how="left")


def add_upstream_features(panel: pd.DataFrame, up: pd.DataFrame, windows, lags) -> pd.DataFrame:
    """up: [date, rain_mm] for the upstream zone (basin-wide, same for every district)."""
    s = up.sort_values("date").set_index("date")["rain_mm"].asfreq("D")
    f = pd.DataFrame(index=s.index)
    for w in windows:
        f[f"upstream_rain_{w}d"] = _trailing_sum(s, w)
    for lag in lags:
        f[f"upstream_rain_3d_lag{lag}"] = _trailing_sum(s, 3).shift(lag)
    return panel.merge(f.reset_index().rename(columns={"index": "date"}), on="date", how="left")


def add_gauge_features(panel: pd.DataFrame, gauge: pd.DataFrame, assigned_districts: set[str]) -> pd.DataFrame:
    """gauge: [district_id, date, water_level_m, discharge_cumec, danger_level_m, warning_level_m, flags]."""
    out = []
    if gauge is None or gauge.empty:
        gauge = pd.DataFrame(columns=["district_id", "date"])
    for did, g in gauge.sort_values(["district_id", "date"]).groupby("district_id"):
        g = g.set_index("date").asfreq("D")
        f = pd.DataFrame(index=g.index)
        f["water_level_m"] = g["water_level_m"]
        f["water_level_change_1d"] = g["water_level_m"].diff(1)
        f["water_level_change_3d"] = g["water_level_m"].diff(3)
        f["water_level_max_7d"] = g["water_level_m"].rolling(7, min_periods=3).max()
        f["discharge_cumec"] = g["discharge_cumec"]
        if "warning_level_m" in g:
            f["level_minus_warning_m"] = g["water_level_m"] - g["warning_level_m"]
        if "danger_level_m" in g:
            f["level_minus_danger_m"] = g["water_level_m"] - g["danger_level_m"]
            f["water_level_vs_danger_pct"] = 100.0 * g["water_level_m"] / g["danger_level_m"]
        f["gauge_interpolated"] = g.get("gauge_interpolated")
        f["district_id"] = did
        out.append(f.reset_index().rename(columns={"index": "date"}))
    cols_empty = [
        "water_level_m", "water_level_change_1d", "water_level_change_3d", "water_level_max_7d",
        "discharge_cumec", "level_minus_warning_m", "level_minus_danger_m", "water_level_vs_danger_pct",
        "gauge_interpolated",
    ]
    if out:
        panel = panel.merge(pd.concat(out, ignore_index=True), on=["district_id", "date"], how="left")
    else:
        for c in cols_empty:
            panel[c] = np.nan
    panel["has_gauge_station"] = panel["district_id"].isin(assigned_districts).astype(int)
    panel["gauge_interpolated"] = panel["gauge_interpolated"].fillna(0).astype(int)  # a flag, not a measurement
    return panel


def add_calendar(panel: pd.DataFrame) -> pd.DataFrame:
    doy = panel["date"].dt.dayofyear
    panel["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    panel["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    panel["month"] = panel["date"].dt.month
    panel["is_monsoon"] = panel["month"].between(6, 9).astype(int)
    return panel


def add_targets(panel: pd.DataFrame, labels: pd.DataFrame, lead: int) -> pd.DataFrame:
    """labels: [district_id, date, risk_class, label_observed]. Adds today's class and the class `lead` days ahead."""
    panel = panel.merge(labels, on=["district_id", "date"], how="left")
    panel = panel.sort_values(["district_id", "date"])
    panel["target_class"] = panel.groupby("district_id")["risk_class"].shift(-lead)
    return panel


def add_rain_deviation(panel: pd.DataFrame, train_end, floor_mm: float = 5.0) -> pd.DataFrame:
    """rainfall_deviation_pct: 7-day rainfall vs the usual 7-day rainfall for the same district and calendar month.

    "Usual" is computed from TRAINING-period rows only (date <= train_end), so validation/test data never
    influence the baseline. The denominator is floored at `floor_mm` so dry months don't explode the percentage.
    """
    panel = panel.copy()
    panel["_m"] = panel["date"].dt.month
    train = panel[panel["date"] <= pd.Timestamp(train_end)]
    clim = train.groupby(["district_id", "_m"])["rain_7d"].mean().rename("_clim").reset_index()
    panel = panel.merge(clim, on=["district_id", "_m"], how="left")
    # a month with no training history falls back to the district's overall training mean
    overall = train.groupby("district_id")["rain_7d"].mean().rename("_overall").reset_index()
    panel = panel.merge(overall, on="district_id", how="left")
    base = panel["_clim"].fillna(panel["_overall"]).clip(lower=floor_mm)
    panel["rainfall_deviation_pct"] = 100.0 * (panel["rain_7d"] - base) / base
    return panel.drop(columns=["_m", "_clim", "_overall"])
