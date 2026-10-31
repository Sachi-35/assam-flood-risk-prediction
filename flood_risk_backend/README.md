# Flood Risk Assessment Backend (v3, hybrid design)

FastAPI + SQLite + scikit-learn/SHAP. Serves a district-level flood-risk **assessment** for Assam to a map dashboard.
Companion project: `../flood_data_prep` (raw data -> the CSVs this backend loads).

## What the numbers are (read this first)
| Component | Type | What it is |
|---|---|---|
| **Hazard** (0 Low .. 3 Severe) | **rule-based** | Rain over the last N days (3/7/15/30) vs the district's own 1991-2018 history for the same time of year. Level = number of baseline quantiles (q75, q90, q97) strictly exceeded. Needs no flood labels. |
| **Vulnerability** (low..severe) | **ML estimate** (RF, SHAP-explained) or **empirical history** | Seasonal flood-impact class expected in a *normal* season, from terrain, population density and seasonal rainfall. Trained on district-year labels 2019-2023. If cross-validation shows the model does not beat the baselines, the district's historical mean class is used instead and the API says `empirical_history`. |
| **Combined** | **rule-based** | vulnerability class + hazard level -> 0-1 Low, 2-3 Moderate, 4-5 High, 6 Severe. Score = (expected vulnerability + hazard) / 6. **Not validated against observed floods; not a probability.** |

**This is not a forecast.** "Window N days" means the N days of rain that have already been observed (or a scenario total you enter in `POST /assess`), never the next N days. Missing rainfall is never treated as zero; a window with < 80 % of days observed gets `status: insufficient_rainfall_data`.

No synthetic data is shipped. Without trained artifacts `/model/metadata` returns 503.

## Setup (separate venv from the data-prep project)
```
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
Copy everything from `flood_data_prep/data/backend_export/` into `data/` (districts.csv, rainfall_daily.csv, climatology.csv,
normal_season_features.csv, season_features.csv, hazard_config.json, label_thresholds.json), then:
```
python scripts/train_model.py            # leave-one-year-out CV vs baselines, writes models_artifacts/   (--model xgb optional)
python scripts/seed_db.py --reset
python scripts/compute_assessments.py --start 2023-06-01 --end 2023-09-30
uvicorn app.main:app --reload            # http://127.0.0.1:8000/docs
pytest tests -q
```
Delete `flood_risk.db` / use `--reset` when the schema changes (v3 replaced the v2 tables).

## Endpoints
`GET /windows` · `GET /districts` · `GET /assessments?window_days=7[&date=YYYY-MM-DD]` · `GET /districts/{id}/assessment?window_days=` ·
`GET /districts/{id}/history?window_days=&start=&end=` · `POST /assess` (scenario: district, window, end date, total mm) · `GET /model/metadata` · `GET /health`.
Every response has `hazard`, `vulnerability` and `combined` blocks, each with a `component_type`, plus a disclaimer.

## Limitations
* ~33 districts x 5 years of labels: the vulnerability model is small-sample; scores are noisy and district-years of one district are correlated.
* Static terrain features are constant per district, so the model can partly learn district identity.
* Impact classes are relative bands of the training years, not official severity categories. No calibration (too few rows).
* `app/services/hazard.py` must stay identical to `flood_data_prep/src/floodprep/climatology.py` (parity was checked on the mock export).
* No river-gauge, land-cover or upstream data: rainfall and terrain only.
