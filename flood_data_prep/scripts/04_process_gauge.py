#!/usr/bin/env python
"""Step 4: clean river-gauge series and attach one primary station to each district.

Input : data/raw/gauge/*.csv                 columns: station, date, water_level_m [, discharge_cumec]
        data/raw/gauge/stations.csv          columns: station, lat, lon [, danger_level_m, warning_level_m, district]
Output: data/interim/gauge_daily.csv, data/interim/gauge_assignment.csv

If you have NO gauge data yet, run this with --skip: the pipeline continues without gauge features
(has_gauge_station = 0 everywhere). Expect a clearly weaker model for the Brahmaputra main stem.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import geopandas as gpd
import pandas as pd

from floodprep.common import add_config_arg, ensure_dir, get_logger, load_config
from floodprep.gauge import assign_stations, load_gauge_raw, qc_station

log = get_logger("04_gauge")


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    ap.add_argument("--skip", action="store_true", help="Proceed without gauge data")
    args = ap.parse_args()
    cfg = load_config(args.config)
    interim = ensure_dir(cfg["paths"]["interim"])
    gdir = cfg["paths"]["raw"] / "gauge"

    if args.skip or not list(gdir.glob("*.csv")):
        if not args.skip:
            log.warning("No gauge CSVs found; writing empty gauge outputs (same as --skip).")
        pd.DataFrame(columns=["district_id", "date"]).to_csv(interim / "gauge_daily.csv", index=False)
        pd.DataFrame(columns=["district_id", "station"]).to_csv(interim / "gauge_assignment.csv", index=False)
        return

    gc, pc = cfg["gauge"], cfg["project"]
    start = pd.Timestamp(pc["start_date"]) - pd.Timedelta(days=cfg["rainfall"]["buffer_days"])
    end = pd.Timestamp(pc["end_date"])
    raw = load_gauge_raw(gdir)

    st_path = gdir / "stations.csv"
    if not st_path.exists():
        sys.exit("data/raw/gauge/stations.csv is required (station, lat, lon, danger_level_m, warning_level_m).")
    stations = pd.read_csv(st_path)
    stations["station"] = stations["station"].astype(str).str.strip()
    districts = gpd.read_file(interim / "districts.geojson")

    assign = assign_stations(stations, districts, gc["max_station_distance_km"])
    log.info("Station assignment:\n" + assign.to_string(index=False))
    no_gauge = sorted(set(districts["district_id"]) - set(assign["district_id"]))
    if no_gauge:
        log.warning(f"No gauge within range for: {no_gauge}  -> has_gauge_station = 0 for these.")

    frames = []
    for row in assign.itertuples():
        s = raw[raw["station"] == row.station]
        if s.empty:
            log.warning(f"Station '{row.station}' (district {row.district_id}) has no rows in the gauge CSVs; check spelling.")
            continue
        q = qc_station(s, start, end, gc["max_spike_dev_m"], gc["interpolate_max_gap_days"])
        meta = stations[stations["station"] == row.station].iloc[0]
        q["danger_level_m"] = meta.get("danger_level_m")
        q["warning_level_m"] = meta.get("warning_level_m")
        q.insert(0, "district_id", row.district_id)
        q.insert(1, "station", row.station)
        frames.append(q)
        log.info(f"{row.district_id} <- {row.station}: {q['water_level_m'].notna().mean()*100:.1f}% days with level")

    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["district_id", "date"])
    out.to_csv(interim / "gauge_daily.csv", index=False)
    assign.to_csv(interim / "gauge_assignment.csv", index=False)
    log.info(f"Saved -> {interim/'gauge_daily.csv'}")


if __name__ == "__main__":
    main()
