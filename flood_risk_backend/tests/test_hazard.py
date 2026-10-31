from datetime import date

import numpy as np
import pandas as pd

from app.services import hazard as H
from app.services.risk_rules import combine

LQ = [0.75, 0.9, 0.97]
Q = {"q75": 30, "q90": 60, "q97": 100}


def test_window_total_missing_is_not_zero():
    rain = {date(2023, 7, d): 10.0 for d in (1, 2, 3)}                         # 4th day absent
    tot, frac = H.window_total(rain, date(2023, 7, 4), 4, 0.75)
    assert tot == 30.0 and frac == 0.75                                         # sum over observed days only
    tot, frac = H.window_total(rain, date(2023, 7, 4), 4, 0.8)
    assert tot is None                                                          # too few observed days -> unknown, not 30, not 0
    assert H.window_total({}, date(2023, 7, 4), 3, 0.8) == (None, 0.0)


def test_real_zero_rain_is_a_valid_total():
    rain = {date(2023, 7, d): 0.0 for d in (1, 2, 3)}
    assert H.window_total(rain, date(2023, 7, 3), 3, 0.8)[0] == 0.0


def test_levels_are_strict_exceedance():
    assert H.level_for_total(0.0, Q, LQ) == 0
    assert H.level_for_total(30.0, Q, LQ) == 0                                  # equal is not exceeding
    assert [H.level_for_total(t, Q, LQ) for t in (31, 61, 101)] == [1, 2, 3]
    assert H.level_for_total(None, Q, LQ) is None and H.level_for_total(5, None, LQ) is None
    assert H.level_for_total(5, {"q75": None, "q90": 1, "q97": 2}, LQ) is None


def test_vectorised_matches_scalar():
    idx = pd.date_range("2023-06-01", periods=60)
    rng = np.random.default_rng(1)
    s = pd.Series(rng.gamma(0.7, 12, 60), index=idx)
    s.iloc[10:13] = np.nan
    q = pd.DataFrame([{"doy": d, **Q} for d in range(1, 367)])
    sums = H.window_sums(s, 7, 0.8)
    lv = H.levels_series(sums, q, LQ)
    rain = {t.date(): v for t, v in s.items() if not np.isnan(v)}
    for t in idx[5:]:
        tot, _ = H.window_total(rain, t.date(), 7, 0.8)
        exp = H.level_for_total(tot, Q, LQ)
        got = lv.loc[t]
        assert (exp is None and np.isnan(got)) or exp == got


def test_combine_bins_and_score():
    assert combine(0, 0.0, 0)[0] == "low" and combine(1, 1.0, 0)[0] == "low"
    assert combine(1, 1.0, 1)[0] == "moderate" and combine(0, 0.0, 3)[0] == "moderate"
    assert combine(2, 2.0, 2)[0] == "high" and combine(3, 3.0, 3) == ("severe", 1.0)
    assert combine(0, 0.0, 0)[1] == 0.0
