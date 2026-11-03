"""Read-only descriptions of how the numbers are made and how much data stands behind them. Not used for any computation."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import District, FloodLabel, RainfallDaily, RainfallIMDRecent, RiskAssessment, Vulnerability
from app.services.assessment import available_windows, hazard_config
from app.services.labels import MIN_HISTORY_YEARS, YEAR_NOTES
from app.services.model_loader import read_metadata

router = APIRouter(tags=["info"])


@router.get("/methodology")
def methodology(db: Session = Depends(get_db)):
    """What is assessed, over which period, how components are combined, and which data are in the database right now."""
    meta = read_metadata()
    n_dist = db.query(func.count(District.id)).scalar()
    n_rain = db.query(func.count(func.distinct(RainfallDaily.district_id))).scalar()
    n_lab = db.query(func.count(FloodLabel.id)).scalar()
    vul_sources = dict(db.query(Vulnerability.source, func.count()).group_by(Vulnerability.source).all())
    cfg = hazard_config(db)
    return {
        "assessment_type": "seasonal district-level flood-risk assessment (not a forecast, no daily or next-day prediction)",
        "assessment_period": {
            "vulnerability": "one value per district: the seasonal (monsoon) flood-impact class expected in a normal season",
            "hazard": "rain accumulated over the N days ending on the chosen date (N from /windows) vs the district's own baseline for that time of year; only where rainfall observations exist",
        },
        "components": {
            "hazard": "rule_based: number of baseline quantiles strictly exceeded (0 Low .. 3 Severe); unknown when the window has too little rainfall data or no baseline",
            "vulnerability": (
                "empirical_history = the district historical mean impact class; "
                f"at least {MIN_HISTORY_YEARS} known years are required. "
                "ML feasibility results are separate and are not integrated"
            ),
            "combined": "rule_based: vulnerability class index + hazard level -> 0-1 Low, 2-3 Moderate, 4-5 High, 6 Severe; unknown if either part is unknown; not validated against observed floods",
        },
        "missing_data_rules": [
            "missing rainfall is never zero; a window with too few observed days has no total and no hazard",
            "unknown inputs never produce Low: hazard, vulnerability and combined stay null",
            "unknown flood-impact years are never counted as zero",
        ],
        "scenario": "POST /assess is a hypothetical rain total typed by the user; it is not stored and not a forecast",
        "year_notes": {str(k): v for k, v in YEAR_NOTES.items()},
        "current_data": {
            "districts": n_dist, "districts_with_rainfall": n_rain, "flood_label_rows": n_lab,
            "vulnerability_by_source": vul_sources, "stored_assessment_rows": db.query(func.count(RiskAssessment.id)).scalar(),
            "hazard_config_loaded": cfg is not None, "windows": available_windows(db),
            "model_trained": meta is not None, "model_vulnerability_source": (meta or {}).get("vulnerability_source"),
        },
    }


@router.get("/rainfall/coverage")
def rainfall_coverage(db: Session = Depends(get_db)):
    """Per district: how many days of rainfall are stored, how many are missing (NULL, not zero), and the date span."""
    stats = {r[0]: r for r in db.query(
        RainfallDaily.district_id, func.min(RainfallDaily.date), func.max(RainfallDaily.date), func.count(RainfallDaily.id),
        func.count(RainfallDaily.rainfall_mm)).group_by(RainfallDaily.district_id).all()}
    out = []
    for d in db.query(District).order_by(District.id).all():
        s = stats.get(d.id)
        if s is None:
            out.append({"district_id": d.id, "name": d.name, "has_rainfall": False, "first_date": None, "last_date": None,
                        "days_stored": 0, "days_observed": 0, "days_missing": 0, "observed_fraction": None,
                        "reason": "No rainfall observations stored for this district."})
        else:
            _, lo, hi, n_rows, n_obs = s
            span = (hi - lo).days + 1
            out.append({"district_id": d.id, "name": d.name, "has_rainfall": True, "first_date": lo.isoformat(), "last_date": hi.isoformat(),
                        "days_stored": n_rows, "days_observed": n_obs, "days_missing": span - n_obs,
                        "observed_fraction": round(n_obs / span, 4), "reason": None})
    return {"districts": len(out), "districts_with_rainfall": sum(o["has_rainfall"] for o in out), "coverage": out}



@router.get("/rainfall/recent")
def recent_imd_rainfall(
    district_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(5000, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    """Recent observed IMD daily rainfall, kept separate from historical station data."""
    query = db.query(RainfallIMDRecent, District.name).join(
        District, District.id == RainfallIMDRecent.district_id
    )

    if district_id is not None:
        query = query.filter(RainfallIMDRecent.district_id == district_id)
    if start is not None:
        query = query.filter(RainfallIMDRecent.date >= start)
    if end is not None:
        query = query.filter(RainfallIMDRecent.date <= end)

    total = query.count()
    rows = (
        query.order_by(RainfallIMDRecent.date, RainfallIMDRecent.district_id)
        .limit(limit)
        .all()
    )

    observations = [
        {
            "district_id": rainfall.district_id,
            "district": district_name,
            "date": rainfall.date.isoformat(),
            "rainfall_mm": rainfall.rainfall_mm,
            "source": rainfall.source,
        }
        for rainfall, district_name in rows
    ]

    return {
        "dataset": "IMD recent observed daily rainfall",
        "total_matching": total,
        "returned": len(observations),
        "limit": limit,
        "filters": {
            "district_id": district_id,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "observations": observations,
        "disclaimer": (
            "Observed rainfall only. These records are separate from the historical "
            "rainfall dataset and do not by themselves establish a flood hazard level "
            "or forecast."
        ),
    }
