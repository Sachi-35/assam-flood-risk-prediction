import numpy as np
import pandas as pd

from floodprep import climatology as C


def series(years=range(1991, 2001), seed=0, p_missing=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{years[0]}-01-01", f"{years[-1]}-12-31")
    s = pd.Series(rng.gamma(0.5, 8, len(idx)), index=idx)
    s[rng.random(len(idx)) < p_missing] = np.nan
    return s


def test_window_sum_requires_enough_observed_days_and_is_not_zero_filled():
    s = pd.Series([1.0, np.nan, np.nan, np.nan, 2.0, 2.0, 2.0], index=pd.date_range("2020-01-01", periods=7))
    w = C.window_sum(s, 3, 0.67)                     # need ceil(3*.67)=3 -> all three observed
    assert np.isnan(w.iloc[3]) and w.iloc[6] == 6.0
    w2 = C.window_sum(s, 3, 0.34)                    # need 2 of 3 observed
    assert np.isnan(w2.iloc[3])                      # zero observed days -> NaN, not 0
    assert w2.iloc[4] != w2.iloc[4]                  # only 1 of 3 observed on day 5 -> still NaN
    assert w2.iloc[5] == 4.0                         # 2 of 3 observed -> sum of the observed days


def test_quantile_table_uses_baseline_years_only():
    s = series(range(1991, 2001))
    s.loc["2000-01-01":] = s.loc["2000-01-01":] + 1000       # a wild final year, outside the baseline
    qt = C.build_quantile_table({"a": s}, [3], (1991, 1999), [0.5, 0.9], doy_halfwidth=10, min_obs_fraction=0.8, min_values=50)
    assert qt["q90"].max() < 500
    assert set(qt.columns) >= {"district_id", "window_days", "doy", "q50", "q90"}


def test_hazard_level_counts_strictly_exceeded_quantiles():
    q = pd.DataFrame({"doy": [1, 2, 3], "q75": [0.0, 10.0, 10.0], "q90": [0.0, 20.0, 20.0], "q97": [0.0, 30.0, 30.0]})
    idx = pd.to_datetime(["2021-01-01", "2021-01-02", "2021-01-03", "2021-01-02"])
    sums = pd.Series([0.0, 25.0, 31.0, np.nan], index=idx)
    h = C.hazard_levels(sums, q, [0.75, 0.9, 0.97])
    assert h["level"].iloc[0] == 0                   # dry day vs dry quantile (0 mm) is NOT an exceedance
    assert h["level"].iloc[1] == 2 and h["level"].iloc[2] == 3 and np.isnan(h["level"].iloc[3])


def test_span_crossing_new_year():
    a, b = C.span_for_year("11-01", "10-31", 2019)
    assert a == pd.Timestamp("2019-11-01") and b == pd.Timestamp("2020-10-31")
    a, b = C.span_for_year("06-01", "09-30", 2019)
    assert b == pd.Timestamp("2019-09-30")


def test_season_features_refuse_poor_coverage_and_report_reason():
    s = series(range(2019, 2020), p_missing=0.5)
    f, why = C.season_features(s, pd.Timestamp("2019-06-01"), pd.Timestamp("2019-09-30"), {}, "a", 1000.0, 20.0, 0.8)
    assert f is None and "observed" in why


def test_season_features_values():
    idx = pd.date_range("2019-06-01", "2019-09-30")
    s = pd.Series(1.0, index=idx)
    s.loc["2019-07-10"] = 60.0
    f, why = C.season_features(s, idx[0], idx[-1], {}, "a", baseline_total_mean=100.0, heavy_threshold=30.0)
    assert why is None and f["season_max1d_mm"] == 60.0 and f["season_heavy_days"] == 1.0
    assert abs(f["season_total_mm"] - (len(idx) - 1 + 60.0)) < 1e-9 and f["season_anomaly_pct"] > 0
    assert f["season_max7d_mm"] == 66.0 and f["season_obs_fraction"] == 1.0


def test_baseline_season_stats():
    s = series(range(1991, 2001))
    mean_total, heavy, n = C.baseline_season_stats(s, "06-01", "09-30", (1991, 1999))
    assert n == 9 and mean_total > 0 and heavy is not None and heavy > 1.0


def test_thin_reference_gives_no_threshold_not_an_invented_one():
    import numpy as np
    import pandas as pd
    from floodprep import climatology as C
    idx = pd.date_range("2016-01-01", "2018-12-31")                       # only 3 years of data
    s = pd.Series(np.random.default_rng(0).gamma(0.5, 10, len(idx)), index=idx)
    full = C.build_quantile_table({"a": s}, [7], [2015, 2018], [0.5, 0.9], 15, 0.8, 60, 1)
    strict = C.build_quantile_table({"a": s}, [7], [2015, 2018], [0.5, 0.9], 15, 0.8, 60, 4)      # needs 4 distinct years
    assert len(full) > 300 and full["n_years"].max() == 3 and strict.empty
    sparse = s.copy()
    sparse.iloc[:] = np.nan                                                # no observations at all
    assert C.build_quantile_table({"a": sparse}, [7], [2015, 2018], [0.5], 15, 0.8, 60, 1).empty
