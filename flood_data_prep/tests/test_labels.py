import numpy as np
import pandas as pd
import pytest

from floodprep.labels import assign_granularity, build_daily_labels, classify, derive_thresholds

CFG = {
    "metric": "affected_population", "threshold_method": "fixed", "thresholds": [100, 1000, 10000], "quantiles": [0.5, 0.9],
    "min_impact": 0, "class_names": ["Low", "Moderate", "High", "Severe"], "absence_policy": "zero_on_report_dates",
    "period_policy": "exclude", "max_period_days": 31, "default_granularity": "daily",
    "granularity_map": {"daily": ["daily"], "period": ["period", "event"], "seasonal": ["seasonal", "annual"]},
}
DIST = pd.DataFrame({"district_id": ["a", "b"], "district_name": ["Alpha", "Beta"], "pop_total": [1e5, 1e5]})
T = pd.Timestamp


def raw(rows):
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for c in ("period_start", "period_end"):
        if c in df:
            df[c] = pd.to_datetime(df[c])
    return df


def run(rows, cfg=None, merge=None, start="2020-07-01", end="2020-07-04", train_end="2020-07-02"):
    return build_daily_labels(raw(rows), DIST, {**CFG, **(cfg or {})}, None, start, end, train_end, merge_into_parent=merge)


def test_classify_boundaries():
    c = classify(pd.Series([0, 99.9, 100, 999, 1000, 10000, np.nan]), [100, 1000, 10000])
    assert c.iloc[:6].tolist() == [0, 0, 1, 1, 2, 3] and np.isnan(c.iloc[6])


def test_thresholds_must_ascend():
    with pytest.raises(ValueError):
        classify(pd.Series([1]), [10, 5, 20])


def test_absent_district_is_zero_only_on_report_dates():
    lab, _, _ = run([{"district": "Alpha", "date": "2020-07-02", "affected_population": 5000}])
    g = lab.set_index(["district_id", "date"])
    assert g.loc[("a", T("2020-07-02")), "risk_class"] == 2
    assert g.loc[("b", T("2020-07-02")), "risk_class"] == 0            # report existed, Beta not listed -> 0
    assert np.isnan(g.loc[("a", T("2020-07-01")), "risk_class"])        # no report that day -> UNKNOWN, not zero
    assert g.loc[("a", T("2020-07-01")), "label_observed"] == 0


def test_absence_policy_unknown_and_zero():
    rows = [{"district": "Alpha", "date": "2020-07-02", "affected_population": 5000}]
    lab, _, _ = run(rows, {"absence_policy": "unknown"})
    assert lab.loc[lab.district_id == "b", "risk_class"].isna().all()
    lab, _, _ = run(rows, {"absence_policy": "zero"})
    assert (lab["risk_class"].notna()).all()


def test_seasonal_and_period_rows_are_never_spread_over_days():
    rows = [{"district": "Alpha", "date": "2020-07-02", "affected_population": 50, "label_granularity": "daily"},
            {"district": "Alpha", "date": "2020-07-04", "affected_population": 90000, "label_granularity": "seasonal",
             "period_start": "2020-05-01", "period_end": "2020-10-31"},
            {"district": "Beta", "date": "2020-07-04", "affected_population": 90000, "label_granularity": "period",
             "period_start": "2020-07-03", "period_end": "2020-07-04"}]
    lab, seasonal, info = run(rows)
    assert lab["risk_class"].max() == 0                      # the 90000s did not leak into any daily label
    assert len(seasonal) == 1 and info["kind_counts"] == {"daily": 1, "seasonal": 1, "period": 1}


def test_short_period_window_policy_is_flagged():
    rows = [{"district": "Alpha", "date": "2020-07-02", "affected_population": 50, "label_granularity": "daily"},
            {"district": "Beta", "date": "2020-07-04", "affected_population": 20000, "label_granularity": "period",
             "period_start": "2020-07-03", "period_end": "2020-07-04"}]
    lab, _, _ = run(rows, {"period_policy": "window"})
    g = lab.set_index(["district_id", "date"])
    assert g.loc[("b", T("2020-07-03")), "risk_class"] == 3 and g.loc[("b", T("2020-07-03")), "label_quality"] == "period"
    assert g.loc[("a", T("2020-07-02")), "label_quality"] == "daily"


def test_daily_row_with_multiday_period_is_not_daily():
    df = raw([{"district": "Alpha", "date": "2020-07-31", "affected_population": 5, "label_granularity": "daily",
               "period_start": "2020-07-01", "period_end": "2020-07-31"}])
    assert assign_granularity(df, CFG)["kind"].iloc[0] == "period"


def test_missing_granularity_column_uses_default():
    out = assign_granularity(raw([{"district": "Alpha", "date": "2020-07-02", "affected_population": 5}]), CFG)
    assert out["kind"].iloc[0] == "daily"


def test_unknown_granularity_is_reported_not_guessed():
    out = assign_granularity(raw([{"district": "Alpha", "date": "2020-07-02", "affected_population": 5, "label_granularity": "mystery"}]), CFG)
    assert out["kind"].iloc[0] == "unknown"


def test_merge_into_parent_adds_values_and_reports_unmatched():
    rows = [{"district": "Alpha", "date": "2020-07-02", "affected_population": 400},
            {"district": "Child", "date": "2020-07-02", "affected_population": 700},
            {"district": "Nowhere", "date": "2020-07-02", "affected_population": 1}]
    lab, _, info = run(rows, merge={"Child": "Alpha"})
    assert lab.set_index(["district_id", "date"]).loc[("a", T("2020-07-02")), "metric_value"] == 1100
    assert info["merged"] == {"Child": "Alpha"} and info["unmatched"] == {"Nowhere": 1}


def test_duplicate_rows_use_max_not_sum():
    rows = [{"district": "Alpha", "date": "2020-07-02", "affected_population": 400},
            {"district": "Alpha", "date": "2020-07-02", "affected_population": 450}]
    lab, _, _ = run(rows)
    assert lab.set_index(["district_id", "date"]).loc[("a", T("2020-07-02")), "metric_value"] == 450


def test_train_quantile_thresholds_use_training_dates_only():
    rows = []
    for i, v in enumerate(range(100, 3100, 100)):                       # 30 positive training days, 100..3000
        rows.append({"district": "Alpha", "date": T("2020-06-01") + pd.Timedelta(days=i), "affected_population": v})
    rows.append({"district": "Alpha", "date": "2020-07-03", "affected_population": 10**9})   # test-period outlier
    cfg = {"threshold_method": "train_quantile", "quantiles": [0.5, 0.9]}
    lab, _, info = run(rows, cfg, start="2020-06-01", end="2020-07-04", train_end="2020-06-30")
    t = info["thresholds"]
    assert 1500 < t[1] < 1700 and 2700 < t[2] < 2900                    # unaffected by the 10**9 value in the test period
    assert lab.set_index(["district_id", "date"]).loc[("a", T("2020-07-03")), "risk_class"] == 3


def test_derive_thresholds_errors_on_too_little_data():
    with pytest.raises(ValueError):
        derive_thresholds(pd.Series([1.0, 2.0, 3.0]), [0.5, 0.9], 0)


def test_pct_metric_uses_population():
    lab, _, info = run([{"district": "Alpha", "date": "2020-07-02", "affected_population": 20000}],
                       {"metric": "affected_pct", "thresholds": [0.5, 5, 15]})
    assert lab.set_index(["district_id", "date"]).loc[("a", T("2020-07-02")), "risk_class"] == 3   # 20 % of 100k


def test_auto_metric_falls_back_without_population():
    d = DIST.drop(columns="pop_total")
    lab, _, info = build_daily_labels(raw([{"district": "Alpha", "date": "2020-07-02", "affected_population": 5000}]), d,
                                      {**CFG, "metric": "auto"}, None, "2020-07-01", "2020-07-03", "2020-07-02")
    assert info["metric_used"] == "affected_population"
