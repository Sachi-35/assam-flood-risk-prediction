"""SAFE alternative to scripts/compute_assessments.py. Dry-run by default; writes only with --apply.

Why: compute_assessments.py DELETES every RiskAssessment (and Vulnerability) row first and commits per district, so a failure
part-way leaves the table emptied or half rebuilt. This script never deletes outside what you ask for, and writes in ONE transaction.

Behaviour
  * Default = DRY-RUN: computes everything, prints what would be inserted / updated / left unchanged, writes NOTHING.
  * --apply : upserts on (district_id, as_of_date, window_days) inside a single transaction; any error rolls back completely.
  * Rows outside the requested date range / windows are never touched.
  * --replace-range (with --apply): first deletes ALL assessment rows inside the requested range and windows, then inserts.
    Needs --confirm-replace-range (or typing REPLACE at the prompt). Without it nothing is written.
  * Vulnerability is NOT refreshed unless --refresh-vulnerability is given; otherwise the stored vulnerability table is used read-only.
    With the flag it is replaced as a whole inside the same transaction (same result as the original script, but atomic).
  * Methodology is unchanged: window sums, hazard levels, combine() and Unknown handling reuse app.services.hazard / risk_rules /
    labels / vulnerability exactly. Missing rain is never zero; Unknown is never Low.
  * Empirical history is the vulnerability source. The trained-model path is used ONLY if ALLOW_ML_VULNERABILITY=true (default false).
  * On --apply a verified backup of a SQLite file is made first (scripts/db_snapshot.py) unless --no-backup.
  * Never run against your real database until you have reviewed a dry-run and have a backup. This script does not create tables.

Usage
  python scripts/assess_safe.py --start 2023-06-01 --end 2023-06-30 --windows 3 7        # dry-run
  python scripts/assess_safe.py --start 2023-06-01 --end 2023-06-30 --apply              # upsert
  python scripts/assess_safe.py --start 2023-06-01 --end 2023-06-30 --apply --replace-range --confirm-replace-range
  python scripts/assess_safe.py --apply --refresh-vulnerability                          # range inferred from stored rainfall
  Optional: --database path/to/file.db   (default: DATABASE_URL / app config)
Exit codes: 0 ok, 2 refused or failed (nothing written).
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.services import hazard as H  # noqa: E402
from app.services.labels import MIN_HISTORY_YEARS, history_mean_index  # noqa: E402
from app.services.risk_rules import combine  # noqa: E402
from app.services.vulnerability import feature_row, history_vulnerability, ml_vulnerability  # noqa: E402

KEY = ("district_id", "as_of_date", "window_days")
ASSESS_FIELDS = ("window_rain_mm", "obs_fraction", "hazard_level", "status", "combined_class", "combined_score", "model_version")
VULN_FIELDS = ("source", "risk_class", "class_index", "expected_index", "proba", "shap_top_features", "model_version")
DEFAULT_MIN_OBS_FRACTION = 0.8          # same fallback as compute_assessments.py (only when hazard_config was not imported)
FALLBACK_WINDOWS = [3, 7, 15, 30]       # same as app.services.assessment.DEFAULT_WINDOWS


class Refused(Exception):
    """The request was refused before anything was written."""


def _checkpoint(name: str) -> None:
    """No-op hook between write steps; tests patch it to simulate a failure at that point."""


# ---------------------------------------------------------------- pure logic (no database) ----------------------------------------
def parse_range(start, end, rain_dates):
    """(lo, hi) as Timestamps. Defaults to the span of stored rainfall (like the original); with no rainfall both are required."""
    try:
        lo = pd.Timestamp(start) if start else None
        hi = pd.Timestamp(end) if end else None
    except (ValueError, TypeError) as e:
        raise Refused(f"invalid date: {e}")
    if rain_dates:
        lo = lo if lo is not None else min(rain_dates)
        hi = hi if hi is not None else max(rain_dates)
    elif lo is None or hi is None:
        raise Refused("No rainfall is stored, so there is no date range to infer: pass --start and --end.")
    if lo > hi:
        raise Refused("--start is after --end")
    return lo.normalize(), hi.normalize()


def check_windows(windows):
    if not windows or any((not isinstance(w, int)) or w <= 0 for w in windows):
        raise Refused("windows must be positive integers")
    return sorted(set(windows))


def build_assessment_rows(district_ids, rain, clim, vul, lo, hi, windows, min_obs, lq):
    """Same computation as compute_assessments.main, as a pure function.

    rain : {district_id: {Timestamp: mm_or_None}}     clim : {(district_id, window): DataFrame[doy, q50..q99]}
    vul  : {district_id: dict with class_index, expected_index, model_version} (absent = vulnerability unavailable)
    """
    days = pd.date_range(lo, hi, freq="D")
    out = []
    for d_id in district_ids:
        v = vul.get(d_id)
        if d_id in rain:
            s = pd.Series(rain[d_id], dtype="float64").sort_index()
            s = s.reindex(pd.date_range(min(s.index.min(), lo), max(s.index.max(), hi), freq="D"))   # gaps stay NaN, never 0
            for w in windows:
                q = clim.get((d_id, w))
                if q is None:
                    q = pd.DataFrame(columns=["doy"])
                sums = H.window_sums(s, w, min_obs)
                frac = H.obs_fractions(s, w)
                lv = H.levels_series(sums, q, lq) if len(q) else pd.Series(float("nan"), index=s.index)
                for t in days:
                    tot, h = sums.loc[t], lv.loc[t]
                    rec = {"district_id": d_id, "as_of_date": t.date(), "window_days": w,
                           "window_rain_mm": None if pd.isna(tot) else float(tot), "obs_fraction": float(frac.loc[t]),
                           "hazard_level": None if pd.isna(h) else int(h), "combined_class": None, "combined_score": None,
                           "model_version": None}
                    if pd.isna(tot):
                        rec["status"] = "insufficient_rainfall_data"
                    elif pd.isna(h):
                        rec["status"] = "no_climatology"
                    elif v is None:
                        rec["status"] = "vulnerability_unavailable"
                    else:
                        rec["combined_class"], rec["combined_score"] = combine(v["class_index"], v["expected_index"], int(h))
                        rec["model_version"], rec["status"] = v["model_version"], "ok"
                    out.append(rec)
        else:
            for w in windows:
                for t in days:
                    out.append({"district_id": d_id, "as_of_date": t.date(), "window_days": w, "window_rain_mm": None,
                                "obs_fraction": 0.0, "hazard_level": None, "combined_class": None, "combined_score": None,
                                "model_version": None, "status": "insufficient_rainfall_data"})
    return out


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)
        except (TypeError, ValueError):
            return False
    return a == b


def diff_assessments(existing: dict, planned: list):
    """existing: {(district_id, as_of_date, window_days): {'id':..., fields...}}. Returns (inserts, updates, unchanged_count)."""
    ins, upd, same = [], [], 0
    for rec in planned:
        k = (rec["district_id"], rec["as_of_date"], rec["window_days"])
        old = existing.get(k)
        if old is None:
            ins.append(rec)
        elif all(_same(old[f], rec[f]) for f in ASSESS_FIELDS):
            same += 1
        else:
            upd.append({"id": old["id"], **{f: rec[f] for f in ASSESS_FIELDS}})
    return ins, upd, same


def diff_vulnerabilities(old: dict, new: dict) -> dict:
    """old/new: {district_id: dict}. Counts only; used for reporting."""
    added = [d for d in new if d not in old]
    removed = [d for d in old if d not in new]
    changed = [d for d in new if d in old and not all(_same(old[d].get(f), new[d].get(f)) for f in VULN_FIELDS)]
    return {"added": sorted(added), "removed": sorted(removed), "changed": sorted(changed),
            "unchanged": len(new) - len(added) - len(changed)}


def plan_vulnerabilities(districts, labels_by_district, normal_seasons, meta, bundle, allow_ml):
    """Mirror of compute_assessments.compute_vulnerabilities WITHOUT deleting anything. Returns ({district_id: dict}, [missing notes]).

    The trained-model route is taken only when allow_ml is True (ALLOW_ML_VULNERABILITY); otherwise empirical history is used.
    """
    src = (meta or {}).get("vulnerability_source")
    out, missing = {}, []
    for d in districts:
        v, ns = None, normal_seasons.get(d.id)
        if allow_ml and src == "ml_model" and bundle is not None and ns is not None:
            try:
                v = ml_vulnerability(bundle, feature_row(ns, d), TOP_N())
            except ValueError as e:
                print(f"  ML vulnerability not possible for {d.name}: {e}")
        if v is None:
            mean, n = history_mean_index(labels_by_district.get(d.id, []))
            if mean is not None:
                v = history_vulnerability(mean)
            elif d.id not in labels_by_district and meta and str(d.id) in meta.get("district_history", {}):
                v = history_vulnerability(meta["district_history"][str(d.id)], meta.get("model_version"))
            else:
                missing.append(f"{d.name} ({n} known year(s), need {MIN_HISTORY_YEARS})")
        if v is not None:
            out[d.id] = v
    return out, missing


def TOP_N() -> int:
    from app.config import settings
    return settings.TOP_N_SHAP_FEATURES


# ---------------------------------------------------------------- database layer (SQLAlchemy imported lazily) -------------------
def _models():
    from app.models import (Climatology, District, FloodLabel, Meta, NormalSeason, RainfallDaily, RiskAssessment,
                            Vulnerability)
    return dict(Climatology=Climatology, District=District, FloodLabel=FloodLabel, Meta=Meta, NormalSeason=NormalSeason,
                RainfallDaily=RainfallDaily, RiskAssessment=RiskAssessment, Vulnerability=Vulnerability)


def _require_tables(db):
    from sqlalchemy import inspect
    need = {"districts", "risk_assessments", "vulnerabilities", "rainfall_daily", "climatology", "meta", "flood_labels", "normal_seasons"}
    have = set(inspect(db.get_bind()).get_table_names())
    if need - have:
        raise Refused(f"database is missing table(s) {sorted(need - have)}; this script never creates tables (run seed_db.py on a COPY first)")


def _load(db, m):
    districts = db.query(m["District"]).order_by(m["District"].id).all()
    meta = {r.key: r.value for r in db.query(m["Meta"]).all()}
    cfg = meta.get("hazard_config")
    labels = {}
    for r in db.query(m["FloodLabel"]).all():
        labels.setdefault(r.district_id, []).append(r)
    rain = {}
    for d_id, dt, mm in db.query(m["RainfallDaily"].district_id, m["RainfallDaily"].date, m["RainfallDaily"].rainfall_mm).all():
        rain.setdefault(d_id, {})[pd.Timestamp(dt)] = mm
    return districts, cfg, labels, rain, {r.district_id: r.features for r in db.query(m["NormalSeason"]).all()}


def _load_climatology(db, m, district_ids, windows):
    C = m["Climatology"]
    rows = {}
    for r in db.query(C).filter(C.district_id.in_(district_ids), C.window_days.in_(windows)).all():
        rows.setdefault((r.district_id, r.window_days), []).append({"doy": r.doy, **{k: getattr(r, k) for k in ("q50", "q75", "q90", "q95", "q97", "q99")}})
    return {k: pd.DataFrame(v) for k, v in rows.items()}


def _existing_in_range(db, m, lo, hi, windows):
    R = m["RiskAssessment"]
    q = db.query(R).filter(R.as_of_date >= lo.date(), R.as_of_date <= hi.date(), R.window_days.in_(windows))
    return {(r.district_id, r.as_of_date, r.window_days): {"id": r.id, **{f: getattr(r, f) for f in ASSESS_FIELDS}} for r in q.all()}


def _vuln_row(v) -> dict:
    return {f: getattr(v, f) for f in VULN_FIELDS}


def run_assessment(db, start=None, end=None, windows=None, apply=False, replace_range=False, confirm_replace_range=False,
                   refresh_vulnerability=False, allow_ml=None, out=print) -> dict:
    """Plan (always) and write (only if apply). Returns a summary dict. Raises Refused before any write if the request is unsafe."""
    from app.config import settings
    from app.services.model_loader import get_model_bundle, read_metadata
    m = _models()
    _require_tables(db)
    if replace_range and apply and not confirm_replace_range:
        raise Refused("--replace-range deletes existing assessment rows in the range; add --confirm-replace-range to proceed. Nothing was written.")
    allow_ml = settings.ALLOW_ML_VULNERABILITY if allow_ml is None else allow_ml

    districts, cfg, labels, rain, normal = _load(db, m)
    windows = check_windows(windows or (cfg or {}).get("windows") or FALLBACK_WINDOWS)
    min_obs = (cfg or {}).get("min_obs_fraction", DEFAULT_MIN_OBS_FRACTION)
    lq = (cfg or {}).get("level_quantiles", [0.75, 0.9, 0.97])
    lo, hi = parse_range(start, end, [t for r in rain.values() for t in r])
    if cfg is None:
        out("NOTE: hazard_config not imported: rain hazard cannot be computed; rows carry observed totals only.")

    stored_vul = {r.district_id: _vuln_row(r) for r in db.query(m["Vulnerability"]).all()}
    vul_notes = None
    if refresh_vulnerability:
        new_vul, missing = plan_vulnerabilities(districts, labels, normal, read_metadata(), get_model_bundle(), allow_ml)
        vul_notes = diff_vulnerabilities(stored_vul, new_vul)
        vul_used, vul_missing = new_vul, missing
    else:
        vul_used, vul_missing = stored_vul, []
        if not stored_vul:
            out("NOTE: no stored vulnerability and --refresh-vulnerability not given: combined stays 'vulnerability_unavailable'.")

    planned = build_assessment_rows([d.id for d in districts], rain, _load_climatology(db, m, [d.id for d in districts], windows),
                                    vul_used, lo, hi, windows, min_obs, lq)
    existing = _existing_in_range(db, m, lo, hi, windows)
    ins, upd, same = diff_assessments(existing, planned)
    planned_keys = {(r["district_id"], r["as_of_date"], r["window_days"]) for r in planned}
    to_delete = len(existing) if replace_range else 0
    if replace_range:                     # replacement = delete the whole range, then insert everything planned
        ins, upd, same = planned, [], 0
    status_counts = pd.Series([r["status"] for r in planned]).value_counts().to_dict()

    summary = {"applied": False, "range": (str(lo.date()), str(hi.date())), "windows": windows, "planned_rows": len(planned),
               "inserted": len(ins), "updated": len(upd), "unchanged": same, "deleted": to_delete,
               "existing_in_range": len(existing), "stale_in_range_not_in_plan": len(set(existing) - planned_keys),
               "status_counts": status_counts, "vulnerability": vul_notes, "vulnerability_unavailable": vul_missing}
    out(f"{'APPLY' if apply else 'DRY-RUN'} | range {summary['range'][0]}..{summary['range'][1]} | windows {windows} | "
        f"mode {'replace-range' if replace_range else 'upsert'}")
    out(f"  planned {len(planned)} | insert {len(ins)} | update {len(upd)} | unchanged {same} | delete {to_delete} "
        f"| stale rows left in place {summary['stale_in_range_not_in_plan'] if not replace_range else 0}")
    out(f"  status: {status_counts}")
    if vul_notes is not None:
        out(f"  vulnerability refresh: +{len(vul_notes['added'])} changed {len(vul_notes['changed'])} removed {len(vul_notes['removed'])} "
            f"unchanged {vul_notes['unchanged']}; unavailable {len(vul_missing)}")
    if not apply:
        out("  DRY-RUN: nothing was written. Re-run with --apply to write.")
        return summary

    R, V = m["RiskAssessment"], m["Vulnerability"]
    try:                                                              # ONE transaction: all or nothing
        if replace_range:
            db.query(R).filter(R.as_of_date >= lo.date(), R.as_of_date <= hi.date(), R.window_days.in_(windows)).delete(synchronize_session=False)
            _checkpoint("after_range_delete")
        if refresh_vulnerability:
            db.query(V).delete(synchronize_session=False)
            _checkpoint("after_vulnerability_delete")
            db.bulk_insert_mappings(V, [{"district_id": d, **v} for d, v in vul_used.items()])
            _checkpoint("after_vulnerability_insert")
        for i in range(0, len(ins), 5000):
            db.bulk_insert_mappings(R, ins[i:i + 5000])
        _checkpoint("after_assessment_insert")
        for i in range(0, len(upd), 5000):
            db.bulk_update_mappings(R, upd[i:i + 5000])
        _checkpoint("after_assessment_update")
        db.commit()
    except Exception:
        db.rollback()
        raise
    summary["applied"] = True
    out("  committed.")
    return summary


# ---------------------------------------------------------------- command line --------------------------------------------------------
def _sqlite_file(db) -> str | None:
    url = db.get_bind().url
    return url.database if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:" else None


def main(argv=None, session_factory=None, confirm_input=input) -> int:
    ap = argparse.ArgumentParser(description="Safe assessment (re)computation. Dry-run unless --apply.")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--windows", type=int, nargs="*")
    ap.add_argument("--apply", action="store_true", help="write changes (default is dry-run)")
    ap.add_argument("--replace-range", action="store_true", help="with --apply: delete existing rows in range+windows first")
    ap.add_argument("--confirm-replace-range", action="store_true", help="explicit confirmation for --replace-range")
    ap.add_argument("--refresh-vulnerability", action="store_true", help="also recompute the vulnerabilities table (replaced atomically)")
    ap.add_argument("--database", help="SQLite file to use instead of DATABASE_URL")
    ap.add_argument("--no-backup", action="store_true", help="skip the automatic pre-write backup (SQLite files only)")
    ap.add_argument("--backup-dir", default="backups")
    a = ap.parse_args(argv)

    if a.replace_range and a.apply and not a.confirm_replace_range:
        print("--replace-range will DELETE existing assessment rows in the requested range and windows.")
        try:
            ok = confirm_input("Type REPLACE to confirm: ").strip() == "REPLACE"
        except EOFError:
            ok = False
        if not ok:
            print("Refused: not confirmed. Nothing was written.", file=sys.stderr)
            return 2
        a.confirm_replace_range = True

    if session_factory is None:
        if a.database:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            if not os.path.isfile(a.database):
                print(f"ERROR: database file not found: {a.database}", file=sys.stderr)
                return 2
            session_factory = sessionmaker(autocommit=False, autoflush=False, bind=create_engine(f"sqlite:///{os.path.abspath(a.database)}"))
        else:
            from app.database import SessionLocal as session_factory
    db = session_factory()
    try:
        if a.apply and not a.no_backup and _sqlite_file(db):
            import db_snapshot
            db.rollback()
            info = db_snapshot.create_backup(_sqlite_file(db), a.backup_dir, "pre_assess")
            print(f"backup: {info['backup']}")
        run_assessment(db, a.start, a.end, a.windows, a.apply, a.replace_range, a.confirm_replace_range, a.refresh_vulnerability)
        return 0
    except Refused as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"FAILED, transaction rolled back, nothing written: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    sys.exit(main())
