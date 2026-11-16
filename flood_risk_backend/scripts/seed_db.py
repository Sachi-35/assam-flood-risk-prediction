"""Creates missing tables and loads whatever the data-prep export provides from data/. TRANSACTIONAL: all tables change together or not at all.

Required : districts.csv                (id, name, state, geometry [GeoJSON Polygon/MultiPolygon string], terrain columns, pop_density_km2)
Optional : flood_labels.csv             historical seasonal flood impact per district-year (see README for columns)
           season_features.csv          only used to fill a missing impact CLASS in flood_labels.csv, or as labels if flood_labels.csv is absent
           rainfall_daily.csv           district_id, date, rainfall_mm, n_stations   (blank rainfall_mm stays NULL: missing is NOT zero)
           climatology.csv, normal_season_features.csv, hazard_config.json, label_thresholds.json
Replacement semantics (unchanged): a missing optional file is reported and SKIPPED (the table keeps what it holds); a present file REPLACES
its table, so running twice gives the same database. Districts are upserted by id and never deleted. It never computes assessments and
never touches tables it does not seed (risk_assessments, vulnerabilities, rainfall_imd_recent, ...).

What is new
  * One transaction: if any table fails, EVERYTHING is rolled back (SystemExit from a loader included).
  * Prints existing / incoming / resulting row counts per table.
  * --dry-run does all the work, prints the counts, then rolls back. Nothing is written (if the tables do not exist yet it uses a throw-away
    in-memory database, so the target file is not even created).
  * Normal seeding never drops anything. On a SQLite file that already has tables, a verified backup is made first (scripts/db_snapshot.py)
    unless --no-backup.
  * The data folder is validated first (scripts/validate_data.py); ERRORs stop the seed unless --skip-validation.
  * --reset is protected: it needs --confirm-reset <exact db path> AND an EMPTY database (zero rows in every table). A database that holds
    data is treated as real and is never reset. It drops only this app's tables.

Usage:
  python scripts/seed_db.py --dry-run
  python scripts/seed_db.py                  # normal, repeatable
  python scripts/seed_db.py --database path/to/copy.db
  python scripts/seed_db.py --reset --confirm-reset path/to/empty.db        # only for an empty/new database
"""
import argparse
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.features import QUANTILE_COLS, SEASON_FEATURES  # noqa: E402
from app.models import Climatology, District, FloodLabel, Meta, NormalSeason, RainfallDaily  # noqa: E402
from app.services.labels import prepare_labels  # noqa: E402
from seed_safety import ResetRefused, check_reset_allowed, format_count_table  # noqa: E402

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


def load_districts(db, stats=None):
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
    db.flush()
    if stats is not None:
        stats["districts"] = len(d)
    print(f"districts: {len(d)} loaded/updated" + ("" if len(d) == EXPECTED_DISTRICTS else f"  (WARNING: expected {EXPECTED_DISTRICTS})"))
    n_geom = {t: sum(1 for g in parsed.values() if g.get("type") == t) for t in ("Polygon", "MultiPolygon")}
    print(f"  geometries: {n_geom}; terrain missing for {int(d[[c for c in TERRAIN[:4] if c in d.columns]].isna().any(axis=1).sum()) if any(c in d.columns for c in TERRAIN[:4]) else len(d)} district(s)")
    for w in warn:
        print(f"  GEOMETRY WARNING (stored as given, may not draw): {w}")
    return {int(r["id"]): r["name"] for _, r in d.iterrows()}


def load_labels(db, names, stats=None):
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
    if stats is not None:
        stats["flood_labels"] = len(recs)
    by = pd.Series([r["status"] for r in recs]).value_counts().to_dict()
    print(f"flood labels: {len(recs)} district-years from {src}: {by}; years {sorted({r['year'] for r in recs})}")
    for p in problems:
        print(f"  LABEL NOTE: {p}")


def load_rainfall(db, ids, stats=None):
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
    if stats is not None:
        stats["rainfall_daily"] = len(recs)
    print(f"rainfall_daily: {len(recs)} rows for {rain['district_id'].nunique()} district(s) "
          f"({int(rain['rainfall_mm'].isna().sum())} missing values kept as NULL, not zero)")


def load_climatology(db, ids, stats=None):
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
    if stats is not None:
        stats["climatology"] = len(recs)
    print(f"climatology: {len(recs)} rows")


def load_normal_seasons(db, ids, stats=None):
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
    db.flush()
    if stats is not None:
        stats["normal_seasons"] = len(ns)
    print(f"normal seasons: {len(ns)} districts")


def load_meta(db, stats=None):
    n = 0
    for key, fn in (("hazard_config", "hazard_config.json"), ("label_thresholds", "label_thresholds.json")):
        if os.path.exists(path(fn)):
            with open(path(fn)) as f:
                db.merge(Meta(key=key, value=json.load(f)))
            n += 1
            print(f"{key}: loaded")
        else:
            print(f"{key}: SKIPPED (data/{fn} not found)")
    db.flush()
    if stats is not None and n:
        stats["meta"] = n


SEEDED_TABLES = {"districts": District, "flood_labels": FloodLabel, "rainfall_daily": RainfallDaily,
                 "climatology": Climatology, "normal_seasons": NormalSeason, "meta": Meta}
MODES = {"districts": "upserted by id (never deleted)", "meta": "upserted by key", "flood_labels": "REPLACED", "rainfall_daily": "REPLACED",
         "climatology": "REPLACED", "normal_seasons": "REPLACED"}


def table_counts(db) -> dict[str, int]:
    from sqlalchemy import func
    return {name: db.query(func.count()).select_from(model).scalar() for name, model in SEEDED_TABLES.items()}


def seed_all(db, commit=True, dry_run=False, report=None):
    """Load every available file into `db` in ONE transaction and return {district_id: name}.

    * Any failure (including SystemExit from a loader) rolls back everything; nothing is half-loaded.
    * dry_run=True: do the work, print the counts, then roll back (nothing is written).
    * commit=False: leave the transaction open for the caller (tests, larger operations).
    * Calling it twice leaves the database unchanged (no duplicates). `report` (a dict) receives before/incoming/after counts.
    """
    stats: dict[str, int] = {}
    try:
        before = table_counts(db)
        names = load_districts(db, stats)
        load_labels(db, names, stats)
        load_rainfall(db, set(names), stats)
        load_climatology(db, set(names), stats)
        load_normal_seasons(db, set(names), stats)
        load_meta(db, stats)
        after = table_counts(db)
        print("\nRow counts (existing -> incoming -> resulting):")
        print(format_count_table(before, {t: stats.get(t) for t in before}, after, MODES))
        if report is not None:
            report.update(before=before, incoming=dict(stats), after=after, dry_run=dry_run)
        if dry_run:
            db.rollback()
            print("DRY-RUN: all changes were rolled back; nothing was written.")
        elif commit:
            db.commit()
    except BaseException:
        db.rollback()
        raise
    return names


def _sqlite_file(engine):
    u = engine.url
    return u.database if u.get_backend_name() == "sqlite" and u.database and u.database != ":memory:" else None


def _has_all_tables(engine) -> bool:
    from sqlalchemy import inspect
    have = set(inspect(engine).get_table_names())
    return {m.__tablename__ for m in SEEDED_TABLES.values()} <= have


def main(argv=None, engine_override=None) -> int:
    ap = argparse.ArgumentParser(description="Transactional seed of the database from data/. Never drops tables unless --reset is fully confirmed.")
    ap.add_argument("--dry-run", action="store_true", help="do everything, print counts, roll back: nothing is written")
    ap.add_argument("--reset", action="store_true", help="drop this app's tables first (protected: empty database + --confirm-reset only)")
    ap.add_argument("--confirm-reset", metavar="DB_PATH", help="the exact database file path, required by --reset")
    ap.add_argument("--database", help="SQLite file to use instead of DATABASE_URL")
    ap.add_argument("--create-db", action="store_true", help="allow --database to name a file that does not exist yet")
    ap.add_argument("--no-backup", action="store_true", help="skip the automatic pre-seed backup")
    ap.add_argument("--backup-dir", default="backups")
    ap.add_argument("--skip-validation", action="store_true", help="do not run scripts/validate_data.py first")
    a = ap.parse_args(argv)

    from sqlalchemy.orm import sessionmaker
    eng = engine_override
    if eng is None and a.database:
        from sqlalchemy import create_engine
        if not os.path.exists(a.database) and not a.create_db:
            print(f"ERROR: database file not found: {a.database} (use --create-db to create a new one)", file=sys.stderr)
            return 2
        eng = create_engine(f"sqlite:///{os.path.abspath(a.database)}", connect_args={"check_same_thread": False})
    eng = eng or engine
    db_file = _sqlite_file(eng)
    print(f"Target database: {db_file or eng.url}")

    if not a.skip_validation:
        import validate_data
        rep = validate_data.validate(DATA_DIR, db_path=db_file if db_file and os.path.exists(db_file) else None)
        print(validate_data.format_report(rep, DATA_DIR))
        if rep.n("ERROR"):
            print("Refused: the data failed validation. Nothing was written. (Fix the data, or use --skip-validation if you accept the risk.)", file=sys.stderr)
            return 2

    try:
        if a.reset:
            check_reset_allowed(db_file, a.confirm_reset)             # raises before anything is dropped
            if a.dry_run:
                print("DRY-RUN: --reset is allowed here (empty database); would drop this app's tables. Nothing dropped.")
            else:
                print("Dropping this app's tables (--reset; database is empty)...")
                Base.metadata.drop_all(bind=eng)
    except ResetRefused as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2

    try:
        if a.dry_run and not _has_all_tables(eng):
            from sqlalchemy import create_engine
            print("NOTE: the target has no tables yet; dry-run uses a throw-away in-memory database (existing counts shown as 0).")
            eng = create_engine("sqlite://")
            Base.metadata.create_all(bind=eng)
        elif not a.dry_run:
            if db_file and not a.no_backup and os.path.exists(db_file):
                from sqlalchemy import inspect
                if inspect(eng).get_table_names():
                    import db_snapshot
                    info = db_snapshot.create_backup(db_file, a.backup_dir, "pre_seed")
                    print(f"backup: {info['backup']}")
            Base.metadata.create_all(bind=eng)                          # only creates MISSING tables; never alters or drops
        db = sessionmaker(autocommit=False, autoflush=False, bind=eng)()
        try:
            seed_all(db, dry_run=a.dry_run)
        finally:
            db.close()
    except SystemExit as e:
        print(f"Seed failed, everything rolled back: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Seed failed, everything rolled back: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if not a.dry_run:
        print("Done. Next: python scripts/assess_safe.py --start YYYY-MM-DD --end YYYY-MM-DD   (dry-run first)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
