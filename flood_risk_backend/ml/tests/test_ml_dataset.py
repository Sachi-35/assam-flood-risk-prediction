"""Guards for the seasonal ML experiment. Run from flood_risk_backend/ml:  python -m pytest tests -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import ml_common as C


def test_no_leaky_or_identifier_features():
    used = set(sum(C.FEATURE_SETS.values(), []))
    for bad in ["pop_total", "pop_density_km2", "centroid_lat", "centroid_lon", "district_id", "year",
                "affected_population", "affected_pct", "risk_class", "n_obs_days"]:
        assert bad not in used


def test_table_counts_and_no_zero_filling():
    df, log = C.build_model_table()
    assert log["labelled_district_years"] == 99
    assert len(df) == 37 and df.district_id.nunique() == 13
    assert (df.n_obs_days >= C.MIN_OBS_DAYS).all()
    assert not df[C.FEATURE_SETS["static_plus_rain"]].isna().any().any()
    assert 2019 not in set(df.year)


def test_low_coverage_gives_nan_not_zero():
    rain = pd.DataFrame({"zone_id": ["x"] * 5, "date": pd.date_range("2021-06-01", periods=5), "rain_mm": [5.0] * 5})
    f = C.season_rain_features(rain, "x", 2021)
    assert f["n_obs_days"] == 5 and np.isnan(f["rain_mean_mm"])


def test_class_matches_authoritative_thresholds():
    labels, _, _ = C.load_inputs()
    r = labels[labels.label_status == "reported"]
    th = [1.643378630758702, 6.7162675535334095, 18.820795486695324]
    assert (np.digitize(r.metric_value, th) == r.risk_class).all()
