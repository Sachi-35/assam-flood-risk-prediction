"""Read-only validation of the data/ files before they are seeded or imported. Never modifies any source file or database.

Checks: required columns, data types, missing/invalid values, district ids and name mapping, dates and date ranges, duplicates,
rainfall values, label values and granularity (one SEASONAL row per district-year, never daily), climatology structure and
unexpected row-count changes (against a baseline JSON and/or the current database). Pure pandas + stdlib: no application import
beyond the label constants.

Severity:  ERROR = do not seed/import this file as is;  WARN = suspicious or silently-handled by the loaders;  INFO = facts.
Exit codes: 0 no ERROR (and no WARN with --strict), 1 validation failed, 2 usage/IO problem.

Usage
  python scripts/validate_data.py                       # validates ./data
  python scripts/validate_data.py --data-dir data --db flood_risk.db      # also flags row-count drops against the database (read-only)
  python scripts/validate_data.py --write-baseline /tmp/counts.json       # record row counts (never inside the data folder)
  python scripts/validate_data.py --baseline /tmp/counts.json --tolerance 0.2
  python scripts/validate_data.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.features import CLASS_ORDER, QUANTILE_COLS  # noqa: E402
from app.services.labels import NAME_ALIASES, STATUSES, norm_name  # noqa: E402

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
EXPECTED_DISTRICTS = 33
EXPECTED_LABEL_YEARS = (2019, 2023)
IMD_SOURCE = "IMD_daily_actual_2026"
EXPECTED_MIN_OBS_FRACTION = 0.8
ASSAM_BBOX = (89.5, 24.0, 96.5, 28.5)          # lon_min, lat_min, lon_max, lat_max (generous)
TERRAIN = ["mean_elevation_m", "elevation_std_m", "mean_slope_deg", "low_lying_frac"]
FILE_TABLE = {"districts.csv": "districts", "flood_labels.csv": "flood_labels", "rainfall_daily.csv": "rainfall_daily",
              "climatology.csv": "climatology", "rainfall_imd_recent.csv": "rainfall_imd_recent"}
STATUS_ALIASES = {"known_impact", "known", "none", "no_impact"}
RAIN_WARN_MM, RAIN_ERROR_MM = 500.0, 1500.0


@dataclass
class Finding:
    severity: str
    file: str
    check: str
    message: str
    count: int | None = None
    examples: list = field(default_factory=list)


class Report:
    def __init__(self):
        self.findings: list[Finding] = []
        self.counts: dict[str, int] = {}
        self.facts: dict[str, object] = {}

    def add(self, sev, file, check, msg, count=None, examples=None):
        self.findings.append(Finding(sev, file, check, msg, count, [str(e) for e in (examples or [])][:5]))

    def n(self, sev):
        return sum(f.severity == sev for f in self.findings)

    def ok(self, strict=False):
        return self.n("ERROR") == 0 and not (strict and self.n("WARN"))


def _read(report, folder, name, required, optional=()):
    """DataFrame of strings (blank -> NaN) or None. Missing file / unreadable file / missing columns are reported here."""
    p = os.path.join(folder, name)
    if not os.path.isfile(p):
        return None
    try:
        df = pd.read_csv(p, dtype=str)
    except Exception as e:                                           # noqa: BLE001 - any parse failure is a finding
        report.add("ERROR", name, "parse", f"cannot be read as CSV: {e}")
        return pd.DataFrame()
    df.columns = [str(c).strip() for c in df.columns]
    report.counts[name] = len(df)
    miss = [c for c in required if c not in df.columns]
    if miss:
        report.add("ERROR", name, "required_columns", f"missing required column(s): {miss}")
    unexpected = [c for c in df.columns if c not in set(required) | set(optional)]
    if unexpected:
        report.add("INFO", name, "extra_columns", f"extra column(s) ignored by the loaders: {unexpected}")
    if len(df) == 0 and not miss:
        report.add("ERROR", name, "empty", "file has a header but no rows")
    return df


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _bad_numeric(report, name, df, col, check="type"):
    """Rows where a non-blank cell is not a number. Returns the numeric Series."""
    raw, val = df[col], _num(df[col])
    bad = raw.notna() & val.isna()
    if bad.any():
        report.add("ERROR", name, check, f"column '{col}' has {int(bad.sum())} non-numeric value(s)", int(bad.sum()), raw[bad].head(5).tolist())
    return val


def _bad_int(report, name, df, col):
    val = _bad_numeric(report, name, df, col)
    frac = val.notna() & (val % 1 != 0)
    if frac.any():
        report.add("ERROR", name, "type", f"column '{col}' must be whole numbers; {int(frac.sum())} value(s) are not", int(frac.sum()), val[frac].head(5).tolist())
    return val


def _dates(report, name, df, col, low=date(1900, 1, 1), today=None):
    """Parse ISO dates and report missing, invalid, impossible and future dates."""
    today = today or date.today()
    raw = df[col]

    parsed_values = []
    invalid = []

    for value in raw:
        if pd.isna(value) or not str(value).strip():
            parsed_values.append(None)
            invalid.append(True)
            continue

        try:
            parsed_values.append(datetime.strptime(str(value).strip(), "%Y-%m-%d").date())
            invalid.append(False)
        except ValueError:
            parsed_values.append(None)
            invalid.append(True)

    bad = pd.Series(invalid, index=df.index)
    if bad.any():
        report.add(
            "ERROR", name, "dates",
            f"column '{col}' has {int(bad.sum())} missing/invalid date(s) (expected YYYY-MM-DD)",
            int(bad.sum()), raw[bad].head(5).tolist()
        )

    valid = [d for d in parsed_values if d is not None]

    if valid:
        outside = [d for d in valid if d < low or d > today]
        if outside:
            report.add(
                "ERROR", name, "date_range",
                f"{len(outside)} date(s) before {low} or after today ({today})",
                len(outside), outside[:5]
            )

        report.facts[f"{name}:date_range"] = [str(min(valid)), str(max(valid))]

    return pd.Series(parsed_values, index=df.index, dtype="object")


def _ids(report, name, df, col, valid_ids, sev, what="not in districts.csv"):
    v = _bad_int(report, name, df, col)
    miss = df[col].isna()
    if miss.any():
        report.add("ERROR", name, "missing_values", f"column '{col}' has {int(miss.sum())} blank value(s)", int(miss.sum()))
    if valid_ids:
        unk = v.notna() & ~v.isin(valid_ids)
        if unk.any():
            report.add(sev, name, "district_ids", f"{int(unk.sum())} row(s) use district_id values {what}: {sorted(set(v[unk].astype(int)))[:10]}",
                       int(unk.sum()), sorted(set(v[unk].astype(int)))[:5])
    return v


def _dups(report, name, df, keys, sev, note=""):
    d = df.duplicated(keys, keep=False)
    if d.any():
        extra = int(df.duplicated(keys, keep="first").sum())
        report.add(sev, name, "duplicates", f"{extra} duplicate row(s) for key {keys}{note}", extra, df.loc[d, keys].head(3).values.tolist())


# ------------------------------------------------------------------------------------------------------------------ per file ---
def _ring_problem(r):
    if not isinstance(r, list) or len(r) < 4:
        return "a ring has fewer than 4 points"
    return None if r[0] == r[-1] else "a ring is not closed"


def _coords(g):
    polys = [g.get("coordinates")] if g.get("type") == "Polygon" else (g.get("coordinates") or [])
    for poly in polys:
        for ring in poly if isinstance(poly, list) else []:
            for pt in ring if isinstance(ring, list) else []:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    yield pt[0], pt[1]


def check_districts(report, folder):
    name = "districts.csv"
    df = _read(report, folder, name, ["id", "name", "state", "geometry"], TERRAIN + ["pop_density_km2"])
    if df is None:
        report.add("ERROR", name, "missing_file", "required file not found")
        return {}
    if df.empty:
        return {}
    ids = _bad_int(report, name, df, "id") if "id" in df else pd.Series(dtype=float)
    if "id" in df:
        if df["id"].isna().any():
            report.add("ERROR", name, "missing_values", "blank district id(s)", int(df["id"].isna().sum()))
        _dups(report, name, df.assign(_i=ids), ["_i"], "ERROR", " (ids must be unique)")
    if "name" in df:
        blank = df["name"].isna() | (df["name"].fillna("").str.strip() == "")
        if blank.any():
            report.add("ERROR", name, "missing_values", f"{int(blank.sum())} district(s) without a name", int(blank.sum()))
        nn = df["name"].fillna("").map(norm_name)
        if nn[nn != ""].duplicated().any():
            report.add("ERROR", name, "duplicates", "duplicate district names (after normalising case/spaces)", int(nn[nn != ""].duplicated().sum()),
                       df.loc[nn.duplicated(keep=False) & (nn != ""), "name"].head(3).tolist())
    if "state" in df and (df["state"].fillna("").str.strip().str.lower() != "assam").any():
        report.add("WARN", name, "state", "some districts are not in state 'Assam'", int((df["state"].fillna("").str.strip().str.lower() != "assam").sum()))
    if "geometry" in df:
        bad_json, bad_shape, outside = [], [], []
        for _, r in df.iterrows():
            label = f"{r.get('name')} (id {r.get('id')})"
            try:
                g = json.loads(r["geometry"])
            except (TypeError, ValueError):
                bad_json.append(label)
                continue
            if not isinstance(g, dict) or g.get("type") not in ("Polygon", "MultiPolygon"):
                bad_shape.append(f"{label}: type {g.get('type') if isinstance(g, dict) else type(g).__name__}")
                continue
            polys = [g.get("coordinates")] if g["type"] == "Polygon" else (g.get("coordinates") or [])
            probs = {_ring_problem(r2) for poly in polys if isinstance(poly, list) for r2 in poly} - {None}
            if not polys or probs:
                bad_shape.append(f"{label}: {sorted(probs) or 'no polygons'}")
            xs = [c for c in _coords(g)]
            if xs and any(not (ASSAM_BBOX[0] <= x <= ASSAM_BBOX[2] and ASSAM_BBOX[1] <= y <= ASSAM_BBOX[3]) for x, y in xs):
                outside.append(label)
        if bad_json:
            report.add("ERROR", name, "geometry", f"{len(bad_json)} geometry value(s) are not valid JSON", len(bad_json), bad_json)
        if bad_shape:
            report.add("ERROR", name, "geometry", f"{len(bad_shape)} geometry value(s) are not drawable Polygon/MultiPolygon", len(bad_shape), bad_shape)
        if outside:
            report.add("WARN", name, "geometry_extent", f"{len(outside)} district(s) have coordinates outside the Assam bounding box (lon/lat swapped?)", len(outside), outside)
    ranges = {"mean_elevation_m": (-50, 5000), "elevation_std_m": (0, 3000), "mean_slope_deg": (0, 90), "low_lying_frac": (0, 1)}
    for c in TERRAIN:
        if c not in df:
            report.add("WARN", name, "terrain", f"terrain column '{c}' is absent (terrain is stored but not used in the main vulnerability)")
            continue
        v = _bad_numeric(report, name, df, c)
        if df[c].isna().any():
            report.add("WARN", name, "terrain", f"'{c}' is blank for {int(df[c].isna().sum())} district(s); stays NULL, never zero", int(df[c].isna().sum()))
        lo, hi = ranges[c]
        out = v.notna() & ((v < lo) | (v > hi))
        if out.any():
            report.add("ERROR", name, "value_range", f"'{c}' has {int(out.sum())} value(s) outside {lo}..{hi}", int(out.sum()), v[out].head(5).tolist())
    if "pop_density_km2" in df and df["pop_density_km2"].notna().any():
        report.add("INFO", name, "population", "pop_density_km2 is present but is not verified and must not enter the main vulnerability calculation")
    report.facts["districts"] = int(len(df))
    return {int(i): n for i, n in zip(ids.dropna(), df.loc[ids.notna(), "name"])}


def check_labels(report, folder, districts, years=EXPECTED_LABEL_YEARS):
    name = "flood_labels.csv"
    p = os.path.join(folder, name)
    if not os.path.isfile(p):
        report.add("WARN", name, "missing_file", "not found: the loaders skip it and the flood-impact endpoint stays empty")
        return
    df = _read(report, folder, name, ["year"], ["district", "district_id", "status", "impact_class", "affected_population",
                                                 "period_start", "period_end", "reporting_period", "caveats"])
    if df is None or df.empty or "year" not in df:
        return
    if "district" not in df and "district_id" not in df:
        report.add("ERROR", name, "required_columns", "needs a 'district' or 'district_id' column")
        return
    for c in df.columns:
        if c.lower() in ("date", "day", "as_of_date", "datetime"):
            report.add("ERROR", name, "granularity", f"column '{c}' suggests daily labels; labels are SEASONAL (one row per district-year) and must not be converted to daily")
    yr = _bad_int(report, name, df, "year")
    if yr.isna().any():
        report.add("ERROR", name, "missing_values", f"{int(yr.isna().sum())} row(s) without a valid year", int(yr.isna().sum()))
    outside = yr.notna() & ((yr < years[0]) | (yr > years[1]))
    if outside.any():
        report.add("WARN", name, "year_range", f"{int(outside.sum())} row(s) have a year outside {years[0]}-{years[1]}", int(outside.sum()), sorted(set(yr[outside].astype(int))))
    # district mapping
    by_name = {norm_name(n): i for i, n in districts.items()}
    did = pd.Series([None] * len(df), index=df.index, dtype="object")
    unmatched = []
    for pos, row in df.iterrows():
        if "district_id" in df and pd.notna(row["district_id"]) and pd.notna(pd.to_numeric(row["district_id"], errors="coerce")):
            i = int(float(row["district_id"]))
            did[pos] = i if (not districts or i in districts) else None
            if did[pos] is None:
                unmatched.append(f"id {i}")
        elif "district" in df and pd.notna(row["district"]):
            k = norm_name(row["district"])
            k = norm_name(NAME_ALIASES.get(k, k))
            did[pos] = by_name.get(k) if districts else k
            if did[pos] is None:
                unmatched.append(row["district"])
        else:
            unmatched.append(f"row {pos + 2}: no district")
    if unmatched and districts:
        report.add("ERROR", name, "district_mapping", f"{len(unmatched)} row(s) do not match any district (they would not be imported)", len(unmatched), sorted(set(map(str, unmatched))))
    if "district" in df:
        aliased = df["district"].dropna().map(lambda s: norm_name(s) in NAME_ALIASES).sum()
        if aliased:
            report.add("INFO", name, "district_mapping", f"{int(aliased)} row(s) use names mapped to a parent district (Bajali/Tamulpur/Sribhumi); they are merged on import")
    key = pd.DataFrame({"d": did.astype(object), "y": yr})
    dup = key.dropna().duplicated(keep=False)
    if dup.any():
        report.add("WARN", name, "duplicates", f"{int(key.dropna().duplicated().sum())} district-year(s) appear more than once (merged on import: counts summed)",
                   int(key.dropna().duplicated().sum()), key.dropna()[dup].head(3).values.tolist())
    # values
    if "status" in df:
        st = df["status"].fillna("").str.strip().str.lower().str.replace(r"[ -]", "_", regex=True)
        bad = ~st.isin(set(STATUSES) | STATUS_ALIASES | {""})
        if bad.any():
            report.add("ERROR", name, "values", f"{int(bad.sum())} unrecognised status value(s) (would become 'unknown')", int(bad.sum()), df.loc[bad, "status"].head(5).tolist())
    else:
        st = pd.Series([""] * len(df), index=df.index)
        report.add("WARN", name, "status", "no status column: status is inferred only from explicit class/count values")
    cls = df["impact_class"].fillna("").str.strip().str.lower() if "impact_class" in df else pd.Series([""] * len(df), index=df.index)
    badc = ~cls.isin(set(CLASS_ORDER) | {""})
    if badc.any():
        report.add("ERROR", name, "values", f"{int(badc.sum())} impact_class value(s) not in {CLASS_ORDER}", int(badc.sum()), df.loc[badc, "impact_class"].head(5).tolist())
    aff = _bad_numeric(report, name, df, "affected_population") if "affected_population" in df else pd.Series([float("nan")] * len(df), index=df.index)
    neg = aff < 0
    if neg.any():
        report.add("ERROR", name, "value_range", f"{int(neg.sum())} negative affected_population value(s)", int(neg.sum()))
    unk = st.eq("unknown")
    if (unk & (cls.ne("") | aff.notna())).any():
        report.add("WARN", name, "consistency", f"{int((unk & (cls.ne('') | aff.notna())).sum())} 'unknown' row(s) carry a class or count (they are cleared on import)", int((unk & (cls.ne('') | aff.notna())).sum()))
    rep = st.isin({"reported", "known", "known_impact"})
    if (rep & cls.eq("") & ~(aff > 0)).any():
        report.add("WARN", name, "consistency", f"{int((rep & cls.eq('') & ~(aff > 0)).sum())} 'reported' row(s) have neither class nor positive count (become unknown)", int((rep & cls.eq('') & ~(aff > 0)).sum()))
    zero = st.isin({"no_reported_impact", "none", "no_impact"}) & (cls.ne("") | (aff > 0))
    if zero.any():
        report.add("WARN", name, "consistency", f"{int(zero.sum())} 'no_reported_impact' row(s) also have a class or positive count (become unknown)", int(zero.sum()))
    if "affected_population" in df:
        blank_rep = rep & aff.isna()
        if blank_rep.any():
            report.add("INFO", name, "missing_values", f"{int(blank_rep.sum())} reported row(s) have no affected_population: stored as NULL, never zero")
    # completeness: one seasonal row per district-year
    if districts:
        got = set(map(tuple, key.dropna().astype(int).drop_duplicates().values.tolist())) if len(key.dropna()) else set()
        yrs = sorted({y for _, y in got})
        if yrs:
            missing = [(d, y) for d in districts for y in range(min(yrs), max(yrs) + 1) if (d, y) not in got]
            if missing:
                report.add("WARN", name, "completeness", f"{len(missing)} district-year(s) between {min(yrs)} and {max(yrs)} have no row (they will simply be absent, i.e. unrecorded)", len(missing), missing)
    report.facts["labels_by_status"] = {k: int(v) for k, v in st.replace("", "(inferred)").value_counts().items()}


def check_rainfall(report, folder, districts):
    name = "rainfall_daily.csv"
    df = _read(report, folder, name, ["district_id", "date", "rainfall_mm"], ["n_stations"])
    if df is None:
        report.add("WARN", name, "missing_file", "not found: rain hazard will be unknown everywhere (this is allowed)")
        return
    if df.empty or {"district_id", "date", "rainfall_mm"} - set(df.columns):
        return
    _ids(report, name, df, "district_id", set(districts), "WARN", "not in districts.csv (ignored by seed_db)")
    parsed = _dates(report, name, df, "date")
    v = _bad_numeric(report, name, df, "rainfall_mm")
    if (v < 0).any():
        report.add("ERROR", name, "rainfall_values", f"{int((v < 0).sum())} negative rainfall value(s)", int((v < 0).sum()), v[v < 0].head(5).tolist())
    if (v > RAIN_ERROR_MM).any():
        report.add("ERROR", name, "rainfall_values", f"{int((v > RAIN_ERROR_MM).sum())} daily total(s) above {RAIN_ERROR_MM:.0f} mm (implausible)", int((v > RAIN_ERROR_MM).sum()), v[v > RAIN_ERROR_MM].head(5).tolist())
    elif (v > RAIN_WARN_MM).any():
        report.add("WARN", name, "rainfall_values", f"{int((v > RAIN_WARN_MM).sum())} daily total(s) above {RAIN_WARN_MM:.0f} mm: check them", int((v > RAIN_WARN_MM).sum()), v[v > RAIN_WARN_MM].head(5).tolist())
    if df["rainfall_mm"].isna().any():
        report.add("INFO", name, "missing_values", f"{int(df['rainfall_mm'].isna().sum())} blank rainfall value(s): stored as NULL (missing is not zero)")
    if "n_stations" in df:
        ns = _bad_int(report, name, df, "n_stations")
        if (ns < 0).any():
            report.add("ERROR", name, "value_range", "negative n_stations", int((ns < 0).sum()))
    _dups(report, name, df.assign(_d=parsed), ["district_id", "_d"], "WARN", " (seed_db keeps the last one)")
    report.facts["rainfall_districts"] = int(df["district_id"].nunique())


def check_climatology(report, folder, districts, windows):
    name = "climatology.csv"
    req = ["district_id", "window_days", "doy"] + QUANTILE_COLS
    df = _read(report, folder, name, req, ["n_values", "n_years"])
    if df is None:
        report.add("WARN", name, "missing_file", "not found: hazard levels cannot be computed (this is allowed)")
        return
    if df.empty or [c for c in req if c not in df.columns]:
        return
    _ids(report, name, df, "district_id", set(districts), "ERROR", "not in districts.csv")
    w, doy = _bad_int(report, name, df, "window_days"), _bad_int(report, name, df, "doy")
    if (w <= 0).any():
        report.add("ERROR", name, "value_range", "window_days must be positive", int((w <= 0).sum()))
    if windows and (w.notna() & ~w.isin(windows)).any():
        report.add("WARN", name, "windows", f"window_days {sorted(set(w[w.notna() & ~w.isin(windows)].astype(int)))} are not in hazard_config windows {windows}")
    if ((doy < 1) | (doy > 366)).any():
        report.add("ERROR", name, "value_range", f"doy outside 1..366 in {int(((doy < 1) | (doy > 366)).sum())} row(s)", int(((doy < 1) | (doy > 366)).sum()))
    q = pd.DataFrame({c: _bad_numeric(report, name, df, c) for c in QUANTILE_COLS})
    if q.isna().any().any():
        report.add("ERROR", name, "missing_values", f"{int(q.isna().any(axis=1).sum())} row(s) have a blank quantile (those hazard levels become Unknown)", int(q.isna().any(axis=1).sum()))
    if (q < 0).any().any():
        report.add("ERROR", name, "value_range", "negative quantile value(s)", int((q < 0).any(axis=1).sum()))
    nonmono = (q.diff(axis=1).iloc[:, 1:] < 0).any(axis=1)
    if nonmono.any():
        report.add("ERROR", name, "structure", f"{int(nonmono.sum())} row(s) have quantiles that decrease ({'<='.join(QUANTILE_COLS)} must be non-decreasing)", int(nonmono.sum()))
    _dups(report, name, df.assign(_w=w, _x=doy), ["district_id", "_w", "_x"], "ERROR", " (district, window, doy must be unique)")
    if "n_years" in df:
        ny = _bad_int(report, name, df, "n_years")
        if (ny <= 0).any():
            report.add("WARN", name, "values", "n_years is zero or negative in some rows", int((ny <= 0).sum()))
    have = df.assign(_w=w).groupby("district_id")["_w"].agg(lambda s: sorted(set(s.dropna().astype(int))))
    if windows:
        short = {k: v for k, v in have.items() if set(windows) - set(v)}
        if short:
            report.add("WARN", name, "coverage", f"{len(short)} district(s) lack some configured windows {windows}", len(short), list(short.items()))
    report.facts["climatology_districts"] = int(df["district_id"].nunique())


def check_imd(report, folder, districts, allowed_sources=(IMD_SOURCE,)):
    name = "rainfall_imd_recent.csv"
    df = _read(report, folder, name, ["district_id", "date", "rainfall_mm"], ["source"])
    if df is None:
        report.add("INFO", name, "missing_file", "not found (recent IMD rainfall is optional)")
        return
    if df.empty or {"district_id", "date", "rainfall_mm"} - set(df.columns):
        return
    _ids(report, name, df, "district_id", set(districts), "ERROR", "not in districts.csv (the importer rejects them)")
    parsed = _dates(report, name, df, "date")
    v = _bad_numeric(report, name, df, "rainfall_mm")
    if df["rainfall_mm"].isna().any():
        report.add("ERROR", name, "missing_values", f"{int(df['rainfall_mm'].isna().sum())} blank/invalid Daily Actual value(s) (the importer rejects them)", int(df["rainfall_mm"].isna().sum()))
    if (v < 0).any():
        report.add("ERROR", name, "rainfall_values", f"{int((v < 0).sum())} negative value(s)", int((v < 0).sum()))
    if (v > RAIN_ERROR_MM).any():
        report.add("ERROR", name, "rainfall_values", f"{int((v > RAIN_ERROR_MM).sum())} daily total(s) above {RAIN_ERROR_MM:.0f} mm", int((v > RAIN_ERROR_MM).sum()))
    if "source" in df:
        src = df["source"].fillna(IMD_SOURCE)
        bad = ~src.isin(allowed_sources)
        if bad.any():
            report.add("ERROR", name, "source", f"{int(bad.sum())} row(s) have a source other than {list(allowed_sources)}: {sorted(set(src[bad]))[:5]}", int(bad.sum()), sorted(set(src[bad])))
    else:
        report.add("INFO", name, "source", f"no source column: rows will be recorded as {IMD_SOURCE}")
    _dups(report, name, df.assign(_d=parsed), ["district_id", "_d"], "ERROR", " (the importer rejects duplicate district/date rows)")
    report.facts["imd_districts"] = int(df["district_id"].nunique())


def check_json_configs(report, folder):
    cfg = None
    p = os.path.join(folder, "hazard_config.json")
    if os.path.isfile(p):
        try:
            cfg = json.load(open(p))
        except ValueError as e:
            report.add("ERROR", "hazard_config.json", "parse", f"not valid JSON: {e}")
        if isinstance(cfg, dict):
            w, lq, mo = cfg.get("windows"), cfg.get("level_quantiles"), cfg.get("min_obs_fraction")
            if not (isinstance(w, list) and w and all(isinstance(x, int) and x > 0 for x in w)):
                report.add("ERROR", "hazard_config.json", "values", "windows must be a non-empty list of positive integers")
            if not (isinstance(lq, list) and len(lq) == 3 and all(isinstance(x, (int, float)) and 0 < x < 1 for x in lq) and lq == sorted(lq)):
                report.add("ERROR", "hazard_config.json", "values", "level_quantiles must be 3 ascending numbers between 0 and 1")
            if not isinstance(mo, (int, float)) or not 0 < mo <= 1:
                report.add("ERROR", "hazard_config.json", "values", "min_obs_fraction must be a number in (0, 1]")
            elif abs(mo - EXPECTED_MIN_OBS_FRACTION) > 1e-9:
                report.add("WARN", "hazard_config.json", "methodology", f"min_obs_fraction is {mo}; the documented methodology requires {EXPECTED_MIN_OBS_FRACTION}")
        elif cfg is not None:
            report.add("ERROR", "hazard_config.json", "values", "must be a JSON object")
            cfg = None
    p = os.path.join(folder, "label_thresholds.json")
    if os.path.isfile(p):
        try:
            lt = json.load(open(p))
            th = lt.get("thresholds") if isinstance(lt, dict) else None
            if not (isinstance(th, list) and len(th) == 3 and th == sorted(th)):
                report.add("ERROR", "label_thresholds.json", "values", "thresholds must be 3 ascending numbers")
        except ValueError as e:
            report.add("ERROR", "label_thresholds.json", "parse", f"not valid JSON: {e}")
    return (cfg or {}).get("windows") if isinstance(cfg, dict) and isinstance(cfg.get("windows"), list) else None


def check_optional_files(report, folder, districts):
    for name in ("season_features.csv", "normal_season_features.csv"):
        if os.path.isfile(os.path.join(folder, name)):
            df = _read(report, folder, name, ["district_id"])
            if df is not None and "district_id" in df and districts:
                _ids(report, name, df, "district_id", set(districts), "WARN", "not in districts.csv")


# --------------------------------------------------------------------------------------------------- row-count changes ---------
def db_counts(db_path: str) -> dict[str, int]:
    """Row counts per table from a SQLite file, opened strictly read-only; tables that do not exist are omitted."""
    uri = "file:" + os.path.abspath(db_path).replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in FILE_TABLE.values() if t in names}
    finally:
        con.close()


def compare_counts(report, incoming: dict[str, int], existing: dict[str, int], tolerance: float, source: str):
    """Flag files whose row count would drop sharply, or would empty a table that holds data. Growth is reported as INFO."""
    for fname, table in FILE_TABLE.items():
        if fname not in incoming or table not in existing:
            continue
        new, old = incoming[fname], existing[table]
        if old == 0:
            continue
        if table == "districts":                    # districts are upserted, never replaced: a smaller file does not delete rows
            continue
        if new == 0:
            report.add("ERROR", fname, "row_count", f"has 0 rows but {source} holds {old}: seeding would empty the table", new)
        elif new < old * (1 - tolerance):
            report.add("WARN", fname, "row_count", f"{new} rows vs {old} in {source} ({(new - old) / old:+.0%}): larger drop than the {tolerance:.0%} tolerance", new)
        elif new != old:
            report.add("INFO", fname, "row_count", f"{new} rows vs {old} in {source} ({(new - old) / old:+.0%})", new)


# --------------------------------------------------------------------------------------------------------- entry points ----------
def validate(folder: str, expected_districts: int | None = EXPECTED_DISTRICTS, db_path: str | None = None, baseline: dict | None = None,
             tolerance: float = 0.2, years=EXPECTED_LABEL_YEARS, allowed_sources=(IMD_SOURCE,)) -> Report:
    r = Report()
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"data folder not found: {folder}")
    districts = check_districts(r, folder)
    if districts and expected_districts and len(districts) != expected_districts:
        r.add("ERROR", "districts.csv", "row_count", f"{len(districts)} districts, expected {expected_districts}", len(districts))
    windows = check_json_configs(r, folder)
    check_labels(r, folder, districts, years)
    check_rainfall(r, folder, districts)
    check_climatology(r, folder, districts, windows)
    check_imd(r, folder, districts, allowed_sources)
    check_optional_files(r, folder, districts)
    if baseline:
        compare_counts(r, r.counts, {FILE_TABLE[k]: v for k, v in baseline.items() if k in FILE_TABLE}, tolerance, "the baseline")
    if db_path:
        try:
            compare_counts(r, r.counts, db_counts(db_path), tolerance, "the database")
        except sqlite3.DatabaseError as e:
            r.add("WARN", os.path.basename(db_path), "database", f"could not read row counts: {e}")
    return r


def format_report(r: Report, folder: str) -> str:
    out = [f"Data validation: {os.path.abspath(folder)}", "Row counts: " + ", ".join(f"{k}={v:,}" for k, v in sorted(r.counts.items()))]
    for sev in ("ERROR", "WARN", "INFO"):
        fs = [f for f in r.findings if f.severity == sev]
        if not fs:
            continue
        out.append(f"\n{sev} ({len(fs)})")
        for f in fs:
            ex = f"  e.g. {f.examples}" if f.examples else ""
            out.append(f"  [{f.file}] {f.check}: {f.message}{ex}")
    out.append(f"\nRESULT: {'FAILED' if r.n('ERROR') else 'PASSED'}  ({r.n('ERROR')} error(s), {r.n('WARN')} warning(s)). Source files were not modified.")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only validation of the seed/import data files.")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    ap.add_argument("--db", help="SQLite file: compare incoming row counts with it (opened read-only)")
    ap.add_argument("--baseline", help="JSON {file: row_count} from an earlier --write-baseline")
    ap.add_argument("--write-baseline", help="write current row counts to this JSON file (must be outside the data folder)")
    ap.add_argument("--tolerance", type=float, default=0.2, help="allowed fractional row-count drop (default 0.2)")
    ap.add_argument("--expected-districts", type=int, default=EXPECTED_DISTRICTS, help="0 disables the district-count check")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.write_baseline and os.path.abspath(a.write_baseline).startswith(os.path.abspath(a.data_dir) + os.sep):
            print("ERROR: --write-baseline must not point inside the data folder", file=sys.stderr)
            return 2
        base = json.load(open(a.baseline)) if a.baseline else None
        r = validate(a.data_dir, a.expected_districts or None, a.db, base, a.tolerance)
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if a.write_baseline:
        with open(a.write_baseline, "w") as f:
            json.dump(r.counts, f, indent=2)
    if a.json:
        print(json.dumps({"counts": r.counts, "facts": r.facts, "errors": r.n("ERROR"), "warnings": r.n("WARN"),
                          "findings": [f.__dict__ for f in r.findings]}, indent=2, default=str))
    else:
        print(format_report(r, a.data_dir))
    return 0 if r.ok(a.strict) else 1


if __name__ == "__main__":
    sys.exit(main())
