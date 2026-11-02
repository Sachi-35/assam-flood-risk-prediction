from sqlalchemy import Column, Date, Float, ForeignKey, Integer, String, UniqueConstraint

from app.database import Base


class RainfallIMDRecent(Base):
    """Recent observed daily rainfall from the IMD district-wise dataset."""
    __tablename__ = "rainfall_imd_recent"
    __table_args__ = (
        UniqueConstraint("district_id", "date", name="uq_imd_rain_district_date"),
    )

    id = Column(Integer, primary_key=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    rainfall_mm = Column(Float, nullable=True)
    source = Column(String, nullable=False, default="IMD_daily_actual_2026")
