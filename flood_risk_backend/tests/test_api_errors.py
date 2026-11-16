"""Reliability: missing tables -> 503 (never auto-created), database errors, unexpected errors, startup checks, logging.
Temporary databases only."""
import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api.routes import assessments
from app.main import app
from app.services import db_health
from tests.api_fixtures import build_db, make_engine, table_names, use_engine


@pytest.fixture
def empty_db(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()                                # a database file with NO tables
    eng = make_engine(path)
    with use_engine(eng):
        yield TestClient(app), str(path), eng
    eng.dispose()


# ------------------------------------------------------------------------------------------- missing tables -> 503 -------------
@pytest.mark.parametrize("method,url,kw", [
    ("get", "/districts", {}),
    ("get", "/windows", {}),
    ("get", "/assessments", {"params": {"window_days": 3}}),
    ("get", "/districts/1/assessment", {"params": {"window_days": 3}}),
    ("get", "/districts/1/flood-impact", {}),
    ("get", "/rainfall/coverage", {}),
    ("get", "/rainfall/recent", {}),
    ("get", "/methodology", {}),
])
def test_missing_tables_give_503_with_guidance(empty_db, method, url, kw):
    client, path, _ = empty_db
    r = getattr(client, method)(url, **kw)
    assert r.status_code == 503, (url, r.status_code, r.text)
    body = r.json()
    assert "not initialised" in body["detail"] and "seed_db.py" in body["detail"] and body["missing_tables"]


def test_api_never_creates_tables_even_when_asked_repeatedly(empty_db):
    client, path, _ = empty_db
    for _ in range(3):
        client.get("/districts")
        client.get("/health/ready")
    assert table_names(path) == set()


def test_liveness_stays_ok_and_readiness_lists_missing_tables(empty_db):
    client, _, _ = empty_db
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready" and set(body["missing_tables"]) == set(db_health.required_tables())


def test_partly_missing_tables_only_break_the_endpoints_that_need_them(tmp_path):
    eng = build_db(tmp_path / "p.db")
    with eng.begin() as c:
        c.execute(text("DROP TABLE risk_assessments"))
    with use_engine(eng):
        client = TestClient(app)
        assert client.get("/districts").status_code == 200
        r = client.get("/assessments", params={"window_days": 3})
        assert r.status_code == 503 and "risk_assessments" in r.json()["detail"]
        ready = client.get("/health/ready")
        assert ready.status_code == 503 and ready.json()["missing_tables"] == ["risk_assessments"]
    eng.dispose()


def test_complete_database_is_ready(tmp_path):
    eng = build_db(tmp_path / "ok.db", with_data=False)
    with use_engine(eng):
        r = TestClient(app).get("/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["tables"] == len(db_health.required_tables())
    eng.dispose()


def test_missing_table_error_parsing():
    assert db_health.missing_table_names(Exception("(sqlite3.OperationalError) no such table: risk_assessments")) == ["risk_assessments"]
    assert db_health.missing_table_names(Exception('relation "districts" does not exist')) == ["districts"]
    assert db_health.missing_table_names(Exception("database is locked")) == []


# ------------------------------------------------------------------------------------------- other failures --------------------
def test_locked_or_unreachable_database_is_503_without_leaking_details(tmp_path, monkeypatch, caplog):
    eng = build_db(tmp_path / "l.db")
    monkeypatch.setattr(assessments, "available_windows", lambda db: (_ for _ in ()).throw(
        OperationalError("SELECT secret", {"p": "x"}, Exception("database is locked"))))
    with use_engine(eng), caplog.at_level(logging.ERROR, logger="flood_api"):
        r = TestClient(app).get("/windows")
    assert r.status_code == 503 and "temporarily unavailable" in r.json()["detail"]
    assert "secret" not in r.text and "locked" not in r.text            # SQL text and driver message stay in the log only
    assert any("503" in rec.getMessage() for rec in caplog.records)
    eng.dispose()


def test_other_database_errors_are_500_json(tmp_path, monkeypatch, caplog):
    eng = build_db(tmp_path / "d.db")
    monkeypatch.setattr(assessments, "available_windows", lambda db: (_ for _ in ()).throw(SQLAlchemyError("boom with internals")))
    with use_engine(eng), caplog.at_level(logging.ERROR, logger="flood_api"):
        r = TestClient(app).get("/windows")
    assert r.status_code == 500 and r.json() == {"detail": "Internal database error."}
    assert "internals" not in r.text and any(rec.levelno >= logging.ERROR for rec in caplog.records)
    eng.dispose()


def test_unexpected_exceptions_are_500_json_and_logged(tmp_path, monkeypatch, caplog):
    eng = build_db(tmp_path / "u.db")
    monkeypatch.setattr(assessments, "available_windows", lambda db: 1 / 0)
    with use_engine(eng), caplog.at_level(logging.ERROR, logger="flood_api"):
        r = TestClient(app, raise_server_exceptions=False).get("/windows")
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error."}
    assert "ZeroDivision" not in r.text
    assert any("unexpected error" in rec.getMessage() for rec in caplog.records)
    eng.dispose()


def test_http_errors_are_not_turned_into_500(tmp_path):
    eng = build_db(tmp_path / "h.db")
    with use_engine(eng):
        c = TestClient(app, raise_server_exceptions=False)
        assert c.get("/districts/99/flood-impact").status_code == 404
        assert c.get("/no-such-route").status_code == 404
        assert c.get("/assessments", params={"window_days": 99}).status_code == 422
    eng.dispose()


# ------------------------------------------------------------------------------------------- model metadata robustness ----------
def test_corrupt_model_metadata_is_503_for_the_model_route_and_ignored_by_methodology(tmp_path, monkeypatch):
    from app.config import settings
    bad = tmp_path / "metadata.json"
    bad.write_text("{not json")
    monkeypatch.setattr(settings, "MODEL_METADATA_PATH", str(bad))
    eng = build_db(tmp_path / "m.db")
    with use_engine(eng):
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/model/metadata")
        assert r.status_code == 503 and "cannot be read" in r.json()["detail"]
        m = c.get("/methodology")
        assert m.status_code == 200 and m.json()["current_data"]["model_trained"] is False
        bad.write_text('{"model_version": "v1"}')                      # valid JSON, wrong structure
        assert c.get("/model/metadata").status_code == 503
    eng.dispose()


# ------------------------------------------------------------------------------------------- startup checks / logging ------------
def test_startup_check_reports_missing_tables_and_creates_nothing(empty_db, caplog):
    _, path, eng = empty_db
    with caplog.at_level(logging.INFO, logger="flood_api.db"):
        r = db_health.startup_check(eng)
    assert r["ok"] is False and r["reachable"] is True and set(r["missing_tables"]) == set(db_health.required_tables())
    assert any(rec.levelno == logging.ERROR and "missing required table" in rec.getMessage() for rec in caplog.records)
    assert table_names(path) == set()


def test_startup_check_with_missing_database_file_does_not_create_it(tmp_path, caplog):
    path = tmp_path / "does_not_exist.db"
    eng = make_engine(path)
    with caplog.at_level(logging.INFO, logger="flood_api.db"):
        r = db_health.startup_check(eng)
    assert r["ok"] is False and r["reachable"] is False and not path.exists()
    assert any("does not exist" in rec.getMessage() for rec in caplog.records)
    eng.dispose()


def test_startup_check_ok_on_complete_database(tmp_path, caplog):
    eng = build_db(tmp_path / "ok.db", with_data=False)
    with caplog.at_level(logging.INFO, logger="flood_api.db"):
        r = db_health.startup_check(eng)
    assert r == {"ok": True, "reachable": True, "missing_tables": [], "error": None}
    assert any("OK" in rec.getMessage() for rec in caplog.records)
    eng.dispose()


def test_application_starts_even_when_the_database_is_not_ready(caplog):
    """Lifespan runs the check, logs, and does not raise or create anything (the app's own engine is the conftest test database)."""
    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
    assert any("Starting" in rec.getMessage() for rec in caplog.records)
