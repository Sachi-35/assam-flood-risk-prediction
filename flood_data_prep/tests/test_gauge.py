import numpy as np
import pandas as pd

from floodprep.gauge import fill_short_gaps, qc_station


def test_short_gap_filled_long_gap_left_empty():
    s = pd.Series([1.0, np.nan, np.nan, 4.0, np.nan, np.nan, np.nan, np.nan, 9.0])
    out = fill_short_gaps(s, max_gap=3)
    assert out.iloc[1:3].tolist() == [2.0, 3.0]          # 2-day gap interpolated
    assert out.iloc[4:8].isna().all()                    # 4-day gap NOT partially filled


def test_spike_removed_and_flagged():
    d = pd.date_range("2020-07-01", periods=30)
    lv = np.full(30, 100.0)
    lv[10] = 140.0
    raw = pd.DataFrame({"date": d, "water_level_m": lv, "discharge_cumec": np.nan})
    out = qc_station(raw, d[0], d[-1], max_spike_dev_m=4.0, max_gap_days=3).set_index("date")
    assert out.loc[d[10], "gauge_spike_removed"] == 1
    assert abs(out.loc[d[10], "water_level_m"] - 100.0) < 1e-9     # replaced by interpolation
    assert out.loc[d[10], "gauge_interpolated"] == 1
