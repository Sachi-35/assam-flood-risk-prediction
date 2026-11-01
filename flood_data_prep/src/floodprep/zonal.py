"""Zonal (area-weighted mean) daily time series from gridded NetCDF rainfall.

Each grid cell contributes in proportion to the share of the cell that lies inside the zone, so small districts on a
coarse grid (IMD 0.25 deg, ~28 km) are handled properly instead of depending on whether a cell *centre* happens to fall inside.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import xarray as xr
from shapely import STRtree
from shapely.geometry import box

VAR_CANDIDATES = ["precip", "rain", "rainfall", "precipitation", "rf", "tp", "pr", "RAINFALL", "rfe", "total_precipitation"]
LAT_NAMES = ["lat", "latitude", "y", "LATITUDE", "Latitude"]
LON_NAMES = ["lon", "longitude", "x", "LONGITUDE", "Longitude"]
TIME_NAMES = ["time", "valid_time", "date", "TIME", "Time"]
MAX_DAILY_MM = 1500.0  # nothing on Earth gets more than this in a day; larger values are fill codes


def _find(ds, names, what):
    for n in names:
        if n in ds.coords or n in ds.dims or n in ds.variables:
            return n
    raise KeyError(f"No {what} coordinate among {names}; dataset has {list(ds.coords)}. Run scripts/00_inspect_inputs.py.")


def detect_variable(ds: xr.Dataset, hint: str = "auto") -> str:
    if hint and hint != "auto":
        if hint not in ds.data_vars:
            raise KeyError(f"rainfall.variable='{hint}' not in file; variables: {list(ds.data_vars)}")
        return hint
    for v in VAR_CANDIDATES:
        if v in ds.data_vars:
            return v
    spatial = [v for v in ds.data_vars if ds[v].ndim >= 3]  # a lone 3-D variable is almost certainly the rainfall
    if len(spatial) == 1:
        return spatial[0]
    raise KeyError(f"Could not detect the rainfall variable in {list(ds.data_vars)}; set rainfall.variable in config.")


def unit_scale(da: xr.DataArray, units_cfg: str = "auto") -> tuple[float, str]:
    """Multiplier that converts the variable to mm/day, and a description of what was assumed."""
    if units_cfg == "mm_per_day":
        return 1.0, "config: mm/day"
    if units_cfg == "m_per_day":
        return 1000.0, "config: m/day -> x1000"
    u = str(da.attrs.get("units", "")).strip().lower().replace(" ", "")
    if u in ("m", "metre", "meter", "meters", "m/day", "m/d"):
        return 1000.0, f"units='{u}' -> metres, x1000"
    if u in ("mm", "mm/day", "mm/d", "mmday-1", "mm/day.", "kgm-2", "kgm-2day-1", "kg/m2", "kg/m^2/day", ""):
        return 1.0, f"units='{u or 'missing'}' -> treated as mm/day"
    if "s-1" in u or "/s" in u:  # kg m-2 s-1 flux
        return 86400.0, f"units='{u}' -> per-second flux, x86400"
    return 1.0, f"UNRECOGNISED units='{u}' -> treated as mm/day (check!)"


def cell_edges(centres: np.ndarray) -> np.ndarray:
    c = np.asarray(centres, dtype="float64")
    if len(c) == 1:
        return np.array([c[0] - 0.025, c[0] + 0.025])
    mid = (c[1:] + c[:-1]) / 2
    return np.concatenate([[c[0] - (mid[0] - c[0])], mid, [c[-1] + (c[-1] - mid[-1])]])


def zone_weights(lons: np.ndarray, lats: np.ndarray, geom):
    """Return (rows, cols, weights, coverage): grid cells overlapping `geom`, the fraction of each cell inside it,
    and the share of the zone's area the grid covers (1.0 = fully covered, ~0 = zone outside the grid)."""
    xe, ye = cell_edges(lons), cell_edges(lats)
    x0, x1 = np.minimum(xe[:-1], xe[1:]), np.maximum(xe[:-1], xe[1:])
    y0, y1 = np.minimum(ye[:-1], ye[1:]), np.maximum(ye[:-1], ye[1:])
    minx, miny, maxx, maxy = geom.bounds
    ci = np.where((x1 >= minx) & (x0 <= maxx))[0]
    ri = np.where((y1 >= miny) & (y0 <= maxy))[0]
    if len(ci) == 0 or len(ri) == 0:
        return np.array([], int), np.array([], int), np.array([]), 0.0
    cells, idx = [], []
    for r in ri:
        for c in ci:
            cells.append(box(x0[c], y0[r], x1[c], y1[r]))
            idx.append((r, c))
    tree = STRtree(cells)
    hits = tree.query(geom, predicate="intersects")
    rows, cols, w, covered = [], [], [], 0.0
    for h in hits:
        inter = cells[h].intersection(geom).area
        if inter <= 0:
            continue
        rows.append(idx[h][0]); cols.append(idx[h][1])
        w.append(inter / cells[h].area)
        covered += inter
    cov = covered / geom.area if geom.area > 0 else 0.0
    return np.array(rows), np.array(cols), np.array(w), float(min(cov, 1.0))


def zonal_mean(ds: xr.Dataset, zones: dict, variable: str = "auto", units: str = "auto", min_valid_weight: float = 0.0):
    """Daily area-weighted mean of the rainfall variable for each zone.

    zones: {zone_id: shapely geometry (lon/lat, EPSG:4326)}
    Returns (long DataFrame [date, zone_id, rain_mm], {zone_id: {"n_cells", "coverage", "status"}}, notes dict).
    status: ok | partial (grid covers < 90 % of the zone) | outside (no overlap; series is all NaN)
    min_valid_weight: a day's value is NaN unless the non-missing cells carry at least this share of the zone's area weight
    (0 = any valid cell is enough, the original behaviour). Missing is never averaged as zero.
    """
    var = detect_variable(ds, variable)
    lat_n, lon_n, t_n = _find(ds, LAT_NAMES, "latitude"), _find(ds, LON_NAMES, "longitude"), _find(ds, TIME_NAMES, "time")
    da = ds[var]
    extra = [d for d in da.dims if d not in (t_n, lat_n, lon_n)]
    for d in extra:  # e.g. a singleton 'expver' / 'number' dimension (ERA5)
        if da.sizes[d] > 1:
            raise ValueError(f"Variable '{var}' has an extra dimension '{d}' of size {da.sizes[d]}; select one first.")
        da = da.isel({d: 0})
    scale, unit_note = unit_scale(da, units)
    da = da.transpose(t_n, lat_n, lon_n)
    arr = da.values.astype("float64") * scale
    arr[(arr < 0) | (arr > MAX_DAILY_MM)] = np.nan  # -9999 / -999 fill codes and absurd values
    lats, lons = ds[lat_n].values, ds[lon_n].values
    dates = pd.to_datetime(ds[t_n].values).normalize()

    frames, info = [], {}
    for zid, geom in zones.items():
        rows, cols, w, cov = zone_weights(lons, lats, geom)
        if len(w) == 0 or cov < 0.01:
            info[zid] = {"n_cells": 0, "coverage": cov, "status": "outside"}
            series = np.full(len(dates), np.nan)
        else:
            vals = arr[:, rows, cols]                       # (time, cells)
            valid = ~np.isnan(vals)
            num = np.where(valid, vals * w, 0.0).sum(axis=1)
            den = (valid * w).sum(axis=1)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                series = np.where((den > 0) & (den >= min_valid_weight * w.sum()), num / np.where(den > 0, den, 1), np.nan)
            info[zid] = {"n_cells": int(len(w)), "coverage": cov, "status": "ok" if cov >= 0.9 else "partial"}
        frames.append(pd.DataFrame({"date": dates, "zone_id": zid, "rain_mm": series}))
    return pd.concat(frames, ignore_index=True), info, {"variable": var, "units": unit_note}
