"""Tests for scripts/db_snapshot.py. Temporary SQLite files only; stdlib only (no app imports)."""
import hashlib
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import db_snapshot as S  # noqa: E402


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _make_db(path, orphan=False):
    con = sqlite3.connect(path)          # foreign keys are NOT enabled on this connection, like the real app
    con.executescript("""
        CREATE TABLE districts (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE risk_assessments (id INTEGER PRIMARY KEY, district_id INTEGER NOT NULL REFERENCES districts(id), v REAL);
        CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
        INSERT INTO districts VALUES (1,'A'),(2,'B');
        INSERT INTO risk_assessments VALUES (1,1,0.5),(2,2,0.7),(3,1,0.9);
    """)
    if orphan:
        con.execute("INSERT INTO risk_assessments VALUES (4, 99, 0.1)")
        con.execute("INSERT INTO risk_assessments VALUES (5, 98, 0.2)")
    con.commit()
    con.close()


def test_report_counts_and_clean(tmp_path):
    db = str(tmp_path / "a.db")
    _make_db(db)
    r = S.build_report(db)
    assert r["integrity_ok"] and r["clean"]
    assert r["tables"] == {"districts": 2, "meta": 0, "risk_assessments": 3}
    assert r["total_rows"] == 5
    assert r["foreign_key_enforcement_enabled_by_this_tool"] is False


def test_orphans_detected_without_modifying_db(tmp_path):
    db = str(tmp_path / "a.db")
    _make_db(db, orphan=True)
    before = _sha(db)
    r = S.build_report(db)
    assert not r["clean"] and r["orphans"]["total"] == 2
    g = r["orphans"]["groups"][0]
    assert (g["table"], g["parent_table"], g["orphan_rows"]) == ("risk_assessments", "districts", 2)
    assert sorted(g["sample_rowids"]) == [4, 5]
    assert _sha(db) == before                      # report is strictly read-only
    con = sqlite3.connect(db)                      # orphans are still there: nothing was repaired or removed
    assert con.execute("SELECT count(*) FROM risk_assessments").fetchone()[0] == 5
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    con.close()


def test_report_does_not_enable_foreign_keys_or_write(tmp_path):
    db = str(tmp_path / "a.db")
    _make_db(db)
    con = S.open_readonly(db)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO districts VALUES (3,'C')")      # connection really is read-only
    con.close()


def test_backup_is_verified_and_original_untouched(tmp_path):
    db = str(tmp_path / "a.db")
    _make_db(db)
    before = _sha(db)
    info = S.create_backup(db, str(tmp_path / "bk"))
    assert os.path.isfile(info["backup"]) and info["backup"] != os.path.abspath(db)
    assert _sha(db) == before
    assert info["tables"] == S.build_report(db)["tables"]
    assert S.build_report(info["backup"])["integrity_ok"]
    assert not any(f.endswith(".partial") for f in os.listdir(tmp_path / "bk"))
    assert info["sha256"] == _sha(info["backup"])


def test_backup_of_database_with_orphans_copies_them_faithfully(tmp_path):
    db = str(tmp_path / "a.db")
    _make_db(db, orphan=True)
    info = S.create_backup(db, str(tmp_path / "bk"))
    assert S.build_report(info["backup"])["orphans"]["total"] == 2


def test_two_backups_never_overwrite(tmp_path):
    db = str(tmp_path / "a.db")
    _make_db(db)
    a = S.create_backup(db, str(tmp_path / "bk"))
    b = S.create_backup(db, str(tmp_path / "bk"))
    assert a["backup"] != b["backup"] and os.path.isfile(a["backup"]) and os.path.isfile(b["backup"])


def test_backup_detects_corrupt_copy(tmp_path, monkeypatch):
    db = str(tmp_path / "a.db")
    _make_db(db)
    monkeypatch.setattr(S, "integrity", lambda con: ["*** in database main ***"])
    with pytest.raises(S.SnapshotError):
        S.create_backup(db, str(tmp_path / "bk"))
    assert S.row_counts(S.open_readonly(db)) == {"districts": 2, "meta": 0, "risk_assessments": 3}


def test_missing_and_non_sqlite_files(tmp_path):
    with pytest.raises(S.SnapshotError):
        S.build_report(str(tmp_path / "nope.db"))
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a database" * 100)
    with pytest.raises(S.SnapshotError):
        S.build_report(str(bad))
    assert not (tmp_path / "nope.db").exists()      # a missing path is not created by read-only access


def test_cli_exit_codes_and_json(tmp_path, capsys):
    good, bad = str(tmp_path / "g.db"), str(tmp_path / "o.db")
    _make_db(good)
    _make_db(bad, orphan=True)
    assert S.main(["report", "--db", good]) == 0
    assert S.main(["report", "--db", bad]) == 1
    assert S.main(["report", "--db", str(tmp_path / "missing.db")]) == 2
    capsys.readouterr()
    assert S.main(["report", "--db", good, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["tables"]["districts"] == 2
    assert S.main(["backup", "--db", good, "--backup-dir", str(tmp_path / "bk"), "--label", "pre"]) == 0
    assert any("_pre_" in f for f in os.listdir(tmp_path / "bk"))
