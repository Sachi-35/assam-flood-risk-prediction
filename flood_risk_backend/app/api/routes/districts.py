import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import District
from app.schemas.district import DistrictOut

router = APIRouter(tags=["districts"])


def _to_out(d: District) -> DistrictOut:
    return DistrictOut(
        id=d.id,
        name=d.name,
        state=d.state,
        geometry=json.loads(d.geometry),
        mean_elevation_m=d.mean_elevation_m,
        elevation_std_m=d.elevation_std_m,
        mean_slope_deg=d.mean_slope_deg,
        low_lying_frac=d.low_lying_frac,
        pop_density_km2=d.pop_density_km2,
    )


@router.get("/districts", response_model=list[DistrictOut])
def list_districts(db: Session = Depends(get_db)):
    """List all districts with boundary geometry, for map rendering."""
    districts = db.query(District).order_by(District.id).all()
    return [_to_out(d) for d in districts]
