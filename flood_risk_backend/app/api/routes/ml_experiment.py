"""Experimental ML feasibility report. Read-only, separate from the main assessments; no model is trained or run here."""
import logging

from fastapi import APIRouter, HTTPException

from app.services.ml_reports import REPORT_DIR, MLReportMalformed, MLReportUnavailable, load_summary

router = APIRouter(prefix="/ml-experiment", tags=["ML experiment"])
log = logging.getLogger("flood_api")
BACKEND_DIR = REPORT_DIR.parents[1]          # kept for backwards compatibility with earlier imports


@router.get("/summary", responses={503: {"description": "Report files missing or malformed"}})
def get_ml_experiment():
    try:
        return load_summary(REPORT_DIR)
    except MLReportUnavailable as e:
        log.warning("ml-experiment: %s", e)
        raise HTTPException(status_code=503, detail=str(e) if str(e) else "ML experiment report files are unavailable.")
    except MLReportMalformed as e:
        log.error("ml-experiment: malformed report: %s", e)
        raise HTTPException(status_code=503, detail=f"The ML experiment report is malformed: {e}")
