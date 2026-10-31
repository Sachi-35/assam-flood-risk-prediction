from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field

DISCLAIMER = ("Not a forecast. Hazard compares rain that has ALREADY fallen (or a scenario you entered) with the district's own history. "
              "Vulnerability is estimated from past seasonal impacts. The combined level is a rule-based index that has not been "
              "validated against observed floods.")


class HazardOut(BaseModel):
    component_type: str = "rule_based"
    level: Optional[int] = Field(None, description="0 Low, 1 Moderate, 2 High, 3 Severe")
    label: Optional[str] = None
    exceeded: Optional[str] = Field(None, description="highest baseline quantile the window total exceeded")
    window_rain_mm: Optional[float] = None
    obs_fraction: Optional[float] = Field(None, description="share of the window's days with rainfall data")


class VulnerabilityOut(BaseModel):
    component_type: str = Field(..., description="ml_estimate or empirical_history")
    risk_class: str
    expected_index: float
    proba: Optional[dict[str, float]] = None
    shap_top_features: Optional[list[dict[str, Any]]] = None
    model_version: Optional[str] = None


class CombinedOut(BaseModel):
    component_type: str = "rule_based_combination"
    risk_class: Optional[str] = None
    risk_score: Optional[float] = Field(None, description="0..1 ordering index, NOT a probability")


class AssessmentOut(BaseModel):
    district_id: int
    district_name: Optional[str] = None
    as_of_date: date
    window_days: int
    basis: str = Field(..., description="observed_window (rain that has fallen) or scenario (user-entered total)")
    status: str
    hazard: HazardOut
    vulnerability: Optional[VulnerabilityOut] = None
    combined: CombinedOut
    disclaimer: str = DISCLAIMER


class ScenarioIn(BaseModel):
    district_id: int
    window_days: int
    window_end_date: date = Field(..., description="calendar day the window ends on (sets the seasonal baseline)")
    window_rain_mm: float = Field(..., ge=0, le=2000, description="total rainfall over the window, mm")


class WindowsOut(BaseModel):
    windows: list[int]
    meaning: str
