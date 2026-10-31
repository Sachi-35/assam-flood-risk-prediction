"""River-gauge loading, QC and station -> district assignment."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

LEVEL_ALIASES = ["water_level_m", "water_level", "wl", "level_m", "level", "gauge_m", "stage_m"]
Q_ALIASES = ["discharge_cumec", "discharge", "q", "flow_cumec", "flow"]
DATE_ALIASES = ["date", "datetime", "timestamp", "observation_date"]
STATION_ALIASES = ["station", "station_name", "site", "site_name", "station_code"]


def _pick(df: pd.DataFrame, aliases: list[str], required: bool, label: str) -> str | None:
    lowered = {c.lower().strip(): c for c in df.columns}
    for a in aliases:
        if a in lowered:
            return lowered[a]
    if required:
        raise ValueError(f"Gauge file is missing a {label} column. Expected one of {aliases}; found {list(df.columns)}")
    return None


def load_gauge_raw(folder: Path) -> pd.DataFrame:
    """Read every CSV in `folder` (except stations.csv) into [station, date, water_level_m, discharge_cumec]."""
    frames = []
    for f in sorted(Path(folder).glob("*.csv")):
        if f.name.lower().startswith("stations"):
            continue
        df = pd.read_csv(f)
        st, dt = _pick(df, STATION_ALIASES, True, "station"), _pick(df, DATE_ALIASES, True, "date")
        lv, q = _pick(df, LEVEL_ALIASES, True, "water level"), _pick(df, Q_ALIASES, False, "discharge")
        out = pd.DataFrame(
            {
                "station": df[st].astype(str).str.strip(),
                "date": pd.to_datetime(df[dt], errors="coerce", dayfirst=True),
                "water_level_m": pd.to_numeric(df[lv], errors="coerce"),
                "discharge_cumec": pd.to_numeric(df[q], errors="coerce") if q else np.nan,
            }
        )
        frames.append(out)
    if not frames:
        raise FileNotFoundError(f"No gauge CSV files found in {folder}")
    raw = pd.concat(frames, ignore_index=True).dropna(subset=["date"])
    raw["date"] = raw["date"].dt.floor("D")
    return raw


def fill_short_gaps(s: pd.Series, max_gap: int) -> pd.Series:
    """Linearly interpolate NaN runs of length <= max_gap; leave longer runs completely empty.

    (pandas' interpolate(limit=n) would fill the first n days of a longer gap with invented values.)
    """
    filled = s.interpolate(limit_area="inside")
    is_na = s.isna()
    run_id = (is_na != is_na.shift()).cumsum()
    run_len = is_na.groupby(run_id).transform("sum")
    return filled.mask(is_na & (run_len > max_gap))


def qc_station(df: pd.DataFrame, start, end, max_spike_dev_m: float, max_gap_days: int) -> pd.DataFrame:
    """Daily-ise, despike and gap-fill ONE station's series. Adds QC flags."""
    d = df.groupby("date", as_index=True)[["water_level_m", "discharge_cumec"]].mean()
    d = d.reindex(pd.date_range(start, end, freq="D"))
    d.index.name = "date"

    lvl = d["water_level_m"].where(d["water_level_m"] > 0)
    med = lvl.rolling(7, center=True, min_periods=3).median()
    spike = (lvl - med).abs() > max_spike_dev_m
    lvl = lvl.mask(spike)
    observed = lvl.notna()
    lvl_f = fill_short_gaps(lvl, max_gap_days)
    q = d["discharge_cumec"].where(d["discharge_cumec"] >= 0)
    q_f = fill_short_gaps(q, max_gap_days)

    out = pd.DataFrame(
        {
            "water_level_m": lvl_f,
            "discharge_cumec": q_f,
            "gauge_interpolated": (lvl_f.notna() & ~observed).astype(int),
            "gauge_spike_removed": spike.fillna(False).astype(int),
        }
    )
    return out.reset_index()


def assign_stations(stations: pd.DataFrame, districts: gpd.GeoDataFrame, max_km: float) -> pd.DataFrame:
    """One PRIMARY station per district.

    Priority: explicit `district` column in stations.csv -> station inside the polygon ->
    nearest station within `max_km` of the district centroid. Districts with none get no row.
    (Averaging stations is wrong: gauge zeros differ, so absolute levels are not comparable.)
    """
    pts = gpd.GeoDataFrame(
        stations.copy(), geometry=gpd.points_from_xy(stations["lon"], stations["lat"]), crs="EPSG:4326"
    )
    proj = "EPSG:32646"  # UTM 46N; fine for distance ranking across Assam
    pts_p, dist_p = pts.to_crs(proj), districts.to_crs(proj)

    rows = []
    for _, d in dist_p.iterrows():
        chosen, how, km = None, None, np.nan
        if "district" in stations.columns:
            explicit = stations[stations["district"].astype(str).str.lower() == str(d["district_name"]).lower()]
            if len(explicit):
                chosen, how = explicit.iloc[0]["station"], "explicit"
        if chosen is None:
            inside = pts_p[pts_p.within(d.geometry)]
            if len(inside):
                chosen, how = inside.iloc[0]["station"], "inside"
        if chosen is None:
            dists = pts_p.distance(d.geometry.centroid) / 1000.0
            i = dists.idxmin()
            if dists[i] <= max_km:
                chosen, how, km = pts_p.loc[i, "station"], "nearest", float(dists[i])
        if chosen is not None:
            rows.append({"district_id": d["district_id"], "station": chosen, "assignment": how, "distance_km": km})
    return pd.DataFrame(rows)
