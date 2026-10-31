import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from app.models import Meta  # noqa: E402


@pytest.fixture(scope="module")
def computed(_setup_db):
    """Run the real batch job with the 'district_history' vulnerability path (no model needed)."""
    import compute_assessments as CA
    from app.services import model_loader
    from tests.conftest import TestingSessionLocal  # noqa: F401
    orig = CA.read_metadata
    CA.read_metadata = lambda: {"vulnerability_source": "district_history", "district_history": {"1": 1.0}, "model_version": "hist"}
    CA.get_model_bundle = lambda: None
    try:
        CA.main("2023-07-01", "2023-07-13", [3, 7])
    finally:
        CA.read_metadata = orig
    yield


def test_health_and_windows(client, computed):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/windows").json()["windows"] == [3, 7]


def test_assessment_values(client, computed):
    r = client.get("/districts/1/assessment", params={"window_days": 3, "date": "2023-07-03"}).json()
    # days 07-01..07-03 = 0+5+50 = 55 mm; q75=30 < 55 <= q90=60  -> level 1 (Moderate)
    assert r["hazard"]["window_rain_mm"] == 55.0 and r["hazard"]["level"] == 1 and r["hazard"]["component_type"] == "rule_based"
    assert r["vulnerability"]["component_type"] == "empirical_history" and r["vulnerability"]["risk_class"] == "moderate"
    assert r["combined"]["risk_class"] == "moderate" and r["basis"] == "observed_window" and "Not a forecast" in r["disclaimer"]


def test_missing_rainfall_gives_unknown_not_low(client, computed):
    r = client.get("/districts/1/assessment", params={"window_days": 3, "date": "2023-07-05"}).json()   # 07-05 has no row: 2 of 3 days observed < 80 %
    assert r["status"] == "insufficient_rainfall_data" and r["hazard"]["level"] is None and r["combined"]["risk_class"] is None
    assert r["hazard"]["window_rain_mm"] is None


def test_list_default_latest_and_unknown_window(client, computed):
    r = client.get("/assessments", params={"window_days": 7}).json()
    assert len(r) == 1 and r[0]["as_of_date"] == "2023-07-10"   # last day with rainfall data
    assert client.get("/assessments", params={"window_days": 5}).status_code == 422
    assert client.get("/assessments", params={"window_days": 7, "date": "1999-01-01"}).status_code == 404


def test_history_range(client, computed):
    h = client.get("/districts/1/history", params={"window_days": 3, "start": "2023-07-03", "end": "2023-07-07"}).json()
    assert [x["as_of_date"] for x in h] == ["2023-07-03", "2023-07-04", "2023-07-05", "2023-07-06", "2023-07-07"]


def test_scenario(client, computed):
    r = client.post("/assess", json={"district_id": 1, "window_days": 3, "window_end_date": "2023-07-15", "window_rain_mm": 150}).json()
    assert r["basis"] == "scenario" and r["hazard"]["level"] == 3 and r["combined"]["risk_class"] == "high"   # vulnerability index 1 + hazard 3 = 4 -> High


def test_model_metadata_503_when_untrained(client):
    r = client.get("/model/metadata")
    assert r.status_code == 503 and "train_model.py" in r.json()["detail"]
