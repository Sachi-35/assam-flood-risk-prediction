from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class DistrictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., examples=[1])
    name: str = Field(..., examples=["Dhemaji"])
    state: str = Field(..., examples=["Assam"])
    geometry: dict[str, Any] = Field(
        ...,
        description="GeoJSON Polygon for the district boundary",
        examples=[
            {
                "type": "Polygon",
                "coordinates": [[[94.4, 27.3], [94.76, 27.3], [94.76, 27.66], [94.4, 27.66], [94.4, 27.3]]],
            }
        ],
    )
    mean_elevation_m: float = Field(..., examples=[110.0])
    elevation_std_m: float = Field(..., examples=[14.2])
    mean_slope_deg: float = Field(..., examples=[2.1])
    low_lying_frac: float = Field(..., examples=[0.35])
    pop_density_km2: Optional[float] = Field(None, examples=[420.0])
