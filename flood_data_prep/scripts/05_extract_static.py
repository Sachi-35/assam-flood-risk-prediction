#!/usr/bin/env python
"""Step 5: static district features from rasters (DEM required; population, land cover, river lines optional).

  data/raw/terrain/dem.tif                 Copernicus GLO-30 mosaic (EPSG:4326, nodata -9999)       -> elevation + slope stats
  data/raw/population/population.tif       WorldPop people-per-pixel                                 -> pop_total, pop_density_km2
  data/raw/landcover/landcover.tif         ESA WorldCover (optional)
  data/raw/rivers/rivers.geojson           river centre-lines (optional)
Output: data/interim/static_features.csv, reports/terrain_quality.csv (+ population check printed)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import geopandas as gpd
import pandas as pd
import rasterio

from floodprep import static
from floodprep.common import add_config_arg, ensure_dir, get_logger, load_config

log = get_logger("05_static")


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    cfg = load_config(ap.parse_args().config)
    raw, interim = cfg["paths"]["raw"], ensure_dir(cfg["paths"]["interim"])
    reports = ensure_dir(cfg["paths"]["reports"])
    tc = cfg.get("terrain", {})
    districts = gpd.read_file(interim / "districts.geojson")

    parts = [districts[["district_id", "area_km2", "centroid_lat", "centroid_lon"]]]

    dem = raw / "terrain" / "dem.tif"
    if not dem.exists():
        sys.exit(f"DEM not found: {dem}. It is required (elevation/slope are the backend's static features).")
    with rasterio.open(dem) as src:
        log.info(f"DEM: {src.width}x{src.height}, CRS={src.crs}, nodata={src.nodata}, dtype={src.dtypes[0]}, "
                 f"pixel={src.res[0]:.10f} deg")
        if src.crs is None or not src.crs.is_geographic and src.crs.to_epsg() != 4326:
            log.warning("DEM CRS is not geographic EPSG:4326; slope code handles geographic CRS only. Reproject first.")
    log.info(f"Computing DEM features (downsample_factor={tc.get('downsample_factor', 1)}) ... this can take several minutes "
             "for the full 30 m mosaic")
    d = static.dem_features(dem, districts, factor=int(tc.get("downsample_factor", 1)),
                            nodata_below=float(tc.get("nodata_below", -500)),
                            low_margin_m=float(tc.get("low_lying_margin_m", 5.0)))
    parts.append(d)
    min_cov = float(tc.get("min_valid_coverage_pct", 95))
    low = d[d["dem_valid_pct"] < min_cov]
    if len(low):
        log.warning(f"DEM valid-pixel coverage below {min_cov}% in: "
                    f"{dict(zip(low['district_id'], low['dem_valid_pct'].round(1)))}")
    d.merge(districts[["district_id"]], on="district_id").to_csv(reports / "terrain_quality.csv", index=False)

    for name, path, fn in [("land cover", raw / "landcover" / "landcover.tif", static.landcover_features),
                           ("rivers", raw / "rivers" / "rivers.geojson", static.river_features)]:
        if path.exists():
            log.info(f"Computing {name} features from {path.name} ...")
            parts.append(fn(path, districts))
        else:
            log.info(f"{name}: not provided -> skipped (optional)")

    pop_path = raw / "population" / "population.tif"
    if pop_path.exists():
        log.info("Computing population totals ...")
        pcfg = cfg.get("population", {}) or {}
        units = pcfg.get("units", "people_per_pixel")
        meta = static.raster_metadata(pop_path)
        p = static.population_features(pop_path, districts, units)
        parts.append(p)
        tot = p.attrs.get("state_total", float("nan"))
        log.info(f"Population raster sums to {tot:,.0f} over the {len(p)} districts "
                 "(Assam: ~31.2 M in Census 2011, roughly 35-37 M around 2020).")
        lo, hi = pcfg.get("expected_state_total", [25e6, 45e6])
        verified = bool(pcfg.get("units_verified", False))
        (reports / "population_check.md").write_text("\n".join([
            "# Population raster check\n", f"File: {pop_path.name}", f"Metadata read from the file: {meta}",
            f"Configured product: {pcfg.get('product')} | year: {pcfg.get('year')} | units: **{units}** | units_verified: **{verified}**",
            f"Sum over the {len(p)} districts: {tot:,.0f} (expected state total {lo:,.0f}-{hi:,.0f}) -> "
            f"{'PLAUSIBLE' if lo < tot < hi else 'OUTSIDE the expected range: units/product are probably not what is configured'}",
            "", ("**UNVERIFIED**: the product, year and units are not confirmed in config.yaml (population.*). `pop_total` and the "
                 "`affected_pct` metric inherit this uncertainty." if not verified else "Units confirmed by the user."),
            "Density = district total / polygon area; the raster is never averaged as a density."]))
        if not verified:
            log.warning("Population product/year/units are UNVERIFIED (set population.* and units_verified in config.yaml); see reports/population_check.md")
        if not (lo < tot < hi) and len(p) >= 30:
            log.error("That total is outside the plausible range. Is the raster a DENSITY (people/km2) or a different "
                      "region/scale? affected_pct would be wrong. Fix before using labels.metric=affected_pct.")
    else:
        log.warning(f"population: {pop_path} not found -> pop_total/pop_density_km2 unavailable. "
                    "labels.metric 'auto' will fall back to absolute affected_population.")

    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on="district_id", how="left")
    out.to_csv(interim / "static_features.csv", index=False)
    log.info("\n" + out.round(2).to_string(index=False))
    log.info(f"Saved -> {interim/'static_features.csv'}")


if __name__ == "__main__":
    main()
