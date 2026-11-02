import pandas as pd

from app.models import RainfallDaily, RainfallIMDRecent, RiskAssessment
from scripts.import_imd_rainfall import import_imd_rainfall


def test_imd_import_is_separate_and_repeatable(db, tmp_path):
    db.query(RainfallIMDRecent).delete()
    db.commit()

    historical_count_before = db.query(RainfallDaily).count()
    assessment_count_before = db.query(RiskAssessment).count()

    csv_path = tmp_path / "sample_imd.csv"
    pd.DataFrame([
        {
            "district_id": 1,
            "date": "2026-08-19",
            "rainfall_mm": 12.5,
            "source": "IMD_daily_actual_2026",
        },
        {
            "district_id": 1,
            "date": "2026-08-20",
            "rainfall_mm": 0.0,
            "source": "IMD_daily_actual_2026",
        },
    ]).to_csv(csv_path, index=False)

    first = import_imd_rainfall(db, csv_path)
    second = import_imd_rainfall(db, csv_path)

    assert first["rows"] == 2
    assert first["districts"] == 1
    assert second["rows"] == 2
    assert db.query(RainfallIMDRecent).count() == 2

    assert db.query(RainfallDaily).count() == historical_count_before
    assert db.query(RiskAssessment).count() == assessment_count_before


def test_imd_recent_api_returns_observations(client, db):
    db.query(RainfallIMDRecent).delete()
    db.add(
        RainfallIMDRecent(
            district_id=1,
            date=pd.Timestamp("2026-08-19").date(),
            rainfall_mm=12.5,
            source="IMD_daily_actual_2026",
        )
    )
    db.commit()

    response = client.get("/rainfall/recent", params={"district_id": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_matching"] == 1
    assert payload["returned"] == 1
    assert payload["observations"][0]["district"] == "Test District"
    assert payload["observations"][0]["rainfall_mm"] == 12.5
    assert payload["observations"][0]["source"] == "IMD_daily_actual_2026"

    db.query(RainfallIMDRecent).delete()
    db.commit()


def test_imd_import_rejects_duplicate_district_dates(db, tmp_path):
    csv_path = tmp_path / "duplicate_imd.csv"
    pd.DataFrame([
        {"district_id": 1, "date": "2026-08-19", "rainfall_mm": 12.5},
        {"district_id": 1, "date": "2026-08-19", "rainfall_mm": 13.0},
    ]).to_csv(csv_path, index=False)

    try:
        import_imd_rainfall(db, csv_path)
        assert False, "Expected duplicate district/date validation to fail"
    except ValueError as exc:
        assert "Duplicate district_id/date" in str(exc)
