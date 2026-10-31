#!/usr/bin/env python
"""Step 1: select the study districts from a boundary file and assign stable ids.

Output: data/interim/districts.geojson  and  data/interim/districts.csv
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import geopandas as gpd

from floodprep.common import (add_config_arg, build_name_lookup, ensure_dir, get_logger, load_config,
                              match_series, slugify)

log = get_logger("01_boundaries")
NAME_CANDIDATES = ["district", "NAME_2", "DISTRICT", "District", "district", "dtname", "DT_NAME", "NAME", "Name", "name", "distname"]


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    cfg = load_config(ap.parse_args().config)
    dcfg = cfg["districts"]
    bf = dcfg["boundary_file"]
    if not Path(bf).exists():
        sys.exit(f"Boundary file not found: {bf}\nSee docs/DATA_SOURCES.md (section 'District boundaries').")

    gdf = gpd.read_file(bf)
    if gdf.crs is None:
        log.warning("Boundary file has no CRS; assuming EPSG:4326")
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326")

    field = dcfg.get("name_field") or next((c for c in NAME_CANDIDATES if c in gdf.columns), None)
    if field is None:
        sys.exit(f"Could not find a district-name column among {list(gdf.columns)}; set districts.name_field in config.")
    log.info(f"Using name column '{field}' ({len(gdf)} polygons in file)")

    # selected = null -> every polygon in the file; names are then taken verbatim from the file (canonical names)
    selected = dcfg.get("selected") or sorted(gdf[field].astype(str).str.strip().unique())
    lookup = build_name_lookup(selected, dcfg.get("aliases"))
    gdf["district_name"], _ = match_series(gdf[field].astype(str).str.strip(), lookup)
    chosen = gdf.dropna(subset=["district_name"]).copy()
    left_out = sorted(set(gdf[field].astype(str).str.strip()) - set(chosen[field].astype(str).str.strip()))
    if left_out:
        log.warning(f"Polygons not selected (not in districts.selected): {left_out}")

    missing = sorted(set(selected) - set(chosen["district_name"]))
    if missing:
        sample = sorted(gdf[field].astype(str).unique())
        log.error(f"Districts NOT found in boundary file: {missing}")
        log.error(f"Names available in the file: {sample}")
        log.error("Fix: add spellings under districts.aliases in config.yaml, or use a newer boundary file "
                  "(Assam districts were re-organised after 2011; e.g. Majuli is missing from 2011-census files).")
        sys.exit(1)

    dup = chosen["district_name"].duplicated(keep=False)
    if dup.any():  # dissolve split polygons of the same district
        chosen = chosen.dissolve(by="district_name", as_index=False)
    chosen["district_id"] = chosen["district_name"].map(slugify)
    chosen["area_km2"] = chosen.to_crs("EPSG:6933").area / 1e6
    cen = chosen.to_crs("EPSG:6933").geometry.centroid.to_crs("EPSG:4326")  # centroid in an equal-area CRS, then back
    chosen["centroid_lon"], chosen["centroid_lat"] = cen.x, cen.y
    keep = ["district_id", "district_name"] + [c for c in ("dt_code", "st_nm") if c in chosen.columns]
    chosen = chosen[keep + ["area_km2", "centroid_lat", "centroid_lon", "geometry"]]
    # invalid polygons break zonal masks; make_valid fixes self-intersections without changing the area noticeably
    bad = ~chosen.geometry.is_valid
    if bad.any():
        log.warning(f"Repairing {int(bad.sum())} invalid geometries: {list(chosen.loc[bad, 'district_name'])}")
        chosen["geometry"] = chosen.geometry.make_valid()
    if chosen["district_id"].duplicated().any():
        sys.exit("Two districts map to the same district_id; check names/aliases.")
    chosen = chosen.sort_values("district_id").reset_index(drop=True)

    out = ensure_dir(cfg["paths"]["interim"])
    chosen.to_file(out / "districts.geojson", driver="GeoJSON")
    chosen.drop(columns="geometry").to_csv(out / "districts.csv", index=False)
    log.info(f"Saved {len(chosen)} districts -> {out/'districts.geojson'}")
    log.info("\n" + chosen.drop(columns="geometry").round(3).to_string(index=False))


if __name__ == "__main__":
    main()
