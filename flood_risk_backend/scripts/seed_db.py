"""Creates the tables and loads whatever the data-prep export provides from data/. Safe to run repeatedly.

Required : districts.csv                (id, name, state, geometry [GeoJSON Polygon/MultiPolygon string], terrain columns, pop_density_km2)
Optional : flood_labels.csv             historical seasonal flood impact per district-year (see README for columns)
           season_features.csv          only used to fill a missing impact CLASS in flood_labels.csv, or as labels if flood_labels.csv is absent
           rainfall_daily.csv           district_id, date, rainfall_mm, n_stations   (blank rainfall_mm stays NULL: missing is NOT zero)
           climatology.csv, normal_season_features.csv, hazard_config.json, label_thresholds.json
A missing optional file is reported and SKIPPED (the table keeps whatever it already holds). A present file REPLACES its table, so
running the script twice gives the same database and never duplicates rows. Districts are upserted by id.
It never computes assessments (scripts/compute_assessments.py does).

Usage:
  python scripts/seed_db.py            # normal, repeatable
  python scripts/seed_db.py --reset    # drops ALL tables first (only needed once if you upgrade from the previous schema)
"""
import argparse
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.features import QUANTILE_COLS, SEASON_FEATURES  # noqa: E402
from app.models import Climatology, District, FloodLabel, Meta, NormalSeason, RainfallDaily  # noqa: E402
from app.services.labels import prepare_labels  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TERRAIN = ["mean_elevation_m", "elevation_std_m", "mean_slope_deg", "low_lying_frac", "pop_density_km2"]
EXPECTED_DISTRICTS = 33


def path(name):
    return os.path.join(DATA_DIR, name)


def nn(v):
    return None if v is None or pd.isna(v) else float(v)


def bulk(db, model, records, chunk=5000):
    for i in range(0, len(records), chunk):
        db.bulk_insert_mappings(model, records[i:i + chunk])
    db.flush()


def _ring_problem(ring):
    if not isinstance(ring, list) or len(ring) < 4:
        return "a ring has fewer than 4 points"
    if ring[0] != ring[-1]:
        return "a ring is not closed"
    return None


def geometry_problems(g) -> list[str]:
    """Problems that would stop the map drawing the district. Reported loudly; the geometry is still stored as given."""
    if not isinstance(g, dict) or g.get("type") not in ("Polygon", "MultiPolygon"):
        return [f"geometry type {g.get('type') if isinstance(g, dict) else type(g).__name__!r} is not Polygon/MultiPolygon"]
    polys = [g.get("coordinates")] if g["type"] == "Polygon" else (g.get("coordinates") or [])
    if not polys:
        return ["no polygons"]
    out = []
    for poly in polys:
        if not isinstance(poly, list) or not poly:
            out.append("a polygon has no rings")
            continue
        out += [p for p in (_ring_problem(r) for r in poly) if p]
    return sorted(set(out))


def load_districts(db):
    p = path("districts.csv")
    if not os.path.exists(p):
        raise SystemExit("data/districts.csv not found. Copy it from flood_data_prep/data/backend_export/ into data/ first.")
    d = pd.read_csv(p)
    need = {"id", "name", "state", "geometry"}
    if need - set(d.columns):
        raise SystemExit(f"districts.csv is missing column(s): {sorted(need - set(d.columns))}")
    if d["id"].duplicated().any():
        raise SystemExit(f"districts.csv has duplicate ids: {sorted(d.loc[d['id'].duplicated(), 'id'].astype(int))}")
    parsed, fatal, warn = {}, [], []
    for _, r in d.iterrows():
        try:
            g = json.loads(r["geometry"])
        except (TypeError, ValueError) as e:
            fatal.append(f"{r['name']} (id {r['id']}): geometry is not valid JSON ({e})")
            continue
        parsed[int(r["id"])] = g
        for pr in geometry_problems(g):
            warn.append(f"{r['name']} (id {r['id']}): {pr}")
    if fatal:
        raise SystemExit("Cannot load districts (nothing was changed):\n  " + "\n  ".join(fatal))
    for _, r in d.iterrows():
        vals = {k: (nn(r[k]) if k in d.columns else None) for k in TERRAIN}
        db.merge(District(id=int(r["id"]), name=r["name"], state=r["state"], geometry=json.dumps(parsed[int(r["id"])]), **vals))
    db.commit()
    print(f"districts: {len(d)} loaded/updated" + ("" if len(d) == EXPECTED_DISTRICTS else f"  (WARNING: expected {EXPECTED_DISTRICTS})"))
    n_geom = {t: sum(1 for g in parsed.values() if g.get("type") == t) for t in ("Polygon", "MultiPolygon")}
    print(f"  geometries: {n_geom}; terrain missing for {int(d[[c for c in TERRAIN[:4] if c in d.columns]].isna().any(axis=1).sum()) if any(c in d.columns for c in TERRAIN[:4]) else len(d)} district(s)")
    for w in warn:
        print(f"  GEOMETRY WARNING (stored as given, may not draw): {w}")
    return {int(r["id"]): r["name"] for _, r in d.iterrows()}


def load_labels(db, names):
    lp, sp = path("flood_labels.csv"), path("season_features.csv")
    fallback = None
    if os.path.exists(sp):
        sf = pd.read_csv(sp)
        if {"district_id", "year", "risk_class"} <= set(sf.columns):
            fallback = {(int(a), int(b)): c for a, b, c in zip(sf["district_id"], sf["year"], sf["risk_class"]) if pd.notna(c)}
    if os.path.exists(lp):
        df, src = pd.read_csv(lp), "flood_labels.csv"
    elif fallback:
        df = pd.DataFrame([{"district_id": k[0], "year": k[1], "impact_class": c,
                            "caveats": "Class only, taken from season_features.csv; the source count (including any explicit zero) is not in that file"}
                           for k, c in fallback.items()])
        src, fallback = "season_features.csv (no flood_labels.csv found; classes only, no counts)", None
    else:
        print("flood labels: SKIPPED (neither data/flood_labels.csv nor data/season_features.csv found; the flood-impact endpoint will return empty lists)")
        return
    try:
        recs, problems = prepare_labels(df, names, fallback)
    except ValueError as e:
        raise SystemExit(f"{src}: {e}")
    db.query(FloodLabel).delete()
    bulk(db, FloodLabel, recs)
    db.commit()
    by = pd.Series([r["status"] for r in recs]).value_counts().to_dict()
    print(f"flood labels: {len(recs)} district-years from {src}: {by}; years {sorted({r['year'] for r in recs})}")
    for p in problems:
        print(f"  LABEL NOTE: {p}")


def load_rainfall(db, ids):
    p = path("rainfall_daily.csv")
    if not os.path.exists(p):
        print("rainfall_daily: SKIPPED (data/rainfall_daily.csv not found; rain hazard will be unknown everywhere)")
        return
    rain = pd.read_csv(p, parse_dates=["date"])
    keep = rain["district_id"].isin(ids)
    if (~keep).any():
        print(f"  NOTE: {int((~keep).sum())} rainfall rows ignored: district_id not in districts ({sorted(rain.loc[~keep, 'district_id'].unique())[:10]})")
    rain = rain[keep]
    dup = rain.duplicated(["district_id", "date"], keep="last")
    if dup.any():
        print(f"  NOTE: {int(dup.sum())} duplicate district-date rows; the last one is kept")
        rain = rain[~dup]
    if "n_stations" not in rain.columns:
        rain = rain.assign(n_stations=pd.NA)
    recs = [{"district_id": int(a), "date": b.date(), "rainfall_mm": nn(c), "n_stations": None if pd.isna(e) else int(e)}
            for a, b, c, e in zip(rain["district_id"], rain["date"], rain["rainfall_mm"], rain["n_stations"])]
    db.query(RainfallDaily).delete()
    bulk(db, RainfallDaily, recs)
    db.commit()
    print(f"rainfall_daily: {len(recs)} rows for {rain['district_id'].nunique()} district(s) "
          f"({int(rain['rainfall_mm'].isna().sum())} missing values kept as NULL, not zero)")


def load_climatology(db, ids):
    p = path("climatology.csv")
    if not os.path.exists(p):
        print("climatology: SKIPPED (data/climatology.csv not found; hazard levels cannot be computed)")
        return
    cl = pd.read_csv(p)
    cl = cl[cl["district_id"].isin(ids)]
    recs = [{"district_id": int(r["district_id"]), "window_days": int(r["window_days"]), "doy": int(r["doy"]),
             "n_values": None if pd.isna(r.get("n_values")) else int(r["n_values"]),
             "n_years": int(r["n_years"]) if "n_years" in cl.columns and pd.notna(r.get("n_years")) else None,
             **{q: nn(r.get(q)) for q in QUANTILE_COLS}} for _, r in cl.iterrows()]
    db.query(Climatology).delete()
    bulk(db, Climatology, recs)
    db.commit()
    print(f"climatology: {len(recs)} rows")


def load_normal_seasons(db, ids):
    p = path("normal_season_features.csv")
    if not os.path.exists(p):
        print("normal seasons: SKIPPED (data/normal_season_features.csv not found; the ML vulnerability cannot be evaluated, history is used)")
        return
    ns = pd.read_csv(p)
    ns = ns[ns["district_id"].isin(ids)]
    db.query(NormalSeason).delete()
    for _, r in ns.iterrows():
        db.add(NormalSeason(district_id=int(r["district_id"]),
                            features={k: nn(r[k]) for k in SEASON_FEATURES if k in ns.columns}))
    db.commit()
    print(f"normal seasons: {len(ns)} districts")


def load_meta(db):
    for key, fn in (("hazard_config", "hazard_config.json"), ("label_thresholds", "label_thresholds.json")):
        if os.path.exists(path(fn)):
            with open(path(fn)) as f:
                db.merge(Meta(key=key, value=json.load(f)))
            print(f"{key}: loaded")
        else:
            print(f"{key}: SKIPPED (data/{fn} not found)")
    db.commit()


def seed_all(db):
    """Load every available file into `db`. Calling it twice leaves the database unchanged (no duplicates)."""
    names = load_districts(db)
    load_labels(db, names)
    load_rainfall(db, set(names))
    load_climatology(db, set(names))
    load_normal_seasons(db, set(names))
    load_meta(db)
    return names


def main(reset=False):
    if reset:
        print("Dropping all tables (--reset)...")
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_all(db)
        print("Done. Next: python scripts/compute_assessments.py --start YYYY-MM-DD --end YYYY-MM-DD")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop all tables first (needed once when upgrading from the previous schema)")
    main(ap.parse_args().reset)
