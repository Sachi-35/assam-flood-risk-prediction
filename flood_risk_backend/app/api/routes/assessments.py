from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import District, RiskAssessment, Vulnerability
from app.schemas.assessment import (AssessmentOut, CombinedOut, HazardOut, ScenarioIn, VulnerabilityOut, WindowsOut)
from app.services import hazard as H
from app.services.assessment import assess_total, hazard_config

router = APIRouter(tags=["assessments"])


def _to_out(db: Session, flat: dict, basis: str, names: dict[int, str]) -> AssessmentOut:
    cfg = hazard_config(db)
    lvl = flat["hazard_level"]
    v = db.get(Vulnerability, flat["district_id"])
    vout = None if v is None else VulnerabilityOut(
        component_type="ml_estimate" if v.source == "ml_model" else "empirical_history", risk_class=v.risk_class,
        expected_index=v.expected_index, proba=v.proba, shap_top_features=v.shap_top_features, model_version=v.model_version)
    return AssessmentOut(
        district_id=flat["district_id"], district_name=names.get(flat["district_id"]), as_of_date=flat["as_of_date"],
        window_days=flat["window_days"], basis=basis, status=flat["status"],
        hazard=HazardOut(level=lvl, label=H.level_name(lvl), exceeded=H.exceeded_label(lvl, cfg["level_quantiles"]),
                         window_rain_mm=None if flat["window_rain_mm"] is None else round(flat["window_rain_mm"], 2),
                         obs_fraction=None if flat["obs_fraction"] is None else round(flat["obs_fraction"], 3)),
        vulnerability=vout, combined=CombinedOut(risk_class=flat["combined_class"], risk_score=flat["combined_score"]))


def _flat(r: RiskAssessment) -> dict:
    return {c.name: getattr(r, c.name) for c in RiskAssessment.__table__.columns}


def _names(db: Session) -> dict[int, str]:
    return {d.id: d.name for d in db.query(District).all()}


def _check_window(db: Session, w: int):
    if w not in hazard_config(db)["windows"]:
        raise HTTPException(422, f"window_days must be one of {hazard_config(db)['windows']}")


@router.get("/windows", response_model=WindowsOut)
def windows(db: Session = Depends(get_db)):
    """Supported window lengths. A window is the last N days of observed rain (or a scenario total), not a forecast horizon."""
    return WindowsOut(windows=hazard_config(db)["windows"],
                      meaning="Rain accumulated over the N days ending on the chosen date, compared with that district's own "
                              "history for the same time of year. Not a prediction of future rain.")


@router.get("/assessments", response_model=list[AssessmentOut])
def list_assessments(window_days: int = Query(...), date_: Optional[date] = Query(None, alias="date"), db: Session = Depends(get_db)):
    """All districts for one window and date (default: latest date with assessments)."""
    _check_window(db, window_days)
    if date_ is None:
        date_ = db.query(func.max(RiskAssessment.as_of_date)).filter_by(window_days=window_days).scalar()
        if date_ is None:
            raise HTTPException(404, "No assessments computed yet: run scripts/compute_assessments.py")
    rows = db.query(RiskAssessment).filter_by(window_days=window_days, as_of_date=date_).order_by(RiskAssessment.district_id).all()
    if not rows:
        raise HTTPException(404, f"No assessments for {date_} / {window_days}-day window.")
    names = _names(db)
    return [_to_out(db, _flat(r), "observed_window", names) for r in rows]


@router.get("/districts/{district_id}/assessment", response_model=AssessmentOut)
def district_assessment(district_id: int, window_days: int = Query(...), date_: Optional[date] = Query(None, alias="date"),
                        db: Session = Depends(get_db)):
    _check_window(db, window_days)
    q = db.query(RiskAssessment).filter_by(district_id=district_id, window_days=window_days)
    r = q.filter_by(as_of_date=date_).first() if date_ else q.order_by(RiskAssessment.as_of_date.desc()).first()
    if r is None:
        raise HTTPException(404, "No assessment for that district/date/window.")
    return _to_out(db, _flat(r), "observed_window", _names(db))


@router.get("/districts/{district_id}/history", response_model=list[AssessmentOut])
def district_history(district_id: int, window_days: int = Query(...), start: Optional[date] = None, end: Optional[date] = None,
                     db: Session = Depends(get_db)):
    _check_window(db, window_days)
    q = db.query(RiskAssessment).filter_by(district_id=district_id, window_days=window_days)
    if start:
        q = q.filter(RiskAssessment.as_of_date >= start)
    if end:
        q = q.filter(RiskAssessment.as_of_date <= end)
    names = _names(db)
    return [_to_out(db, _flat(r), "observed_window", names) for r in q.order_by(RiskAssessment.as_of_date).all()]


@router.post("/assess", response_model=AssessmentOut)
def assess_scenario(body: ScenarioIn, db: Session = Depends(get_db)):
    """What-if: 'if the last N days had brought X mm'. A scenario, not a forecast. Needs no trained model, only a computed vulnerability."""
    _check_window(db, body.window_days)
    if db.get(District, body.district_id) is None:
        raise HTTPException(404, "Unknown district")
    flat = assess_total(db, body.district_id, body.window_days, body.window_end_date, float(body.window_rain_mm), 1.0)
    return _to_out(db, flat, "scenario", _names(db))
