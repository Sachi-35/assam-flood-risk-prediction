"""Historical flood-impact labels (district-year): normalisation for import, and the empirical-history vulnerability.

Nothing here invents a value. The three states stay apart:
  reported            known impact (a class and/or an affected-population count)
  no_reported_impact  the source supports an actual zero
  unknown             no usable information (never zero, never Low)
A missing affected_population is stored as NULL; 0 is stored only when the source says 0.
"""
from __future__ import annotations

import math
import re
from typing import Iterable

import pandas as pd

from app.features import CLASS_ORDER

STATUSES = ("reported", "no_reported_impact", "unknown")

# Documented project caveats that apply to a whole reporting year (from the data-preparation work). They are exposed as
# `year_note` on each record and in GET /methodology; the frontend also shows them next to the year, so they are NOT added to
# `caveats` (that would print them twice).
YEAR_NOTES = {
    2019: "Some 2019 records are a fourth-wave snapshot, not a complete season.",
    2020: "The 2020 affected-population total does not reconcile with the source memo.",
}

# Districts that are not separate polygons in the boundary file, mapped as in data preparation.
# Bajali -> Barpeta and Sribhumi -> Karimganj are in the data-prep config; Tamulpur -> Baksa is the documented parent.
NAME_ALIASES = {"bajali": "barpeta", "tamulpur": "baksa", "sribhumi": "karimganj"}

_COLUMN_ALIASES = {
    "district_id": ["district_id", "id"],
    "district": ["district", "district_name", "name"],
    "year": ["year"],
    "status": ["status", "impact_status"],
    "impact_class": ["impact_class", "risk_class", "class"],
    "affected_population": ["affected_population", "affected", "population_affected"],
    "reporting_period": ["reporting_period", "period"],
    "caveats": ["caveats", "caveat", "notes", "quality_flags"],
}
MIN_HISTORY_YEARS = 2          # fewer known district-years than this: no empirical vulnerability


def norm_name(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _pick(df: pd.DataFrame, key: str):
    for c in _COLUMN_ALIASES[key]:
        if c in df.columns:
            return c
    return None


def _num(v):
    if v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip()):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _text(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    t = str(v).strip()
    return t or None


def _caveat_list(v) -> list[str]:
    t = _text(v)
    return [] if t is None else [p.strip() for p in re.split(r"[|;]", t) if p.strip()]


def normalise_status(raw, cls, aff):
    """(status, note). `raw` may be empty: then the status is inferred ONLY from explicit values, never from absence."""
    r = (_text(raw) or "").lower().replace(" ", "_").replace("-", "_")
    r = {"known_impact": "reported", "known": "reported", "none": "no_reported_impact", "no_impact": "no_reported_impact"}.get(r, r)
    if r and r not in STATUSES:
        return "unknown", f"unrecognised status '{raw}' treated as unknown"
    if not r:
        if cls is not None or (aff is not None and aff > 0):
            r = "reported"
        elif aff == 0:
            r = "no_reported_impact"
        else:
            r = "unknown"
    if r == "reported" and cls is None and not (aff is not None and aff > 0):
        return "unknown", "marked reported but has no class or positive count"
    if r == "no_reported_impact" and (cls is not None or (aff is not None and aff > 0)):
        return "unknown", "marked no_reported_impact but also has a class or positive count (conflict)"
    return r, None


def prepare_labels(df: pd.DataFrame, districts: dict[int, str], class_fallback: dict[tuple[int, int], str] | None = None):
    """Turns a raw label table into FloodLabel dicts. Returns (records, problems).

    `districts` maps id -> name. Rows whose district cannot be matched are NOT dropped silently: they are listed in `problems`.
    Two rows for the same district-year (e.g. Bajali + Barpeta) are merged: counts are summed when both are known.
    `class_fallback` {(district_id, year): class} fills a missing class only (used with season_features.csv).
    """
    problems: list[str] = []
    cols = {k: _pick(df, k) for k in _COLUMN_ALIASES}
    if cols["year"] is None or (cols["district_id"] is None and cols["district"] is None):
        raise ValueError("flood label file needs a 'year' column and a 'district_id' or 'district' column")
    by_name = {norm_name(n): i for i, n in districts.items()}
    pcols = (_pick_extra(df, "period_start"), _pick_extra(df, "period_end"))
    merged: dict[tuple[int, int], dict] = {}
    n_src: dict[tuple[int, int], int] = {}
    for pos, row in df.iterrows():
        did = None
        if cols["district_id"] is not None and _num(row[cols["district_id"]]) is not None:
            did = int(_num(row[cols["district_id"]]))
            if did not in districts:
                problems.append(f"row {pos + 2}: district_id {did} is not in the districts table (row not imported)")
                continue
            label = districts[did]
        else:
            label = _text(row[cols["district"]]) if cols["district"] else None
            key = norm_name(label or "")
            key = norm_name(NAME_ALIASES.get(key, key))
            did = by_name.get(key)
            if did is None:
                problems.append(f"row {pos + 2}: district '{label}' does not match any of the {len(districts)} districts (row not imported)")
                continue
        yr = _num(row[cols["year"]])
        if yr is None or int(yr) != yr:
            problems.append(f"row {pos + 2}: year '{row[cols['year']]}' is not an integer (row not imported)")
            continue
        yr = int(yr)
        cls = _text(row[cols["impact_class"]]).lower() if cols["impact_class"] and _text(row[cols["impact_class"]]) else None
        if cls is None and class_fallback:
            cls = class_fallback.get((did, yr))
        if cls is not None and cls not in CLASS_ORDER:
            problems.append(f"row {pos + 2}: impact class '{cls}' is not one of {CLASS_ORDER}; class ignored")
            cls = None
        aff = _num(row[cols["affected_population"]]) if cols["affected_population"] else None
        if aff is not None and aff < 0:
            problems.append(f"row {pos + 2}: negative affected_population ignored")
            aff = None
        status, note = normalise_status(row[cols["status"]] if cols["status"] else None, cls, aff)
        caveats = _caveat_list(row[cols["caveats"]]) if cols["caveats"] else []
        if note:
            caveats.append(f"Import note: {note}.")
            problems.append(f"row {pos + 2} ({label}, {yr}): {note}")
        period = _text(row[cols["reporting_period"]]) if cols["reporting_period"] else None
        if period is None and all(pcols):
            a, b = _text(row[pcols[0]]), _text(row[pcols[1]])
            period = f"{a} to {b}" if a and b else None
        if status == "unknown":
            cls, aff = None, None
        if status == "no_reported_impact":
            cls = None
        rec = {"district_id": did, "year": yr, "status": status, "impact_class": cls, "affected_population": aff,
               "reporting_period": period, "caveats": caveats}
        k = (did, yr)
        n_src[k] = n_src.get(k, 0) + 1
        merged[k] = rec if k not in merged else _merge(merged[k], rec)
    for k, n in n_src.items():
        if n > 1:
            merged[k]["caveats"].append(f"Merged from {n} source rows (counts summed where known).")
            problems.append(f"district {districts[k[0]]}, {k[1]}: {n} source rows merged into one district-year")
    return list(merged.values()), problems


def _pick_extra(df, name):
    return name if name in df.columns else None


_RANK = {"reported": 2, "no_reported_impact": 1, "unknown": 0}


def _merge(a: dict, b: dict) -> dict:
    top = a if _RANK[a["status"]] >= _RANK[b["status"]] else b
    out = dict(top)
    if a["affected_population"] is not None and b["affected_population"] is not None:
        out["affected_population"] = a["affected_population"] + b["affected_population"]
    else:
        out["affected_population"] = a["affected_population"] if a["affected_population"] is not None else b["affected_population"]
    ia = CLASS_ORDER.index(a["impact_class"]) if a["impact_class"] else -1
    ib = CLASS_ORDER.index(b["impact_class"]) if b["impact_class"] else -1
    out["impact_class"] = CLASS_ORDER[max(ia, ib)] if max(ia, ib) >= 0 else None
    out["caveats"] = list(dict.fromkeys(a["caveats"] + b["caveats"]))
    out["reporting_period"] = a["reporting_period"] or b["reporting_period"]
    return out


def history_mean_index(rows: Iterable) -> tuple[float | None, int]:
    """Mean class index (0 low .. 3 severe) over the district's KNOWN years, and how many years that is.

    reported + class -> its class index; no_reported_impact -> 0 (the lowest band, since bands are quantiles of positive impacts);
    unknown and reported-without-class years are skipped (never counted as zero).
    """
    vals = []
    for r in rows:
        if r.status == "reported" and r.impact_class in CLASS_ORDER:
            vals.append(CLASS_ORDER.index(r.impact_class))
        elif r.status == "no_reported_impact":
            vals.append(0)
    if len(vals) < MIN_HISTORY_YEARS:
        return None, len(vals)
    return sum(vals) / len(vals), len(vals)
