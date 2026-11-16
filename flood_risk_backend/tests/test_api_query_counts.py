"""Query behaviour: the number of SQL statements per request must NOT grow with the number of rows returned (no N+1).

Before this change every returned assessment cost ~3 extra queries (hazard config twice + vulnerability), and the name lookup loaded every
district's full boundary geometry. Temporary databases only.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.main import app
from tests.api_fixtures import build_db, use_engine

MAX_STATEMENTS = 14           # generous ceiling for one request; the real number is far lower and, above all, constant


def count_statements(engine, fn):
    seen = []

    def before(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)
    event.listen(engine, "before_cursor_execute", before)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", before)
    return seen, result


def call(engine, method, url, **kw):
    with use_engine(engine):
        client = TestClient(app)
        return count_statements(engine, lambda: getattr(client, method)(url, **kw))


def test_assessments_list_statement_count_is_independent_of_district_count(tmp_path):
    small, big = build_db(tmp_path / "s.db", n_districts=3, days=5), build_db(tmp_path / "b.db", n_districts=33, days=5)
    s_stmts, s_resp = call(small, "get", "/assessments", params={"window_days": 3, "date": "2023-07-05"})
    b_stmts, b_resp = call(big, "get", "/assessments", params={"window_days": 3, "date": "2023-07-05"})
    assert s_resp.status_code == b_resp.status_code == 200 and len(s_resp.json()) == 3 and len(b_resp.json()) == 33
    assert len(b_stmts) == len(s_stmts) <= MAX_STATEMENTS, (len(s_stmts), len(b_stmts))
    small.dispose(), big.dispose()


def test_history_statement_count_is_independent_of_row_count(tmp_path):
    few, many = build_db(tmp_path / "f.db", n_districts=3, days=5), build_db(tmp_path / "m.db", n_districts=3, days=300)
    f_stmts, f_resp = call(few, "get", "/districts/1/history", params={"window_days": 3})
    m_stmts, m_resp = call(many, "get", "/districts/1/history", params={"window_days": 3})
    assert len(f_resp.json()) == 5 and len(m_resp.json()) == 300
    assert len(m_stmts) == len(f_stmts) <= MAX_STATEMENTS, (len(f_stmts), len(m_stmts))
    few.dispose(), many.dispose()


def test_name_lookups_do_not_load_district_geometry(tmp_path):
    eng = build_db(tmp_path / "g.db", n_districts=5, days=3)
    for url, kw in (("/assessments", {"params": {"window_days": 3}}), ("/districts/1/history", {"params": {"window_days": 3}}),
                    ("/districts/1/assessment", {"params": {"window_days": 3}}), ("/rainfall/coverage", {})):
        stmts, r = call(eng, "get", url, **kw)
        assert r.status_code == 200, url
        assert not any("districts.geometry" in s for s in stmts), f"{url} loads boundary geometry just to read names"
    eng.dispose()


def test_scenario_and_single_assessment_have_a_small_constant_cost(tmp_path):
    eng = build_db(tmp_path / "c.db", n_districts=33, days=30)
    stmts, r = call(eng, "get", "/districts/1/assessment", params={"window_days": 7})
    assert r.status_code == 200 and len(stmts) <= MAX_STATEMENTS
    stmts, r = call(eng, "post", "/assess", json={"district_id": 1, "window_days": 3, "window_end_date": "2023-07-15", "window_rain_mm": 90})
    assert r.status_code == 200 and len(stmts) <= MAX_STATEMENTS
    eng.dispose()


def test_results_are_identical_whatever_the_loading_strategy(tmp_path):
    """The optimisation must not change any value: spot-check the joined fields against the stored rows."""
    eng = build_db(tmp_path / "v.db", n_districts=4, days=5)
    with use_engine(eng):
        rows = TestClient(app).get("/assessments", params={"window_days": 3, "date": "2023-07-05"}).json()
    by = {r["district_id"]: r for r in rows}
    assert by[1]["district_name"] == "District 1" and by[1]["vulnerability"]["component_type"] == "ml_estimate"
    assert by[2]["vulnerability"]["risk_class"] == "moderate" and by[4]["vulnerability"] is None
    assert by[1]["status"] == "ok" and by[1]["hazard"]["window_rain_mm"] == 55.0 and by[1]["combined"]["risk_class"] == "high"
    assert by[1]["unavailable_reason"] is None and "No rainfall observations" in by[2]["unavailable_reason"]
    eng.dispose()
