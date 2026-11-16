"""Uniform JSON error responses. Every error body keeps the shape {"detail": ...} that the frontend client already parses."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.services.db_health import MISSING_TABLES_HELP, missing_table_names

log = logging.getLogger("flood_api")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        missing = missing_table_names(exc)
        if missing:
            log.error("%s %s -> 503, missing table(s): %s", request.method, request.url.path, ", ".join(missing))
            return JSONResponse(status_code=503, content={
                "detail": f"The database is not initialised: required table(s) missing ({', '.join(sorted(set(missing)))}). {MISSING_TABLES_HELP}",
                "missing_tables": sorted(set(missing))})
        if isinstance(exc, OperationalError):                              # locked, cannot open, connection lost ...
            log.error("%s %s -> 503, database unavailable: %s", request.method, request.url.path, exc.__class__.__name__)
            return JSONResponse(status_code=503, content={"detail": "The database is temporarily unavailable. Please try again shortly."})
        log.exception("%s %s -> 500, database error", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal database error."})

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        log.exception("%s %s -> 500, unexpected error", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})
