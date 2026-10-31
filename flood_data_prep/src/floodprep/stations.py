"""Station-level daily rainfall (Assam Water Dept / NWDP manual gauges) -> district daily rainfall.

Rules (each is counted and reported by scripts/03_extract_rainfall.py, never applied silently):
  * a missing observation stays missing. It is NEVER turned into 0 mm. Negative values are invalid -> missing.
  * identical duplicate station-days are collapsed; CONFLICTING duplicates (values differ by > tol) are resolved by `duplicate_policy`
    (default 'missing': the day becomes missing, nothing is averaged or chosen) and every such record is written to an audit file.
  * values above `review_mm` are flagged for review (kept); values above `max_daily_mm` are excluded from use but kept in the audit.
  * a station's district comes from its COORDINATES (polygon) when they fall inside a district, else from the District column.
  * district value = mean of the stations that reported that day; `n_stations` is kept.
  * a district with no station at all may borrow nearby stations by inverse-distance weighting (flagged source='idw').
    Days without any usable station stay missing.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from .common import build_name_lookup, match_series, slugify

DEFAULT_COLUMNS = {"station": "Station", "district": "District", "lat": "Latitude", "lon": "Longitude",
                   "date": "Data Acquisition Time", "rain": "Manual Daily Rainfall (mm)", "agency": "Agency"}
DEFAULT_MISSING = ["", "NA", "N/A", "NaN", "NULL", "-", "--"]


def _norm(c: str) -> str:
    return "".join(ch for ch in str(c).lower() if ch.isalnum())


def _resolve_columns(df_cols, colmap: dict) -> dict:
    """logical name -> actual column in the file (case/space/punctuation-insensitive). Raises with the columns found."""
    have = {_norm(c): c for c in df_cols}
    out, missing = {}, []
    for logical, wanted in colmap.items():
        if wanted is None:
            continue
        cands = [wanted] if isinstance(wanted, str) else list(wanted)
        hit = next((c for c in cands if _norm(c) in have), None)
        if hit is not None:
            out[logical] = have[_norm(hit)]
        elif logical in ("agency",):
            continue
        else:
            missing.append(wanted if isinstance(wanted, str) else "/".join(wanted))
    if missing:
        raise ValueError(f"Rainfall CSV lacks column(s) {missing}; found {list(df_cols)}. Fix rainfall.station_csv.columns in config.yaml.")
    return out


def load_station_csvs(folder: Path, files: list[str] | None, colmap: dict | None = None, missing_values=None,
                      dayfirst: bool = True, date_shift_days: int = 0, max_daily_mm: float = 1000.0, review_mm: float = 300.0):
    """Read and clean all station CSVs. Returns (clean station-day frame, qc dict)."""
    colmap = {**DEFAULT_COLUMNS, **(colmap or {})}
    miss_tokens = {str(m).strip().lower() for m in (DEFAULT_MISSING if missing_values is None else missing_values)}
    paths = [Path(folder) / f for f in files] if files else sorted(Path(folder).glob("*.csv"))
    absent = [p.name for p in paths if not p.exists()]
    if absent:
        raise FileNotFoundError(f"Rainfall file(s) not found in {folder}: {absent}")
    if not paths:
        raise FileNotFoundError(f"No rainfall CSV files in {folder}")

    frames, qc = [], {"files": {}, "rows_read": 0}
    for p in paths:
        raw = pd.read_csv(p, dtype=str, keep_default_na=False, low_memory=False)
        cols = _resolve_columns(raw.columns, colmap)
        df = pd.DataFrame({k: raw[v] for k, v in cols.items()})
        n = len(df)
        d = pd.to_datetime(df["date"].str.strip(), format="mixed", dayfirst=dayfirst, errors="coerce")
        bad_date = int(d.isna().sum())
        df["date"] = d.dt.floor("D") + pd.Timedelta(days=date_shift_days)
        r_txt = df["rain"].astype(str).str.strip()
        is_token = r_txt.str.lower().isin(miss_tokens)
        r = pd.to_numeric(r_txt.where(~is_token), errors="coerce")
        non_numeric = int((r.isna() & ~is_token).sum())
        negative = int((r < 0).sum())
        too_big = int((r > max_daily_mm).sum())
        neg_values = r[r < 0].round(1).value_counts().head(5).to_dict()
        df["rain_raw"] = r
        df["flag"] = np.where(r > max_daily_mm, "above_max_excluded", np.where(r > review_mm, "review_extreme", ""))
        r = r.where((r >= 0) & (r <= max_daily_mm))
        df["rain"] = r
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        df["source_file"] = p.name
        qc["files"][p.name] = {"rows": n, "bad_dates": bad_date, "missing_tokens": int(is_token.sum()),
                               "non_numeric_text": non_numeric, "negative": negative, "negative_values_top": neg_values,
                               f"above_{int(max_daily_mm)}mm": too_big, f"above_{int(review_mm)}mm_review": int((df["flag"] != "").sum()),
                               "columns_used": cols,
                               "date_min": str(df["date"].min().date()) if df["date"].notna().any() else None,
                               "date_max": str(df["date"].max().date()) if df["date"].notna().any() else None}
        qc["rows_read"] += n
        frames.append(df.dropna(subset=["date"]))
    out = pd.concat(frames, ignore_index=True)
    out["station_id"] = out["station"].astype(str).str.strip().map(slugify) + "__" + out["district"].astype(str).str.strip().map(slugify)

    # --- duplicates --------------------------------------------------------------------------------------------
    g = out.groupby(["station_id", "date"])["rain"]
    cnt = g.transform("size")
    qc["duplicate_rows"] = int((cnt > 1).sum())
    spread = (g.transform("max") - g.transform("min")).fillna(0.0)
    qc["conflicting_duplicate_rows"] = int(((cnt > 1) & (spread > 0.1)).sum())
    return out, qc


def duplicate_audit(df: pd.DataFrame, tol: float = 0.1) -> pd.DataFrame:
    """Every row that belongs to a duplicated station-day, with whether the group's values conflict."""
    g = df.groupby(["station_id", "date"])["rain"]
    cnt, spread = g.transform("size"), (g.transform("max") - g.transform("min")).fillna(0.0)
    out = df[cnt > 1].copy()
    out["conflict"] = (spread[cnt > 1] > tol).values
    return out[["station_id", "station", "date", "source_file", "rain_raw", "rain", "conflict"]].sort_values(["station_id", "date"])


def collapse_duplicates(df: pd.DataFrame, policy: str = "missing", tol: float = 0.1) -> pd.DataFrame:
    """One row per station-day. policy for CONFLICTING duplicates: missing (default) | mean | max | first.
    Non-conflicting duplicates collapse to their value. Adds n_source_rows and conflict."""
    if policy not in ("missing", "mean", "max", "first"):
        raise ValueError("rainfall.station_csv.duplicate_policy must be missing | mean | max | first")
    agg = "mean" if policy == "missing" else policy
    res = df.groupby(["station_id", "date"], as_index=False).agg(
        rain=("rain", agg), rmin=("rain", "min"), rmax=("rain", "max"), n_source_rows=("rain", "size"),
        station=("station", "first"), district=("district", "first"), lat=("lat", "median"), lon=("lon", "median"))
    res["conflict"] = (res["rmax"] - res["rmin"]).fillna(0.0) > tol
    if policy == "missing":
        res.loc[res["conflict"], "rain"] = np.nan
    return res.drop(columns=["rmin", "rmax"])


def station_table(df: pd.DataFrame, districts: gpd.GeoDataFrame, aliases: dict | None, mode: str = "polygon_then_column"):
    """One row per station with its district assignment and diagnostic flags."""
    st = df.groupby("station_id", as_index=False).agg(
        station=("station", "first"), district_col=("district", "first"), lat=("lat", "median"), lon=("lon", "median"),
        n_obs=("rain", "count"), first_date=("date", "min"), last_date=("date", "max"))
    ok = st["lat"].between(-90, 90) & st["lon"].between(-180, 180) & st["lat"].notna() & st["lon"].notna()
    pts = gpd.GeoDataFrame(st.loc[ok].copy(), geometry=gpd.points_from_xy(st.loc[ok, "lon"], st.loc[ok, "lat"]), crs="EPSG:4326")
    joined = gpd.sjoin(pts, districts[["district_id", "district_name", "geometry"]].to_crs("EPSG:4326"), how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]
    st["district_poly"] = joined["district_id"].reindex(st.index)
    lookup = build_name_lookup(list(districts["district_name"]), aliases)
    col_name, _ = match_series(st["district_col"], lookup)
    name_to_id = dict(zip(districts["district_name"], districts["district_id"]))
    st["district_name_col"] = col_name
    st["district_col_id"] = col_name.map(name_to_id)
    if mode == "polygon":
        st["district_id"] = st["district_poly"]
    elif mode == "column":
        st["district_id"] = st["district_col_id"]
    else:
        st["district_id"] = st["district_poly"].fillna(st["district_col_id"])
    st["assigned_by"] = np.where(st["district_poly"].notna() & (st["district_id"] == st["district_poly"]), "polygon",
                                 np.where(st["district_id"].notna(), "column", "none"))
    st["flag_outside_assam"] = st["district_poly"].isna()
    st["flag_name_mismatch"] = st["district_poly"].notna() & st["district_col_id"].notna() & (st["district_poly"] != st["district_col_id"])
    st["flag_unmatched_column_name"] = st["district_col_id"].isna()
    return st


def aggregate_to_districts(clean: pd.DataFrame, stations: pd.DataFrame, min_stations: int = 1) -> pd.DataFrame:
    """Mean of reporting stations per district-day. Only observed values count (NaN rain rows are dropped first)."""
    m = clean.merge(stations[["station_id", "district_id"]], on="station_id", how="left")
    m = m.dropna(subset=["district_id", "rain"])
    out = m.groupby(["district_id", "date"], as_index=False).agg(rain_mm=("rain", "mean"), n_stations=("rain", "count"))
    out = out[out["n_stations"] >= min_stations]
    out["source"] = "stations"
    return out


def idw_fill_districts(clean: pd.DataFrame, stations: pd.DataFrame, districts: gpd.GeoDataFrame, targets: list[str],
                       radius_km: float = 50.0, power: float = 2.0, max_stations: int = 4) -> pd.DataFrame:
    """For districts with NO station: inverse-distance mean of nearby stations (distance from station to the district polygon)."""
    proj = "EPSG:32646"  # UTM 46N: adequate for distances inside Assam
    dist = districts.to_crs(proj).set_index("district_id")
    st = stations.dropna(subset=["district_id", "lat", "lon"])
    pts = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]), crs="EPSG:4326").to_crs(proj)
    pts.index = st["station_id"].values
    wide = clean.dropna(subset=["rain"]).pivot_table(index="date", columns="station_id", values="rain", aggfunc="mean")
    frames = []
    for did in targets:
        d = pts.distance(dist.loc[did, "geometry"]) / 1000.0
        near = d[(d <= radius_km) & d.index.isin(wide.columns)].sort_values().head(max_stations)
        if near.empty:
            continue
        w = 1.0 / np.maximum(near.values, 1.0) ** power
        vals = wide[near.index]
        valid = vals.notna().to_numpy()
        num = np.where(valid, vals.fillna(0).to_numpy() * w, 0.0).sum(axis=1)
        den = (valid * w).sum(axis=1)
        series = pd.Series(np.where(den > 0, num / np.where(den > 0, den, 1), np.nan), index=vals.index)
        f = pd.DataFrame({"district_id": did, "date": series.index, "rain_mm": series.values,
                          "n_stations": valid.sum(axis=1), "source": "idw"}).dropna(subset=["rain_mm"])
        frames.append(f)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["district_id", "date", "rain_mm", "n_stations", "source"])
