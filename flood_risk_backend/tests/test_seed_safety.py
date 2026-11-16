"""Tests for scripts/seed_safety.py (protected --reset guard, count table). Temporary SQLite files only; stdlib only."""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import seed_safety as S  # noqa: E402


def make(path, rows=0, empty_tables=True):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE districts (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE my_notes (t TEXT)")                      # an unrelated table
    con.executemany("INSERT INTO districts VALUES (?)", [(i,) for i in range(rows)])
    con.commit()
    con.close()


def test_reset_requires_exact_path_confirmation(tmp_path):
    p = str(tmp_path / "a.db")
    make(p)
    for bad in (None, "", str(tmp_path / "other.db")):
        with pytest.raises(S.ResetRefused):
            S.check_reset_allowed(p, bad)


def test_reset_refused_for_database_with_data_even_when_confirmed(tmp_path):
    p = str(tmp_path / "real.db")
    make(p, rows=3)
    before = open(p, "rb").read()
    with pytest.raises(S.ResetRefused) as e:
        S.check_reset_allowed(p, p)
    assert "REAL database" in str(e.value) and "districts=3" in str(e.value)
    assert open(p, "rb").read() == before                              # the check itself is read-only


def test_unrelated_table_with_rows_also_blocks_reset(tmp_path):
    p = str(tmp_path / "a.db")
    make(p)
    con = sqlite3.connect(p)
    con.execute("INSERT INTO my_notes VALUES ('keep me')")
    con.commit()
    con.close()
    with pytest.raises(S.ResetRefused):
        S.check_reset_allowed(p, p)


def test_reset_allowed_for_empty_or_new_database(tmp_path):
    p = str(tmp_path / "empty.db")
    make(p)
    S.check_reset_allowed(p, p)                                         # tables exist but hold zero rows
    S.check_reset_allowed(str(tmp_path / "new.db"), str(tmp_path / "new.db"))       # file does not exist yet
    assert not (tmp_path / "new.db").exists()                           # and was not created by the check


def test_reset_refused_without_file_database(tmp_path):
    with pytest.raises(S.ResetRefused):
        S.check_reset_allowed(None, "x")


def test_reset_refused_for_non_sqlite_file(tmp_path):
    p = tmp_path / "junk.db"
    p.write_bytes(b"not a database" * 50)
    with pytest.raises(S.ResetRefused):
        S.check_reset_allowed(str(p), str(p))


def test_count_table_shows_existing_incoming_resulting():
    t = S.format_count_table({"flood_labels": 165, "rainfall_daily": 10}, {"flood_labels": 165, "rainfall_daily": None},
                             {"flood_labels": 165, "rainfall_daily": 10}, {"flood_labels": "REPLACED"})
    assert "165" in t and "REPLACED" in t and "SKIPPED" in t and "existing" in t and "resulting" in t
