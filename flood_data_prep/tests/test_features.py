import numpy as np
import pandas as pd

from floodprep import features as F


def _rain(n=60, seed=1):
    rng = np.random.default_rng(seed)
    d = pd.date_range("2020-05-01", periods=n)
    return pd.DataFrame({"district_id": "a", "date": d, "rain_mm": rng.gamma(1, 8, n)})


def test_windows_are_trailing_sums():
    rain = _rain()
    panel = F.make_panel(["a"], "2020-05-31", "2020-06-29")
    out = F.add_local_rain_features(panel, rain, [1, 3, 7], 0.85)
    d = pd.Timestamp("2020-06-10")
    exp = rain.set_index("date")["rain_mm"].loc[d - pd.Timedelta(days=2): d].sum()
    assert abs(out.set_index("date").loc[d, "rain_3d"] - exp) < 1e-9


def test_no_future_leakage():
    """Changing rainfall AFTER day t must not change any feature on day t."""
    rain = _rain()
    panel = F.make_panel(["a"], "2020-05-31", "2020-06-29")
    a = F.add_local_rain_features(panel, rain, [1, 3, 7, 14], 0.85)
    r2 = rain.copy()
    cut = pd.Timestamp("2020-06-15")
    r2.loc[r2["date"] > cut, "rain_mm"] += 500
    b = F.add_local_rain_features(panel, r2, [1, 3, 7, 14], 0.85)
    cols = [c for c in a.columns if c not in ("district_id", "date")]
    pd.testing.assert_frame_equal(a[a.date <= cut][cols].reset_index(drop=True), b[b.date <= cut][cols].reset_index(drop=True))


def test_upstream_lag_uses_past_only():
    d = pd.date_range("2020-06-01", periods=20)
    up = pd.DataFrame({"date": d, "rain_mm": np.arange(20, dtype=float)})
    panel = F.make_panel(["a"], "2020-06-05", "2020-06-20")
    out = F.add_upstream_features(panel, up, [3], [2]).set_index("date")
    t = pd.Timestamp("2020-06-10")
    assert out.loc[t, "upstream_rain_3d_lag2"] == out.loc[t - pd.Timedelta(days=2), "upstream_rain_3d"]


def test_target_is_future_class():
    d = pd.date_range("2020-06-01", periods=5)
    panel = F.make_panel(["a"], d[0], d[-1])
    labels = pd.DataFrame({"district_id": "a", "date": d, "risk_class": [0, 0, 3, 0, 0], "label_observed": 1})
    out = F.add_targets(panel, labels, 1)
    assert out["target_class"].tolist()[:2] == [0, 3]       # features on day 2 predict class of day 3
    assert np.isnan(out["target_class"].iloc[-1])


def test_gauge_features_without_any_gauge():
    panel = F.make_panel(["a"], "2020-06-01", "2020-06-05")
    out = F.add_gauge_features(panel, pd.DataFrame(), set())
    assert (out["has_gauge_station"] == 0).all() and out["water_level_m"].isna().all()


def test_rain_deviation_uses_training_period_only():
    d = pd.date_range("2020-06-01", "2021-06-30")
    panel = F.make_panel(["a"], d[0], d[-1])
    panel["rain_7d"] = 50.0
    panel.loc[panel["date"] > "2020-12-31", "rain_7d"] = 500.0           # "future" huge rainfall
    out = F.add_rain_deviation(panel, "2020-12-31").set_index("date")
    # baseline is the TRAIN mean (50), so the future's 500 mm shows as +900 %, not diluted by itself
    assert abs(out.loc["2021-06-10", "rainfall_deviation_pct"] - 900.0) < 1e-9
    assert abs(out.loc["2020-07-10", "rainfall_deviation_pct"]) < 1e-9


def test_danger_pct():
    d = pd.date_range("2020-07-01", periods=3)
    panel = F.make_panel(["a"], d[0], d[-1])
    g = pd.DataFrame({"district_id": "a", "date": d, "water_level_m": [5.0, 9.0, 10.0], "discharge_cumec": np.nan,
                      "danger_level_m": 10.0, "warning_level_m": 9.0, "gauge_interpolated": 0})
    out = F.add_gauge_features(panel, g, {"a"})
    assert out["water_level_vs_danger_pct"].tolist() == [50.0, 90.0, 100.0]
