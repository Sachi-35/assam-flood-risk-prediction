"""Loads and validates the shipped ML feasibility report (ml/reports/*). EXPERIMENTAL and separate from every main assessment.

Nothing here trains or runs a model. It only reads the two report files the experiment script wrote, checks their structure, and builds the
response for GET /ml-experiment/summary. Every number and every statistical limitation sentence is derived from the report itself, so the text
cannot go stale when the experiment is re-run. Only the qualitative notes taken from ml/reports/ML_FEASIBILITY_REPORT.md are fixed text.
"""
from __future__ import annotations

import csv
import json
import logging
import math
from pathlib import Path

log = logging.getLogger("flood_api.ml_reports")

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPORT_DIR = BACKEND_DIR / "ml" / "reports"
REPORT_FILE = "model_comparison.json"
PREDICTIONS_FILE = "oof_predictions.csv"
CLASSES = ["Low", "Moderate", "High", "Severe"]
PRIMARY_SCHEME = "4class/LODO/"           # leave-one-district-out, 4 classes: the scheme the endpoint reports
BASELINES = {"majority", "district_history"}
ATTRITION_KEYS = ("labelled_district_years", "after_excluding_2019_snapshots", "with_any_rainfall_station", "with_at_least_30_rain_days",
                  "rows_missing_static")
PERM_KEYS = ("observed_macro_f1", "perm_mean", "perm_p95", "p_value")
PERM_SETS = ("static_plus_rain", "rain_only")
ALPHA = 0.05


class MLReportUnavailable(Exception):
    """A report file does not exist (HTTP 503)."""


class MLReportMalformed(Exception):
    """A report file exists but does not have the expected structure (HTTP 503)."""


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _nonneg_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def _bad(msg: str):
    raise MLReportMalformed(msg)


# --------------------------------------------------------------------------------------------------------------- validation ---------
def validate_report(report) -> None:
    """Raises MLReportMalformed with a specific message unless the JSON has the structure the endpoint (and the frontend type) needs."""
    if not isinstance(report, dict):
        _bad("model_comparison.json must contain a JSON object")
    for k in ("n_rows", "n_districts", "attrition", "class_counts", "results", "permutation_test_LODO_RF_4class"):
        if k not in report:
            _bad(f"model_comparison.json is missing '{k}'")
    if not _nonneg_int(report["n_rows"]) or report["n_rows"] == 0:
        _bad("'n_rows' must be a positive integer")
    if not _nonneg_int(report["n_districts"]) or report["n_districts"] == 0:
        _bad("'n_districts' must be a positive integer")
    att = report["attrition"]
    if not isinstance(att, dict) or any(not _nonneg_int(att.get(k)) for k in ATTRITION_KEYS):
        _bad(f"'attrition' must be an object with non-negative integers for {list(ATTRITION_KEYS)}")
    cc = report["class_counts"]
    if not isinstance(cc, dict) or not cc or any(not _nonneg_int(v) for v in cc.values()):
        _bad("'class_counts' must map class names to non-negative integers")
    perm = report["permutation_test_LODO_RF_4class"]
    if not isinstance(perm, dict):
        _bad("'permutation_test_LODO_RF_4class' must be an object")
    for name in PERM_SETS:
        block = perm.get(name)
        if not isinstance(block, dict) or any(not _num(block.get(k)) for k in PERM_KEYS):
            _bad(f"'permutation_test_LODO_RF_4class.{name}' must contain numbers for {list(PERM_KEYS)}")
        if not 0 <= block["p_value"] <= 1:
            _bad(f"'permutation_test_LODO_RF_4class.{name}.p_value' must be between 0 and 1")
    if not isinstance(report["results"], dict):
        _bad("'results' must be an object")


def _parse_models(results: dict) -> list[dict]:
    """The 4-class leave-one-district-out models. A malformed single entry is skipped and logged; none valid -> malformed report."""
    out, skipped = [], []
    for key, m in results.items():
        if not key.startswith(PRIMARY_SCHEME):
            continue
        name = key.split("/")[2] if key.count("/") >= 2 else ""
        model, features = name.split("|", 1) if "|" in name else (name, "baseline")
        ci = m.get("macro_f1_ci95_district_bootstrap") if isinstance(m, dict) else None
        ok = (isinstance(m, dict) and model and all(_num(m.get(k)) for k in ("accuracy", "balanced_accuracy", "macro_f1", "ordinal_mae"))
              and (ci is None or (isinstance(ci, list) and len(ci) == 2 and all(_num(c) for c in ci) and ci[0] <= ci[1])))
        if not ok:
            skipped.append(key)
            continue
        out.append({"model": model, "features": features, "accuracy": m["accuracy"], "balanced_accuracy": m["balanced_accuracy"],
                    "macro_f1": m["macro_f1"], "macro_f1_ci95": None if ci is None else [ci[0], ci[1]], "ordinal_mae": m["ordinal_mae"]})
    if skipped:
        log.warning("ML report: skipped %d malformed result entr%s: %s", len(skipped), "y" if len(skipped) == 1 else "ies", skipped[:5])
    if not out:
        _bad(f"'results' has no valid '{PRIMARY_SCHEME}*' entries")
    return out


def _parse_predictions(path: Path, expected_rows: int) -> list[dict]:
    need = ["district_id", "year", "risk_class", "4class/LODO/logreg|static_plus_rain", "4class/LODO/random_forest|static_plus_rain"]
    try:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            missing = [c for c in need if c not in (reader.fieldnames or [])]
            if missing:
                _bad(f"oof_predictions.csv is missing column(s) {missing}")
            rows, bad = [], 0
            for r in reader:
                try:
                    cls = [int(r["risk_class"]), int(r[need[3]]), int(r[need[4]])]
                    if not all(0 <= c < len(CLASSES) for c in cls) or not (r["district_id"] or "").strip():
                        raise ValueError
                    rows.append({"district_id": r["district_id"], "year": int(r["year"]), "actual_class": CLASSES[cls[0]],
                                 "logreg_prediction": CLASSES[cls[1]], "random_forest_prediction": CLASSES[cls[2]]})
                except (ValueError, TypeError):
                    bad += 1
    except (csv.Error, UnicodeDecodeError) as e:
        raise MLReportMalformed(f"oof_predictions.csv cannot be parsed: {e.__class__.__name__}")
    if bad:
        log.warning("ML report: skipped %d malformed row(s) in %s", bad, path.name)
    if not rows:
        _bad("oof_predictions.csv has no valid rows")
    if len(rows) != expected_rows:
        log.warning("ML report: %s has %d valid rows but model_comparison.json says n_rows=%d", path.name, len(rows), expected_rows)
    return rows


# --------------------------------------------------------------------------------------------------------------- limitations -------
def build_limitations(report: dict, models: list[dict]) -> list[str]:
    """Limitation sentences computed from the report. Nothing numeric is typed in by hand."""
    att, perm, n_rows, n_dist = report["attrition"], report["permutation_test_LODO_RF_4class"], report["n_rows"], report["n_districts"]
    chance = 1 / len(report["class_counts"])
    out = [f"Only {n_rows} district-season samples from {n_dist} districts were usable "
           f"({att['labelled_district_years']} labelled district-years; {att['after_excluding_2019_snapshots']} after excluding the 2019 "
           f"short-period snapshots; {att['with_any_rainfall_station']} had any rainfall station; {att['with_at_least_30_rain_days']} had "
           f"at least 30 rainfall days). Districts without rainfall stations can never receive an estimate."]

    cand = [m for m in models if m["model"] not in BASELINES and m["macro_f1_ci95"] is not None]
    if cand:
        incl = sum(1 for m in cand if m["macro_f1_ci95"][0] <= chance <= m["macro_f1_ci95"][1])
        below = sum(1 for m in cand if m["macro_f1_ci95"][1] < chance)
        above = sum(1 for m in cand if m["macro_f1_ci95"][0] > chance)
        s = (f"{incl} of {len(cand)} four-class models (baselines excluded) have a 95% bootstrap interval for macro-F1 that includes "
             f"chance level (about {chance:.2f}); {below} entirely below chance, {above} entirely above it.")
        out.append(s + (" No model is distinguishable from chance on the upside." if above == 0 else ""))
        best = max(cand, key=lambda m: m["macro_f1"])
        lo, hi = best["macro_f1_ci95"]
        s = f"Best four-class macro-F1 under leave-one-district-out validation: {best['macro_f1']:.2f} ({best['model']}, {best['features']}; interval {lo:.2f}-{hi:.2f})."
        if "static" in best["features"]:
            s += " With so few districts, terrain-based skill cannot be separated from the model recognising district identity."
        out.append(s)

    rf = next((m for m in models if m["model"] == "random_forest" and m["features"] == "static_plus_rain"), None)
    if rf:
        loyo = report["results"].get("4class/LOYO/random_forest|static_plus_rain")
        extra = f" and {loyo['macro_f1']:.2f} under leave-one-year-out validation" if isinstance(loyo, dict) and _num(loyo.get("macro_f1")) else ""
        out.append(f"The Random Forest with terrain and rainfall (the intended primary model) scored macro-F1 {rf['macro_f1']:.2f} under "
                   f"leave-one-district-out validation{extra}; chance is about {chance:.2f}.")

    ps = ", ".join(f"p = {perm[n]['p_value']:.2f} ({n.replace('_', ' ').replace('static plus rain', 'terrain + rain')})" for n in PERM_SETS)
    if all(perm[n]["p_value"] >= ALPHA for n in PERM_SETS):
        out.append(f"The Random Forest label-permutation test did not show evidence of predictive signal: {ps}.")
    else:
        sig = [n for n in PERM_SETS if perm[n]["p_value"] < ALPHA]
        out.append(f"The Random Forest label-permutation test gave p < {ALPHA} for {', '.join(sig)} ({ps}); with this few samples treat it as "
                   f"exploratory, not as validation.")

    out += ["Flood labels use relative impact bands and a population denominator that is not verified (see ml/reports/ML_FEASIBILITY_REPORT.md).",
            "These are retrospective out-of-fold validation results, not current predictions.",
            "No trained model is integrated into the live assessment system; the main risk map uses the rule-based hazard and the empirical "
            "historical vulnerability."]
    return out


# --------------------------------------------------------------------------------------------------------------- entry point -------
def load_summary(report_dir: Path | str = REPORT_DIR) -> dict:
    """Validated summary for GET /ml-experiment/summary. Raises MLReportUnavailable (files absent) or MLReportMalformed (bad content)."""
    d = Path(report_dir)
    rp, pp = d / REPORT_FILE, d / PREDICTIONS_FILE
    absent = [p.name for p in (rp, pp) if not p.is_file()]
    if absent:
        raise MLReportUnavailable(f"ML experiment report file(s) unavailable: {', '.join(absent)}")
    try:
        report = json.loads(rp.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise MLReportMalformed(f"{REPORT_FILE} is not valid JSON ({e.__class__.__name__})")
    validate_report(report)
    models = _parse_models(report["results"])
    predictions = _parse_predictions(pp, report["n_rows"])
    if sum(report["class_counts"].values()) != report["n_rows"]:
        log.warning("ML report: class_counts sum (%d) differs from n_rows (%d)", sum(report["class_counts"].values()), report["n_rows"])
    return {
        "status": "experimental_not_integrated",
        "n_rows": report["n_rows"],
        "n_districts": report["n_districts"],
        "attrition": {k: report["attrition"][k] for k in ATTRITION_KEYS},
        "class_counts": report["class_counts"],
        "models": models,
        "permutation_test": {n: {k: report["permutation_test_LODO_RF_4class"][n][k] for k in PERM_KEYS} for n in PERM_SETS},
        "predictions": predictions,
        "limitations": build_limitations(report, models),
    }
