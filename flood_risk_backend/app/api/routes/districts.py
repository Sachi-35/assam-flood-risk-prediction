import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import District, FloodLabel
from app.schemas.district import DistrictOut
from app.schemas.impact import FloodImpactOut
from app.services.labels import YEAR_NOTES

router = APIRouter(tags=["districts"])


def _to_out(d: District) -> DistrictOut:
    return DistrictOut(
        id=d.id,
        name=d.name,
        state=d.state,
        geometry=json.loads(d.geometry),        # Polygon or MultiPolygon, passed through unchanged
        mean_elevation_m=d.mean_elevation_m,
        elevation_std_m=d.elevation_std_m,
        mean_slope_deg=d.mean_slope_deg,
        low_lying_frac=d.low_lying_frac,
        pop_density_km2=d.pop_density_km2,
    )


@router.get("/districts", response_model=list[DistrictOut])
def list_districts(db: Session = Depends(get_db)):
    """Every stored district with its boundary and terrain (null where unknown). Independent of assessments and rainfall."""
    districts = db.query(District).order_by(District.id).all()
    return [_to_out(d) for d in districts]


@router.get("/districts/{district_id}/flood-impact", response_model=list[FloodImpactOut])
def flood_impact(district_id: int, db: Session = Depends(get_db)):
    """Historical seasonal flood impact, one record per district-year that has a processed label row.

    status: reported | no_reported_impact | unknown. A year with no row is simply absent (the frontend shows it as unknown).
    affected_population is null when missing; 0 only when the source says zero. An empty list means no labels were imported
    for this district (it does not mean there were no floods).
    """
    if db.get(District, district_id) is None:
        raise HTTPException(404, "Unknown district")
    rows = db.query(FloodLabel).filter_by(district_id=district_id).order_by(FloodLabel.year).all()
    return [FloodImpactOut(year=r.year, status=r.status, impact_class=r.impact_class, affected_population=r.affected_population,
                           reporting_period=r.reporting_period, caveats=list(r.caveats or []), year_note=YEAR_NOTES.get(r.year))
            for r in rows]
