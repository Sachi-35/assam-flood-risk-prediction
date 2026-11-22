"""API validation: unknown ids -> 404, bad ranges/parameters -> 422, limits, error body shape. Temporary database only."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.api_fixtures import build_db, use_engine


@pytest.fixture
def client(tmp_path):
    eng = build_db(tmp_path / "api.db", n_districts=3, days=5)
    with use_engine(eng):
        yield TestClient(app)
    eng.dispose()


def detail(r):
    body = r.json()
    assert "detail" in body, body                               # the frontend client reads {"detail": ...} on every error
    return body["detail"]


# ------------------------------------------------------------------------------------------- unknown districts -> 404 ---------
@pytest.mark.parametrize("method,url,kw", [
    ("get", "/districts/99/assessment", {"params": {"window_days": 3}}),
    ("get", "/districts/99/history", {"params": {"window_days": 3}}),
    ("get", "/districts/99/flood-impact", {}),
    ("get", "/rainfall/recent", {"params": {"district_id": 99}}),
    ("get", "/rainfall/combined", {"params": {"district_id": 99}}),
    ("post", "/assess", {"json": {"district_id": 99, "window_days": 3, "window_end_date": "2023-07-15", "window_rain_mm": 10}}),
])
def test_unknown_district_is_404_with_a_clear_message(client, method, url, kw):
    r = getattr(client, method)(url, **kw)
    assert r.status_code == 404 and "district" in detail(r).lower()


def test_known_district_without_data_is_still_404_but_says_so(client):
    r = client.get("/districts/3/assessment", params={"window_days": 3, "date": "1999-01-01"})
    assert r.status_code == 404 and "No assessment" in detail(r)
    assert client.get("/districts/3/flood-impact").json() == []               # known district without labels: empty list, not 404


def test_non_integer_district_id_is_422(client):
    assert client.get("/districts/abc/assessment", params={"window_days": 3}).status_code == 422


# ------------------------------------------------------------------------------------------- invalid ranges -> 422 -------------
def test_history_start_after_end_is_422(client):
    r = client.get("/districts/1/history", params={"window_days": 3, "start": "2023-07-05", "end": "2023-07-01"})
    assert r.status_code == 422 and "start" in detail(r) and "end" in detail(r)


def test_history_same_day_range_is_valid(client):
    r = client.get("/districts/1/history", params={"window_days": 3, "start": "2023-07-03", "end": "2023-07-03"})
    assert r.status_code == 200 and [x["as_of_date"] for x in r.json()] == ["2023-07-03"]



def test_combined_rainfall_date_range_validation(client):
    assert client.get("/rainfall/combined", params={"start": "2026-09-01", "end": "2026-08-01"}).status_code == 422
    assert client.get("/rainfall/combined", params={"start": "2018-12-31"}).status_code == 422
    assert client.get("/rainfall/combined", params={"end": "2026-11-02"}).status_code == 422
    assert client.get("/rainfall/combined", params={"start": "2026-11-01", "end": "2026-11-01"}).status_code == 200


def test_combined_rainfall_limit_bounds(client):
    assert client.get("/rainfall/combined", params={"limit": 50000}).status_code == 200
    for bad in ("0", "50001", "-1", "x"):
        assert client.get("/rainfall/combined", params={"limit": bad}).status_code == 422

def test_recent_rainfall_start_after_end_is_422(client):
    assert client.get("/rainfall/recent", params={"start": "2026-09-01", "end": "2026-08-01"}).status_code == 422
    assert client.get("/rainfall/recent", params={"start": "2026-08-19", "end": "2026-08-19"}).status_code == 200


# ------------------------------------------------------------------------------------------- query parameters ------------------
@pytest.mark.parametrize("window", ["0", "-3", "367", "abc", "3.5", ""])
def test_bad_window_days_is_422(client, window):
    for url in ("/assessments", "/districts/1/assessment", "/districts/1/history"):
        assert client.get(url, params={"window_days": window}).status_code == 422, (url, window)


def test_window_not_configured_is_422_and_lists_valid_windows(client):
    r = client.get("/assessments", params={"window_days": 5})
    assert r.status_code == 422 and "[3, 7]" in detail(r)


def test_missing_window_days_is_422(client):
    assert client.get("/assessments").status_code == 422


@pytest.mark.parametrize("bad", ["2023-13-45", "yesterday", "2023/07/01", "20230701x"])
def test_bad_dates_are_422(client, bad):
    assert client.get("/assessments", params={"window_days": 3, "date": bad}).status_code == 422
    assert client.get("/districts/1/history", params={"window_days": 3, "start": bad}).status_code == 422
    assert client.get("/rainfall/recent", params={"end": bad}).status_code == 422


def test_scenario_body_validation(client):
    ok = {"district_id": 1, "window_days": 3, "window_end_date": "2023-07-15", "window_rain_mm": 100}
    assert client.post("/assess", json=ok).status_code == 200
    for patch in ({"window_rain_mm": -1}, {"window_rain_mm": 2001}, {"window_days": 0}, {"window_days": 5}, {"window_end_date": "nope"},
                  {"district_id": "x"}, {"window_rain_mm": "lots"}):
        assert client.post("/assess", json={**ok, **patch}).status_code == 422, patch
    assert client.post("/assess", json={k: v for k, v in ok.items() if k != "window_rain_mm"}).status_code == 422
    assert client.post("/assess", content=b"not json", headers={"Content-Type": "application/json"}).status_code == 422


# ------------------------------------------------------------------------------------------- limits -------------------------------
def test_history_limit_truncates_oldest_first_and_says_so(client):
    r = client.get("/districts/1/history", params={"window_days": 3, "limit": 2})
    assert r.status_code == 200 and [x["as_of_date"] for x in r.json()] == ["2023-07-01", "2023-07-02"]
    assert r.headers["X-Total-Count"] == "5" and r.headers["X-Result-Truncated"] == "true"
    full = client.get("/districts/1/history", params={"window_days": 3})
    assert len(full.json()) == 5 and full.headers["X-Total-Count"] == "5" and "X-Result-Truncated" not in full.headers


@pytest.mark.parametrize("limit", ["0", "-1", "3661", "x"])
def test_history_limit_bounds(client, limit):
    assert client.get("/districts/1/history", params={"window_days": 3, "limit": limit}).status_code == 422


def test_recent_rainfall_limit_bounds_keep_the_frontend_value_valid(client):
    assert client.get("/rainfall/recent", params={"limit": 10000}).status_code == 200      # the frontend client asks for 10000
    for bad in ("0", "10001", "-5", "x"):
        assert client.get("/rainfall/recent", params={"limit": bad}).status_code == 422
    body = client.get("/rainfall/recent", params={"limit": 2}).json()
    assert body["returned"] == 2 and body["total_matching"] == 3 and body["limit"] == 2


# ------------------------------------------------------------------------------------------- unchanged valid behaviour ----------
def test_valid_requests_still_work_and_nothing_computed_is_404(client):
    assert client.get("/assessments", params={"window_days": 3}).status_code == 200
    assert client.get("/assessments", params={"window_days": 3, "date": "1999-01-01"}).status_code == 404
    r = client.get("/districts/1/assessment", params={"window_days": 3})
    assert r.status_code == 200 and r.json()["as_of_date"] == "2023-07-05"                 # latest when no date is given


def test_empty_assessment_table_is_404_with_guidance(tmp_path):
    from sqlalchemy.orm import sessionmaker
    from app.models import RiskAssessment
    eng = build_db(tmp_path / "e.db")
    s = sessionmaker(bind=eng)()
    s.query(RiskAssessment).delete()
    s.commit()
    s.close()
    with use_engine(eng):
        r = TestClient(app).get("/assessments", params={"window_days": 3})
    assert r.status_code == 404 and "assess" in detail(r)
    eng.dispose()
