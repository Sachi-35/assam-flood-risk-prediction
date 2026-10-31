"""Annual / seasonal flood-impact labels: one row per district and year. Never spread over days.

  * Only the files named in labels.files (the authoritative version) are used. Summary files are excluded by pattern; other
    candidate versions are only COMPARED with the authoritative one and reported.
  * A district missing for a year is unknown (excluded) unless labels.annual.absent_district_policy = zero.
  * Class boundaries are quantiles of the metric over TRAINING years only; cross-validation recomputes them inside each fold.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

import numpy as np
import pandas as pd

from .common import normalize_name
from .labels import match_districts


def discover_files(folder: Path, files: list[str] | None, exclude_patterns: list[str]):
    """-> (authoritative paths, other candidate paths, excluded paths)."""
    allc = sorted(Path(folder).glob("*.csv"))
    excluded = [p for p in allc if any(fnmatch.fnmatch(p.name.lower(), pat.lower()) for pat in exclude_patterns)]
    cands = [p for p in allc if p not in excluded]
    if files:
        auth = [Path(folder) / f for f in files]
        missing = [p.name for p in auth if not p.exists()]
        if missing:
            raise FileNotFoundError(f"labels.files lists {missing}, not found in {folder}. Available: {[p.name for p in allc]}")
        others = [p for p in cands if p not in auth]
    else:
        auth, others = cands, []
    return auth, others, excluded


DAILY_TOKENS = ("daily", "day")


def load_annual_file(path: Path, annual_granularities: list[str], min_period_days: int = 60):
    """Read one label CSV. Returns (rows kept as annual, info). Required: district, affected_population and year (or a date).

    A row is ANNUAL/SEASONAL if (a) its label_granularity matches an entry of `annual_granularities` exactly or as a word/substring
    (so 'seasonal_aggregate' matches 'seasonal'), or the field is empty, or (b) it has a period of >= `min_period_days` days and the
    granularity is not a daily one. Everything else is dropped AND reported (values and counts). `info['kept_by']` shows which rule
    kept the rows; `info['invalid_rows']` lists rows whose year or value could not be parsed. Nothing is dropped silently.
    """
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df.columns = [c.strip().lower() for c in df.columns]
    miss = {"district", "affected_population"} - set(df.columns)
    if miss:
        raise ValueError(f"{path.name}: missing column(s) {sorted(miss)}; found {list(df.columns)}")
    df["_raw_pop"] = df["affected_population"]
    df["district"] = df["district"].str.strip()
    df["affected_population"] = pd.to_numeric(df["affected_population"].str.replace(",", "", regex=False).str.strip(), errors="coerce")
    for c in ("period_start", "period_end", "date"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c].str.strip().replace("", np.nan), format="mixed", errors="coerce").dt.floor("D")
    df["_raw_year"] = df["year"] if "year" in df.columns else ""
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"].str.strip(), errors="coerce")
    elif "period_end" in df.columns and df["period_end"].notna().any():
        df["year"] = df["period_start"].dt.year if "period_start" in df.columns else df["period_end"].dt.year
    elif "date" in df.columns:
        df["year"] = df["date"].dt.year
    else:
        raise ValueError(f"{path.name}: no 'year', period or date column to identify the year")
    ok_gran = {normalize_name(g) for g in annual_granularities}

    def gran_ok(v: str) -> bool:
        n = normalize_name(v)
        return n == "" or n in ok_gran or any(t and (t in n) for t in ok_gran)

    if "label_granularity" in df.columns:
        g = df["label_granularity"].map(normalize_name)
        by_gran = df["label_granularity"].map(gran_ok)
        is_daily = g.map(lambda x: any(t in x.split() or x == t for t in DAILY_TOKENS))
    else:
        by_gran, is_daily = pd.Series(True, index=df.index), pd.Series(False, index=df.index)
    if {"period_start", "period_end"} <= set(df.columns):
        plen = (df["period_end"] - df["period_start"]).dt.days + 1
        by_period = plen.ge(min_period_days).fillna(False) & ~is_daily
    else:
        by_period = pd.Series(False, index=df.index)
    is_annual = by_gran | by_period
    not_annual = df.loc[~is_annual, "label_granularity"].value_counts().to_dict() if "label_granularity" in df.columns else {}
    bad = df["year"].isna() | df["affected_population"].isna()
    info = {"file": path.name, "rows": len(df), "non_annual_rows": int((~is_annual).sum()), "non_annual_values": not_annual,
            "kept_by": {"label_granularity": int((by_gran & is_annual).sum()), "period_length_only": int((~by_gran & by_period).sum())},
            "granularity_values": df["label_granularity"].value_counts(dropna=False).to_dict() if "label_granularity" in df.columns else {},
            "has_period": {"period_start", "period_end"} <= set(df.columns),
            "bad_year_or_value": int(bad.sum()),
            "invalid_rows": df.loc[bad, ["district", "_raw_year", "_raw_pop"]].head(10).values.tolist(),
            "unparsed_periods": {c: int(df[c].isna().sum()) for c in ("period_start", "period_end") if c in df.columns}}
    kept = df[is_annual].dropna(subset=["year", "affected_population"]).drop(columns=["_raw_pop", "_raw_year"]).copy()
    kept["year"] = kept["year"].astype(int)
    kept["source_file"] = path.name
    if len(df) and kept.empty:
        raise ValueError(f"{path.name}: all {len(df)} rows were discarded (non-annual: {info['non_annual_values']}, invalid: {info['invalid_rows']}). "
                         "Check labels.annual.granularities / min_period_days in config.yaml.")
    return kept, info


def build_annual_labels(rows: pd.DataFrame, districts: pd.DataFrame, cfg: dict, aliases, merge_into_parent, years: list[int]):
    """Collapse to one row per (district, year). Returns (labels frame without classes, info dict).

    rows: concatenated annual rows with columns district, year, affected_population, [period_start, period_end, quality_flag]
    """
    acfg = cfg.get("annual", {})
    rows = rows.copy()
    flags = acfg.get("exclude_quality_flags") or []
    if flags and "quality_flag" in rows.columns:
        drop = rows["quality_flag"].isin(flags)
        rows = rows[~drop]
    rows, minfo = match_districts(rows, districts, aliases, merge_into_parent)
    info = {"unmatched": minfo["unmatched"], "merged": minfo["merged"]}
    info["name_map"] = (rows.groupby(["district", "district_name"]).size().rename("rows").reset_index()
                        .rename(columns={"district": "name_in_file", "district_name": "boundary_district"}))
    rows = rows[rows["year"].isin(years)]

    policy = acfg.get("duplicate_policy", "max")
    key = ["district_id", "district", "year"]
    grp = rows.groupby(key)
    dup = grp.size()
    info["duplicate_keys"] = int((dup > 1).sum())
    info["duplicate_examples"] = dup[dup > 1].head(5).reset_index().astype(str).values.tolist()
    dkeys = dup[dup > 1].index
    info["duplicate_detail"] = rows.set_index(key).loc[dkeys].reset_index() if len(dkeys) else rows.iloc[0:0]
    agg = {"max": "max", "sum": "sum", "first": "first"}[policy]
    per_name = grp.agg(affected_population=("affected_population", agg), n_source_rows=("affected_population", "size")).reset_index()
    for c in ("period_start", "period_end"):
        if c in rows.columns:
            per_name[c] = grp[c].min().values if c == "period_start" else grp[c].max().values
    if "quality_flag" in rows.columns:
        per_name["quality_flags"] = grp["quality_flag"].agg(lambda s: ";".join(sorted({str(x) for x in s if str(x)}))).values
    for c in ("source_pdf", "source_section", "source_page"):
        if c in rows.columns:
            per_name[c] = grp[c].agg(lambda s: ";".join(sorted({str(x) for x in s if str(x)}))).values
    if "source_file" in rows.columns:
        per_name["source_file"] = grp["source_file"].agg(lambda s: ";".join(sorted(set(s)))).values
    # names folded into the same parent polygon: add them up
    sums = {"affected_population": "sum", "n_source_rows": "sum"}
    for c in ("period_start",):
        if c in per_name:
            sums[c] = "min"
    if "period_end" in per_name:
        sums["period_end"] = "max"
    for c in ("quality_flags", "source_file", "source_pdf", "source_section", "source_page"):
        if c in per_name:
            sums[c] = lambda s: ";".join(sorted({x for v in s for x in str(v).split(";") if x}))
    lab = per_name.groupby(["district_id", "year"], as_index=False).agg(sums)
    lab["label_status"] = "reported"

    all_ids = sorted(districts["district_id"])
    grid = pd.MultiIndex.from_product([all_ids, sorted(years)], names=["district_id", "year"]).to_frame(index=False)
    lab = grid.merge(lab, on=["district_id", "year"], how="left")
    absent = lab["affected_population"].isna()
    info["absent_district_years"] = int(absent.sum())
    if acfg.get("absent_district_policy", "unknown") == "zero":
        lab.loc[absent, "affected_population"] = 0.0
        lab.loc[absent, "label_status"] = "absent_as_zero"
    else:
        lab.loc[absent, "label_status"] = "unknown"
    return lab, info


def add_metric(lab: pd.DataFrame, districts: pd.DataFrame, metric: str):
    has_pop = "pop_total" in districts.columns and districts["pop_total"].notna().all()
    if metric == "auto":
        metric = "affected_pct" if has_pop else "affected_population"
    if metric == "affected_pct":
        if not has_pop:
            raise ValueError("labels.metric = affected_pct needs population for every district (population raster missing)")
        pop = districts.set_index("district_id")["pop_total"]
        lab["metric_value"] = 100.0 * lab["affected_population"] / lab["district_id"].map(pop)
    else:
        lab["metric_value"] = lab["affected_population"].astype(float)
    return lab, metric


def derive_thresholds(values, quantiles) -> list[float]:
    """Three boundaries from quantiles of the training values. A first boundary of 0 is moved just above 0 (zero stays Low)."""
    v = pd.Series(values).dropna().to_numpy(dtype=float)
    if len(v) < 12:
        raise ValueError(f"Only {len(v)} labelled district-years to derive thresholds from (need >= 12).")
    t = [float(np.quantile(v, q)) for q in quantiles]
    if t[0] <= 0:
        t[0] = float(np.nextafter(0.0, 1.0))
    if not (t[0] < t[1] < t[2]):
        raise ValueError(f"Quantile boundaries are not strictly increasing ({t}); too many identical values. Adjust labels.annual.quantiles.")
    return t


def classify(values: pd.Series, thresholds) -> pd.Series:
    cls = pd.Series(np.digitize(values.fillna(0).to_numpy(), thresholds), index=values.index, dtype="float64")
    return cls.where(values.notna())
