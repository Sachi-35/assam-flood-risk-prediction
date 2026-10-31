import json
import os
import sys
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "test_flood_risk.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Climatology, District, Meta, NormalSeason, RainfallDaily  # noqa: E402

engine = create_engine(os.environ["DATABASE_URL"], connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

HAZARD_CFG = {"windows": [3, 7], "level_quantiles": [0.75, 0.9, 0.97], "min_obs_fraction": 0.8,
              "baseline_years": [1991, 2018], "doy_halfwidth": 15}
# Hand-written plumbing fixtures (NOT training data): constant baseline quantiles so levels are easy to reason about.
Q = {3: dict(q50=10, q75=30, q90=60, q95=80, q97=100, q99=140), 7: dict(q50=20, q75=60, q90=120, q95=150, q97=180, q99=250)}
RAIN = {date(2023, 7, 1) + timedelta(days=i): v for i, v in enumerate([0, 5, 50, 0, None, 10, 80, 5, 0, 0]) if v is not None}
GAP = date(2023, 7, 5)                     # 07-05 has NO row: missing, not zero


def pytest_sessionfinish(session, exitstatus):
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    poly = {"type": "Polygon", "coordinates": [[[94.0, 27.0], [94.1, 27.0], [94.1, 27.1], [94.0, 27.1], [94.0, 27.0]]]}
    db.add(District(id=1, name="Test District", state="Assam", geometry=json.dumps(poly), mean_elevation_m=100.0, elevation_std_m=10.0,
                    mean_slope_deg=2.0, low_lying_frac=0.4, pop_density_km2=350.0))
    for d, v in RAIN.items():
        db.add(RainfallDaily(district_id=1, date=d, rainfall_mm=v, n_stations=1))
    for w, q in Q.items():
        for doy in range(150, 260):
            db.add(Climatology(district_id=1, window_days=w, doy=doy, n_values=500, **q))
    db.add(NormalSeason(district_id=1, features={"season_total_mm": 900.0, "season_anomaly_pct": 0.0}))
    db.add(Meta(key="hazard_config", value=HAZARD_CFG))
    db.commit()
    db.close()
    yield


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    s = TestingSessionLocal()
    yield s
    s.close()
