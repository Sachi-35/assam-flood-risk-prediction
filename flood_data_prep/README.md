# Flood-risk data preparation

**Default mode: `project.mode: seasonal` (hybrid design).** The real data are annual/seasonal district impact labels (2019-2023) and manual
gauge rainfall, so a daily or next-day model cannot honestly be trained. Instead this project produces:

1. a **district-year table** (seasonal rainfall + terrain + population -> impact class) for the ML *vulnerability* model;
2. a **rainfall climatology** (district x window x day-of-year quantiles from 1991-2018) for the rule-based window *hazard*;
3. daily district rainfall for the dashboard.

Annual labels are **never spread over days**. The original daily pipeline is kept: set `project.mode: daily` (and see `docs/LABELS.md`) if daily labels ever exist.

```
raw data -> flood_data_prep -> data/backend_export/*.csv -> backend: train_model.py / seed_db.py / compute_assessments.py
```

## Inputs

| Dataset | Path |
|---|---|
| District boundaries (33) | `data/raw/boundaries/assam_districts.geojson` |
| **Primary rainfall: CHIRPS v3.0 final daily** (0.05 deg, mm/day), downloaded by `scripts/02_download_rainfall.py --workers 6` (resumable; a few thousand small reads, Assam window only) | `data/raw/rainfall/chirps_v3_<product>_<year>.nc` (`rainfall.chirps_v3.*`) |
| Supplementary: NWDP station CSVs (`Station, District, Latitude, Longitude, Data Acquisition Time, Manual Daily Rainfall (mm), Agency`): only 13/33 districts, ~27 % of days, no zeros -> NOT a primary source | `data/raw/rainfall/rainfall_assam_1991_2020.csv`, `rainfall_assam_2021_2025.csv` |
| Annual labels | `data/processed/labels/annual/` - authoritative file named in `labels.files` (default `seasonal_flood_labels_all_years.csv`); `*summary*` files are excluded; other versions are only compared in the audit |
| DEM (GLO-30) / population (WorldPop, optional) | `data/raw/terrain/dem.tif`, `data/raw/population/population.tif` |

No gauge, river or land-cover data: those features do not exist (never zero-filled).

## Run

```bash
pip install -r requirements.txt && pytest tests -q        # 74 passed
python scripts/00_inspect_inputs.py                       # FIRST; read/paste it
python scripts/02_download_rainfall.py                    # ONCE: CHIRPS v3.0 (needs internet; see docs/DATA_SOURCES.md)
python scripts/run_pipeline.py                            # steps 00-11 (--no-compare skips the model comparison)
```
Read in order: `reports/input_inspection.md`, `rainfall_station_report.md`, `terrain_quality.csv`, **`label_audit.md`**, `data_quality.md`, `model_comparison.md`.
Then copy `data/backend_export/*` to the backend's `data/`.

## Decisions that are config-driven, because I could not see your files
`rainfall.station_csv.missing_values / date_dayfirst / date_shift_days / duplicate_policy`, `labels.annual.absent_district_policy` (default *unknown*, not zero), `labels.annual.duplicate_policy` (max), `labels.files`, `season.source` (label period, fixed 06-01..09-30 alternative), `hazard.*`. The reports show what each choice did to your data.

## Rules the code enforces
- Missing rainfall stays missing; negatives are invalid; a real 0 stays 0. Window totals need >= 80 % observed days.
- District rainfall = area-weighted mean of the CHIRPS v3 cells over the polygon; a day needs >= 90 % valid cell weight, else it is missing. Stations stay supplementary (strict duplicate/extreme audit; IDW off).
- District-years whose season has < 80 % observed days are KEPT in the table with `rainfall_status` explaining why and all rainfall features empty; model steps exclude them and say so.
- Class boundaries = quantiles of impact over **training years (<= 2021)** only. The hazard baseline (1991-2018) ends before the label years.
- Step 10 compares LR / RF / XGBoost against baselines with leave-one-year-out and leave-district-out validation, and says whether the best model clears the best baseline.

## Honest limits
- CHIRPS is a satellite+station blend, not a gauge measurement; its daily split (sat vs rnl) is modelled. Check `chirps_vs_stations.md`.
- 33 districts x 5 years: tiny, correlated sample; intervals are optimistic; no calibration.
- No river-stage data; terrain features are constant per district; GLO-30 is a surface model; population is single-year.
- Bajali -> Barpeta and Tamulpur -> Baksa merges assume those parents (verify). The combined hazard+vulnerability level is rule-based and unvalidated.
