from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import assessments, districts, health, model
from app.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Capstone backend: district flood-risk ASSESSMENT for Assam. Combines (1) a rule-based rainfall hazard level for a "
        "user-selected window (3/7/15/30 days of observed or scenario rain vs the district's own history) with (2) a machine-learning "
        "estimate of seasonal flood-impact vulnerability (SHAP-explained). It is NOT a forecast and the combined level is not "
        "validated against observed floods. See README.md."
    ),
    version="0.3.0",
)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
for r in (health, districts, assessments, model):
    app.include_router(r.router)
