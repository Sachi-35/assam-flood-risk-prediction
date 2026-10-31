"""Creates the tables and loads the data-prep export from data/ into the database.

Loads: districts.csv, rainfall_daily.csv, climatology.csv, normal_season_features.csv, hazard_config.json, label_thresholds.json.
Does NOT compute assessments (scripts/compute_assessments.py does, after train_model.py).

Usage:  python scripts/seed_db.py --reset
"""
import argparse
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.features import QUANTILE_COLS, SEASON_FEATURES  # noqa: E402
from app.models import Climatology, District, Meta, NormalSeason, RainfallDaily  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def need(name):
    p = os.path.join(DATA_DIR, name)
    if not os.path.exists(p):
        raise SystemExit(f"data/{name} not found. Copy the files from flood_data_prep/data/backend_export/ into data/ first.")
    return p


def nn(v):
    return None if pd.isna(v) else float(v)


def bulk(db, model, records, chunk=5000):
    for i in range(0, len(records), chunk):
        db.bulk_insert_mappings(model, records[i:i + chunk])
        db.commit()


def main(reset=False):
    if reset:
        print("Dropping all tables...")
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(District).count() and not reset:
            raise SystemExit("Database already seeded; use --reset to reload.")
        d = pd.read_csv(need("districts.csv"))
        for _, r in d.iterrows():
            json.loads(r["geometry"])
            db.add(District(id=int(r["id"]), name=r["name"], state=r["state"], geometry=r["geometry"],
                            mean_elevation_m=float(r["mean_elevation_m"]), elevation_std_m=float(r["elevation_std_m"]),
                            mean_slope_deg=float(r["mean_slope_deg"]), low_lying_frac=float(r["low_lying_frac"]),
                            pop_density_km2=nn(r.get("pop_density_km2"))))
        db.commit()
        ids = set(d["id"].astype(int))
        print(f"districts: {len(d)}")

        rain = pd.read_csv(need("rainfall_daily.csv"), parse_dates=["date"])
        rain = rain[rain["district_id"].isin(ids)]
        recs = [{"district_id": int(a), "date": b.date(), "rainfall_mm": nn(c), "n_stations": None if pd.isna(e) else int(e)}
                for a, b, c, e in zip(rain["district_id"], rain["date"], rain["rainfall_mm"], rain["n_stations"])]
        bulk(db, RainfallDaily, recs)
        print(f"rainfall_daily: {len(recs)} rows ({int(rain['rainfall_mm'].isna().sum())} missing values kept as NULL, not zero)")

        cl = pd.read_csv(need("climatology.csv"))
        recs = [{"district_id": int(r["district_id"]), "window_days": int(r["window_days"]), "doy": int(r["doy"]),
                 "n_values": int(r["n_values"]),
                 "n_years": int(r["n_years"]) if "n_years" in cl.columns and pd.notna(r.get("n_years")) else None, **{q: nn(r.get(q)) for q in QUANTILE_COLS}} for _, r in cl.iterrows()]
        bulk(db, Climatology, recs)
        print(f"climatology: {len(recs)} rows")

        ns = pd.read_csv(need("normal_season_features.csv"))
        for _, r in ns.iterrows():
            db.add(NormalSeason(district_id=int(r["district_id"]),
                                features={k: (None if pd.isna(r[k]) else float(r[k])) for k in SEASON_FEATURES if k in ns.columns}))
        db.commit()
        for key, fn in (("hazard_config", "hazard_config.json"), ("label_thresholds", "label_thresholds.json")):
            p = os.path.join(DATA_DIR, fn)
            if os.path.exists(p):
                db.add(Meta(key=key, value=json.load(open(p))))
        db.commit()
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    main(ap.parse_args().reset)
