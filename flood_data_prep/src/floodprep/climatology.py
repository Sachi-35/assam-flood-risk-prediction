"""Rainfall climatology, window hazard levels and seasonal features.

HAZARD (rule-based, needs no flood labels): for a window of w days ending on date t, the window rainfall total is compared with the
district's own history: totals of the same length that ended within +-`doy_halfwidth` days of the same calendar day in the BASELINE
years (default 1991-2018, chosen to end before the label period so there is no overlap). Exceeding the baseline
quantiles in `level_quantiles` gives level 1 (Moderate) / 2 (High) / 3 (Severe). Level 0 = Low.

Missing data: a window total is computed only if at least `min_obs_fraction` of its days were observed (rolling sum over OBSERVED days;
missing days are not zeros). Otherwise the total, and the hazard, are missing.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

LEVEL_NAMES = ["Low", "Moderate", "High", "Severe"]
SEASON_FEATURES = ["season_total_mm", "season_anomaly_pct", "season_max1d_mm", "season_max3d_mm", "season_max7d_mm",
                   "season_heavy_days", "hazard_max_level_7d", "hazard_days_high_7d", "hazard_max_level_30d", "hazard_days_high_30d"]
STATIC_FEATURES = ["elev_mean_m", "elev_std_m", "slope_mean_deg", "low_lying_frac", "pop_density_km2"]


def qcol(p: float) -> str:
    return f"q{int(round(p * 100))}"


def full_series(daily: pd.DataFrame, district_id: str, start, end) -> pd.Series:
    """Daily rainfall of one district on a complete calendar index; days with no data are NaN (never 0)."""
    s = daily.loc[daily["district_id"] == district_id].set_index("date")["rain_mm"]
    s = s[~s.index.duplicated(keep="first")]
    return s.reindex(pd.date_range(start, end, freq="D"))


def window_sum(s: pd.Series, w: int, min_obs_fraction: float) -> pd.Series:
    """Trailing w-day total over OBSERVED days; NaN unless >= min_obs_fraction of the days were observed."""
    need = max(1, math.ceil(w * min_obs_fraction))
    return s.rolling(w, min_periods=need).sum()


def window_obs_fraction(s: pd.Series, w: int) -> pd.Series:
    return s.notna().astype(float).rolling(w, min_periods=1).sum() / w


def build_quantile_table(series_by_district: dict[str, pd.Series], windows, baseline_years, grid, doy_halfwidth: int = 15,
                         min_obs_fraction: float = 0.8, min_values: int = 200, min_years: int = 1) -> pd.DataFrame:
    """Quantiles of window totals by district x window x day-of-year, from baseline years only.

    A (district, window, doy) row exists ONLY if its pool has >= min_values window totals from >= min_years distinct years;
    otherwise there is no row and the hazard there is unknown (no threshold is invented). n_years / n_values are kept per row.
    """
    y0, y1 = baseline_years
    rows = []
    for did, s in series_by_district.items():
        for w in windows:
            sums = window_sum(s, w, min_obs_fraction)
            sums = sums[(sums.index.year >= y0) & (sums.index.year <= y1)].dropna()
            if sums.empty:
                continue
            doy = sums.index.dayofyear.to_numpy()
            vals = sums.to_numpy()
            yrs = sums.index.year.to_numpy()
            by_doy = {d: vals[doy == d] for d in range(1, 367)}
            yby = {d: yrs[doy == d] for d in range(1, 367)}
            for d in range(1, 367):
                neigh = [((d - 1 + k) % 366) + 1 for k in range(-doy_halfwidth, doy_halfwidth + 1)]
                pool = np.concatenate([by_doy[n] for n in neigh])
                if len(pool) < min_values or len(pool) == 0:
                    continue
                ny = len(np.unique(np.concatenate([yby[n] for n in neigh])))
                if ny < min_years:
                    continue
                qs = np.quantile(pool, grid)
                rows.append({"district_id": did, "window_days": w, "doy": d, "n_values": len(pool), "n_years": ny,
                             **{qcol(p): float(q) for p, q in zip(grid, qs)}})
    return pd.DataFrame(rows)


def hazard_levels(sums: pd.Series, qrows: pd.DataFrame, level_quantiles) -> pd.DataFrame:
    """Level 0..3 for each window total, from the quantile rows (index doy) of ONE district and window.

    A level is the number of `level_quantiles` that the total strictly exceeds (strict: a dry window of 0 mm never exceeds a 0 mm quantile).
    """
    q = qrows.set_index("doy")
    doy = sums.index.dayofyear
    cols = [qcol(p) for p in level_quantiles]
    thr = q.reindex(doy)[cols].to_numpy()
    v = sums.to_numpy()[:, None]
    lvl = (v > thr).sum(axis=1).astype(float)
    lvl[np.isnan(sums.to_numpy()) | np.isnan(thr).any(axis=1)] = np.nan
    return pd.DataFrame({"window_rain_mm": sums.to_numpy(), "level": lvl}, index=sums.index)


def hazard_table(series_by_district, qtable, windows, level_quantiles, min_obs_fraction=0.8) -> dict:
    """{(district, w): DataFrame(index=date, window_rain_mm, obs_fraction, level)} for every date in each series."""
    out = {}
    for did, s in series_by_district.items():
        for w in windows:
            qr = qtable[(qtable["district_id"] == did) & (qtable["window_days"] == w)]
            sums = window_sum(s, w, min_obs_fraction)
            if qr.empty:
                h = pd.DataFrame({"window_rain_mm": sums.to_numpy(), "level": np.nan}, index=sums.index)
            else:
                h = hazard_levels(sums, qr, level_quantiles)
            h["obs_fraction"] = window_obs_fraction(s, w).to_numpy()
            out[(did, w)] = h
    return out


# ---------------------------------------------------------------------------------------------------------------
# Seasonal features
# ---------------------------------------------------------------------------------------------------------------
def span_for_year(md_start: str, md_end: str, year: int):
    """Calendar span 'MM-DD'..'MM-DD' starting in `year` (ends next year if the end month-day is before the start)."""
    s = pd.Timestamp(f"{year}-{md_start}")
    e = pd.Timestamp(f"{year + (1 if md_end < md_start else 0)}-{md_end}")
    return s, e


def season_features(s: pd.Series, start, end, haz: dict, did: str, baseline_total_mean: float | None,
                    heavy_threshold: float | None, min_obs_fraction: float = 0.8):
    """Seasonal rainfall features of one district for [start, end]. Returns (dict, reason_if_none)."""
    span = s.loc[start:end]
    n = len(span)
    obs = int(span.notna().sum())
    if n == 0 or obs / n < min_obs_fraction:
        return None, f"observed {obs}/{n} days (< {min_obs_fraction:.0%})"
    total = float(span.sum())
    scaled = total * n / obs                                    # season total scaled for the observed share (<=20 % gaps)
    f = {"season_total_mm": scaled, "season_obs_fraction": obs / n, "season_days": n,
         "season_max1d_mm": float(span.max())}
    for w, name in ((3, "season_max3d_mm"), (7, "season_max7d_mm")):
        f[name] = float(window_sum(s, w, min_obs_fraction).loc[start:end].max())
    f["season_anomaly_pct"] = (100.0 * (scaled - baseline_total_mean) / baseline_total_mean
                               if baseline_total_mean and baseline_total_mean > 0 else np.nan)
    f["season_heavy_days"] = float((span > heavy_threshold).sum()) if heavy_threshold is not None else np.nan
    for w in (7, 30):
        h = haz.get((did, w))
        lv = h["level"].loc[start:end].dropna() if h is not None else pd.Series(dtype=float)
        f[f"hazard_max_level_{w}d"] = float(lv.max()) if len(lv) else np.nan
        f[f"hazard_days_high_{w}d"] = float((lv >= 2).sum()) if len(lv) else np.nan
    return f, None


def baseline_season_stats(s: pd.Series, md_start: str, md_end: str, baseline_years, min_obs_fraction: float = 0.8,
                          heavy_quantile: float = 0.95):
    """(mean season total over baseline years with enough data, wet-day heavy threshold, n_years used)."""
    totals, wet = [], []
    for y in range(baseline_years[0], baseline_years[1] + 1):
        a, b = span_for_year(md_start, md_end, y)
        span = s.loc[a:b]
        if len(span) == 0 or span.notna().mean() < min_obs_fraction:
            continue
        totals.append(float(span.sum()) * len(span) / span.notna().sum())
        wet.append(span[span >= 1.0].dropna().to_numpy())
    if not totals:
        return None, None, 0
    wet = np.concatenate(wet) if wet else np.array([])
    return float(np.mean(totals)), (float(np.quantile(wet, heavy_quantile)) if len(wet) >= 50 else None), len(totals)
