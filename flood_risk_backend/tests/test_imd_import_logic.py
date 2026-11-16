"""Pure-logic tests for scripts/import_imd_rainfall.py validation and upsert diffing (no database)."""
import io
import os
import sys
from datetime import date

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import import_imd_rainfall as M  # noqa: E402


def frame(text):
    return pd.read_csv(io.StringIO(text.strip() + "\n"), dtype=str)


GOOD = "district_id,date,rainfall_mm,source\n1,2026-08-19,12.5,IMD_daily_actual_2026\n1,2026-08-20,0.0,IMD_daily_actual_2026\n2,2026-08-19,3,"


def test_valid_rows_and_default_source():
    rec, rej = M.validate_frame(frame(GOOD), {1, 2})
    assert not rej and len(rec) == 3
    assert rec[2]["source"] == "IMD_daily_actual_2026"                       # blank source takes the intended default
    assert rec[1]["rainfall_mm"] == 0.0 and rec[0]["date"] == date(2026, 8, 19)


def test_absent_source_column_is_allowed():
    rec, rej = M.validate_frame(frame("district_id,date,rainfall_mm\n1,2026-08-19,1.5"), {1})
    assert not rej and rec[0]["source"] == "IMD_daily_actual_2026"


def test_required_columns_and_empty_file():
    with pytest.raises(ValueError, match="missing required columns"):
        M.validate_frame(frame("district_id,date\n1,2026-08-19"), {1})
    with pytest.raises(ValueError, match="no data rows"):
        M.validate_frame(pd.DataFrame(columns=["district_id", "date", "rainfall_mm"], dtype=str), {1})


def test_other_sources_are_rejected_unless_approved():
    text = "district_id,date,rainfall_mm,source\n1,2026-08-19,1,SOMETHING_ELSE\n1,2026-08-20,2,IMD_daily_actual_2026"
    rec, rej = M.validate_frame(frame(text), {1})
    assert len(rec) == 1 and list(rej) == ["disallowed_source"] and rej["disallowed_source"][0][0] == 2
    rec2, rej2 = M.validate_frame(frame(text), {1}, approved_sources=["SOMETHING_ELSE"])
    assert len(rec2) == 2 and not rej2


def test_every_kind_of_bad_row_is_rejected_never_coerced():
    text = """district_id,date,rainfall_mm,source
1,2026-08-19,12.5,IMD_daily_actual_2026
1,2026-08-20,,IMD_daily_actual_2026
1,2026-08-21,abc,IMD_daily_actual_2026
1,2026-08-22,-1,IMD_daily_actual_2026
1,2026-08-23,99999,IMD_daily_actual_2026
9,2026-08-24,5,IMD_daily_actual_2026
x,2026-08-25,5,IMD_daily_actual_2026
1.5,2026-08-25,5,IMD_daily_actual_2026
1,not-a-date,5,IMD_daily_actual_2026
1,2026-02-31,5,IMD_daily_actual_2026"""
    rec, rej = M.validate_frame(frame(text), {1, 2})
    assert [r["rainfall_mm"] for r in rec] == [12.5]                         # blank rain is NOT turned into 0
    assert {k: len(v) for k, v in rej.items()} == {"missing_rainfall": 2, "negative_rainfall": 1, "implausible_rainfall": 1,
                                                  "unknown_district": 1, "invalid_district_id": 2, "invalid_date": 2}


def test_duplicate_district_dates_are_all_rejected_with_original_message():
    text = "district_id,date,rainfall_mm\n1,2026-08-19,12.5\n1,2026-08-19,13.0\n2,2026-08-19,1.0"
    rec, rej = M.validate_frame(frame(text), {1, 2})
    assert [r["district_id"] for r in rec] == [2] and [ln for ln, _ in rej["duplicate"]] == [2, 3]
    assert "Duplicate district_id/date" in M.rejection_message(rej)              # same wording the existing test relies on


def test_rejection_message_lists_unknown_ids_and_sources():
    _, rej = M.validate_frame(frame("district_id,date,rainfall_mm,source\n9,2026-08-19,1,BAD"), {1})
    assert "9" in M.rejection_message(rej) or "BAD" in M.rejection_message(rej)


def test_diff_upsert_insert_update_skip_and_untouched_rows():
    existing = {(1, date(2026, 8, 19)): {"id": 10, "rainfall_mm": 12.5, "source": "IMD_daily_actual_2026"},
                (1, date(2026, 8, 20)): {"id": 11, "rainfall_mm": 1.0, "source": "IMD_daily_actual_2026"},
                (5, date(2026, 1, 1)): {"id": 12, "rainfall_mm": 7.0, "source": "IMD_daily_actual_2026"}}      # not in the file
    rec, _ = M.validate_frame(frame(GOOD), {1, 2})
    ins, upd, same = M.diff_upsert(existing, rec)
    assert [(r["district_id"], r["date"]) for r in ins] == [(2, date(2026, 8, 19))]
    assert upd == [{"id": 11, "rainfall_mm": 0.0, "source": "IMD_daily_actual_2026"}] and same == 1
    assert all(u["id"] != 12 for u in upd)                                      # rows absent from the file are never touched
    assert M.diff_upsert({(r["district_id"], r["date"]): {"id": 1, "rainfall_mm": r["rainfall_mm"], "source": r["source"]} for r in rec}, rec) == ([], [], 3)


def test_shipped_imd_csv_passes_validation():
    p = M.DEFAULT_CSV
    if not os.path.exists(p):
        return
    ids = set(pd.read_csv(os.path.join(os.path.dirname(p), "districts.csv"))["id"])
    rec, rej = M.validate_frame(pd.read_csv(p, dtype=str), ids)
    assert not rej and len(rec) == 2294
