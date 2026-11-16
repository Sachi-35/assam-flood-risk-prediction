"""Import recent IMD daily rainfall into its own table (rainfall_imd_recent). Never touches historical rainfall or risk assessments.

Default = SAFE UPSERT on (district_id, date): new rows are inserted, changed rows are updated, identical rows are skipped, and every row
already in the table that the CSV does not mention is KEPT. Re-running the same file changes nothing.
  --replace   explicit FULL replacement of the table by the CSV (the old behaviour). Never the default.
  --dry-run   validate and report inserted/updated/skipped/rejected/deleted counts; write nothing.

Validation: required columns; integer district ids that exist in the database; parseable dates; numeric, non-negative rainfall (a blank or
invalid Daily Actual value is rejected, never turned into zero); no duplicate (district_id, date) rows; the source must be
IMD_daily_actual_2026 (blank/absent = that value). Another source is rejected unless approved explicitly with --allow-source NAME.
Strict by default: ANY bad row stops the import (ValueError, nothing written, all problems listed). With --skip-invalid the good rows are
imported and bad rows are counted as "rejected" (rows involved in a duplicate district/date are ALL rejected: the right value is unknowable).
One transaction: any failure rolls back completely. On a real write to a SQLite file a verified backup is made first unless --no-backup.

Usage:
  python scripts/import_imd_rainfall.py --dry-run
  python scripts/import_imd_rainfall.py                       # upsert
  python scripts/import_imd_rainfall.py --replace             # full replacement (explicit)
  python scripts/import_imd_rainfall.py --csv other.csv --allow-source IMD_other --skip-invalid
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

DEFAULT_CSV = Path(__file__).resolve().parents[1] / "data" / "rainfall_imd_recent.csv"
EXPECTED_SOURCE = "IMD_daily_actual_2026"
MAX_DAILY_MM = 1500.0
REQUIRED = ("district_id", "date", "rainfall_mm")

_MESSAGES = {
    "invalid_district_id": "District IDs must be whole numbers",
    "invalid_date": "Invalid or missing dates",
    "missing_rainfall": "IMD CSV contains missing or invalid Daily Actual values.",
    "negative_rainfall": "Rainfall values cannot be negative.",
    "implausible_rainfall": f"Rainfall values above {MAX_DAILY_MM:.0f} mm/day are rejected",
    "duplicate": "Duplicate district_id/date rows found in IMD CSV.",
    "unknown_district": "District IDs do not exist in the database",
    "disallowed_source": f"Source value not approved (only {EXPECTED_SOURCE} unless --allow-source is given)",
}


class ImportRejected(ValueError):
    """The file (or, with skip_invalid, some rows) failed validation. Nothing was written."""


def _checkpoint(name: str) -> None:
    """No-op hook between write steps; tests patch it to simulate a failure at that point."""


# ------------------------------------------------------------------ pure validation / diff (no database) -------------------------
def validate_frame(df: pd.DataFrame, valid_ids, approved_sources=()):
    """Returns (clean_records, rejects). rejects = {category: [(csv_line, detail), ...]}; each row appears under one category only.

    df must have been read with dtype=str. clean_records: dicts with district_id, date (datetime.date), rainfall_mm, source.
    """
    allowed = {EXPECTED_SOURCE} | set(approved_sources)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
    if len(df) == 0:
        raise ValueError("CSV has no data rows")
    d = pd.DataFrame({"line": range(2, len(df) + 2)})
    num_id = pd.to_numeric(df["district_id"], errors="coerce")
    d["district_id"] = num_id
    d["date"] = pd.to_datetime(df["date"], errors="coerce")
    d["rain"] = pd.to_numeric(df["rainfall_mm"], errors="coerce")
    d["source"] = (df["source"].fillna("").str.strip().replace("", EXPECTED_SOURCE) if "source" in df.columns else EXPECTED_SOURCE)
    d["raw_id"], d["raw_source"] = df["district_id"], d["source"]
    reason = pd.Series([None] * len(d), dtype="object")

    def mark(mask, cat):
        reason[mask & reason.isna()] = cat

    mark(d["district_id"].isna() | (d["district_id"] % 1 != 0), "invalid_district_id")
    mark(d["date"].isna(), "invalid_date")
    mark(d["rain"].isna(), "missing_rainfall")
    mark(d["rain"] < 0, "negative_rainfall")
    mark(d["rain"] > MAX_DAILY_MM, "implausible_rainfall")
    mark(~d["source"].isin(allowed), "disallowed_source")
    if valid_ids is not None:
        mark(~d["district_id"].isin(set(valid_ids)) & d["district_id"].notna(), "unknown_district")
    candidate = reason.isna()
    dup = d[candidate].duplicated(["district_id", "date"], keep=False)
    reason[dup[dup].index] = "duplicate"

    rejects: dict[str, list] = {}
    for pos in reason[reason.notna()].index:
        cat = reason[pos]
        detail = {"unknown_district": int(d.loc[pos, "district_id"]) if pd.notna(d.loc[pos, "district_id"]) else None,
                  "disallowed_source": d.loc[pos, "source"]}.get(cat, df.iloc[pos].to_dict() if cat != "duplicate" else
                                                                (int(d.loc[pos, "district_id"]), str(d.loc[pos, "date"].date())))
        rejects.setdefault(cat, []).append((int(d.loc[pos, "line"]), detail))
    ok = d[reason.isna()]
    records = [{"district_id": int(r.district_id), "date": r.date.date(), "rainfall_mm": float(r.rain), "source": str(r.source)} for r in ok.itertuples()]
    return records, rejects


def rejection_message(rejects: dict) -> str:
    parts = []
    for cat, items in rejects.items():
        extra = ""
        if cat == "unknown_district":
            extra = f": {sorted({d for _, d in items})}"
        elif cat == "disallowed_source":
            extra = f": {sorted({d for _, d in items})}"
        parts.append(f"{_MESSAGES.get(cat, cat)}{extra} [{len(items)} row(s), CSV lines {[ln for ln, _ in items[:5]]}]")
    return "; ".join(parts)


def diff_upsert(existing: dict, records: list):
    """existing: {(district_id, date): {'id', 'rainfall_mm', 'source'}}. Returns (inserts, updates, skipped_count)."""
    ins, upd, same = [], [], 0
    for r in records:
        old = existing.get((r["district_id"], r["date"]))
        if old is None:
            ins.append(r)
        elif old["rainfall_mm"] is not None and abs(old["rainfall_mm"] - r["rainfall_mm"]) < 1e-9 and old["source"] == r["source"]:
            same += 1
        else:
            upd.append({"id": old["id"], "rainfall_mm": r["rainfall_mm"], "source": r["source"]})
    return ins, upd, same


# ------------------------------------------------------------------ database layer (SQLAlchemy imported lazily) ------------------
def import_imd_rainfall(db, csv_path, replace=False, dry_run=False, approve_sources=(), skip_invalid=False):
    """Validate the CSV and upsert (default) or fully replace the IMD table, in ONE transaction. Returns a summary dict.

    Raises ValueError (ImportRejected for bad rows) before writing anything. With dry_run=True nothing is written.
    """
    from app.models import District, RainfallIMDRecent as T

    df = pd.read_csv(csv_path, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    valid_ids = {r[0] for r in db.query(District.id).all()}
    records, rejects = validate_frame(df, valid_ids, approve_sources)
    n_rejected = sum(len(v) for v in rejects.values())
    if rejects and not skip_invalid:
        raise ImportRejected(rejection_message(rejects) + ". Nothing was imported (use --skip-invalid to import only the valid rows).")
    if replace and not records:
        raise ImportRejected("--replace with no valid rows would empty the table; refusing. Nothing was changed.")

    existing = {(r.district_id, r.date): {"id": r.id, "rainfall_mm": r.rainfall_mm, "source": r.source} for r in db.query(T).all()}
    n_before = len(existing)
    if replace:
        ins, upd, skipped, deleted = records, [], 0, n_before
    else:
        (ins, upd, skipped), deleted = diff_upsert(existing, records), 0
    clean = pd.DataFrame(records) if records else pd.DataFrame(columns=["district_id", "date"])
    result = {"rows": len(records), "districts": int(clean["district_id"].nunique()),
              "first_date": str(min(clean["date"])) if records else None, "last_date": str(max(clean["date"])) if records else None,
              "mode": "replace" if replace else "upsert", "dry_run": bool(dry_run), "applied": False,
              "inserted": len(ins), "updated": len(upd), "skipped": skipped, "rejected": n_rejected, "deleted": deleted,
              "existing_before": n_before, "resulting": n_before - deleted + len(ins),
              "rejects": {k: v[:10] for k, v in rejects.items()}}
    if dry_run:
        db.rollback()                                                    # ends the read transaction; nothing was written
        return result
    try:
        if replace:
            db.query(T).delete(synchronize_session=False)               # only the separate IMD table
            _checkpoint("after_delete")
        for i in range(0, len(ins), 5000):
            db.bulk_insert_mappings(T, ins[i:i + 5000])
        _checkpoint("after_insert")
        for i in range(0, len(upd), 5000):
            db.bulk_update_mappings(T, upd[i:i + 5000])
        _checkpoint("before_commit")
        db.commit()
    except Exception:
        db.rollback()
        raise
    result["applied"] = True
    return result


def main(argv=None, session_factory=None):
    ap = argparse.ArgumentParser(description="Safe import of recent IMD rainfall (upsert by default).")
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--replace", action="store_true", help="explicit full replacement of rainfall_imd_recent (default is upsert)")
    ap.add_argument("--dry-run", action="store_true", help="validate and report only; write nothing")
    ap.add_argument("--allow-source", action="append", default=[], metavar="NAME", help=f"explicitly approve an extra source value (default only {EXPECTED_SOURCE})")
    ap.add_argument("--skip-invalid", action="store_true", help="import valid rows and count bad rows as rejected (default: any bad row stops the import)")
    ap.add_argument("--database", help="SQLite file to use instead of DATABASE_URL")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--backup-dir", default="backups")
    a = ap.parse_args(argv)

    csv_path = Path(a.csv)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 2
    if session_factory is None:
        from sqlalchemy.orm import sessionmaker
        if a.database:
            from sqlalchemy import create_engine
            if not os.path.isfile(a.database):
                print(f"ERROR: database file not found: {a.database}", file=sys.stderr)
                return 2
            eng = create_engine(f"sqlite:///{os.path.abspath(a.database)}")
        else:
            from app.database import engine as eng
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    db = session_factory()
    try:
        from sqlalchemy import inspect
        bind = db.get_bind()
        if a.dry_run:
            have = set(inspect(bind).get_table_names())
            if not {"districts", "rainfall_imd_recent"} <= have:
                print("ERROR: the database lacks the districts/rainfall_imd_recent tables; run scripts/seed_db.py first (dry-run never creates tables).", file=sys.stderr)
                return 2
        else:
            from app.database import Base
            import app.models  # noqa: F401  (registers tables)
            url = bind.url
            db_file = url.database if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:" else None
            if db_file and not a.no_backup and os.path.exists(db_file) and inspect(bind).get_table_names():
                import db_snapshot
                db.rollback()
                print(f"backup: {db_snapshot.create_backup(db_file, a.backup_dir, 'pre_imd')['backup']}")
            Base.metadata.create_all(bind=bind)                          # creates only missing tables
        r = import_imd_rainfall(db, csv_path, a.replace, a.dry_run, a.allow_source, a.skip_invalid)
    except ValueError as e:
        print(f"Rejected, nothing written: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"FAILED, transaction rolled back, nothing written: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    finally:
        db.close()
    print(("DRY-RUN (nothing written) " if r["dry_run"] else "IMD rainfall import successful ") + f"[{r['mode']}]")
    print(f"Rows in file (valid): {r['rows']} | inserted {r['inserted']} | updated {r['updated']} | skipped (unchanged) {r['skipped']} "
          f"| rejected {r['rejected']} | deleted {r['deleted']}")
    print(f"Table rows: {r['existing_before']} -> {r['resulting']} | districts {r['districts']} | dates {r['first_date']} to {r['last_date']}")
    for cat, items in r["rejects"].items():
        print(f"  rejected [{cat}] {len(items)}+ e.g. CSV lines {[ln for ln, _ in items[:5]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
