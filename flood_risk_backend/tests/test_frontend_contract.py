"""Response shapes the frontend relies on (src/api/types.ts + client.ts). If a backend change breaks one of these, the UI breaks.

The spec below was written from the supplied types.ts. Keys the backend returns beyond the spec (unavailable_reason, year_note) are allowed:
the frontend ignores unknown fields. Nullability is checked in both directions where the TypeScript type says `| null`.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.api_fixtures import build_db, use_engine

NUM = "num"
HAZARD = {"component_type": ("enum", {"rule_based"}), "level": "int|null", "label": "str|null", "exceeded": "str|null",
          "window_rain_mm": "num|null", "obs_fraction": "num|null"}
SHAP = {"feature_name": "str", "contribution_value": "num", "direction": "str"}
VULN = {"component_type": ("enum", {"ml_estimate", "empirical_history"}), "risk_class": "str", "expected_index": "num",
        "proba": "dict|null", "shap_top_features": [[SHAP], "null"], "model_version": "str|null"}
COMBINED = {"component_type": ("enum", {"rule_based_combination"}), "risk_class": "str|null", "risk_score": "num|null"}
ASSESSMENT = {"district_id": "int", "district_name": "str|null", "as_of_date": "str", "window_days": "int",
              "basis": ("enum", {"observed_window", "scenario"}), "status": "str", "hazard": HAZARD, "vulnerability": [VULN, "null"],
              "combined": COMBINED, "disclaimer": "str"}
DISTRICT = {"id": "int", "name": "str", "state": "str", "geometry": {"type": "str", "coordinates": "any"},
            "mean_elevation_m": "num|null", "elevation_std_m": "num|null", "mean_slope_deg": "num|null", "low_lying_frac": "num|null",
            "pop_density_km2": "num|null"}
FLOOD_IMPACT = {"year": "int", "status": "str|null", "impact_class": "str|null", "affected_population": "num|null",
                "reporting_period": "str|null", "caveats": "list|null"}
RECENT = {"dataset": "str", "total_matching": "int", "returned": "int", "limit": "int",
          "filters": {"district_id": "int|null", "start": "str|null", "end": "str|null"},
          "observations": [{"district_id": "int", "district": "str", "date": "str", "rainfall_mm": "num", "source": "str"}],
          "disclaimer": "str"}
PERM = {"observed_macro_f1": "num", "perm_mean": "num", "perm_p95": "num", "p_value": "num"}
ML_SUMMARY = {"status": "str", "n_rows": "int", "n_districts": "int",
              "attrition": {"labelled_district_years": "int", "after_excluding_2019_snapshots": "int", "with_any_rainfall_station": "int",
                            "with_at_least_30_rain_days": "int", "rows_missing_static": "int"},
              "class_counts": "dict",
              "models": [{"model": "str", "features": "str", "accuracy": "num", "balanced_accuracy": "num", "macro_f1": "num",
                          "macro_f1_ci95": "list|null", "ordinal_mae": "num"}],
              "permutation_test": {"static_plus_rain": PERM, "rain_only": PERM},
              "predictions": [{"district_id": "str", "year": "int", "actual_class": "str", "logreg_prediction": "str",
                               "random_forest_prediction": "str"}],
              "limitations": ["str"]}
WINDOWS = {"windows": ["int"], "meaning": "str"}

_BASIC = {"int": lambda v: isinstance(v, int) and not isinstance(v, bool), "num": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
          "str": lambda v: isinstance(v, str), "list": lambda v: isinstance(v, list), "dict": lambda v: isinstance(v, dict), "any": lambda v: True,
          "null": lambda v: v is None}


def check(value, spec, path="$"):
    """Raise AssertionError describing the first mismatch. Spec: 'int|null' strings, {key: spec} dicts, [item_spec] lists,
    [spec_a, 'null'] alternatives, ('enum', {values})."""
    if isinstance(spec, str):
        assert any(_BASIC[t](value) for t in spec.split("|")), f"{path}: {value!r} is not {spec}"
    elif isinstance(spec, tuple):
        assert value in spec[1], f"{path}: {value!r} not in {spec[1]}"
    elif isinstance(spec, dict):
        assert isinstance(value, dict), f"{path}: expected an object, got {value!r}"
        for k, sub in spec.items():
            assert k in value, f"{path}: missing key '{k}'"
            check(value[k], sub, f"{path}.{k}")
    elif isinstance(spec, list) and len(spec) == 2 and spec[1] == "null":
        if value is not None:
            check(value, spec[0], path)
    elif isinstance(spec, list):
        assert isinstance(value, list), f"{path}: expected a list, got {value!r}"
        for i, item in enumerate(value):
            check(item, spec[0], f"{path}[{i}]")


@pytest.fixture
def client(tmp_path):
    eng = build_db(tmp_path / "contract.db", n_districts=3, days=5)
    with use_engine(eng):
        yield TestClient(app)
    eng.dispose()


def test_checker_itself_detects_mismatches():
    check({"a": 1, "b": None}, {"a": "int", "b": "str|null"})
    for bad in ({"a": "x", "b": None}, {"b": None}, {"a": 1, "b": 3}):
        with pytest.raises(AssertionError):
            check(bad, {"a": "int", "b": "str|null"})
    with pytest.raises(AssertionError):
        check({"a": True}, {"a": "int"})                       # bool is not an int for the frontend's purposes


def test_health_and_windows(client):
    assert client.get("/health").json() == {"status": "ok"}
    check(client.get("/windows").json(), WINDOWS)


def test_districts(client):
    body = client.get("/districts").json()
    assert len(body) == 3
    check(body, [DISTRICT])
    assert body[0]["pop_density_km2"] is None                   # null is passed through, never converted to 0


def test_assessment_list_covers_known_and_unknown_cases(client):
    body = client.get("/assessments", params={"window_days": 3}).json()
    check(body, [ASSESSMENT])
    assert {r["status"] for r in body} == {"ok", "insufficient_rainfall_data"}
    unknown = next(r for r in body if r["status"] == "insufficient_rainfall_data")
    assert unknown["hazard"]["level"] is None and unknown["combined"]["risk_class"] is None and unknown["hazard"]["window_rain_mm"] is None
    assert next(r for r in body if r["district_id"] == 3)["vulnerability"] is None             # no vulnerability -> null


def test_vulnerability_variants(client):
    body = client.get("/assessments", params={"window_days": 3}).json()
    ml = next(r for r in body if r["district_id"] == 1)["vulnerability"]
    hist = next(r for r in body if r["district_id"] == 2)["vulnerability"]
    assert ml["component_type"] == "ml_estimate" and isinstance(ml["proba"], dict) and isinstance(ml["shap_top_features"], list)
    assert hist["component_type"] == "empirical_history" and hist["proba"] is None and hist["shap_top_features"] is None


def test_district_assessment_and_history(client):
    check(client.get("/districts/1/assessment", params={"window_days": 3, "date": "2023-07-05"}).json(), ASSESSMENT)
    h = client.get("/districts/1/history", params={"window_days": 3, "start": "2023-07-01", "end": "2023-07-05"})
    check(h.json(), [ASSESSMENT])
    assert [x["as_of_date"] for x in h.json()] == sorted(x["as_of_date"] for x in h.json())


def test_scenario_response(client):
    r = client.post("/assess", json={"district_id": 1, "window_days": 3, "window_end_date": "2023-07-15", "window_rain_mm": 150})
    check(r.json(), ASSESSMENT)
    assert r.json()["basis"] == "scenario" and "HYPOTHETICAL" in r.json()["disclaimer"]


def test_flood_impact(client):
    body = client.get("/districts/1/flood-impact").json()
    check(body, [FLOOD_IMPACT])
    unknown = next(r for r in body if r["year"] == 2022)
    assert unknown["status"] == "unknown" and unknown["affected_population"] is None and unknown["impact_class"] is None


def test_recent_rainfall_matches_frontend_type_and_query_names(client):
    body = client.get("/rainfall/recent", params={"limit": 10000}).json()
    check(body, RECENT)
    assert body["limit"] == 10000 and body["filters"] == {"district_id": None, "start": None, "end": None}
    f = client.get("/rainfall/recent", params={"district_id": 1, "start": "2026-08-20", "end": "2026-08-21"}).json()
    assert f["filters"] == {"district_id": 1, "start": "2026-08-20", "end": "2026-08-21"} and f["returned"] == 2


def test_ml_experiment_summary_matches_frontend_type(client):
    r = client.get("/ml-experiment/summary")
    assert r.status_code == 200
    check(r.json(), ML_SUMMARY)


def test_model_metadata_untrained_is_503_with_string_detail(client):
    r = client.get("/model/metadata")
    assert r.status_code == 503 and isinstance(r.json()["detail"], str) and "train_model.py" in r.json()["detail"]


def test_error_bodies_are_parseable_by_the_frontend_client(client):
    """client.ts reads body.detail as a string or as a list of {msg}; every error must use one of those."""
    cases = [client.get("/districts/99/assessment", params={"window_days": 3}),            # 404 string
             client.get("/assessments", params={"window_days": 5}),                         # 422 string
             client.get("/assessments", params={"window_days": "x"}),                       # 422 list of {loc,msg}
             client.get("/model/metadata")]                                                 # 503 string
    for r in cases:
        d = r.json()["detail"]
        assert isinstance(d, str) or (isinstance(d, list) and all("msg" in e for e in d)), r.json()
