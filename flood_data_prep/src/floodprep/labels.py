"""Turn flood-impact records (affected population per district) into a 4-class severity label.

Principles (see docs/LABELS.md):
  * A label is only created for a day the source actually speaks about. Annual / seasonal totals are NEVER copied across days.
  * Granularity is preserved (daily | period | seasonal); only daily (and optionally short period) rows become daily labels.
  * A district missing from a daily report is treated according to labels.absence_policy, stated explicitly.
  * Class thresholds are derived from TRAINING dates only (or taken from config) and reused unchanged for val/test.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import build_name_lookup, match_series, normalize_name

AUDIT_COLS = ["period_start", "period_end", "label_granularity", "source_pdf", "source_section"]


# ---------------------------------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------------------------------
def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip().replace({"": np.nan, "nan": np.nan, "-": np.nan}),
                         errors="coerce")


def _date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", format="mixed").dt.floor("D")   # ISO (YYYY-MM-DD) is the expected format


def load_label_csvs(folder: Path) -> pd.DataFrame:
    """Read every CSV directly inside `folder`. Required: district, date, affected_population. Audit columns are kept."""
    frames = []
    for f in sorted(Path(folder).glob("*.csv")):
        df = pd.read_csv(f, dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]
        missing = {"district", "date", "affected_population"} - set(df.columns)
        if missing:
            raise ValueError(f"{f.name}: missing column(s) {sorted(missing)}; found {list(df.columns)}")
        df["affected_population"] = _num(df["affected_population"])
        df["date"] = _date(df["date"])
        for c in ("period_start", "period_end"):
            if c in df.columns:
                df[c] = _date(df[c])
        df["source_file"] = f.name
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No label CSVs in {folder}")
    out = pd.concat(frames, ignore_index=True)
    n0 = len(out)
    out = out.dropna(subset=["date", "district"])
    keep = [c for c in out.columns if c != "source_file"]
    out = out.drop_duplicates(subset=keep)   # the same record present in several files (e.g. clean + audit copy)
    out.attrs["rows_read"], out.attrs["rows_dropped_bad_date"] = n0, n0 - len(out)
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------------------------------------------
# Granularity
# ---------------------------------------------------------------------------------------------------------------
def assign_granularity(raw: pd.DataFrame, cfg_labels: dict) -> pd.DataFrame:
    """Add `kind` in {daily, period, seasonal, unknown} from label_granularity (or from period_start/end, or the default)."""
    raw = raw.copy()
    gmap = {}
    for kind, names in cfg_labels["granularity_map"].items():
        for n in names:
            gmap[normalize_name(n)] = kind
    maxd = int(cfg_labels.get("max_period_days", 31))

    if "label_granularity" in raw.columns:
        raw["kind"] = raw["label_granularity"].fillna("").map(lambda v: gmap.get(normalize_name(v), "unknown"))
        raw.loc[raw["label_granularity"].fillna("").str.strip() == "", "kind"] = cfg_labels.get("default_granularity", "daily")
    else:
        raw["kind"] = cfg_labels.get("default_granularity", "daily")
    # A "daily" row that carries a multi-day period is not a daily value.
    if {"period_start", "period_end"} <= set(raw.columns):
        span = (raw["period_end"] - raw["period_start"]).dt.days + 1
        multi = raw["kind"].eq("daily") & span.gt(1)
        raw.loc[multi, "kind"] = np.where(span[multi] <= maxd, "period", "seasonal")
        raw["period_days"] = span
    return raw


# ---------------------------------------------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------------------------------------------
def match_districts(raw: pd.DataFrame, districts: pd.DataFrame, aliases: dict | None, merge_into_parent: dict | None):
    """Add district_name (canonical), `merged_from` (original name when folded into a parent) and district_id.

    Returns (raw_matched, info) with info = {"unmatched": {name: n_rows}, "merged": {child: parent}}.
    Unmatched names are REPORTED (not dropped silently); their rows are removed from the matched frame.
    """
    names = list(districts["district_name"])
    lookup = build_name_lookup(names, aliases)
    raw = raw.copy()
    mapped, unmatched = match_series(raw["district"], lookup)
    raw["district_name"] = mapped
    raw["merged_from"] = None
    merged = {}
    if merge_into_parent:
        mlookup = {normalize_name(k): (k, v) for k, v in merge_into_parent.items()}
        for idx in raw.index[raw["district_name"].isna()]:
            key = normalize_name(raw.at[idx, "district"])
            if key in mlookup:
                child, parent = mlookup[key]
                parent_c = lookup.get(normalize_name(parent))
                if parent_c is None:
                    continue
                raw.at[idx, "district_name"] = parent_c
                raw.at[idx, "merged_from"] = raw.at[idx, "district"]
                merged[child] = parent_c
    still = raw["district_name"].isna()
    counts = raw.loc[still, "district"].value_counts().to_dict()
    raw["district_id"] = raw["district_name"].map(dict(zip(districts["district_name"], districts["district_id"])))
    return raw[~still].copy(), {"unmatched": counts, "merged": merged}


# ---------------------------------------------------------------------------------------------------------------
# Thresholds and classes
# ---------------------------------------------------------------------------------------------------------------
def classify(metric: pd.Series, thresholds: list[float]) -> pd.Series:
    """Class 0..3 from three ascending thresholds (class k if t_{k-1} <= metric < t_k). NaN stays NaN."""
    t = list(thresholds)
    if len(t) != 3 or sorted(t) != t:
        raise ValueError("labels.thresholds must be 3 ascending numbers")
    cls = pd.Series(np.digitize(metric.fillna(0).to_numpy(), t), index=metric.index, dtype="float64")
    return cls.where(metric.notna())


def derive_thresholds(train_values: pd.Series, quantiles: list[float], min_impact: float) -> list[float]:
    """Three class boundaries [Low|Moderate, Moderate|High, High|Severe].

    Low      : impact <= min_impact (none / negligible)
    Moderate : impact above that, below the first quantile of the POSITIVE training values
    High     : between the two quantiles
    Severe   : at or above the second quantile
    Raises if there is too little data or the quantiles collapse.
    """
    if len(quantiles) != 2:
        raise ValueError("labels.quantiles needs exactly 2 numbers, e.g. [0.50, 0.90]")
    pos = train_values[train_values > min_impact].dropna()
    if len(pos) < 20:
        raise ValueError(f"Only {len(pos)} positive training observations; cannot derive quantile thresholds "
                         "(see reports/label_audit.md). Provide more labelled days or use threshold_method: fixed.")
    t = [float(np.nextafter(min_impact, np.inf))] + [float(np.quantile(pos, q)) for q in quantiles]
    if not (t[0] < t[1] < t[2]):
        raise ValueError(f"Quantile thresholds are not strictly increasing ({t}); the positive values are too repetitive. "
                         "Change labels.quantiles or use threshold_method: fixed.")
    return t


# ---------------------------------------------------------------------------------------------------------------
# Daily label construction
# ---------------------------------------------------------------------------------------------------------------
def build_daily_labels(raw: pd.DataFrame, districts: pd.DataFrame, cfg_labels: dict, aliases: dict | None,
                       start, end, train_end, merge_into_parent: dict | None = None,
                       thresholds_path: Path | None = None):
    """Return (labels, seasonal, info).

    labels   : [district_id, date, metric_value, risk_class, risk_label, label_observed, label_quality]
               risk_class is NaN where the source says nothing about that district-day.
    seasonal : seasonal/annual rows kept as-is (never spread over days)
    info     : dict with everything the audit report needs
    """
    start, end, train_end = pd.Timestamp(start), pd.Timestamp(end), pd.Timestamp(train_end)
    raw = assign_granularity(raw, cfg_labels)
    raw, minfo = match_districts(raw, districts, aliases, merge_into_parent)
    info = {"unmatched": minfo["unmatched"], "merged": minfo["merged"], "kind_counts": raw["kind"].value_counts().to_dict(),
            "rows_after_matching": len(raw)}

    # --- metric ----------------------------------------------------------------------------------------------
    metric = cfg_labels["metric"]
    has_pop = "pop_total" in districts.columns and districts["pop_total"].notna().all()
    if metric == "auto":
        metric = "affected_pct" if has_pop else "affected_population"
    if metric == "affected_pct" and not has_pop:
        raise ValueError("labels.metric = affected_pct needs a population value for every district "
                         "(provide data/raw/population/population.tif and rerun step 05), or use 'auto'/'affected_population'.")
    info["metric_used"] = metric

    # one value per (original name, date, kind): duplicates from several sources -> max ; then SUM across names merged into a parent
    def collapse(df):
        per_name = df.groupby(["district_id", "district", "date"], as_index=False)["affected_population"].max()
        return per_name.groupby(["district_id", "date"], as_index=False)["affected_population"].sum(min_count=1)

    daily = collapse(raw[raw["kind"] == "daily"].dropna(subset=["affected_population"]))
    seasonal = raw[raw["kind"].isin(["seasonal", "unknown"])].copy()
    period = raw[raw["kind"] == "period"].dropna(subset=["affected_population"]).copy()
    info["period_rows"] = len(period)

    pop = districts.set_index("district_id")["pop_total"] if has_pop else None

    def to_metric(vals: pd.Series, ids: pd.Series) -> pd.Series:
        return 100.0 * vals / ids.map(pop) if metric == "affected_pct" else vals.astype(float)

    # --- grid ------------------------------------------------------------------------------------------------
    ids = sorted(districts["district_id"])
    grid = pd.MultiIndex.from_product([ids, pd.date_range(start, end, freq="D")], names=["district_id", "date"]).to_frame(index=False)
    grid = grid.merge(daily.rename(columns={"affected_population": "_val"}), on=["district_id", "date"], how="left")
    report_dates = set(daily["date"].unique())
    on_report_day = grid["date"].isin(report_dates)
    policy = cfg_labels.get("absence_policy", "zero_on_report_dates")
    val = grid["_val"]
    if policy == "zero_on_report_dates":
        val = val.where(~on_report_day, val.fillna(0.0))
    elif policy == "zero":
        val = val.fillna(0.0)
    elif policy != "unknown":
        raise ValueError(f"unknown labels.absence_policy '{policy}'")
    grid["label_quality"] = np.where(val.notna(), "daily", "")
    info["daily_report_dates"] = len(report_dates)

    # --- optional short periods -> every day of the period gets the period's value (flagged) ---------------------
    if cfg_labels.get("period_policy", "exclude") == "window" and len(period):
        maxd = int(cfg_labels.get("max_period_days", 31))
        use = period.dropna(subset=["period_start", "period_end"])
        use = use[(use["period_end"] - use["period_start"]).dt.days + 1 <= maxd]
        rows = []
        for r in use.itertuples():
            for d in pd.date_range(r.period_start, r.period_end):
                rows.append((r.district_id, d, r.affected_population))
        if rows:
            pw = pd.DataFrame(rows, columns=["district_id", "date", "_pv"]).groupby(["district_id", "date"], as_index=False)["_pv"].max()
            grid = grid.assign(_val_filled=val).merge(pw, on=["district_id", "date"], how="left")
            take = grid["_val_filled"].isna() & grid["_pv"].notna()
            val = grid["_val_filled"].where(~take, grid["_pv"])
            grid.loc[take, "label_quality"] = "period"
            grid = grid.drop(columns=["_val_filled", "_pv"])
        info["period_rows_used"] = len(use)
    else:
        info["period_rows_used"] = 0

    grid["metric_value"] = to_metric(val, grid["district_id"])
    grid["label_observed"] = grid["metric_value"].notna().astype(int)

    # --- thresholds (TRAIN dates only) ----------------------------------------------------------------------------
    method = cfg_labels.get("threshold_method", "train_quantile")
    if method == "fixed":
        thr = list(cfg_labels["thresholds"])
    elif method == "train_quantile":
        tr = grid[(grid["date"] <= train_end) & grid["metric_value"].notna()]["metric_value"]
        thr = derive_thresholds(tr, cfg_labels["quantiles"], float(cfg_labels.get("min_impact", 0)))
    else:
        raise ValueError(f"unknown labels.threshold_method '{method}'")
    info["thresholds"] = thr
    info["threshold_method"] = method
    if thresholds_path is not None:
        Path(thresholds_path).write_text(json.dumps({"metric": metric, "method": method, "thresholds": thr,
                                                     "quantiles": cfg_labels.get("quantiles") if method == "train_quantile" else None,
                                                     "min_impact": cfg_labels.get("min_impact", 0),
                                                     "train_end": str(train_end.date())}, indent=2))
    grid["risk_class"] = classify(grid["metric_value"], thr)
    names = cfg_labels["class_names"]
    grid["risk_label"] = grid["risk_class"].map(lambda c: names[int(c)] if pd.notna(c) else np.nan)
    cols = ["district_id", "date", "metric_value", "risk_class", "risk_label", "label_observed", "label_quality"]
    return grid[cols], seasonal, info
