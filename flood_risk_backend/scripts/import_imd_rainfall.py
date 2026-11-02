"""Import recent IMD daily rainfall into its own table.

Safe to rerun: replaces only rainfall_imd_recent, never historical rainfall
or risk assessments.
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import District, RainfallIMDRecent  # noqa: E402


DEFAULT_CSV = Path(__file__).resolve().parents[1] / "data" / "rainfall_imd_recent.csv"


def import_imd_rainfall(db, csv_path):
    df = pd.read_csv(csv_path)

    required = {"district_id", "date", "rainfall_mm"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    df = df.copy()
    df["district_id"] = pd.to_numeric(df["district_id"], errors="raise").astype(int)
    df["date"] = pd.to_datetime(df["date"], errors="raise").dt.date
    df["rainfall_mm"] = pd.to_numeric(df["rainfall_mm"], errors="coerce")

    if df["rainfall_mm"].isna().any():
        raise ValueError("IMD CSV contains missing or invalid Daily Actual values.")
    if (df["rainfall_mm"] < 0).any():
        raise ValueError("Rainfall values cannot be negative.")
    if df.duplicated(["district_id", "date"]).any():
        raise ValueError("Duplicate district_id/date rows found in IMD CSV.")

    valid_ids = {row[0] for row in db.query(District.id).all()}
    unknown_ids = sorted(set(df["district_id"]) - valid_ids)
    if unknown_ids:
        raise ValueError(f"District IDs do not exist in the database: {unknown_ids}")

    if "source" in df.columns:
        df["source"] = df["source"].fillna("IMD_daily_actual_2026").astype(str)
    else:
        df["source"] = "IMD_daily_actual_2026"

    records = [
        RainfallIMDRecent(
            district_id=int(row.district_id),
            date=row.date,
            rainfall_mm=float(row.rainfall_mm),
            source=row.source,
        )
        for row in df.itertuples(index=False)
    ]

    try:
        # This deletes records only from the separate IMD table.
        db.query(RainfallIMDRecent).delete(synchronize_session=False)
        db.add_all(records)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "rows": len(records),
        "districts": df["district_id"].nunique(),
        "first_date": str(df["date"].min()),
        "last_date": str(df["date"].max()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = import_imd_rainfall(db, csv_path)
        print("IMD rainfall import successful")
        print(f"Rows: {result['rows']}")
        print(f"Districts: {result['districts']}")
        print(f"Date range: {result['first_date']} to {result['last_date']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
