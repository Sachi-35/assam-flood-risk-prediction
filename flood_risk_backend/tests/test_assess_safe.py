"""Database tests for scripts/assess_safe.py. Every test builds its OWN temporary SQLite file (tmp_path); the app/real database is never used."""
import hashlib
import json
import os
import sqlite3
import sys
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from app.database import Base  # noqa: E402
from app.models import Climatology, District, FloodLabel, Meta, RainfallDaily, RiskAssessment, Vulnerability  # noqa: E402
import assess_safe as A  # noqa: E402

POLY = json.dumps({"type": "Polygon", "coordinates": [[[94.0, 27.0], [94.1, 27.0], [94.1, 27.1], [94.0, 27.1], [94.0, 27.0]]]})
Q = {3: dict(q50=10, q75=30, q90=60, q95=80, q97=100, q99=140), 7: dict(q50=20, q75=60, q90=120, q95=150, q97=180, q99=250)}
RAIN = [0, 5, 50, 0, None, 10, 80, 5, 0, 0]
START, END = "2023-07-01", "2023-07-10"      # 3 districts x 10 days x 2 windows = 60 planned rows
TABLES = ("risk_assessments", "vulnerabilities", "rainfall_daily", "climatology", "flood_labels", "districts", "meta")


def make_db(tmp_path, name="t.db"):
    path = str(tmp_path / name)
    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=eng)
    SL = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    db = SL()
    for i in (1, 2, 3):
        db.add(District(id=i, name=f"D{i}", state="Assam", geometry=POLY))
    for i, v in enumerate(RAIN):                              # d1 and d2 have rain (07-05 is a gap), d3 has none
        for d in (1, 2):
            db.add(RainfallDaily(district_id=d, date=date(2023, 7, 1) + timedelta(days=i), rainfall_mm=v, n_stations=1))
    for w, q in Q.items():                                    # climatology only for d1: d2 -> no_climatology
        for doy in range(150, 260):
            db.add(Climatology(district_id=1, window_days=w, doy=doy, n_values=500, **q))
    db.add(Meta(key="hazard_config", value={"windows": [3, 7], "level_quantiles": [0.75, 0.9, 0.97], "min_obs_fraction": 0.8}))
    for y, c in ((2020, "moderate"), (2021, "high"), (2022, "high")):    # d1: 3 known years -> history vulnerability
        db.add(FloodLabel(district_id=1, year=y, status="reported", impact_class=c))
    db.add(FloodLabel(district_id=2, year=2021, status="reported", impact_class="low"))   # d2: 1 known year -> unavailable
    db.commit()
    return path, SL, db


def snap(path):
    con = sqlite3.connect(path)
    out = {t: con.execute(f"SELECT * FROM {t} ORDER BY 1,2,3" if t not in ("meta",) else f"SELECT * FROM {t}").fetchall() for t in TABLES}
    con.close()
    return out


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def run(db, **kw):
    return A.run_assessment(db, kw.pop("start", START), kw.pop("end", END), kw.pop("windows", [3, 7]), out=lambda *_: None, **kw)


def test_dry_run_is_default_and_modifies_nothing(tmp_path):
    path, SL, db = make_db(tmp_path)
    before, h = snap(path), sha(path)
    s = run(db, refresh_vulnerability=True)               # apply not given
    db.close()
    assert s["applied"] is False and s["inserted"] == 60 and s["updated"] == 0
    assert snap(path) == before and sha(path) == h
    assert A.main(["--database", path, "--start", START, "--end", END, "--no-backup"]) == 0     # CLI default is also a dry-run
    assert snap(path) == before and sha(path) == h


def test_apply_inserts_expected_rows_without_touching_vulnerability(tmp_path):
    path, SL, db = make_db(tmp_path)
    s = run(db, apply=True)
    assert s["applied"] and s["inserted"] == 60
    rows = db.query(RiskAssessment).all()
    assert len(rows) == 60 and db.query(Vulnerability).count() == 0           # no --refresh-vulnerability: table untouched
    by = {(r.district_id, r.as_of_date, r.window_days): r for r in rows}
    r = by[(1, date(2023, 7, 8), 3)]                                           # 07-06..07-08 = 10+80+5 = 95: above q90 (60), below q97 (100) -> level 2
    assert r.window_rain_mm == 95.0 and r.hazard_level == 2 and r.status == "vulnerability_unavailable" and r.combined_class is None
    gap = by[(1, date(2023, 7, 7), 3)]                                         # 07-05 is a gap: only 2 of 3 days observed (< 80%) -> Unknown, not 90, not 0
    assert gap.window_rain_mm is None and gap.hazard_level is None and gap.status == "insufficient_rainfall_data"
    assert by[(2, date(2023, 7, 8), 3)].status == "no_climatology" and by[(2, date(2023, 7, 8), 3)].hazard_level is None
    assert by[(3, date(2023, 7, 8), 3)].status == "insufficient_rainfall_data" and by[(3, date(2023, 7, 8), 3)].window_rain_mm is None
    db.close()


def test_refresh_vulnerability_only_when_requested(tmp_path):
    path, SL, db = make_db(tmp_path)
    db.add(Vulnerability(district_id=3, source="district_history", risk_class="low", class_index=0, expected_index=0.0))
    db.commit()
    run(db, apply=True)
    assert [v.district_id for v in db.query(Vulnerability).all()] == [3]       # stored row preserved, nothing recomputed
    run(db, apply=True, refresh_vulnerability=True)
    v = {x.district_id: x for x in db.query(Vulnerability).all()}
    assert set(v) == {1} and v[1].source == "district_history" and v[1].risk_class == "high" and abs(v[1].expected_index - 1.6667) < 1e-3
    r = db.query(RiskAssessment).filter_by(district_id=1, as_of_date=date(2023, 7, 8), window_days=3).one()
    assert r.status == "ok" and r.combined_class == "high" and r.model_version is None        # vulnerability index 2 + hazard 2 = 4 -> high
    assert abs(r.combined_score - 0.6111) < 1e-3
    db.close()


def test_repeated_execution_is_idempotent(tmp_path):
    path, SL, db = make_db(tmp_path)
    run(db, apply=True, refresh_vulnerability=True)
    first = snap(path)
    s = run(db, apply=True, refresh_vulnerability=True)
    assert (s["inserted"], s["updated"], s["unchanged"]) == (0, 0, 60)
    assert snap(path) == first                                                  # same rows, same ids, no duplicates
    db.close()


def test_records_outside_range_and_windows_are_unchanged(tmp_path):
    path, SL, db = make_db(tmp_path)
    db.add_all([
        RiskAssessment(district_id=1, as_of_date=date(2020, 1, 1), window_days=3, status="ok", hazard_level=1, window_rain_mm=12.3, obs_fraction=1.0, combined_class="low", combined_score=0.2),
        RiskAssessment(district_id=1, as_of_date=date(2023, 7, 5), window_days=15, status="ok", hazard_level=2, window_rain_mm=1.0, obs_fraction=1.0),   # in range, window not requested
        RiskAssessment(district_id=1, as_of_date=date(2023, 8, 1), window_days=7, status="insufficient_rainfall_data"),
    ])
    db.commit()
    outside = [(r.id, r.district_id, r.as_of_date, r.window_days, r.status, r.hazard_level, r.window_rain_mm) for r in db.query(RiskAssessment).all()]
    run(db, apply=True, refresh_vulnerability=True)
    run(db, apply=True, replace_range=True, confirm_replace_range=True)
    now = {(r.id, r.district_id, r.as_of_date, r.window_days, r.status, r.hazard_level, r.window_rain_mm) for r in db.query(RiskAssessment).all()}
    assert set(outside) <= now and db.query(RiskAssessment).count() == 63
    db.close()


def test_upsert_corrects_drifted_row_and_keeps_its_id(tmp_path):
    path, SL, db = make_db(tmp_path)
    run(db, apply=True)
    r = db.query(RiskAssessment).filter_by(district_id=1, as_of_date=date(2023, 7, 8), window_days=3).one()
    rid, good = r.id, r.hazard_level
    r.hazard_level = 0
    db.commit()
    s = run(db, apply=True)
    assert (s["inserted"], s["updated"], s["unchanged"]) == (0, 1, 59)
    r2 = db.query(RiskAssessment).filter_by(district_id=1, as_of_date=date(2023, 7, 8), window_days=3).one()
    db.refresh(r2)
    assert r2.id == rid and r2.hazard_level == good and db.query(RiskAssessment).count() == 60
    db.close()


def test_replace_range_requires_confirmation(tmp_path):
    path, SL, db = make_db(tmp_path)
    db.add(RiskAssessment(district_id=99, as_of_date=date(2023, 7, 3), window_days=3, status="ok"))     # stale row inside the range
    db.commit()
    before = snap(path)
    with pytest.raises(A.Refused):
        run(db, apply=True, replace_range=True)                                  # no confirmation: refused before any write
    assert snap(path) == before
    # CLI: refused without the flag and when the prompt is not answered with REPLACE
    base = ["--database", path, "--start", START, "--end", END, "--apply", "--replace-range", "--no-backup"]
    assert A.main(base, confirm_input=lambda _p: "yes") == 2 and snap(path) == before
    assert A.main(base, confirm_input=lambda _p: (_ for _ in ()).throw(EOFError())) == 2 and snap(path) == before
    # without --apply, --replace-range is only reported
    assert A.main(["--database", path, "--start", START, "--end", END, "--replace-range"]) == 0 and snap(path) == before
    # confirmed: the stale row inside the range is removed and the range is rebuilt
    s = run(db, apply=True, replace_range=True, confirm_replace_range=True)
    assert s["deleted"] == 1 and s["inserted"] == 60
    db.expire_all()
    assert db.query(RiskAssessment).count() == 60 and db.query(RiskAssessment).filter_by(district_id=99).count() == 0
    db.close()


def test_typed_confirmation_allows_replace(tmp_path):
    path, SL, db = make_db(tmp_path)
    db.close()
    argv = ["--database", path, "--start", START, "--end", END, "--apply", "--replace-range", "--no-backup"]
    assert A.main(argv, confirm_input=lambda _p: "REPLACE") == 0
    con = sqlite3.connect(path)
    assert con.execute("SELECT count(*) FROM risk_assessments").fetchone()[0] == 60
    con.close()


def test_failure_at_any_step_rolls_back_everything(tmp_path, monkeypatch):
    for step in ("after_range_delete", "after_vulnerability_delete", "after_vulnerability_insert", "after_assessment_insert"):
        path, SL, db = make_db(tmp_path, f"{step}.db")
        db.add(Vulnerability(district_id=3, source="district_history", risk_class="low", class_index=0, expected_index=0.0))
        run(db, apply=True)                                                     # existing assessments for the range
        db.add(RiskAssessment(district_id=1, as_of_date=date(2019, 1, 1), window_days=3, status="ok"))
        db.commit()
        before = snap(path)

        def boom(name, _step=step):
            if name == _step:
                raise RuntimeError("simulated failure")
        monkeypatch.setattr(A, "_checkpoint", boom)
        with pytest.raises(RuntimeError):
            run(db, apply=True, replace_range=True, confirm_replace_range=True, refresh_vulnerability=True)
        db.close()
        assert snap(path) == before, f"state changed after failure at {step}"
        monkeypatch.setattr(A, "_checkpoint", lambda name: None)


def test_failure_through_cli_returns_error_and_keeps_data(tmp_path, monkeypatch):
    path, SL, db = make_db(tmp_path)
    run(db, apply=True)
    db.close()
    before = snap(path)
    monkeypatch.setattr(A, "_checkpoint", lambda name: (_ for _ in ()).throw(RuntimeError("x")) if name == "after_assessment_insert" else None)
    assert A.main(["--database", path, "--start", START, "--end", END, "--apply", "--replace-range", "--confirm-replace-range", "--no-backup"]) == 2
    assert snap(path) == before


def test_apply_makes_verified_backup_first(tmp_path):
    path, SL, db = make_db(tmp_path)
    db.close()
    before = snap(path)
    bk = tmp_path / "bk"
    assert A.main(["--database", path, "--start", START, "--end", END, "--apply", "--backup-dir", str(bk)]) == 0
    files = os.listdir(bk)
    assert len(files) == 1 and "_pre_assess_" in files[0]
    assert snap(str(bk / files[0])) == before                                  # backup holds the PRE-write state
    assert snap(path)["risk_assessments"] != before["risk_assessments"]


def test_refuses_database_without_tables_and_never_creates_them(tmp_path):
    p = str(tmp_path / "empty.db")
    sqlite3.connect(p).close()
    eng = create_engine(f"sqlite:///{p}")
    db = sessionmaker(bind=eng)()
    with pytest.raises(A.Refused):
        A.run_assessment(db, START, END, [3], out=lambda *_: None)
    db.close()
    con = sqlite3.connect(p)
    assert con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
    con.close()


def test_results_match_original_compute_assessments(tmp_path, monkeypatch):
    """Same inputs -> identical vulnerabilities and assessment rows as the ORIGINAL script (run only against a temp DB)."""
    import compute_assessments as C
    pa, SLa, dba = make_db(tmp_path, "orig.db")
    pb, SLb, dbb = make_db(tmp_path, "safe.db")
    dba.close()
    monkeypatch.setattr(C, "SessionLocal", SLa)
    monkeypatch.setattr(C, "engine", SLa.kw["bind"])
    C.main(START, END, [3, 7])
    run(dbb, apply=True, refresh_vulnerability=True)
    dbb.close()

    def rows(p):
        con = sqlite3.connect(p)
        a = con.execute("SELECT district_id, as_of_date, window_days, window_rain_mm, obs_fraction, hazard_level, status, combined_class, combined_score, model_version FROM risk_assessments ORDER BY 1,2,3").fetchall()
        v = con.execute("SELECT district_id, source, risk_class, class_index, expected_index, model_version FROM vulnerabilities ORDER BY 1").fetchall()
        con.close()
        return a, v
    assert rows(pa) == rows(pb) and len(rows(pa)[0]) == 60 and len(rows(pa)[1]) == 1
