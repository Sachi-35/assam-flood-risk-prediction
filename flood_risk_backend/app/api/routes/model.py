import logging

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from app.schemas.model_metadata import ModelMetadataOut
from app.services.model_loader import NOT_TRAINED_MSG, read_metadata

router = APIRouter(tags=["model"])
log = logging.getLogger("flood_api")


@router.get("/model/metadata", response_model=ModelMetadataOut)
def get_model_metadata():
    """Training data size, cross-validation scores vs baselines, and limitations of the vulnerability model."""
    try:
        meta = read_metadata()
    except (OSError, ValueError) as e:
        log.error("model metadata file is unreadable: %s", e.__class__.__name__)
        raise HTTPException(status_code=503, detail="The model metadata file exists but cannot be read (corrupt JSON).")
    if meta is None:
        raise HTTPException(status_code=503, detail=NOT_TRAINED_MSG)
    try:
        return ModelMetadataOut(**meta)
    except (ValidationError, TypeError) as e:
        log.error("model metadata file has an invalid structure: %s", e.__class__.__name__)
        raise HTTPException(status_code=503, detail="The model metadata file exists but does not have the expected structure.")
