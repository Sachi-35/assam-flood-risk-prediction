"""Computes vulnerability per district, then the hazard/combined assessment rows for every district, date and window in a range.

Run after seed_db.py (train_model.py is optional).

Vulnerability (one value per district, seasonal):
  1. ml_estimate       only if train_model.py found that the model beats the baselines AND the district has normal-season features;
  2. empirical_history otherwise: the district's own mean impact class over its KNOWN years in flood_labels (needs >= 2 known years);
  3. none              (vulnerability_unavailable) when neither is possible. Never a default class.

Assessment rows exist for ALL districts. A district without rainfall data gets rows with hazard/combined unknown
(status insufficient_rainfall_data, obs_fraction 0): missing rain is never zero and unknown is never Low.
The date range defaults to the span of the stored rainfall; with no rainfall at all you must pass --start and --end
(the rows then carry vulnerability only).

The table is derived data: each run replaces it completely.

Usage:  python scripts/compute_assessments.py [--start 2019-01-01] [--end 2023-12-31] [--windows 3 7 15 30]
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Climatology, District, FloodLabel, NormalSeason, RainfallDaily, RiskAssessment, Vulnerability  # noqa: E402
from app.services import hazard as H  # noqa: E402
from app.services.assessment import DEFAULT_WINDOWS, hazard_config, level_quantiles  # noqa: E402
from app.services.labels import MIN_HISTORY_YEARS, history_mean_index  # noqa: E402
from app.services.model_loader import get_model_bundle, read_metadata  # noqa: E402
from app.services.risk_rules import combine  # noqa: E402
from app.services.vulnerability import feature_row, history_vulnerability, ml_vulnerability  # noqa: E402

DEFAULT_MIN_OBS_FRACTION = 0.8      # used only when hazard_config.json was not imported (then no baseline exists either)


def compute_vulnerabilities(db):
    db.query(Vulnerability).delete()
    meta, bundle = read_metadata(), get_model_bundle()
    src = (meta or {}).get("vulnerability_source")
    labels = {}
    for r in db.query(FloodLabel).all():
        labels.setdefault(r.district_id, []).append(r)
    counts, missing = {"ml_model": 0, "district_history": 0}, []
    for d in db.query(District).order_by(District.id).all():
        v, ns = None, db.get(NormalSeason, d.id)
        if src == "ml_model" and bundle is not None and ns is not None:
            try:
                v = ml_vulnerability(bundle, feature_row(ns.features, d), settings.TOP_N_SHAP_FEATURES)
            except ValueError as e:
                print(f"  ML vulnerability not possible for {d.name}: {e}")
        if v is None:
            mean, n = history_mean_index(labels.get(d.id, []))
            if mean is not None:
                v = history_vulnerability(mean)
            elif d.id not in labels and meta and str(d.id) in meta.get("district_history", {}):
                v = history_vulnerability(meta["district_history"][str(d.id)], meta.get("model_version"))
            else:
                missing.append(f"{d.name} ({n} known year(s), need {MIN_HISTORY_YEARS})")
        if v is not None:
            db.add(Vulnerability(district_id=d.id, **v))
            counts[v["source"]] += 1
    db.commit()
    print(f"vulnerability: ml_model {counts['ml_model']}, district_history {counts['district_history']}, "
          f"unavailable {len(missing)}  (trained model source: {src or 'none, model not trained'})")
    if missing:
        shown = "; ".join(missing[:8]) + (f"; ... and {len(missing) - 8} more" if len(missing) > 8 else "")
        print("  no vulnerability (too few known years or no labels): " + shown)


def main(start, end, windows):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        cfg = hazard_config(db)
        windows = windows or (cfg or {}).get("windows") or DEFAULT_WINDOWS
        min_obs = (cfg or {}).get("min_obs_fraction", DEFAULT_MIN_OBS_FRACTION)
        lq = level_quantiles(db)
        if cfg is None:
            print("NOTE: hazard_config.json not imported: rain hazard cannot be computed; rows carry vulnerability and observed totals only.")
        compute_vulnerabilities(db)
        vul = {v.district_id: v for v in db.query(Vulnerability).all()}

        rain = {}
        for d_id, dt, mm in db.query(RainfallDaily.district_id, RainfallDaily.date, RainfallDaily.rainfall_mm).all():
            rain.setdefault(d_id, {})[pd.Timestamp(dt)] = mm
        if rain:
            lo = pd.Timestamp(start) if start else min(min(r) for r in rain.values())
            hi = pd.Timestamp(end) if end else max(max(r) for r in rain.values())
        elif start and end:
            lo, hi = pd.Timestamp(start), pd.Timestamp(end)
            print("NOTE: no rainfall stored; writing vulnerability-only rows for the requested range.")
        else:
            raise SystemExit("No rainfall is stored, so there is no date range to infer: pass --start and --end.")
        if lo > hi:
            raise SystemExit("--start is after --end")
        days = pd.date_range(lo, hi, freq="D")

        db.query(RiskAssessment).delete()
        db.commit()
        total_rows, n_rain = 0, 0
        for d in db.query(District).order_by(District.id).all():
            v = vul.get(d.id)
            recs = []
            if d.id in rain:
                n_rain += 1
                s = pd.Series(rain[d.id]).sort_index()
                s = s.reindex(pd.date_range(min(s.index.min(), lo), max(s.index.max(), hi), freq="D"))   # gaps stay NaN, never 0
                for w in windows:
                    q = pd.DataFrame([{"doy": c.doy, **{k: getattr(c, k) for k in ("q50", "q75", "q90", "q95", "q97", "q99")}}
                                      for c in db.query(Climatology).filter_by(district_id=d.id, window_days=w).all()])
                    sums = H.window_sums(s, w, min_obs)
                    frac = H.obs_fractions(s, w)
                    lv = H.levels_series(sums, q, lq) if len(q) else pd.Series(float("nan"), index=s.index)
                    for t in days:
                        tot, h = sums.loc[t], lv.loc[t]
                        rec = {"district_id": d.id, "as_of_date": t.date(), "window_days": w,
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
                            rec["combined_class"], rec["combined_score"] = combine(v.class_index, v.expected_index, int(h))
                            rec["model_version"], rec["status"] = v.model_version, "ok"
                        recs.append(rec)
            else:
                for w in windows:
                    for t in days:
                        recs.append({"district_id": d.id, "as_of_date": t.date(), "window_days": w, "window_rain_mm": None,
                                     "obs_fraction": 0.0, "hazard_level": None, "combined_class": None, "combined_score": None,
                                     "model_version": None, "status": "insufficient_rainfall_data"})
            db.bulk_insert_mappings(RiskAssessment, recs)
            db.commit()
            total_rows += len(recs)
        print(f"risk_assessments: {total_rows} rows | {len(days)} day(s) x windows {list(windows)} | "
              f"districts with rainfall {n_rain}, without {db.query(District).count() - n_rain} (their hazard/combined stay unknown)")
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--windows", type=int, nargs="*")
    a = ap.parse_args()
    main(a.start, a.end, a.windows)
