"""Database health helpers. READ-ONLY: this module never creates, alters or drops anything.

Tables are created only by scripts/seed_db.py (or your own migration); the API reports a clear 503 when they are missing.
"""
from __future__ import annotations

import logging
import os
import re

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

log = logging.getLogger("flood_api.db")

_MISSING_TABLE = re.compile(
    r"no such table: ([\w.\"]+)"                                    # SQLite
    r"|relation \"([\w.]+)\" does not exist"                        # PostgreSQL
    r"|Table '[\w]*\.?(\w+)' doesn't exist", re.IGNORECASE)         # MySQL

MISSING_TABLES_HELP = "Run scripts/seed_db.py on this database (it creates the tables and loads data). The API never creates tables itself."


def required_tables() -> list[str]:
    """Every table the application's models define."""
    import app.models  # noqa: F401  (registers the models)
    from app.database import Base
    return sorted(Base.metadata.tables)


def missing_tables(bind) -> list[str]:
    have = set(inspect(bind).get_table_names())
    return [t for t in required_tables() if t not in have]


def missing_table_names(exc: BaseException) -> list[str]:
    """Table names from a 'no such table' style database error; [] when the error is something else."""
    msg = str(getattr(exc, "orig", None) or exc)
    return [next(g for g in m.groups() if g).strip('"') for m in _MISSING_TABLE.finditer(msg)]


def startup_check(engine) -> dict:
    """Log (never raise, never create) whether the database is reachable and has all required tables."""
    url = engine.url
    shown = url.render_as_string(hide_password=True)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:" and not os.path.exists(url.database):
        log.error("Database file does not exist: %s. The API will answer 503 for data endpoints. %s", url.database, MISSING_TABLES_HELP)
        return {"ok": False, "reachable": False, "missing_tables": None, "error": "database file not found"}
    try:
        missing = missing_tables(engine)
    except SQLAlchemyError as e:
        log.error("Database %s is not reachable: %s", shown, e.__class__.__name__)
        return {"ok": False, "reachable": False, "missing_tables": None, "error": e.__class__.__name__}
    if missing:
        log.error("Database %s is missing required table(s): %s. %s", shown, ", ".join(missing), MISSING_TABLES_HELP)
    else:
        log.info("Database %s OK (%d required tables present)", shown, len(required_tables()))
    return {"ok": not missing, "reachable": True, "missing_tables": missing, "error": None}
