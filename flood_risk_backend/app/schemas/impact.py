from typing import Optional

from pydantic import BaseModel, Field


class FloodImpactOut(BaseModel):
    """One record per district-year that has a processed label row (mirrors the frontend's FloodImpactRecord)."""
    year: int
    status: str = Field(..., description="reported | no_reported_impact | unknown. Never use no_reported_impact for a missing label.")
    impact_class: Optional[str] = Field(None, description="low|moderate|high|severe, only with status 'reported'. Relative bands, not official categories.")
    affected_population: Optional[float] = Field(None, description="absolute count from the source; null when missing (never 0 for missing)")
    reporting_period: Optional[str] = None
    caveats: list[str] = Field(default_factory=list, description="quality flags stored with the record")
    year_note: Optional[str] = Field(None, description="documented caveat for the whole reporting year (2019, 2020), if any")
