from sqlalchemy import JSON, Column, Float, ForeignKey, Integer, String, UniqueConstraint

from app.database import Base


class FloodLabel(Base):
    """Historical seasonal flood impact of one district-year, as prepared by flood_data_prep (flood_labels.csv).

    Three states are kept apart and never merged:
      reported            a known impact (impact_class and/or affected_population)
      no_reported_impact  the source supports an actual zero
      unknown             no usable information (NOT zero, NOT Low)
    affected_population is NULL when missing; 0 is stored only when the source says zero.
    """
    __tablename__ = "flood_labels"
    __table_args__ = (UniqueConstraint("district_id", "year", name="uq_flood_label"),)

    id = Column(Integer, primary_key=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    status = Column(String, nullable=False)                 # reported | no_reported_impact | unknown
    impact_class = Column(String, nullable=True)            # low | moderate | high | severe (only with status reported)
    affected_population = Column(Float, nullable=True)
    reporting_period = Column(String, nullable=True)
    caveats = Column(JSON, nullable=True)                   # list[str]
