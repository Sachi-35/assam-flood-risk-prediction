"""Builds assessment rows / responses from stored rainfall, climatology and vulnerability."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import Climatology, Meta, Vulnerability
from app.services import hazard as H
from app.services.risk_rules import combine


def hazard_config(db: Session) -> dict:
    m = db.get(Meta, "hazard_config")
    if m is None:
        raise RuntimeError("hazard_config missing: run scripts/seed_db.py --reset with the data-prep export in data/.")
    return m.value


def climatology_row(db: Session, district_id: int, window_days: int, as_of: date) -> dict | None:
    r = (db.query(Climatology).filter_by(district_id=district_id, window_days=window_days, doy=as_of.timetuple().tm_yday).first())
    return None if r is None else {c: getattr(r, c) for c in ("q50", "q75", "q90", "q95", "q97", "q99")}


def assess_total(db: Session, district_id: int, window_days: int, as_of: date, total, obs_fraction) -> dict:
    """Combine a window total (observed or scenario) with climatology and the stored vulnerability. Returns a flat dict."""
    cfg = hazard_config(db)
    lq = cfg["level_quantiles"]
    out = {"district_id": district_id, "as_of_date": as_of, "window_days": window_days, "window_rain_mm": total,
           "obs_fraction": obs_fraction, "hazard_level": None, "combined_class": None, "combined_score": None,
           "model_version": None, "status": "ok"}
    if total is None:
        out["status"] = "insufficient_rainfall_data"
        return out
    level = H.level_for_total(total, climatology_row(db, district_id, window_days, as_of), lq)
    if level is None:
        out["status"] = "no_climatology"
        return out
    out["hazard_level"] = level
    v = db.get(Vulnerability, district_id)
    if v is None:
        out["status"] = "vulnerability_unavailable"
        return out
    out["combined_class"], out["combined_score"] = combine(v.class_index, v.expected_index, level)
    out["model_version"] = v.model_version
    return out
