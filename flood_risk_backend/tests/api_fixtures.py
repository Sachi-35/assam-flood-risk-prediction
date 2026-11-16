"""Shared helpers for the API tests: a temporary multi-district SQLite database and a dependency override that points the app at it.

Every database here is a temporary file; the conftest test database and any real database are never touched.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import (Climatology, District, FloodLabel, Meta, RainfallDaily, RainfallIMDRecent, RiskAssessment,
                        Vulnerability)

POLY = {"type": "Polygon", "coordinates": [[[94.0, 27.0], [94.1, 27.0], [94.1, 27.1], [94.0, 27.1], [94.0, 27.0]]]}
HAZARD_CFG = {"windows": [3, 7], "level_quantiles": [0.75, 0.9, 0.97], "min_obs_fraction": 0.8}
Q = {3: dict(q50=10, q75=30, q90=60, q95=80, q97=100, q99=140), 7: dict(q50=20, q75=60, q90=120, q95=150, q97=180, q99=250)}
START = date(2023, 7, 1)
RAIN = [0, 5, 50, 0, None, 10, 80, 5, 0, 0]


def make_engine(path):
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


def build_db(path, n_districts=3, days=5, with_data=True):
    """Tables + data. District 1 has rainfall, climatology, an ML-style vulnerability, labels and IMD rows; the LAST district has no vulnerability."""
    eng = make_engine(path)
    Base.metadata.create_all(bind=eng)
    if not with_data:
        return eng
    s = sessionmaker(bind=eng)()
    s.add_all([District(id=i, name=f"District {i}", state="Assam", geometry=json.dumps(POLY), mean_elevation_m=100.0, elevation_std_m=10.0,
                        mean_slope_deg=2.0, low_lying_frac=0.4, pop_density_km2=None) for i in range(1, n_districts + 1)])
    s.add(Meta(key="hazard_config", value=HAZARD_CFG))
    for i, v in enumerate(RAIN):
        if v is not None:
            s.add(RainfallDaily(district_id=1, date=START + timedelta(days=i), rainfall_mm=float(v), n_stations=1))
    for w, q in Q.items():
        s.add_all([Climatology(district_id=1, window_days=w, doy=doy, n_values=500, **q) for doy in range(150, 260)])
    s.add(Vulnerability(district_id=1, source="ml_model", risk_class="high", class_index=2, expected_index=2.2,
                        proba={"low": 0.1, "moderate": 0.2, "high": 0.6, "severe": 0.1}, model_version="test-v1",
                        shap_top_features=[{"feature_name": "x", "contribution_value": 0.1, "direction": "increases_risk"}]))
    for d in range(2, n_districts):
        s.add(Vulnerability(district_id=d, source="district_history", risk_class="moderate", class_index=1, expected_index=1.0))
    rows = []
    for d in range(1, n_districts + 1):
        for w in (3, 7):
            for k in range(days):
                ok = d == 1 and k >= w
                rows.append(dict(district_id=d, as_of_date=START + timedelta(days=k), window_days=w,
                                 window_rain_mm=55.0 if ok else None, obs_fraction=1.0 if ok else (0.0 if d != 1 else 0.5),
                                 hazard_level=1 if ok else None, status="ok" if ok else "insufficient_rainfall_data",
                                 combined_class="high" if ok else None, combined_score=0.5 if ok else None, model_version=None))
    s.bulk_insert_mappings(RiskAssessment, rows)
    s.add(FloodLabel(district_id=1, year=2021, status="reported", impact_class="high", affected_population=1000.0,
                     reporting_period="1 Jun - 18 Sep", caveats=["class only"]))
    s.add(FloodLabel(district_id=1, year=2022, status="unknown"))
    s.add_all([RainfallIMDRecent(district_id=1, date=date(2026, 8, 19) + timedelta(days=i), rainfall_mm=1.5 * i, source="IMD_daily_actual_2026") for i in range(3)])
    s.commit()
    s.close()
    return eng


@contextmanager
def use_engine(engine):
    """Point the app's get_db dependency at `engine`, then restore whatever override was there before."""
    SL = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _get_db():
        db = SL()
        try:
            yield db
        finally:
            db.close()
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _get_db
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


def table_names(path):
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    finally:
        con.close()
