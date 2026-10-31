#!/usr/bin/env python
"""Step 11 (seasonal mode): is a candidate climatology reference period defensible? Decides NOTHING.

For each candidate period in hazard.reference_candidates (default: the configured one plus a few wider ones) it builds the same quantile
table as step 07 with the configured minimum coverage (min_baseline_values, min_baseline_years, min_obs_fraction) and reports, per
district, how many calendar days get a threshold. Districts/days without one will have UNKNOWN hazard.

    python scripts/11_reference_period_check.py        ->  reports/reference_period_check.md
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from floodprep import climatology as C
from floodprep.common import add_config_arg, ensure_dir, get_logger, load_config

log = get_logger("11_reference")


def main():
    ap = add_config_arg(argparse.ArgumentParser(description=__doc__))
    cfg = load_config(ap.parse_args().config)
    if cfg["project"].get("mode", "seasonal") != "seasonal":
        return log.info("Only used in seasonal mode.")
    hz, reports = cfg["hazard"], ensure_dir(cfg["paths"]["reports"])
    min_frac = float(cfg["rainfall"].get("min_obs_fraction", 0.8))
    rain = pd.read_csv(cfg["paths"]["interim"] / "rainfall_daily.csv", parse_dates=["date"]).rename(columns={"zone_id": "district_id"})
    names = pd.read_csv(cfg["paths"]["interim"] / "districts.csv").set_index("district_id")["district_name"]
    d0, d1 = rain["date"].min(), rain["date"].max()
    series = {d: C.full_series(rain, d, d0, d1) for d in names.index if (rain["district_id"] == d).any()}
    first_label_year = pd.Timestamp(cfg["project"]["start_date"]).year
    cands = hz.get("reference_candidates") or [hz["baseline_years"], [2012, 2018], [2008, 2018], [2001, 2018]]
    cands = [list(map(int, c)) for c in cands]
    L = ["# Climatology reference-period check\n",
         f"Rainfall available: {d0.date()} .. {d1.date()}; districts with any rainfall: {len(series)} of {len(names)}. "
         f"Thresholds: >= {hz['min_baseline_values']} window totals from >= {hz.get('min_baseline_years', 1)} years per (district, window, day-of-year); "
         f">= {min_frac:.0%} of a window's days observed. Configured period: {hz['baseline_years']}. "
         "This report does not choose a period; a day without enough data has an UNKNOWN hazard.\n"]
    for y0, y1 in cands:
        note = "" if y1 < first_label_year else f"  **OVERLAPS the label years (>= {first_label_year}): not allowed**"
        qt = C.build_quantile_table(series, hz["windows"], [y0, y1], hz["quantile_grid"], hz["doy_halfwidth"], min_frac,
                                    hz["min_baseline_values"], int(hz.get("min_baseline_years", 1)))
        rows = []
        for did in series:
            r = {"district": names[did]}
            for w in hz["windows"]:
                q = qt[(qt["district_id"] == did) & (qt["window_days"] == w)] if len(qt) else qt
                r[f"w{w}_days_with_threshold_pct"] = round(100 * len(q) / 366, 1)
            r["min_years_in_pool"] = int(qt[qt["district_id"] == did]["n_years"].min()) if len(qt) and (qt["district_id"] == did).any() else 0
            rows.append(r)
        t = pd.DataFrame(rows)
        wcols = [c for c in t.columns if c.startswith("w")]
        usable = int((t[wcols].min(axis=1) >= 90).sum())
        L.append(f"## {y0}-{y1}{note}\n\nDistricts with a threshold on >= 90 % of calendar days for ALL windows: **{usable} of {len(names)}** "
                 f"({len(names) - len(series)} have no rainfall at all).\n")
        L.append("```\n" + t.to_string(index=False) + "\n```\n")
    (reports / "reference_period_check.md").write_text("\n".join(L))
    log.info(f"Written {reports/'reference_period_check.md'}")


if __name__ == "__main__":
    main()
