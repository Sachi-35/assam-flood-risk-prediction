"""
Centralized configuration, loaded from environment variables / .env.

Nothing else in the app should hardcode a DB path or model path — import
`settings` from here instead.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env if present (no-op if it doesn't exist)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    # --- Database ---
    # SQLite by default (zero setup, good for this capstone demo).
    # To use Postgres instead, set DATABASE_URL, e.g.:
    #   postgresql+psycopg2://user:password@localhost:5432/flood_risk
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'flood_risk.db'}"
    )

    # --- Model artifacts ---
    MODEL_PATH: str = os.getenv(
        "MODEL_PATH", str(BASE_DIR / "models_artifacts" / "model.joblib")
    )
    EXPLAINER_PATH: str = os.getenv(
        "EXPLAINER_PATH", str(BASE_DIR / "models_artifacts" / "explainer.joblib")
    )
    FEATURE_LIST_PATH: str = os.getenv(
        "FEATURE_LIST_PATH", str(BASE_DIR / "models_artifacts" / "feature_list.json")
    )
    MODEL_METADATA_PATH: str = os.getenv(
        "MODEL_METADATA_PATH", str(BASE_DIR / "models_artifacts" / "metadata.json")
    )

    # --- CORS ---
    CORS_ORIGINS: list[str] = os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
    ).split(",")

    # --- Misc ---
    APP_NAME: str = "Localized Flood Risk Assessment API"
    TOP_N_SHAP_FEATURES: int = int(os.getenv("TOP_N_SHAP_FEATURES", "5"))


settings = Settings()
