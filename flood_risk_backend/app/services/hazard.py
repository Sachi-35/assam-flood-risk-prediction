"""Rule-based window hazard. Needs no flood labels.

The window total (rain of the last w days) is compared with the district's own baseline distribution of w-day totals for the same
calendar window (+-15 days, baseline years only, computed by the data-prep project). Level = number of `level_quantiles`
(default q75, q90, q97) that the total STRICTLY exceeds: 0 Low, 1 Moderate, 2 High, 3 Severe.

Missing rainfall is never zero: a window total exists only if >= min_obs_fraction of its days were observed, else it is None.
KEEP IDENTICAL to floodprep.climatology (window_sum / hazard_levels); tests/test_hazard.py pins the behaviour.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.features import LEVEL_NAMES, QUANTILE_COLS


def qcol(p: float) -> str:
    return f"q{int(round(p * 100))}"


def window_total(rain_by_date: dict, end: date, w: int, min_obs_fraction: float):
    """(total over observed days or None, observed fraction) for the w days ending on `end` (inclusive)."""
    vals = [rain_by_date.get(end - timedelta(days=i)) for i in range(w)]
    obs = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
    frac = len(obs) / w
    if len(obs) < max(1, math.ceil(w * min_obs_fraction)):
        return None, frac
    return float(sum(obs)), frac


def level_for_total(total, qrow: dict | None, level_quantiles) -> int | None:
    """Level 0..3, or None if the total or any needed baseline quantile is missing."""
    if total is None or qrow is None:
        return None
    thr = [qrow.get(qcol(p)) for p in level_quantiles]
    if any(t is None or (isinstance(t, float) and math.isnan(t)) for t in thr):
        return None
    return int(sum(total > t for t in thr))


def exceeded_label(level: int | None, level_quantiles) -> str | None:
    if level is None:
        return None
    return "none of the baseline quantiles" if level == 0 else f"baseline quantile q{int(round(level_quantiles[level - 1] * 100))}"


def level_name(level: int | None) -> str | None:
    return None if level is None else LEVEL_NAMES[level]


# ---- vectorised versions (batch job) -----------------------------------------------------------------------------
def window_sums(series: pd.Series, w: int, min_obs_fraction: float) -> pd.Series:
    """Trailing w-day total over observed days; NaN unless enough days were observed. `series` has a complete daily index."""
    return series.rolling(w, min_periods=max(1, math.ceil(w * min_obs_fraction))).sum()


def obs_fractions(series: pd.Series, w: int) -> pd.Series:
    return series.notna().astype(float).rolling(w, min_periods=1).sum() / w


def levels_series(sums: pd.Series, qdf: pd.DataFrame, level_quantiles) -> pd.Series:
    """Level for every window total; `qdf` has columns doy + quantile columns for ONE district and window."""
    q = qdf.set_index("doy")
    thr = q.reindex(sums.index.dayofyear)[[qcol(p) for p in level_quantiles]].to_numpy()
    v = sums.to_numpy()[:, None]
    lvl = (v > thr).sum(axis=1).astype(float)
    lvl[np.isnan(sums.to_numpy()) | np.isnan(thr).any(axis=1)] = np.nan
    return pd.Series(lvl, index=sums.index)
