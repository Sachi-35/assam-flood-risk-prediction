from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import District, RainfallDaily, RiskAssessment, Vulnerability
from app.schemas.assessment import (DISCLAIMER, SCENARIO_DISCLAIMER, AssessmentOut, CombinedOut, HazardOut, ScenarioIn, VulnerabilityOut,
                                    WindowsOut)
from app.services import hazard as H
from app.services.assessment import DEFAULT_LEVEL_QUANTILES, assess_total, available_windows, hazard_config, unavailable_reason

router = APIRouter(tags=["assessments"])

MAX_HISTORY_ROWS = 3660          # ten years of daily rows for one district and window
MAX_WINDOW_DAYS = 366
_ERRORS = {404: {"description": "Unknown district, or nothing computed for the request"},
           422: {"description": "Invalid window_days / date range / parameters"},
           503: {"description": "Database not initialised or unavailable"}}


@dataclass
class _Ctx:
    """Everything `_to_out` needs, loaded ONCE per request with a fixed number of queries (no per-row queries)."""
    lq: list[float]
    min_obs: Optional[float]
    rain_ids: set[int]
    names: dict[int, str]
    vul: dict[int, Vulnerability] = field(default_factory=dict)


def _load_ctx(db: Session, district_ids: Optional[list[int]] = None) -> _Ctx:
    """district_ids=None loads all districts (for /assessments); a list restricts every lookup to those ids."""
    cfg = hazard_config(db) or {}
    d_q, r_q, v_q = db.query(District.id, District.name), db.query(RainfallDaily.district_id).distinct(), db.query(Vulnerability)
    if district_ids is not None:
        d_q, r_q, v_q = (d_q.filter(District.id.in_(district_ids)), r_q.filter(RainfallDaily.district_id.in_(district_ids)),
                         v_q.filter(Vulnerability.district_id.in_(district_ids)))
    return _Ctx(lq=cfg.get("level_quantiles", DEFAULT_LEVEL_QUANTILES), min_obs=cfg.get("min_obs_fraction"),
                rain_ids={r[0] for r in r_q.all()}, names={r[0]: r[1] for r in d_q.all()}, vul={v.district_id: v for v in v_q.all()})


def _to_out(ctx: _Ctx, flat: dict, basis: str) -> AssessmentOut:
    lvl = flat["hazard_level"]
    v = ctx.vul.get(flat["district_id"])
    vout = None if v is None else VulnerabilityOut(
        component_type="ml_estimate" if v.source == "ml_model" else "empirical_history", risk_class=v.risk_class,
        expected_index=v.expected_index, proba=v.proba, shap_top_features=v.shap_top_features, model_version=v.model_version)
    reason = unavailable_reason(flat, v is not None, flat["district_id"] in ctx.rain_ids, ctx.min_obs)
    return AssessmentOut(
        district_id=flat["district_id"], district_name=ctx.names.get(flat["district_id"]), as_of_date=flat["as_of_date"],
        window_days=flat["window_days"], basis=basis, status=flat["status"],
        hazard=HazardOut(level=lvl, label=H.level_name(lvl), exceeded=H.exceeded_label(lvl, ctx.lq),
                         window_rain_mm=None if flat["window_rain_mm"] is None else round(flat["window_rain_mm"], 2),
                         obs_fraction=None if flat["obs_fraction"] is None else round(flat["obs_fraction"], 3)),
        vulnerability=vout, combined=CombinedOut(risk_class=flat["combined_class"], risk_score=flat["combined_score"]),
        unavailable_reason=reason, disclaimer=SCENARIO_DISCLAIMER if basis == "scenario" else DISCLAIMER)


def _flat(r: RiskAssessment) -> dict:
    return {c.name: getattr(r, c.name) for c in RiskAssessment.__table__.columns}


def _check_window(db: Session, w: int):
    ok = available_windows(db)
    if w not in ok:
        raise HTTPException(422, f"window_days must be one of {ok}" if ok else "No rainfall windows are configured or stored yet.")


def _require_district(db: Session, district_id: int):
    if db.query(District.id).filter(District.id == district_id).first() is None:
        raise HTTPException(404, f"Unknown district: {district_id}")


def _check_range(start: Optional[date], end: Optional[date]):
    if start is not None and end is not None and start > end:
        raise HTTPException(422, f"start ({start}) must be on or before end ({end}).")


@router.get("/windows", response_model=WindowsOut)
def windows(db: Session = Depends(get_db)):
    """Supported window lengths. A window is the last N days of observed rain (or a scenario total), not a forecast horizon."""
    return WindowsOut(windows=available_windows(db),
                      meaning="Rain accumulated over the N days ending on the chosen date, compared with that district's own "
                              "history for the same time of year. Not a prediction of future rain.")


@router.get("/assessments", response_model=list[AssessmentOut], responses=_ERRORS)
def list_assessments(window_days: int = Query(..., ge=1, le=MAX_WINDOW_DAYS), date_: Optional[date] = Query(None, alias="date"),
                     db: Session = Depends(get_db)):
    """All districts for one window and date (default: latest date with assessments)."""
    _check_window(db, window_days)
    if date_ is None:
        date_ = db.query(func.max(RiskAssessment.as_of_date)).filter_by(window_days=window_days).scalar()
        if date_ is None:
            raise HTTPException(404, "No assessments computed yet: run scripts/assess_safe.py (or scripts/compute_assessments.py)")
    rows = db.query(RiskAssessment).filter_by(window_days=window_days, as_of_date=date_).order_by(RiskAssessment.district_id).all()
    if not rows:
        raise HTTPException(404, f"No assessments for {date_} / {window_days}-day window.")
    ctx = _load_ctx(db)                                         # fixed number of queries, however many districts
    return [_to_out(ctx, _flat(r), "observed_window") for r in rows]


@router.get("/districts/{district_id}/assessment", response_model=AssessmentOut, responses=_ERRORS)
def district_assessment(district_id: int, window_days: int = Query(..., ge=1, le=MAX_WINDOW_DAYS),
                        date_: Optional[date] = Query(None, alias="date"), db: Session = Depends(get_db)):
    _check_window(db, window_days)
    _require_district(db, district_id)
    q = db.query(RiskAssessment).filter_by(district_id=district_id, window_days=window_days)
    r = q.filter_by(as_of_date=date_).first() if date_ else q.order_by(RiskAssessment.as_of_date.desc()).first()
    if r is None:
        raise HTTPException(404, "No assessment for that district/date/window.")
    return _to_out(_load_ctx(db, [district_id]), _flat(r), "observed_window")


@router.get("/districts/{district_id}/history", response_model=list[AssessmentOut], responses=_ERRORS)
def district_history(district_id: int, response: Response, window_days: int = Query(..., ge=1, le=MAX_WINDOW_DAYS),
                     start: Optional[date] = None, end: Optional[date] = None,
                     limit: int = Query(MAX_HISTORY_ROWS, ge=1, le=MAX_HISTORY_ROWS, description="maximum rows returned (oldest first)"),
                     db: Session = Depends(get_db)):
    """Assessments for one district and window, oldest first. Headers X-Total-Count / X-Result-Truncated tell you if `limit` cut the list."""
    _check_range(start, end)
    _check_window(db, window_days)
    _require_district(db, district_id)
    q = db.query(RiskAssessment).filter_by(district_id=district_id, window_days=window_days)
    if start:
        q = q.filter(RiskAssessment.as_of_date >= start)
    if end:
        q = q.filter(RiskAssessment.as_of_date <= end)
    total = q.count()
    rows = q.order_by(RiskAssessment.as_of_date).limit(limit).all()
    response.headers["X-Total-Count"] = str(total)
    if total > len(rows):
        response.headers["X-Result-Truncated"] = "true"
    ctx = _load_ctx(db, [district_id])                          # one set of lookups for the whole list (was 3 queries per row)
    return [_to_out(ctx, _flat(r), "observed_window") for r in rows]


@router.post("/assess", response_model=AssessmentOut, responses=_ERRORS)
def assess_scenario(body: ScenarioIn, db: Session = Depends(get_db)):
    """HYPOTHETICAL what-if: 'if the last N days had brought X mm'. Not stored, not a forecast, never mixed with observed records.

    Needs no trained model. Hazard needs the district's baseline (climatology); without it the result is status no_climatology
    (hazard and combined unknown) rather than an invented level.
    """
    _check_window(db, body.window_days)
    _require_district(db, body.district_id)
    flat = assess_total(db, body.district_id, body.window_days, body.window_end_date, float(body.window_rain_mm), 1.0)
    return _to_out(_load_ctx(db, [body.district_id]), flat, "scenario")
