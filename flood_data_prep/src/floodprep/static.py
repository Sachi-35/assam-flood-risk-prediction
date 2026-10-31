"""Static (time-invariant) district features from rasters and river lines."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask as rio_mask

# ESA WorldCover class codes
WC_CROP, WC_BUILT, WC_WATER, WC_WETLAND, WC_TREE = 40, 50, 80, 90, 10


def _clip(src, geom_wgs84, crs_src_geom):
    """Clip raster to district; returns (array, transform) with nodata -> NaN (float) or masked."""
    out, tf = rio_mask(src, [crs_src_geom], crop=True, filled=False, all_touched=False)
    return out[0], tf


def _district_window(src, geom, factor: int):
    """Read only the district's bounding window, optionally decimated by `factor` (average resampling).

    Returns (masked 2-D float32 array of valid pixels INSIDE the polygon, affine transform, n_pixels_inside_polygon).
    """
    from rasterio.enums import Resampling
    from rasterio.features import geometry_mask
    from rasterio.windows import Window, from_bounds
    from rasterio.transform import Affine

    win = from_bounds(*geom.bounds, transform=src.transform).round_offsets().round_lengths()
    win = win.intersection(Window(0, 0, src.width, src.height))
    h, w = max(int(win.height // factor), 1), max(int(win.width // factor), 1)
    arr = src.read(1, window=win, out_shape=(h, w), masked=True, resampling=Resampling.average if factor > 1 else Resampling.nearest)
    tf = src.window_transform(win) @ Affine.scale(win.width / w, win.height / h)
    inside = geometry_mask([geom], out_shape=(h, w), transform=tf, invert=True, all_touched=False)
    data = np.ma.array(arr.astype("float32"), mask=np.ma.getmaskarray(arr) | ~inside)
    return data, tf, int(inside.sum())


def _slope_deg(dem: np.ndarray, transform) -> np.ndarray:
    """Slope in degrees. For a geographic CRS the cell size in metres is computed PER ROW from that row's latitude
    (a degree of longitude shrinks with cos(lat)), so the 30 m angular grid is not treated as a constant 30 m.
    NaN (no-data) pixels stay NaN and do not leak into their neighbours' slopes beyond the 1-pixel stencil."""
    rows = dem.shape[0]
    lat = transform.f + transform.e * (np.arange(rows) + 0.5)          # latitude of each row centre
    dy = abs(transform.e) * 110_574.0                                   # metres per degree of latitude (mid-latitude)
    dx = abs(transform.a) * 111_320.0 * np.cos(np.radians(lat))         # per-row metres per pixel in x
    gy = np.gradient(dem, dy, axis=0)
    gx = np.gradient(dem, axis=1) / dx[:, None]
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def dem_features(dem_path: Path, districts: gpd.GeoDataFrame, factor: int = 1, nodata_below: float = -500.0,
                 low_margin_m: float = 5.0) -> pd.DataFrame:
    """Per-district elevation statistics + slope from the DEM, using the district polygon as the mask.

    Note: Copernicus GLO-30 is a surface model (canopy / buildings included), so values in forest and cities read high.
    """
    rows = []
    with rasterio.open(dem_path) as src:
        dist = districts.to_crs(src.crs)
        for (_, d_ll), (_, d) in zip(districts.iterrows(), dist.iterrows()):
            data, tf, n_inside = _district_window(src, d.geometry, factor)
            z = np.ma.filled(data.astype("float32"), np.nan)
            z[z < nodata_below] = np.nan
            n_valid = int(np.isfinite(z).sum())
            rec = {"district_id": d_ll["district_id"], "dem_valid_pct": 100.0 * n_valid / n_inside if n_inside else 0.0}
            if n_valid == 0:
                rows.append(rec)
                continue
            slope = _slope_deg(z, tf)
            slope[~np.isfinite(z)] = np.nan
            v = z[np.isfinite(z)]
            p2, p50, p98 = np.percentile(v, [2, 50, 98])
            rec.update(
                elev_mean_m=float(v.mean()), elev_min_m=float(v.min()), elev_max_m=float(v.max()),
                elev_p05_m=float(np.percentile(v, 5)), elev_median_m=float(p50), elev_p95_m=float(np.percentile(v, 95)),
                elev_std_m=float(v.std()), elev_range_m=float(p98 - p2),
                slope_mean_deg=float(np.nanmean(slope)), slope_p90_deg=float(np.nanpercentile(slope, 90)),
                # share of the district within `low_margin_m` of its own low ground (p2, robust to single-pixel pits):
                # a crude floodplain proxy. Relative to the district, so it is large in flat districts.
                low_lying_frac=float((v <= p2 + low_margin_m).mean()),
            )
            rows.append(rec)
    return pd.DataFrame(rows)


def landcover_features(lc_path: Path, districts: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    with rasterio.open(lc_path) as src:
        dist = districts.to_crs(src.crs)
        for (_, d_ll), (_, d) in zip(districts.iterrows(), dist.iterrows()):
            arr, _ = _clip(src, None, d.geometry)
            valid = arr.compressed() if np.ma.is_masked(arr) else arr.ravel()
            n = max(len(valid), 1)
            rows.append(
                {
                    "district_id": d_ll["district_id"],
                    "pct_cropland": 100.0 * float(np.sum(valid == WC_CROP)) / n,
                    "pct_built": 100.0 * float(np.sum(valid == WC_BUILT)) / n,
                    "pct_water": 100.0 * float(np.sum(valid == WC_WATER)) / n,
                    "pct_wetland": 100.0 * float(np.sum(valid == WC_WETLAND)) / n,
                    "pct_tree": 100.0 * float(np.sum(valid == WC_TREE)) / n,
                }
            )
    return pd.DataFrame(rows)


def raster_metadata(path: Path) -> dict:
    with rasterio.open(path) as src:
        return {"size": f"{src.width}x{src.height}", "crs": str(src.crs), "dtype": src.dtypes[0], "nodata": src.nodata,
                "pixel_size": (round(abs(src.transform.a), 6), round(abs(src.transform.e), 6)), "bounds": tuple(round(b, 4) for b in src.bounds),
                "tags": {k: v for k, v in src.tags().items()} }


def population_features(pop_path: Path, districts: gpd.GeoDataFrame, units: str = "people_per_pixel") -> pd.DataFrame:
    """District population = sum of the raster over the district polygon.

    `units` (config population.units) says what the raster holds and is NEVER guessed:
      people_per_pixel : district total = sum of pixels
      people_per_km2   : each pixel is multiplied by its own area (latitude-dependent) before summing
    pop_density_km2 is always district total / district polygon area.
    (Original note) The raster should be PEOPLE PER PIXEL (WorldPop 'ppp'). A density raster (people per km2) would give nonsense totals;
    the sanity check below compares the total against the plausible range for Assam (about 31 million people in 2011,
    roughly 35-37 million around 2020).
    Pixels are counted if their CENTRE is inside the polygon, so a few people near borders can go to the neighbour.
    """
    rows = []
    with rasterio.open(pop_path) as src:
        dist = districts.to_crs(src.crs)
        for (_, d_ll), (_, d) in zip(districts.iterrows(), dist.iterrows()):
            arr, _ = _clip(src, None, d.geometry)
            data = np.ma.filled(arr.astype("float64"), np.nan)
            data[data < 0] = np.nan
            if units == "people_per_km2":
                dy_km = abs(src.transform.e) * 111.32
                lat0 = float(d_ll.geometry.centroid.y)
                data = data * dy_km * (abs(src.transform.a) * 111.32 * np.cos(np.radians(lat0)))
            elif units != "people_per_pixel":
                raise ValueError("population.units must be people_per_pixel or people_per_km2")
            total = float(np.nansum(data)) if not np.isnan(data).all() else np.nan
            rows.append({"district_id": d_ll["district_id"], "pop_total": total,
                         "pop_density_km2": total / d_ll["area_km2"] if d_ll["area_km2"] else np.nan})
    out = pd.DataFrame(rows)
    state_total = out["pop_total"].sum()
    out.attrs["state_total"] = state_total
    return out


def river_features(rivers_path: Path, districts: gpd.GeoDataFrame) -> pd.DataFrame:
    """River-line density and distance from district centroid to the nearest river."""
    proj = "EPSG:6933"  # equal-area
    riv = gpd.read_file(rivers_path).to_crs(proj)
    dist = districts.to_crs(proj)
    riv_union = riv.geometry.union_all() if hasattr(riv.geometry, "union_all") else riv.geometry.unary_union
    rows = []
    for _, d in dist.iterrows():
        clipped = riv_union.intersection(d.geometry)
        rows.append(
            {
                "district_id": d["district_id"],
                "river_density_km_per_km2": (clipped.length / 1000.0) / (d.geometry.area / 1e6),
                "centroid_dist_to_river_km": d.geometry.centroid.distance(riv_union) / 1000.0,
                "river_touches_district": int(not clipped.is_empty),
            }
        )
    return pd.DataFrame(rows)
