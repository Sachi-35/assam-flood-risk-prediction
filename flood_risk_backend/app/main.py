from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import assessments, districts, health, info, model
from app.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Capstone backend: seasonal district flood-risk ASSESSMENT for Assam. Combines (1) a rule-based rainfall hazard level for a "
        "user-selected window of already-observed (or hypothetical scenario) rain, only where rainfall data exist, with (2) seasonal "
        "flood-impact vulnerability: an ML estimate when cross-validation supports it, otherwise the district's own historical class. "
        "Also serves 2019-2023 historical flood impact per district. NOT a forecast; the combined level is not validated against "
        "observed floods. See README.md and GET /methodology."
    ),
    version="0.4.0",
)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
for r in (health, districts, assessments, info, model):
    app.include_router(r.router)
