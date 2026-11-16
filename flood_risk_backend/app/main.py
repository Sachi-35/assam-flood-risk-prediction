import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import assessments, districts, health, info, model, ml_experiment
from app.config import settings
from app.database import engine
from app.errors import register_exception_handlers
from app.services.db_health import startup_check

log = logging.getLogger("flood_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: configure logging and CHECK the database. It never creates, alters or resets tables; problems are logged and the
    affected endpoints answer 503 with a clear message."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.info("Starting %s; vulnerability method: %s", settings.APP_NAME,
             "ML vulnerability explicitly allowed (ALLOW_ML_VULNERABILITY=true)" if settings.ALLOW_ML_VULNERABILITY else "empirical history (default)")
    startup_check(engine)
    yield

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Capstone backend: seasonal district flood-risk ASSESSMENT for Assam. Combines (1) a rule-based rainfall hazard level for a "
        "user-selected window of already-observed (or hypothetical scenario) rain, only where rainfall data exist, with (2) seasonal "
        "flood-impact vulnerability: the district's own historical class. ML feasibility results are presented separately and are not integrated. "
        "Also serves 2019-2023 historical flood impact per district. NOT a forecast; the combined level is not validated against "
        "observed floods. See README.md and GET /methodology."
    ),
    version="0.4.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Total-Count", "X-Result-Truncated"])
register_exception_handlers(app)
for r in (health, districts, assessments, info, model, ml_experiment):
    app.include_router(r.router)
