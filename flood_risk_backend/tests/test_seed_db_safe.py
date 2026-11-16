"""Database tests for the transactional scripts/seed_db.py. Temporary SQLite files and temporary data folders only."""
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
from app.models import (Climatology, District, FloodLabel, Meta, NormalSeason, RainfallDaily, RainfallIMDRecent,  # noqa: E402
                        RiskAssessment, Vulnerability)
import seed_db as S  # noqa: E402

N = 33
Q = dict(q50=10, q75=30, q90=60, q95=80, q97=100, q99=140)
POLY = json.dumps({"type": "Polygon", "coordinates": [[[91.0, 26.0], [91.1, 26.0], [91.1, 26.1], [91.0, 26.1], [91.0, 26.0]]]})
SEEDED = ("districts", "flood_labels", "rainfall_daily", "climatology", "normal_seasons", "meta")


def write(folder, name, rows):
    pd.DataFrame(rows).to_csv(os.path.join(folder, name), index=False)


def make_data(tmp_path, labels=True, rain=True, clim=True):
    f = tmp_path / "data"
    f.mkdir(exist_ok=True)
    write(f, "districts.csv", [dict(id=i, name=f"D{i}", state="Assam", geometry=POLY, mean_elevation_m=50.0, elevation_std_m=5.0,
                                    mean_slope_deg=1.0, low_lying_frac=0.3, pop_density_km2=None) for i in range(1, N + 1)])
    if labels:
        write(f, "flood_labels.csv", [dict(district=f"D{i}", year=y, status="reported" if y == 2020 else "unknown", impact_class="low" if y == 2020 else None,
                                           affected_population=10 if y == 2020 else None) for i in range(1, N + 1) for y in (2019, 2020)])
    if rain:
        write(f, "rainfall_daily.csv", [dict(district_id=1, date=f"2023-07-{d:02d}", rainfall_mm=float(d), n_stations=1) for d in range(1, 6)])
    if clim:
        write(f, "climatology.csv", [dict(district_id=1, window_days=w, doy=doy, n_values=50, n_years=5, **Q) for w in (3, 7) for doy in range(180, 190)])
    (f / "hazard_config.json").write_text(json.dumps({"windows": [3, 7], "level_quantiles": [0.75, 0.9, 0.97], "min_obs_fraction": 0.8}))
    return str(f)


def make_db(tmp_path, name="t.db"):
    path = str(tmp_path / name)
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    return path, eng


def tables(path):
    con = sqlite3.connect(path)
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1")]
    out = {t: con.execute(f'SELECT * FROM "{t}" ORDER BY 1').fetchall() for t in names}
    con.close()
    return out


def preload(eng):
    """Old content: stale labels/rainfall, a district not in the new file, assessment/vulnerability/IMD rows, and an unrelated table."""
    s = sessionmaker(bind=eng)()
    s.add(District(id=50, name="OldOnly", state="Assam", geometry=POLY))
    s.add(District(id=1, name="OldName", state="Assam", geometry=POLY))
    s.flush()
    s.add(FloodLabel(district_id=50, year=2021, status="reported", impact_class="high"))
    s.add(RainfallDaily(district_id=50, date=date(2020, 1, 1), rainfall_mm=9.0, n_stations=1))
    s.add(RiskAssessment(district_id=50, as_of_date=date(2023, 7, 1), window_days=3, status="ok", hazard_level=1))
    s.add(Vulnerability(district_id=50, source="district_history", risk_class="high", class_index=2, expected_index=2.0))
    s.add(RainfallIMDRecent(district_id=50, date=date(2026, 8, 19), rainfall_mm=4.0, source="IMD_daily_actual_2026"))
    s.commit()
    s.close()
    con = sqlite3.connect(eng.url.database)
    con.execute("CREATE TABLE my_notes (t TEXT)")
    con.execute("INSERT INTO my_notes VALUES ('unrelated')")
    con.commit()
    con.close()


def run(monkeypatch, tmp_path, eng, *argv, data=None):
    monkeypatch.setattr(S, "DATA_DIR", data or make_data(tmp_path))
    return S.main(list(argv) + ["--no-backup"] if "--backup-dir" not in argv else list(argv), engine_override=eng)


def test_dry_run_writes_nothing_and_prints_counts(tmp_path, monkeypatch, capsys):
    path, eng = make_db(tmp_path)
    preload(eng)
    before = tables(path)
    assert run(monkeypatch, tmp_path, eng, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "existing" in out and "incoming" in out and "resulting" in out and "DRY-RUN" in out
    assert tables(path) == before                                          # every table, including unrelated ones, identical


def test_dry_run_without_tables_does_not_create_them(tmp_path, monkeypatch):
    p = str(tmp_path / "empty.db")
    sqlite3.connect(p).close()
    eng = create_engine(f"sqlite:///{p}")
    assert run(monkeypatch, tmp_path, eng, "--dry-run") == 0
    con = sqlite3.connect(p)
    assert con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
    con.close()


def test_normal_seed_loads_and_is_repeatable(tmp_path, monkeypatch):
    path, eng = make_db(tmp_path)
    assert run(monkeypatch, tmp_path, eng) == 0
    first = tables(path)
    assert len(first["districts"]) == N and len(first["flood_labels"]) == 2 * N and len(first["rainfall_daily"]) == 5 and len(first["climatology"]) == 20
    assert run(monkeypatch, tmp_path, eng) == 0
    assert tables(path) == first                                           # no duplicates, same ids


def test_replacement_semantics_are_preserved(tmp_path, monkeypatch):
    path, eng = make_db(tmp_path)
    preload(eng)
    data = make_data(tmp_path, rain=False)                                 # rainfall_daily.csv ABSENT -> table must be left alone
    assert run(monkeypatch, tmp_path, eng, data=data) == 0
    t = tables(path)
    assert all(row[1] != 50 for row in t["flood_labels"]) and len(t["flood_labels"]) == 2 * N      # present file REPLACES the table
    assert [r[1] for r in t["rainfall_daily"]] == [50]                                              # absent file -> skipped, old rows kept
    ids = {r[0]: r[1] for r in t["districts"]}
    assert 50 in ids and ids[1] == "D1" and len(ids) == N + 1                                       # upsert by id; old district never deleted


def test_unrelated_tables_and_assessments_survive_seeding(tmp_path, monkeypatch):
    path, eng = make_db(tmp_path)
    preload(eng)
    keep = {k: v for k, v in tables(path).items() if k in ("risk_assessments", "vulnerabilities", "rainfall_imd_recent", "my_notes")}
    assert len(keep) == 4 and all(keep.values())
    assert run(monkeypatch, tmp_path, eng) == 0
    after = tables(path)
    assert {k: after[k] for k in keep} == keep


def test_failure_in_any_table_rolls_back_everything(tmp_path, monkeypatch):
    path, eng = make_db(tmp_path)
    preload(eng)
    before = tables(path)
    monkeypatch.setattr(S, "DATA_DIR", make_data(tmp_path))

    def boom(db, ids, stats=None):
        raise RuntimeError("simulated climatology failure")
    monkeypatch.setattr(S, "load_climatology", boom)                       # districts, labels and rainfall were already written in the transaction
    assert S.main(["--no-backup"], engine_override=eng) == 2
    assert tables(path) == before


def test_loader_systemexit_rolls_back_too(tmp_path, monkeypatch):
    path, eng = make_db(tmp_path)
    preload(eng)
    before = tables(path)
    data = make_data(tmp_path)
    write(data, "flood_labels.csv", [dict(district="D1", status="reported")])      # no 'year' column -> loader exits
    monkeypatch.setattr(S, "DATA_DIR", data)
    assert S.main(["--no-backup", "--skip-validation"], engine_override=eng) == 2
    assert tables(path) == before                                          # new districts that were already merged are gone again


def test_reset_is_refused_without_confirmation_and_on_real_data(tmp_path, monkeypatch):
    path, eng = make_db(tmp_path)
    preload(eng)
    before = tables(path)
    assert run(monkeypatch, tmp_path, eng, "--reset") == 2                                   # no --confirm-reset
    assert run(monkeypatch, tmp_path, eng, "--reset", "--confirm-reset", path) == 2          # confirmed, but the database holds data
    assert run(monkeypatch, tmp_path, eng, "--reset", "--confirm-reset", path, "--dry-run") == 2
    assert tables(path) == before


def test_reset_on_empty_database_is_allowed_and_dry_run_drops_nothing(tmp_path, monkeypatch):
    path, eng = make_db(tmp_path)                                          # tables exist, zero rows
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE my_notes (t TEXT)")
    con.commit()
    con.close()
    assert run(monkeypatch, tmp_path, eng, "--reset", "--confirm-reset", path, "--dry-run") == 0
    assert "districts" in tables(path)
    assert run(monkeypatch, tmp_path, eng, "--reset", "--confirm-reset", path) == 0
    t = tables(path)
    assert len(t["districts"]) == N and "my_notes" in t                    # reseeded; the unrelated table was never dropped


def test_bad_data_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    path, eng = make_db(tmp_path)
    preload(eng)
    before = tables(path)
    data = make_data(tmp_path)
    write(data, "rainfall_daily.csv", [dict(district_id=1, date="2023-07-01", rainfall_mm=-5.0, n_stations=1)])
    assert run(monkeypatch, tmp_path, eng, data=data) == 2
    assert tables(path) == before
    assert run(monkeypatch, tmp_path, eng, "--skip-validation", data=data) == 0      # explicit opt-out still works


def test_backup_is_made_before_seeding_an_existing_database(tmp_path, monkeypatch):
    path, eng = make_db(tmp_path)
    preload(eng)
    before = tables(path)
    monkeypatch.setattr(S, "DATA_DIR", make_data(tmp_path))
    bk = tmp_path / "bk"
    assert S.main(["--backup-dir", str(bk)], engine_override=eng) == 0
    files = os.listdir(bk)
    assert len(files) == 1 and "_pre_seed_" in files[0]
    assert tables(str(bk / files[0])) == before                            # the backup holds the PRE-seed state


def test_seed_all_default_still_commits_for_existing_callers(tmp_path, monkeypatch):
    path, eng = make_db(tmp_path)
    monkeypatch.setattr(S, "DATA_DIR", make_data(tmp_path))
    db = sessionmaker(bind=eng)()
    names = S.seed_all(db)                                                 # same call the older tests make
    db.close()
    assert len(names) == N and len(tables(path)["districts"]) == N
