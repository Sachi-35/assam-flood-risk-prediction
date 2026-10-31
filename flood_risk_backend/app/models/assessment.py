from sqlalchemy import JSON, Column, Date, Float, ForeignKey, Integer, String, UniqueConstraint

from app.database import Base


class Vulnerability(Base):
    """Structural/seasonal vulnerability of a district: ML estimate (or empirical history fallback) at normal-season rainfall."""
    __tablename__ = "vulnerabilities"

    district_id = Column(Integer, ForeignKey("districts.id"), primary_key=True)
    source = Column(String, nullable=False)              # "ml_model" | "district_history"
    risk_class = Column(String, nullable=False)          # low | moderate | high | severe
    class_index = Column(Integer, nullable=False)        # 0..3
    expected_index = Column(Float, nullable=False)       # probability-weighted class index (== class_index for history)
    proba = Column(JSON, nullable=True)                  # {class: probability}; NULL for the history fallback
    shap_top_features = Column(JSON, nullable=True)
    model_version = Column(String, nullable=True)


class RiskAssessment(Base):
    """Window hazard (rule-based) + vulnerability, for the window of `window_days` ending on `as_of_date`.

    This is NOT a forecast: it describes rain that has already been observed (or a user scenario, via POST /assess).
    """
    __tablename__ = "risk_assessments"
    __table_args__ = (UniqueConstraint("district_id", "as_of_date", "window_days", name="uq_assessment"),)

    id = Column(Integer, primary_key=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=False, index=True)
    as_of_date = Column(Date, nullable=False, index=True)
    window_days = Column(Integer, nullable=False, index=True)
    window_rain_mm = Column(Float, nullable=True)
    obs_fraction = Column(Float, nullable=True)
    hazard_level = Column(Integer, nullable=True)
    status = Column(String, nullable=False)              # ok | insufficient_rainfall_data | no_climatology | vulnerability_unavailable
    combined_class = Column(String, nullable=True)
    combined_score = Column(Float, nullable=True)
    model_version = Column(String, nullable=True)
