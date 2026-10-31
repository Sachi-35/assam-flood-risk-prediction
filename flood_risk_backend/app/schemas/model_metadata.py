from typing import Any, Optional

from pydantic import BaseModel, Field


class ModelMetadataOut(BaseModel):
    model_version: str
    model_type: str
    trained_at: str
    training_rows: int
    feature_list: list[str]
    class_counts: dict[str, int]
    vulnerability_source: str = Field(..., description="ml_model, or district_history if the model did not beat the baselines")
    cross_validation: dict[str, Any] = Field(..., description="leave-one-year-out scores of the model and baselines")
    thresholds: Optional[list[float]] = None
    notes: str
