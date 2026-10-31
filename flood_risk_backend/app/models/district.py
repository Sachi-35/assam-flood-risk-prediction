from sqlalchemy import Column, Float, Integer, String, Text

from app.database import Base


class District(Base):
    __tablename__ = "districts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    state = Column(String, nullable=False)
    # GeoJSON string (no PostGIS: ~33 static polygons served whole to the frontend).
    geometry = Column(Text, nullable=False)

    # Terrain statistics from the Copernicus GLO-30 DEM (a surface model: canopy/buildings included)
    mean_elevation_m = Column(Float, nullable=False)
    elevation_std_m = Column(Float, nullable=False)
    mean_slope_deg = Column(Float, nullable=False)
    low_lying_frac = Column(Float, nullable=False)
    pop_density_km2 = Column(Float, nullable=True)        # empty when no population raster was provided
