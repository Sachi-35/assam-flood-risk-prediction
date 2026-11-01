"""Builds assessment rows / responses from stored rainfall, climatology and vulnerability."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import Climatology, Meta, RiskAssessment, Vulnerability
from app.services import hazard as H
from app.services.risk_rules import combine

DEFAULT_LEVEL_QUANTILES = [0.75, 0.9, 0.97]       # only used to word `exceeded`; levels need climatology rows, which carry their own data
DEFAULT_WINDOWS = [3, 7, 15, 30]                  # UI choices only; used when the data-prep hazard_config.json was not imported


def hazard_config(db: Session) -> dict | None:
    """The data-prep hazard configuration, or None when it was not imported (then no hazard can be computed from rainfall)."""
    m = db.get(Meta, "hazard_config")
    return None if m is None else m.value


def level_quantiles(db: Session) -> list[float]:
    cfg = hazard_config(db)
    return (cfg or {}).get("level_quantiles", DEFAULT_LEVEL_QUANTILES)


def available_windows(db: Session) -> list[int]:
    """Windows from hazard_config.json; else the windows that already have stored assessments; else none."""
    cfg = hazard_config(db)
    if cfg and cfg.get("windows"):
        return list(cfg["windows"])
    rows = db.query(RiskAssessment.window_days).distinct().order_by(RiskAssessment.window_days).all()
    return [r[0] for r in rows]


def climatology_row(db: Session, district_id: int, window_days: int, as_of: date) -> dict | None:
    r = (db.query(Climatology).filter_by(district_id=district_id, window_days=window_days, doy=as_of.timetuple().tm_yday).first())
    return None if r is None else {c: getattr(r, c) for c in ("q50", "q75", "q90", "q95", "q97", "q99")}


def assess_total(db: Session, district_id: int, window_days: int, as_of: date, total, obs_fraction) -> dict:
    """Combine a window total (observed or scenario) with climatology and the stored vulnerability. Returns a flat dict.

    Unknown stays unknown: no climatology -> no hazard level -> no combined class. Nothing is defaulted to Low.
    """
    out = {"district_id": district_id, "as_of_date": as_of, "window_days": window_days, "window_rain_mm": total,
           "obs_fraction": obs_fraction, "hazard_level": None, "combined_class": None, "combined_score": None,
           "model_version": None, "status": "ok"}
    if total is None:
        out["status"] = "insufficient_rainfall_data"
        return out
    level = H.level_for_total(total, climatology_row(db, district_id, window_days, as_of), level_quantiles(db))
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


def unavailable_reason(flat: dict, has_vulnerability: bool, has_rainfall: bool, min_obs_fraction: float | None) -> str | None:
    """Why hazard / combined is unknown (null when both are known). Mirrors `status` in words and adds coverage detail."""
    st = flat["status"]
    if st == "ok":
        return None
    if st == "insufficient_rainfall_data":
        if not has_rainfall:
            return "No rainfall observations are stored for this district (rainfall covers only some districts). Hazard and combined are unknown; missing rain is never treated as zero."
        pct = None if flat["obs_fraction"] is None else round(100 * flat["obs_fraction"])
        need = "" if min_obs_fraction is None else f" (at least {round(100 * min_obs_fraction)}% required)"
        return f"Only {pct if pct is not None else '?'}% of the {flat['window_days']} days in this window have rainfall data{need}. Hazard and combined are unknown."
    if st == "no_climatology":
        return "A rain total exists but there is no historical baseline for this district, window and day of year, so it cannot be compared."
    if st == "vulnerability_unavailable":
        return "Rain hazard is known but no vulnerability could be computed for this district (too few known historical years), so the combined level is unknown."
    return None
