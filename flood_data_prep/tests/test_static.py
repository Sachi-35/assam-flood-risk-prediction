import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from floodprep import static


def _dem(path, lat_top=27.0, px=0.00027777778, h=200, w=200, slope_m_per_m=0.1):
    """A plane rising northwards by `slope_m_per_m`, so the true slope is atan(0.1) = 5.71 deg everywhere."""
    dy_m = px * 110_574.0
    z = (np.arange(h)[::-1] * dy_m * slope_m_per_m)[:, None] * np.ones((1, w))
    z = z.astype("float32") + 100
    z[:5, :5] = -9999.0
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(94.0, lat_top, px, px), nodata=-9999.0) as dst:
        dst.write(z, 1)
    return 94.0, lat_top - h * px, 94.0 + w * px, lat_top


def test_slope_of_known_plane_and_nodata(tmp_path):
    b = _dem(tmp_path / "d.tif")
    g = gpd.GeoDataFrame({"district_id": ["x"], "area_km2": [10.0]}, geometry=[box(*b)], crs="EPSG:4326")
    out = static.dem_features(tmp_path / "d.tif", g).iloc[0]
    assert abs(out["slope_mean_deg"] - np.degrees(np.arctan(0.1))) < 0.3
    assert out["dem_valid_pct"] < 100.0 and out["elev_min_m"] > 0          # -9999 corner excluded, not averaged in


def test_slope_uses_latitude_dependent_pixel_width():
    tf = from_origin(94.0, 27.0, 0.0003, 0.0003)
    z = np.tile(np.arange(10, dtype="float64") * 10.0, (10, 1))            # +10 m per pixel eastwards
    s27 = static._slope_deg(z, tf)
    tf60 = from_origin(94.0, 60.0, 0.0003, 0.0003)
    s60 = static._slope_deg(z, tf60)
    assert s60.mean() > s27.mean()                                          # pixels are narrower at 60 N -> steeper


def test_downsampling_runs(tmp_path):
    b = _dem(tmp_path / "d.tif")
    g = gpd.GeoDataFrame({"district_id": ["x"], "area_km2": [10.0]}, geometry=[box(*b)], crs="EPSG:4326")
    out = static.dem_features(tmp_path / "d.tif", g, factor=4).iloc[0]
    assert abs(out["elev_mean_m"] - static.dem_features(tmp_path / "d.tif", g).iloc[0]["elev_mean_m"]) < 5


def test_population_sum(tmp_path):
    p = tmp_path / "p.tif"
    with rasterio.open(p, "w", driver="GTiff", height=100, width=100, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(94.0, 27.0, 0.01, 0.01), nodata=-99999.0) as dst:
        dst.write(np.full((100, 100), 2.0, dtype="float32"), 1)
    g = gpd.GeoDataFrame({"district_id": ["x"], "area_km2": [100.0]}, geometry=[box(94.2, 26.2, 94.7, 26.7)], crs="EPSG:4326")
    out = static.population_features(p, g).iloc[0]
    assert abs(out["pop_total"] - 2.0 * 50 * 50) < 2.0 * 120               # 50x50 pixels of 2 people (edge pixels tolerance)
