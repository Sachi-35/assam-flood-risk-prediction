from sqlalchemy import JSON, Column, Date, Float, ForeignKey, Integer, String, UniqueConstraint

from app.database import Base


class RainfallDaily(Base):
    """District daily rainfall from station data. rainfall_mm is NULL when no station reported: missing is NOT zero."""
    __tablename__ = "rainfall_daily"
    __table_args__ = (UniqueConstraint("district_id", "date", name="uq_rain_district_date"),)

    id = Column(Integer, primary_key=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    rainfall_mm = Column(Float, nullable=True)
    n_stations = Column(Integer, nullable=True)


class Climatology(Base):
    """Quantiles of window rainfall totals, per district x window x day-of-year, from baseline years only."""
    __tablename__ = "climatology"
    __table_args__ = (UniqueConstraint("district_id", "window_days", "doy", name="uq_clim"),)

    id = Column(Integer, primary_key=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=False, index=True)
    window_days = Column(Integer, nullable=False, index=True)
    doy = Column(Integer, nullable=False)
    n_values = Column(Integer, nullable=True)
    n_years = Column(Integer, nullable=True)         # distinct reference years behind this threshold
    q50 = Column(Float)
    q75 = Column(Float)
    q90 = Column(Float)
    q95 = Column(Float)
    q97 = Column(Float)
    q99 = Column(Float)


class NormalSeason(Base):
    """Reference 'normal season' features of a district (median over baseline years); input to the vulnerability model."""
    __tablename__ = "normal_seasons"

    district_id = Column(Integer, ForeignKey("districts.id"), primary_key=True)
    features = Column(JSON, nullable=False)


class Meta(Base):
    """Small key/value store: 'hazard_config', 'label_thresholds'."""
    __tablename__ = "meta"

    key = Column(String, primary_key=True)
    value = Column(JSON, nullable=False)
