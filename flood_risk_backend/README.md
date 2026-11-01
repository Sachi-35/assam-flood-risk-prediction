# Flood Risk Assessment Backend (v0.4: seasonal / annual, matches the updated frontend)

FastAPI + SQLite. Serves a district-level, **seasonal** flood-risk assessment for Assam's 33 districts, plus the 2019-2023 historical
flood impact, to the React/Leaflet frontend (`flood_risk_frontend`). Companion project: `../flood_data_prep`.

**This is not a forecast and there is no daily or next-day prediction.** Everything that is unknown stays unknown (null) in the API.

## What the numbers are
| Component | Type | What it is |
|---|---|---|
| **Vulnerability** (low..severe) | `empirical_history` (default) or `ml_estimate` | Seasonal flood-impact class expected in a normal season. Default: the district's own mean class over its **known** years in `flood_labels` (needs >= 2 known years; `no_reported_impact` counts as the lowest band, `unknown` years are skipped, never counted as zero). `ml_estimate` (RF + SHAP) is used **only if** `train_model.py` ran and its leave-one-year-out CV beat the baselines, and only for districts that have normal-season features; other districts fall back to history. |
| **Hazard** (0 Low .. 3 Severe) | rule-based | Rain over the last N days (3/7/15/30) that has **already been observed**, vs the district's own baseline for that time of year. Only for districts with rainfall data; unknown if < 80 % of the window's days were observed, or no baseline exists. Missing rain is never zero. |
| **Combined** | rule-based | vulnerability class index + hazard level -> 0-1 Low, 2-3 Moderate, 4-5 High, 6 Severe. **Unknown whenever hazard or vulnerability is unknown** (never Low). Not validated against observed floods; the score is an ordering index, not a probability. |
| **Scenario** (`POST /assess`) | hypothetical | "If the last N days had brought X mm". Not stored, not a forecast, `basis: "scenario"` and a HYPOTHETICAL disclaimer. |

`GET /methodology` returns the same description plus what data is loaded right now. If the model did not beat the baselines (or was never trained)
`/model/metadata` says so (503 when untrained) and no accuracy or SHAP claim is made.

## Files to copy into `data/`
Only **`districts.csv`** is required. Every other file is optional; a missing one is reported and skipped, never faked.

| File | From | What it enables |
|---|---|---|
| `districts.csv` (required) | `flood_data_prep/data/backend_export/` | 33 districts: `id,name,state,geometry` (GeoJSON Polygon/MultiPolygon string) + `mean_elevation_m,elevation_std_m,mean_slope_deg,low_lying_frac,pop_density_km2` (blank = unknown) |
| `flood_labels.csv` | flood_data_prep label step (**see below, new**) | Historical flood impact endpoint, empirical vulnerability |
| `rainfall_daily.csv` | backend_export | `district_id,date,rainfall_mm,n_stations`; blank `rainfall_mm` = missing (kept NULL) |
| `climatology.csv`, `hazard_config.json` | backend_export | Hazard levels (rain total vs baseline), windows list |
| `normal_season_features.csv`, `season_features.csv` | backend_export | Only for the optional ML vulnerability (`train_model.py`). `season_features.csv` alone can also supply impact **classes** if `flood_labels.csv` has none |
| `label_thresholds.json` | backend_export | Stored for metadata only |

### `flood_labels.csv` columns (one row per district-year; I could not see your processed label file, so check these names)
`district_id` **or** `district` (name; Bajali -> Barpeta, Tamulpur -> Baksa, Sribhumi -> Karimganj are mapped, unmatched names are listed and not imported),
`year`, `status` (`reported` | `no_reported_impact` | `unknown`; may be blank, then inferred only from explicit values),
`impact_class` (`low|moderate|high|severe`, also accepted as `risk_class`), `affected_population` (blank = missing, `0` = explicit zero),
`reporting_period` (or `period_start` + `period_end`), `caveats` (separate several with `;` or `|`).
Two rows for the same district-year (e.g. Bajali + Barpeta) are merged and counts summed; the record says so in its caveats.
The 2019 and 2020 year caveats are returned as `year_note` (not repeated in `caveats`; the frontend prints them itself).

## Setup (macOS)
```
cd flood_risk_backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# copy the files above into data/
python scripts/seed_db.py --reset          # --reset only the FIRST time (schema changed from v3); afterwards plain `python scripts/seed_db.py`
python scripts/compute_assessments.py --start 2023-06-01 --end 2023-09-30
uvicorn app.main:app --reload              # http://127.0.0.1:8000/docs
pytest tests -q
```
Optional ML vulnerability (only if `season_features.csv`, `normal_season_features.csv` are in `data/`): `python scripts/train_model.py` before `compute_assessments.py`.

* `seed_db.py` is repeatable: a present file replaces its table (no duplicates), districts are upserted, a missing file leaves its table untouched.
  It prints geometry warnings, unmatched label rows, merged rows and missing-file notes. Re-run `compute_assessments.py` afterwards.
* `compute_assessments.py` writes rows for **all** districts. Districts without rainfall get hazard/combined unknown (`obs_fraction` 0).
  With no rainfall imported at all you must pass `--start/--end`; the map then shows vulnerability only.
* Pick `--start/--end` inside the period you want on the map (the frontend offers exactly the dates stored). Dates beyond the rainfall data are stored as unknown.

## Endpoints
`GET /windows` · `GET /districts` · `GET /districts/{id}/flood-impact` · `GET /assessments?window_days=7[&date=]` · `GET /districts/{id}/assessment` ·
`GET /districts/{id}/history` · `POST /assess` (hypothetical) · `GET /model/metadata` · `GET /methodology` · `GET /rainfall/coverage` · `GET /health`.
Assessments carry `hazard`, `vulnerability`, `combined` separately plus `unavailable_reason` (why a value is unknown, with the observed share of days).

## Verification status
* `pytest`: 36 tests. `tests/test_integration.py` uses **synthetic** files (33 invented square districts, invented labels) to prove behaviour and the
  response shapes expected by the frontend types. **Nothing has been run on your real boundary file, labels or rainfall.** Check the output of
  `seed_db.py` (district count, geometry warnings, label counts by status, unmatched names) on the real files before presenting.
* `hazard.py` must stay identical to `flood_data_prep/src/floodprep/climatology.py` (golden parity test).

## Limitations
* Rainfall exists for at most the districts with stations (about 13 of 33): hazard and combined are unknown elsewhere, by design.
* Empirical vulnerability rests on <= 5 years per district and relative impact bands; with so few rows an ML model usually will not beat the baselines.
* Terrain is constant per district; GLO-30 is a surface model; population density is unverified. No gauge, river or land-cover data.
* Hazard needs a rainfall baseline (`climatology.csv`); without it hazard is unknown for every district.
