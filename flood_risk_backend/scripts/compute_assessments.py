"""Computes vulnerability per district and the hazard/combined assessment for every date and window in a range.

Run after seed_db.py (and train_model.py). Without a trained model, vulnerability falls back to metadata history if present, else
assessments are stored with status 'vulnerability_unavailable' (hazard only).

Usage:  python scripts/compute_assessments.py [--start 2019-01-01] [--end 2023-12-31] [--windows 3 7 15 30]
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Climatology, District, NormalSeason, RainfallDaily, RiskAssessment, Vulnerability  # noqa: E402
from app.services import hazard as H  # noqa: E402
from app.services.assessment import hazard_config  # noqa: E402
from app.services.model_loader import get_model_bundle, read_metadata  # noqa: E402
from app.services.risk_rules import combine  # noqa: E402
from app.services.vulnerability import feature_row, history_vulnerability, ml_vulnerability  # noqa: E402
from app.config import settings  # noqa: E402


def compute_vulnerabilities(db):
    db.query(Vulnerability).delete()
    meta, bundle = read_metadata(), get_model_bundle()
    src = (meta or {}).get("vulnerability_source")
    n = 0
    for d in db.query(District).all():
        ns = db.get(NormalSeason, d.id)
        if ns is None or meta is None:
            continue
        try:
            if src == "ml_model" and bundle is not None:
                v = ml_vulnerability(bundle, feature_row(ns.features, d), settings.TOP_N_SHAP_FEATURES)
            elif src == "district_history" and str(d.id) in meta.get("district_history", {}):
                v = history_vulnerability(meta["district_history"][str(d.id)], meta.get("model_version"))
            else:
                continue
        except ValueError as e:
            print(f"  vulnerability skipped for {d.name}: {e}")
            continue
        db.add(Vulnerability(district_id=d.id, **v))
        n += 1
    db.commit()
    print(f"vulnerability: {n} districts (source: {src or 'none - model not trained'})")


def main(start, end, windows):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        cfg = hazard_config(db)
        windows = windows or cfg["windows"]
        compute_vulnerabilities(db)
        vul = {v.district_id: v for v in db.query(Vulnerability).all()}
        db.query(RiskAssessment).delete()
        db.commit()
        total_rows = 0
        for d in db.query(District).all():
            rows = db.query(RainfallDaily).filter_by(district_id=d.id).all()
            if not rows:
                print(f"  no rainfall for {d.name}: skipped")
                continue
            s = pd.Series({pd.Timestamp(r.date): r.rainfall_mm for r in rows}).sort_index()
            s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))
            lo = pd.Timestamp(start) if start else s.index.min()
            hi = pd.Timestamp(end) if end else s.index.max()
            recs = []
            for w in windows:
                q = pd.DataFrame([{"doy": c.doy, **{k: getattr(c, k) for k in ("q50", "q75", "q90", "q95", "q97", "q99")}}
                                  for c in db.query(Climatology).filter_by(district_id=d.id, window_days=w).all()])
                sums = H.window_sums(s, w, cfg["min_obs_fraction"])
                frac = H.obs_fractions(s, w)
                lv = H.levels_series(sums, q, cfg["level_quantiles"]) if len(q) else pd.Series(float("nan"), index=s.index)
                for t in s.loc[lo:hi].index:
                    tot, h = sums.loc[t], lv.loc[t]
                    rec = {"district_id": d.id, "as_of_date": t.date(), "window_days": w,
                           "window_rain_mm": None if pd.isna(tot) else float(tot), "obs_fraction": float(frac.loc[t]),
                           "hazard_level": None if pd.isna(h) else int(h), "combined_class": None, "combined_score": None,
                           "model_version": None}
                    if pd.isna(tot):
                        rec["status"] = "insufficient_rainfall_data"
                    elif pd.isna(h):
                        rec["status"] = "no_climatology"
                    elif d.id not in vul:
                        rec["status"] = "vulnerability_unavailable"
                    else:
                        v = vul[d.id]
                        rec["combined_class"], rec["combined_score"] = combine(v.class_index, v.expected_index, int(h))
                        rec["model_version"], rec["status"] = v.model_version, "ok"
                    recs.append(rec)
            db.bulk_insert_mappings(RiskAssessment, recs)
            db.commit()
            total_rows += len(recs)
        print(f"risk_assessments: {total_rows} rows")
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--windows", type=int, nargs="*")
    a = ap.parse_args()
    main(a.start, a.end, a.windows)
