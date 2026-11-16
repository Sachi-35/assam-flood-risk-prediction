"""ML report loader/validator + ML separation + ALLOW_ML_VULNERABILITY default. No database and no model needed."""
import ast
import csv
import importlib.util
import json
import logging
import os
import re
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.services import ml_reports as M  # noqa: E402

CLASSES = M.CLASSES
BACKEND = os.path.join(os.path.dirname(__file__), "..")
SHIPPED = os.path.join(BACKEND, "ml", "reports")


# ------------------------------------------------------------------------------------------------------------ helpers ----------
def metrics(f1, ci=None, acc=0.3):
    return {"accuracy": acc, "balanced_accuracy": acc, "macro_f1": f1, "macro_precision": 0.3, "macro_recall": 0.3, "ordinal_mae": 1.1,
            "macro_f1_ci95_district_bootstrap": ci if ci is not None else [max(f1 - 0.1, 0), f1 + 0.1]}


def make_report(**over):
    r = {"n_rows": 4, "n_districts": 2,
         "attrition": {"labelled_district_years": 10, "after_excluding_2019_snapshots": 8, "with_any_rainfall_station": 5,
                       "with_at_least_30_rain_days": 4, "rows_missing_static": 0},
         "class_counts": {"Low": 1, "Moderate": 1, "High": 1, "Severe": 1},
         "results": {"4class/LODO/majority": metrics(0.06, [0.0, 0.12]),
                     "4class/LODO/logreg|static_plus_rain": metrics(0.30, [0.15, 0.45]),
                     "4class/LODO/random_forest|static_plus_rain": metrics(0.20, [0.10, 0.30]),
                     "4class/LOYO/random_forest|static_plus_rain": metrics(0.35)},
         "permutation_test_LODO_RF_4class": {n: {"observed_macro_f1": 0.2, "perm_mean": 0.23, "perm_p95": 0.38, "p_value": 0.6} for n in M.PERM_SETS}}
    r.update(over)
    return r


def write_dir(tmp_path, report=None, rows=None, name="reports"):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    (d / M.REPORT_FILE).write_text(json.dumps(make_report() if report is None else report))
    cols = ["district_id", "year", "risk_label", "risk_class", "4class/LODO/logreg|static_plus_rain", "4class/LODO/random_forest|static_plus_rain"]
    rows = rows if rows is not None else [["a", 2020, "Low", 0, 0, 1], ["a", 2021, "High", 2, 2, 3], ["b", 2020, "Severe", 3, 3, 3], ["b", 2021, "Moderate", 1, 0, 1]]
    with (d / M.PREDICTIONS_FILE).open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    return d


# ------------------------------------------------------------------------------------------------------------ shipped report ---
def test_shipped_report_loads_and_matches_its_json_exactly():
    s = M.load_summary(SHIPPED)
    raw = json.load(open(os.path.join(SHIPPED, "model_comparison.json")))
    assert s["status"] == "experimental_not_integrated"
    assert (s["n_rows"], s["n_districts"]) == (raw["n_rows"], raw["n_districts"])
    assert s["attrition"] == raw["attrition"] and s["class_counts"] == raw["class_counts"]
    assert s["permutation_test"] == raw["permutation_test_LODO_RF_4class"]
    lodo = [k for k in raw["results"] if k.startswith("4class/LODO/")]
    assert len(s["models"]) == len(lodo)
    with open(os.path.join(SHIPPED, "oof_predictions.csv")) as f:
        assert len(s["predictions"]) == sum(1 for _ in csv.DictReader(f))
    assert set(s) == {"status", "n_rows", "n_districts", "attrition", "class_counts", "models", "permutation_test", "predictions", "limitations"}


def test_every_number_in_the_limitations_comes_from_the_shipped_report():
    s = M.load_summary(SHIPPED)
    raw = json.load(open(os.path.join(SHIPPED, "model_comparison.json")))
    text = " ".join(s["limitations"])
    first = s["limitations"][0]
    for v in (raw["n_rows"], raw["n_districts"], *raw["attrition"].values()):
        if v:
            assert str(v) in first
    rf = raw["results"]["4class/LODO/random_forest|static_plus_rain"]["macro_f1"]
    assert f"{rf:.2f}" in text
    for n in M.PERM_SETS:
        assert f"{raw['permutation_test_LODO_RF_4class'][n]['p_value']:.2f}" in text


def test_chance_level_statement_is_accurate_for_the_shipped_report():
    """The old hard-coded sentence said ALL four-class intervals include chance (~0.25). The shipped report shows otherwise."""
    raw = json.load(open(os.path.join(SHIPPED, "model_comparison.json")))
    cand = {k: v for k, v in raw["results"].items() if k.startswith("4class/LODO/") and k.split("/")[2] not in M.BASELINES}
    ci = [v["macro_f1_ci95_district_bootstrap"] for v in cand.values()]
    incl, below, above = (sum(lo <= 0.25 <= hi for lo, hi in ci), sum(hi < 0.25 for lo, hi in ci), sum(lo > 0.25 for lo, hi in ci))
    assert below >= 1                                                  # at least one interval lies wholly below chance, so "all include chance" was false
    s = M.load_summary(SHIPPED)
    line = next(x for x in s["limitations"] if "bootstrap interval" in x)
    assert f"{incl} of {len(ci)}" in line and f"{below} entirely below" in line and f"{above} entirely above" in line
    assert not any(x.startswith("All four-class model confidence intervals include") for x in s["limitations"])


def test_best_model_sentence_names_the_actual_best_model():
    raw = json.load(open(os.path.join(SHIPPED, "model_comparison.json")))
    cand = {k: v for k, v in raw["results"].items() if k.startswith("4class/LODO/") and k.split("/")[2] not in M.BASELINES}
    best_key = max(cand, key=lambda k: cand[k]["macro_f1"])
    model, feats = best_key.split("/")[2].split("|")
    line = next(x for x in M.load_summary(SHIPPED)["limitations"] if x.startswith("Best four-class"))
    assert model in line and feats in line and f"{cand[best_key]['macro_f1']:.2f}" in line


# ------------------------------------------------------------------------------------------------------------ no stale text -----
def test_limitations_follow_the_report_when_numbers_change(tmp_path):
    rep = make_report(n_rows=40, n_districts=9)
    rep["attrition"]["with_at_least_30_rain_days"] = 40
    rep["permutation_test_LODO_RF_4class"]["static_plus_rain"]["p_value"] = 0.01
    rows = [["a", 2020, "Low", 0, 0, 1]] * 40
    s = M.load_summary(write_dir(tmp_path, rep, rows))
    text = " ".join(s["limitations"])
    assert s["limitations"][0].startswith("Only 40 district-season samples from 9 districts")
    assert "did not show evidence of predictive signal" not in text and "p < 0.05" in text            # significant p must not be described as "no signal"


def test_interval_counts_adapt_to_the_report(tmp_path):
    rep = make_report()
    rep["results"]["4class/LODO/logreg|static_plus_rain"] = metrics(0.6, [0.4, 0.8])                   # wholly above chance
    line = next(x for x in M.load_summary(write_dir(tmp_path, rep))["limitations"] if "bootstrap interval" in x)
    assert "1 entirely above" in line and "No model is distinguishable from chance on the upside" not in line


# ------------------------------------------------------------------------------------------------------------ missing / malformed ---
def test_missing_files_are_reported_as_unavailable(tmp_path):
    with pytest.raises(M.MLReportUnavailable, match="oof_predictions.csv"):
        d = write_dir(tmp_path)
        os.remove(d / M.PREDICTIONS_FILE)
        M.load_summary(d)
    with pytest.raises(M.MLReportUnavailable):
        M.load_summary(tmp_path / "nowhere")


@pytest.mark.parametrize("break_it, expect", [
    (lambda r: r.pop("attrition"), "missing 'attrition'"),
    (lambda r: r["attrition"].pop("rows_missing_static"), "attrition"),
    (lambda r: r.update(n_rows="37"), "n_rows"),
    (lambda r: r.update(n_rows=0), "n_rows"),
    (lambda r: r.update(class_counts={}), "class_counts"),
    (lambda r: r.update(results=[]), "results"),
    (lambda r: r["permutation_test_LODO_RF_4class"]["rain_only"].update(p_value=1.5), "p_value"),
    (lambda r: r["permutation_test_LODO_RF_4class"].pop("static_plus_rain"), "static_plus_rain"),
    (lambda r: r.update(results={"4class/LOYO/majority": metrics(0.1)}), "no valid"),
])
def test_malformed_report_structure_is_rejected_with_a_specific_message(tmp_path, break_it, expect):
    rep = make_report()
    break_it(rep)
    with pytest.raises(M.MLReportMalformed) as e:
        M.load_summary(write_dir(tmp_path, rep))
    assert expect in str(e.value)


def test_json_that_is_not_json_or_not_an_object(tmp_path):
    d = write_dir(tmp_path)
    (d / M.REPORT_FILE).write_text("{broken")
    with pytest.raises(M.MLReportMalformed, match="not valid JSON"):
        M.load_summary(d)
    (d / M.REPORT_FILE).write_text("[1, 2, 3]")
    with pytest.raises(M.MLReportMalformed, match="JSON object"):
        M.load_summary(d)


def test_one_bad_result_entry_is_skipped_not_fatal(tmp_path, caplog):
    rep = make_report()
    rep["results"]["4class/LODO/xgboost|rain_only"] = {"accuracy": "n/a"}
    with caplog.at_level(logging.WARNING, logger="flood_api.ml_reports"):
        s = M.load_summary(write_dir(tmp_path, rep))
    assert all(m["model"] != "xgboost" for m in s["models"]) and len(s["models"]) == 3
    assert any("skipped 1 malformed result" in r.getMessage() for r in caplog.records)


def test_prediction_csv_problems(tmp_path, caplog):
    d = write_dir(tmp_path, rows=[["a", 2020, "Low", 0, 0, 1], ["a", "x", "Low", 0, 0, 1], ["b", 2020, "?", 9, 0, 1], ["", 2020, "Low", 0, 0, 1]])
    with caplog.at_level(logging.WARNING, logger="flood_api.ml_reports"):
        s = M.load_summary(d)
    assert len(s["predictions"]) == 1 and s["predictions"][0]["actual_class"] == "Low"
    assert any("skipped 3 malformed row" in r.getMessage() for r in caplog.records)
    with pytest.raises(M.MLReportMalformed, match="no valid rows"):
        M.load_summary(write_dir(tmp_path, rows=[["a", "x", "Low", 9, 9, 9]], name="r2"))
    (d / M.PREDICTIONS_FILE).write_text("district_id,year\na,2020\n")
    with pytest.raises(M.MLReportMalformed, match="missing column"):
        M.load_summary(d)


def test_row_count_disagreement_is_logged_not_fatal(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="flood_api.ml_reports"):
        M.load_summary(write_dir(tmp_path, make_report(n_rows=99)))
    assert any("n_rows=99" in r.getMessage() for r in caplog.records)


def test_loader_never_modifies_the_report_files(tmp_path):
    d = write_dir(tmp_path)
    before = {f: open(d / f, "rb").read() for f in os.listdir(d)}
    M.load_summary(d)
    assert {f: open(d / f, "rb").read() for f in os.listdir(d)} == before


# ------------------------------------------------------------------------------------------------------------ ML stays separate ---
def _imports(path):
    tree = ast.parse(open(path).read())
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


def test_report_loader_and_route_do_not_import_any_model_or_assessment_code():
    banned = ("sklearn", "xgboost", "joblib", "shap", "app.services.vulnerability", "app.services.model_loader", "app.services.assessment",
              "app.services.ordinal_xgb", "app.models", "app.database")
    for path in ("app/services/ml_reports.py", "app/api/routes/ml_experiment.py"):
        mods = _imports(os.path.join(BACKEND, path))
        assert not [m for m in mods if m.startswith(banned)], (path, mods)


def test_main_assessment_routes_do_not_import_the_ml_report_loader():
    for path in ("app/api/routes/assessments.py", "app/services/assessment.py", "app/services/vulnerability.py", "app/api/routes/districts.py"):
        assert not [m for m in _imports(os.path.join(BACKEND, path)) if "ml_reports" in m or "ml_experiment" in m], path


# ------------------------------------------------------------------------------------------------------------ ALLOW_ML_VULNERABILITY ----
def _fresh_settings(monkeypatch, value):
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)        # a developer's own .env must not influence the default check
    if value is None:
        monkeypatch.delenv("ALLOW_ML_VULNERABILITY", raising=False)
    else:
        monkeypatch.setenv("ALLOW_ML_VULNERABILITY", value)
    spec = importlib.util.spec_from_file_location("config_probe", os.path.join(BACKEND, "app", "config.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.settings


def test_ml_vulnerability_is_off_by_default_and_only_on_when_explicit(monkeypatch):
    assert _fresh_settings(monkeypatch, None).ALLOW_ML_VULNERABILITY is False
    for off in ("false", "0", "no", "", "maybe"):
        assert _fresh_settings(monkeypatch, off).ALLOW_ML_VULNERABILITY is False, off
    for on in ("true", "TRUE", "1", "yes"):
        assert _fresh_settings(monkeypatch, on).ALLOW_ML_VULNERABILITY is True, on


def test_env_example_documents_the_flag_as_false():
    text = open(os.path.join(BACKEND, ".env.example")).read()
    assert re.search(r"^ALLOW_ML_VULNERABILITY=false\s*$", text, re.M)
