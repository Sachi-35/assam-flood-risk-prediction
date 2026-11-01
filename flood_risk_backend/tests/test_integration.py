"""Integration tests for the seasonal/annual backend (v0.4).

SYNTHETIC: every file written here is hand-made plumbing (33 square districts, alternating Polygon/MultiPolygon; invented label rows).
They prove the code paths, the missing/zero/unknown distinctions and the API shape. They say NOTHING about the real Assam boundary file,
the real 2019-2023 labels or the real rainfall: those must be verified by running scripts/seed_db.py on the real data (see README).
"""
import json
import os
import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import FloodLabel, RiskAssessment  # noqa: E402

N = 33
NAMES = [f"District {i:02d}" for i in range(1, N + 1)]
NAMES[0], NAMES[1], NAMES[2] = "Barpeta", "Baksa", "Karimganj"       # real parents of Bajali / Tamulpur / Sribhumi


def square(x, y, s=0.1):
    return [[x, y], [x + s, y], [x + s, y + s], [x, y + s], [x, y]]


def geom(i):
    x, y = 90 + (i % 10) * 0.5, 25 + (i // 10) * 0.5
    if i % 2:
        return {"type": "MultiPolygon", "coordinates": [[square(x, y)], [square(x + 0.2, y)]]}
    return {"type": "Polygon", "coordinates": [square(x, y)]}


def write_districts(folder, n=N, terrain=True, bad_geometry=None):
    rows = []
    for i in range(1, n + 1):
        g = geom(i - 1) if i != bad_geometry else {"type": "Point", "coordinates": [91, 26]}
        rows.append({"id": i, "name": NAMES[i - 1], "state": "Assam", "geometry": json.dumps(g),
                     "mean_elevation_m": 50.0 + i if terrain and i != 5 else None, "elevation_std_m": 5.0 if terrain else None,
                     "mean_slope_deg": 1.0 if terrain else None, "low_lying_frac": 0.3 if terrain else None, "pop_density_km2": None})
    pd.DataFrame(rows).to_csv(os.path.join(folder, "districts.csv"), index=False)


def write_labels(folder):
    rows = [
        # district 1 (Barpeta, also receives Bajali): two source rows merged for 2021
        {"district": "Barpeta", "year": 2021, "status": "reported", "impact_class": "high", "affected_population": 1000, "reporting_period": "1 Jun to 30 Sep", "caveats": "check A"},
        {"district": "Bajali", "year": 2021, "status": "reported", "impact_class": "high", "affected_population": 500},
        {"district": "Barpeta", "year": 2019, "status": "reported", "impact_class": "severe", "affected_population": 9000},
        {"district": "Barpeta", "year": 2022, "status": "no_reported_impact", "affected_population": 0},          # explicit zero
        {"district": "Barpeta", "year": 2023, "status": "unknown"},                                                # unknown, not zero
        # district 2 (Baksa): class only, count missing (NOT zero); one explicit zero
        {"district": "Baksa", "year": 2020, "status": "reported", "impact_class": "moderate"},
        {"district": "Tamulpur", "year": 2022, "status": "no_reported_impact", "affected_population": 0},
        # district 3: only one known year -> no empirical vulnerability
        {"district": "Karimganj", "year": 2021, "status": "reported", "impact_class": "low", "affected_population": 10},
        {"district": "Karimganj", "year": 2020, "status": "unknown"},
        # unmatched name must be reported, never silently dropped
        {"district": "Atlantis", "year": 2021, "status": "reported", "impact_class": "low", "affected_population": 1},
    ]
    pd.DataFrame(rows).to_csv(os.path.join(folder, "flood_labels.csv"), index=False)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """An isolated empty database + data folder, wired into the app for the duration of one test."""
    import seed_db
    import compute_assessments as CA
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    Base.metadata.create_all(bind=eng)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(seed_db, "DATA_DIR", str(data))
    monkeypatch.setattr(CA, "SessionLocal", Session)
    monkeypatch.setattr(CA, "engine", eng)
    monkeypatch.setattr(CA, "read_metadata", lambda: None)
    monkeypatch.setattr(CA, "get_model_bundle", lambda: None)
    saved = dict(app.dependency_overrides)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = override
    yield type("Env", (), {"data": str(data), "Session": Session, "seed": seed_db, "CA": CA, "client": TestClient(app)})
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


def seed(env):
    db = env.Session()
    try:
        return env.seed.seed_all(db)
    finally:
        db.close()


# ---------------------------------------------------------------- districts (A) -----------------------------------------------------
def test_all_33_districts_with_polygon_and_multipolygon_and_no_assessments(env):
    write_districts(env.data)
    seed(env)
    r = env.client.get("/districts")
    assert r.status_code == 200 and len(r.json()) == 33
    types = {d["geometry"]["type"] for d in r.json()}
    assert types == {"Polygon", "MultiPolygon"}
    mp = next(d for d in r.json() if d["geometry"]["type"] == "MultiPolygon")
    assert len(mp["geometry"]["coordinates"]) == 2                                   # both parts preserved
    # no rainfall, no labels, no assessments computed: districts and the other endpoints still behave
    assert env.client.get("/assessments", params={"window_days": 7}).status_code in (404, 422)
    assert env.client.get("/windows").json()["windows"] == []


def test_terrain_null_is_kept_not_zero(env):
    write_districts(env.data)
    seed(env)
    d5 = next(d for d in env.client.get("/districts").json() if d["id"] == 5)
    assert d5["mean_elevation_m"] is None and d5["pop_density_km2"] is None
    write_districts(env.data, terrain=False)
    seed(env)                                                                        # re-seed: terrain becomes null, districts stay
    ds = env.client.get("/districts").json()
    assert len(ds) == 33 and all(d["mean_slope_deg"] is None for d in ds)


def test_invalid_geometry_is_reported_and_kept_not_dropped(env, capsys):
    write_districts(env.data, bad_geometry=7)
    seed(env)
    out = capsys.readouterr().out
    assert "GEOMETRY WARNING" in out and "District 07" in out
    assert len(env.client.get("/districts").json()) == 33                            # still returned; the frontend lists it as undrawable


def test_unparseable_geometry_aborts_without_changing_anything(env):
    write_districts(env.data)
    seed(env)
    df = pd.read_csv(os.path.join(env.data, "districts.csv"))
    df.loc[3, "geometry"] = "{not json"
    df.to_csv(os.path.join(env.data, "districts.csv"), index=False)
    with pytest.raises(SystemExit):
        seed(env)
    assert len(env.client.get("/districts").json()) == 33


# ---------------------------------------------------------------- seeding (repeatable) ------------------------------------------------
def test_seeding_twice_does_not_duplicate(env):
    write_districts(env.data)
    write_labels(env.data)
    seed(env)
    db = env.Session()
    first = (db.query(FloodLabel).count(), len(env.client.get("/districts").json()))
    db.close()
    seed(env)
    db = env.Session()
    assert (db.query(FloodLabel).count(), len(env.client.get("/districts").json())) == first
    db.close()


def test_missing_optional_files_are_skipped_with_a_message(env, capsys):
    write_districts(env.data)
    seed(env)
    out = capsys.readouterr().out
    assert "rainfall_daily: SKIPPED" in out and "climatology: SKIPPED" in out and "flood labels: SKIPPED" in out


def test_missing_districts_file_stops_with_a_clear_message(env):
    with pytest.raises(SystemExit, match="districts.csv not found"):
        seed(env)


# ---------------------------------------------------------------- historical impact (B) -------------------------------------------------
def test_flood_impact_states_zero_and_missing_are_kept_apart(env, capsys):
    write_districts(env.data)
    write_labels(env.data)
    seed(env)
    out = capsys.readouterr().out
    assert "Atlantis" in out and "not imported" in out                               # unmatched district reported, not silent
    rec = {r["year"]: r for r in env.client.get("/districts/1/flood-impact").json()}
    assert rec[2021]["status"] == "reported" and rec[2021]["impact_class"] == "high"
    assert rec[2021]["affected_population"] == 1500.0                                # Bajali merged into Barpeta, summed
    assert any("Merged" in c for c in rec[2021]["caveats"]) and "check A" in rec[2021]["caveats"]
    assert rec[2021]["reporting_period"] == "1 Jun to 30 Sep"
    assert rec[2022]["status"] == "no_reported_impact" and rec[2022]["affected_population"] == 0.0    # an explicit zero
    assert rec[2022]["impact_class"] is None
    assert rec[2023]["status"] == "unknown" and rec[2023]["affected_population"] is None             # unknown is NOT zero
    assert 2020 not in rec                                                           # no row: simply absent
    d2 = {r["year"]: r for r in env.client.get("/districts/2/flood-impact").json()}
    assert d2[2020]["status"] == "reported" and d2[2020]["affected_population"] is None              # missing count stays null
    assert d2[2022]["status"] == "no_reported_impact"                                # Tamulpur -> Baksa


def test_year_notes_2019_2020_are_exposed_separately(env):
    write_districts(env.data)
    write_labels(env.data)
    seed(env)
    r19 = next(r for r in env.client.get("/districts/1/flood-impact").json() if r["year"] == 2019)
    assert "fourth-wave" in r19["year_note"] and r19["caveats"] == []                # not duplicated into caveats (frontend shows the note itself)
    r20 = next(r for r in env.client.get("/districts/2/flood-impact").json() if r["year"] == 2020)
    assert "reconcile" in r20["year_note"]
    r21 = next(r for r in env.client.get("/districts/1/flood-impact").json() if r["year"] == 2021)
    assert r21["year_note"] is None


def test_flood_impact_empty_list_and_404(env):
    write_districts(env.data)
    seed(env)                                                                        # no label file at all
    assert env.client.get("/districts/4/flood-impact").json() == []
    assert env.client.get("/districts/999/flood-impact").status_code == 404


def test_labels_fall_back_to_season_features_classes_only(env):
    write_districts(env.data)
    pd.DataFrame([{"district_id": 4, "year": 2021, "risk_class": "moderate"}]).to_csv(os.path.join(env.data, "season_features.csv"), index=False)
    seed(env)
    r = env.client.get("/districts/4/flood-impact").json()
    assert r[0]["impact_class"] == "moderate" and r[0]["affected_population"] is None and "Class only" in r[0]["caveats"][0]


# ---------------------------------------------------------------- vulnerability / hazard / combined (C-F) ------------------------------
def test_vulnerability_only_assessments_for_all_33_without_any_rainfall(env):
    write_districts(env.data)
    write_labels(env.data)
    seed(env)
    with pytest.raises(SystemExit):                                                  # no rainfall -> no range to infer
        env.CA.main(None, None, [7])
    env.CA.main("2023-06-01", "2023-06-03", [7])
    assert env.client.get("/windows").json()["windows"] == [7]
    rows = env.client.get("/assessments", params={"window_days": 7, "date": "2023-06-02"}).json()
    assert len(rows) == 33                                                            # every district has a row
    by = {r["district_id"]: r for r in rows}
    for r in rows:
        assert r["hazard"]["level"] is None and r["combined"]["risk_class"] is None and r["status"] == "insufficient_rainfall_data"
        assert r["hazard"]["window_rain_mm"] is None and r["hazard"]["obs_fraction"] == 0.0
        assert "No rainfall observations" in r["unavailable_reason"]
    # district 1: 2019 severe(3), 2021 high(2, merged rows), 2022 none(0); 2023 unknown is skipped -> mean 5/3 = 1.67 -> high; empirical, no model claims
    v1 = by[1]["vulnerability"]
    assert v1["component_type"] == "empirical_history" and v1["risk_class"] == "high" and v1["proba"] is None and v1["shap_top_features"] is None
    # district 2: moderate(1) + no_reported_impact(0) = 0.5 -> index 0 (round-half-even) -> low; documented rule
    assert by[2]["vulnerability"]["component_type"] == "empirical_history"
    # district 3: one known year only -> vulnerability unavailable, and NOT defaulted to Low
    assert by[3]["vulnerability"] is None
    # a district with no labels at all -> unavailable
    assert by[10]["vulnerability"] is None
    assert env.client.get("/model/metadata").status_code == 503                      # no model trained, none claimed


def _write_rain_and_climatology(env, rain_ids=(1,)):
    days = pd.date_range("2023-07-01", "2023-07-10")
    vals = [0, 5, 50, 0, None, 10, 80, 5, 0, 0]
    rows = [{"district_id": i, "date": d.date().isoformat(), "rainfall_mm": v, "n_stations": 1} for i in rain_ids for d, v in zip(days, vals)]
    pd.DataFrame(rows).to_csv(os.path.join(env.data, "rainfall_daily.csv"), index=False)
    cl = [{"district_id": i, "window_days": 3, "doy": doy, "n_values": 100, "n_years": 28, "q50": 10, "q75": 30, "q90": 60, "q95": 80, "q97": 100, "q99": 140}
          for i in rain_ids for doy in range(150, 260)]
    pd.DataFrame(cl).to_csv(os.path.join(env.data, "climatology.csv"), index=False)
    json.dump({"windows": [3], "level_quantiles": [0.75, 0.9, 0.97], "min_obs_fraction": 0.8}, open(os.path.join(env.data, "hazard_config.json"), "w"))


def test_partial_rainfall_hazard_known_only_where_data_exist_and_combined_follows(env):
    write_districts(env.data)
    write_labels(env.data)
    _write_rain_and_climatology(env, rain_ids=(1, 2, 3))
    seed(env)
    env.CA.main("2023-07-01", "2023-07-10", [3])
    day = {r["district_id"]: r for r in env.client.get("/assessments", params={"window_days": 3, "date": "2023-07-03"}).json()}
    assert len(day) == 33
    d1 = day[1]                                                                       # 0+5+50 = 55 > q75 30, <= q90 60 -> level 1; vulnerability high(2) -> 3 pts -> moderate
    assert d1["status"] == "ok" and d1["hazard"]["level"] == 1 and d1["combined"]["risk_class"] == "moderate" and d1["unavailable_reason"] is None
    assert day[4]["hazard"]["level"] is None and day[4]["combined"]["risk_class"] is None          # no station: unknown, not Low
    # district 3: hazard known, vulnerability unavailable (one known year) -> combined unknown, not Low
    d3 = day[3]
    assert d3["hazard"]["level"] == 1 and d3["vulnerability"] is None and d3["combined"]["risk_class"] is None
    assert d3["status"] == "vulnerability_unavailable" and "no vulnerability" in d3["unavailable_reason"]
    # 07-05 is a gap (NULL, not zero): 3-day windows ending 07-05 have 2 of 3 days -> below 80 % -> unknown with coverage in the reason
    gap = {r["district_id"]: r for r in env.client.get("/assessments", params={"window_days": 3, "date": "2023-07-05"}).json()}[1]
    assert gap["status"] == "insufficient_rainfall_data" and gap["hazard"]["window_rain_mm"] is None
    assert gap["hazard"]["obs_fraction"] == pytest.approx(0.667, abs=1e-3) and "67%" in gap["unavailable_reason"] and "80%" in gap["unavailable_reason"]
    # history gives the frontend its dates even for a district without rain
    assert len(env.client.get("/districts/20/history", params={"window_days": 3}).json()) == 10


def test_insufficient_coverage_never_becomes_a_low_level(env):
    write_districts(env.data)
    _write_rain_and_climatology(env, rain_ids=(1,))
    seed(env)
    env.CA.main("2023-07-01", "2023-07-14", [3])
    for r in env.client.get("/districts/1/history", params={"window_days": 3}).json():
        if r["hazard"]["window_rain_mm"] is None:
            assert r["hazard"]["level"] is None and r["combined"]["risk_class"] is None and r["status"] == "insufficient_rainfall_data"
    late = env.client.get("/districts/1/assessment", params={"window_days": 3, "date": "2023-07-14"}).json()
    assert late["hazard"]["level"] is None and late["hazard"]["obs_fraction"] == 0.0     # beyond the data: unknown, not zero rain


def test_rainfall_coverage_endpoint(env):
    write_districts(env.data)
    _write_rain_and_climatology(env, rain_ids=(1, 2))
    seed(env)
    c = env.client.get("/rainfall/coverage").json()
    assert c["districts"] == 33 and c["districts_with_rainfall"] == 2
    one = c["coverage"][0]
    assert one["days_stored"] == 10 and one["days_observed"] == 9 and one["days_missing"] == 1 and one["has_rainfall"]
    assert c["coverage"][5]["has_rainfall"] is False and "No rainfall" in c["coverage"][5]["reason"]


# ---------------------------------------------------------------- scenario (G) -----------------------------------------------------
def test_scenario_is_labelled_hypothetical_and_not_stored(env):
    write_districts(env.data)
    write_labels(env.data)
    _write_rain_and_climatology(env, rain_ids=(1,))
    seed(env)
    env.CA.main("2023-07-01", "2023-07-10", [3])
    db = env.Session()
    before = db.query(RiskAssessment).count()
    db.close()
    r = env.client.post("/assess", json={"district_id": 1, "window_days": 3, "window_end_date": "2023-07-15", "window_rain_mm": 150}).json()
    assert r["basis"] == "scenario" and r["hazard"]["level"] == 3 and "HYPOTHETICAL" in r["disclaimer"] and "not a forecast" in r["disclaimer"]
    db = env.Session()
    assert db.query(RiskAssessment).count() == before                                 # nothing written
    db.close()
    # a district with no baseline: hazard stays unknown instead of an invented level
    r = env.client.post("/assess", json={"district_id": 9, "window_days": 3, "window_end_date": "2023-07-15", "window_rain_mm": 150}).json()
    assert r["status"] == "no_climatology" and r["hazard"]["level"] is None and r["combined"]["risk_class"] is None and r["unavailable_reason"]


def test_scenario_without_any_hazard_config_does_not_crash(env):
    write_districts(env.data)
    seed(env)
    env.CA.main("2023-07-01", "2023-07-02", [3])
    r = env.client.post("/assess", json={"district_id": 1, "window_days": 3, "window_end_date": "2023-07-15", "window_rain_mm": 50})
    assert r.status_code == 200 and r.json()["status"] == "no_climatology"


# ---------------------------------------------------------------- methodology ------------------------------------------------------------
def test_methodology_endpoint_states_what_is_not_done(env):
    write_districts(env.data)
    write_labels(env.data)
    seed(env)
    m = env.client.get("/methodology").json()
    assert "not a forecast" in m["assessment_type"] and "no daily" in m["assessment_type"]
    assert m["current_data"]["districts"] == 33 and m["current_data"]["model_trained"] is False
    assert set(m["year_notes"]) == {"2019", "2020"}


# ---------------------------------------------------------------- frontend contract (copied from flood_risk_frontend/src/api/types.ts) --
DISTRICT_KEYS = {"id", "name", "state", "geometry", "mean_elevation_m", "elevation_std_m", "mean_slope_deg", "low_lying_frac", "pop_density_km2"}
ASSESSMENT_KEYS = {"district_id", "district_name", "as_of_date", "window_days", "basis", "status", "hazard", "vulnerability", "combined", "disclaimer"}
HAZARD_KEYS = {"component_type", "level", "label", "exceeded", "window_rain_mm", "obs_fraction"}
VULN_KEYS = {"component_type", "risk_class", "expected_index", "proba", "shap_top_features", "model_version"}
COMBINED_KEYS = {"component_type", "risk_class", "risk_score"}
IMPACT_KEYS = {"year", "status", "impact_class", "affected_population", "reporting_period", "caveats"}


def test_response_shapes_match_the_frontend_types(env):
    write_districts(env.data)
    write_labels(env.data)
    _write_rain_and_climatology(env, rain_ids=(1,))
    seed(env)
    env.CA.main("2023-07-01", "2023-07-10", [3])
    c = env.client
    assert DISTRICT_KEYS <= set(c.get("/districts").json()[0])
    w = c.get("/windows").json()
    assert set(w) == {"windows", "meaning"} and w["windows"] == [3]
    a = c.get("/assessments", params={"window_days": 3}).json()[0]
    assert ASSESSMENT_KEYS <= set(a) and HAZARD_KEYS <= set(a["hazard"]) and COMBINED_KEYS <= set(a["combined"])
    withv = next(x for x in c.get("/assessments", params={"window_days": 3}).json() if x["vulnerability"])
    assert VULN_KEYS <= set(withv["vulnerability"])
    assert withv["vulnerability"]["component_type"] in {"ml_estimate", "empirical_history"}
    assert a["basis"] in {"observed_window", "scenario"} and a["status"] in {"ok", "insufficient_rainfall_data", "no_climatology", "vulnerability_unavailable"}
    assert IMPACT_KEYS <= set(c.get("/districts/1/flood-impact").json()[0])
    assert c.get("/districts/1/history", params={"window_days": 3}).status_code == 200
    assert c.get("/districts/1/assessment", params={"window_days": 3}).status_code == 200
    s = c.post("/assess", json={"district_id": 1, "window_days": 3, "window_end_date": "2023-07-15", "window_rain_mm": 10}).json()
    assert ASSESSMENT_KEYS <= set(s)
    assert c.get("/assessments", params={"window_days": 5}).status_code == 422
    assert c.get("/assessments", params={"window_days": 3, "date": "1999-01-01"}).status_code == 404
