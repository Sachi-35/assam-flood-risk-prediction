"""Database tests for scripts/import_imd_rainfall.py. Temporary SQLite files and temporary CSVs only."""
import json
import os
import sqlite3
import sys
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from app.database import Base  # noqa: E402
from app.models import District, RainfallDaily, RainfallIMDRecent, RiskAssessment  # noqa: E402
import import_imd_rainfall as M  # noqa: E402

POLY = json.dumps({"type": "Polygon", "coordinates": [[[91.0, 26.0], [91.1, 26.0], [91.1, 26.1], [91.0, 26.1], [91.0, 26.0]]]})
SRC = "IMD_daily_actual_2026"


def make_db(tmp_path, name="t.db"):
    path = str(tmp_path / name)
    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=eng)
    SL = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    db = SL()
    for i in (1, 2, 3):
        db.add(District(id=i, name=f"D{i}", state="Assam", geometry=POLY))
    db.add(RainfallDaily(district_id=1, date=date(2020, 7, 1), rainfall_mm=5.0, n_stations=1))        # historical rainfall
    db.add(RiskAssessment(district_id=1, as_of_date=date(2023, 7, 1), window_days=3, status="ok", hazard_level=1))
    db.add(RainfallIMDRecent(district_id=1, date=date(2026, 8, 19), rainfall_mm=1.0, source=SRC))     # will be updated by the CSV
    db.add(RainfallIMDRecent(district_id=3, date=date(2026, 8, 1), rainfall_mm=7.0, source=SRC))      # not in the CSV
    db.commit()
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE my_notes (t TEXT)")
    con.execute("INSERT INTO my_notes VALUES ('unrelated')")
    con.commit()
    con.close()
    return path, SL, db


def snap(path):
    con = sqlite3.connect(path)
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1")]
    out = {t: con.execute(f'SELECT * FROM "{t}" ORDER BY 1').fetchall() for t in names}
    con.close()
    return out


def imd(path):
    return {(r[1], r[2]): (r[3], r[4]) for r in snap(path)["rainfall_imd_recent"]}


def csv(tmp_path, rows, name="in.csv"):
    p = tmp_path / name
    pd.DataFrame(rows).to_csv(p, index=False)
    return str(p)


GOOD = [dict(district_id=1, date="2026-08-19", rainfall_mm=12.5, source=SRC),          # existing, changed
        dict(district_id=1, date="2026-08-20", rainfall_mm=0.0, source=SRC),           # new
        dict(district_id=2, date="2026-08-19", rainfall_mm=3.0, source=SRC)]            # new


def test_default_is_upsert_and_keeps_rows_not_in_csv(tmp_path):
    path, SL, db = make_db(tmp_path)
    r = M.import_imd_rainfall(db, csv(tmp_path, GOOD))
    assert (r["mode"], r["inserted"], r["updated"], r["skipped"], r["rejected"], r["deleted"]) == ("upsert", 2, 1, 0, 0, 0)
    assert (r["existing_before"], r["resulting"], r["applied"]) == (2, 4, True)
    t = imd(path)
    assert t[(1, "2026-08-19")] == (12.5, SRC) and t[(1, "2026-08-20")] == (0.0, SRC)            # 0.0 stays 0.0
    assert t[(3, "2026-08-01")] == (7.0, SRC)                                                      # row absent from the CSV survived
    db.close()


def test_repeating_the_same_import_changes_nothing(tmp_path):
    path, SL, db = make_db(tmp_path)
    p = csv(tmp_path, GOOD)
    M.import_imd_rainfall(db, p)
    first = snap(path)
    r = M.import_imd_rainfall(db, p)
    assert (r["inserted"], r["updated"], r["skipped"]) == (0, 0, 3) and r["rows"] == 3
    assert snap(path) == first                                                                     # same ids, no duplicates
    db.close()


def test_replace_is_explicit_and_removes_other_rows(tmp_path):
    path, SL, db = make_db(tmp_path)
    r = M.import_imd_rainfall(db, csv(tmp_path, GOOD), replace=True)
    assert (r["mode"], r["deleted"], r["inserted"], r["updated"], r["resulting"]) == ("replace", 2, 3, 0, 3)
    assert (3, "2026-08-01") not in imd(path) and len(imd(path)) == 3
    db.close()


def test_replace_with_no_valid_rows_is_refused(tmp_path):
    path, SL, db = make_db(tmp_path)
    before = snap(path)
    bad = csv(tmp_path, [dict(district_id=1, date="2026-08-19", rainfall_mm=-1.0, source=SRC)])
    with pytest.raises(M.ImportRejected):
        M.import_imd_rainfall(db, bad, replace=True)
    with pytest.raises(M.ImportRejected):
        M.import_imd_rainfall(db, bad, replace=True, skip_invalid=True)                            # would empty the table
    assert snap(path) == before
    db.close()


def test_dry_run_reports_but_writes_nothing(tmp_path):
    path, SL, db = make_db(tmp_path)
    before = snap(path)
    r = M.import_imd_rainfall(db, csv(tmp_path, GOOD), dry_run=True)
    assert (r["inserted"], r["updated"], r["skipped"], r["applied"], r["dry_run"]) == (2, 1, 0, False, True)
    r2 = M.import_imd_rainfall(db, csv(tmp_path, GOOD), dry_run=True, replace=True)
    assert (r2["deleted"], r2["inserted"]) == (2, 3)
    assert snap(path) == before
    db.close()


def test_other_sources_are_rejected_unless_explicitly_approved(tmp_path):
    path, SL, db = make_db(tmp_path)
    before = snap(path)
    rows = GOOD + [dict(district_id=2, date="2026-08-20", rainfall_mm=1.0, source="SOMETHING_ELSE")]
    with pytest.raises(M.ImportRejected, match="not approved"):
        M.import_imd_rainfall(db, csv(tmp_path, rows))
    assert snap(path) == before                                                                    # nothing imported, not even the good rows
    r = M.import_imd_rainfall(db, csv(tmp_path, rows), approve_sources=["SOMETHING_ELSE"])
    assert r["inserted"] == 3 and imd(path)[(2, "2026-08-20")][1] == "SOMETHING_ELSE"
    db.close()


def test_invalid_rows_strict_vs_skip_invalid(tmp_path):
    path, SL, db = make_db(tmp_path)
    before = snap(path)
    rows = GOOD + [dict(district_id=99, date="2026-08-21", rainfall_mm=1.0, source=SRC),          # unknown district
                   dict(district_id=1, date="2026-08-22", rainfall_mm=None, source=SRC),          # missing value
                   dict(district_id=2, date="2026-08-23", rainfall_mm=-3.0, source=SRC),          # negative
                   dict(district_id=2, date="2026-08-24", rainfall_mm=1.0, source=SRC),
                   dict(district_id=2, date="2026-08-24", rainfall_mm=2.0, source=SRC)]           # duplicate pair
    p = csv(tmp_path, rows)
    with pytest.raises(ValueError):
        M.import_imd_rainfall(db, p)
    assert snap(path) == before
    r = M.import_imd_rainfall(db, p, skip_invalid=True)
    assert (r["inserted"], r["updated"], r["rejected"]) == (2, 1, 5) and set(r["rejects"]) == {"unknown_district", "missing_rainfall", "negative_rainfall", "duplicate"}
    assert (2, "2026-08-24") not in imd(path) and (2, "2026-08-23") not in imd(path)               # bad rows never reached the table
    db.close()


def test_failure_at_any_step_rolls_back_everything(tmp_path, monkeypatch):
    for replace, step in ((True, "after_delete"), (True, "after_insert"), (True, "before_commit"), (False, "after_insert"), (False, "before_commit")):
        path, SL, db = make_db(tmp_path, f"{replace}_{step}.db")
        before = snap(path)

        def boom(name, _s=step):
            if name == _s:
                raise RuntimeError("simulated failure")
        monkeypatch.setattr(M, "_checkpoint", boom)
        with pytest.raises(RuntimeError):
            M.import_imd_rainfall(db, csv(tmp_path, GOOD), replace=replace)
        db.close()
        assert snap(path) == before, f"state changed after failure at {step} (replace={replace})"
        monkeypatch.setattr(M, "_checkpoint", lambda name: None)


def test_historical_rainfall_assessments_and_unrelated_tables_are_untouched(tmp_path):
    path, SL, db = make_db(tmp_path)
    keep = {k: v for k, v in snap(path).items() if k in ("rainfall_daily", "risk_assessments", "districts", "my_notes")}
    M.import_imd_rainfall(db, csv(tmp_path, GOOD))
    M.import_imd_rainfall(db, csv(tmp_path, GOOD), replace=True)
    after = snap(path)
    assert {k: after[k] for k in keep} == keep and all(keep.values())
    db.close()


def test_existing_behaviour_blank_source_column_defaults(tmp_path):
    path, SL, db = make_db(tmp_path)
    p = csv(tmp_path, [dict(district_id=2, date="2026-08-19", rainfall_mm=3.0)])
    M.import_imd_rainfall(db, p)
    assert imd(path)[(2, "2026-08-19")] == (3.0, SRC)
    db.close()


def test_cli_dry_run_default_upsert_replace_and_rejection(tmp_path):
    path, SL, db = make_db(tmp_path)
    db.close()
    good, bad = csv(tmp_path, GOOD), csv(tmp_path, GOOD + [dict(district_id=2, date="2026-08-20", rainfall_mm=1.0, source="NOPE")], "bad.csv")
    before = snap(path)
    assert M.main(["--csv", good, "--dry-run"], session_factory=SL) == 0 and snap(path) == before
    assert M.main(["--csv", bad, "--no-backup"], session_factory=SL) == 2 and snap(path) == before        # bad source: refused, nothing written
    assert M.main(["--csv", good, "--no-backup"], session_factory=SL) == 0 and len(imd(path)) == 4        # upsert keeps the other row
    assert M.main(["--csv", good, "--replace", "--no-backup"], session_factory=SL) == 0 and len(imd(path)) == 3
    assert M.main(["--csv", good, "--allow-source", "NOPE", "--no-backup"], session_factory=SL) == 0
    assert M.main(["--csv", str(tmp_path / "missing.csv")], session_factory=SL) == 2


def test_cli_makes_a_verified_backup_before_writing(tmp_path):
    path, SL, db = make_db(tmp_path)
    db.close()
    before = snap(path)
    bk = tmp_path / "bk"
    assert M.main(["--csv", csv(tmp_path, GOOD), "--backup-dir", str(bk)], session_factory=SL) == 0
    files = os.listdir(bk)
    assert len(files) == 1 and "_pre_imd_" in files[0] and snap(str(bk / files[0])) == before
