from fastapi import APIRouter, HTTPException

from app.schemas.model_metadata import ModelMetadataOut
from app.services.model_loader import NOT_TRAINED_MSG, read_metadata

router = APIRouter(tags=["model"])


@router.get("/model/metadata", response_model=ModelMetadataOut)
def get_model_metadata():
    """Training data size, cross-validation scores vs baselines, and limitations of the vulnerability model."""
    meta = read_metadata()
    if meta is None:
        raise HTTPException(status_code=503, detail=NOT_TRAINED_MSG)
    return ModelMetadataOut(**meta)
