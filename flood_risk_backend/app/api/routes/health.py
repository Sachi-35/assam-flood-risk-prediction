from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.db_health import MISSING_TABLES_HELP, missing_tables, required_tables

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Liveness only: the process is up. Unchanged response shape."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready(db: Session = Depends(get_db)):
    """Readiness: the database is reachable and every required table exists. 503 otherwise (this endpoint never creates tables)."""
    missing = missing_tables(db.get_bind())
    if missing:
        return JSONResponse(status_code=503, content={
            "status": "not_ready", "database": "missing_tables", "missing_tables": missing,
            "detail": f"Required table(s) missing: {', '.join(missing)}. {MISSING_TABLES_HELP}"})
    return {"status": "ok", "database": "ok", "tables": len(required_tables())}
