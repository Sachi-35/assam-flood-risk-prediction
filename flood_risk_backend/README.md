# Localized Flood Risk Assessment: backend (Assam, 33 districts)

FastAPI + SQLAlchemy + SQLite backend for a **district-level, seasonal flood-risk assessment** of Assam, plus the 2019–2023 historical flood-impact
records, served to the React/TypeScript/Leaflet frontend.

**What this is not.** It is **not a forecast**. There is no daily or next-day flood prediction. Machine learning does **not** power the risk map
(the main vulnerability is an empirical historical method; the ML work is a separate, exploratory feasibility study that is insufficient to claim a
reliable prediction model). Hypothetical rainfall scenarios are simulations, not forecasts.

Documentation: [`docs/API.md`](docs/API.md) (endpoints, parameters, errors) · [`docs/SCHEMA.md`](docs/SCHEMA.md) (tables, constraints) ·
[`docs/INTEGRATION.md`](docs/INTEGRATION.md) (adding this version to an existing project safely) · [`docs/CHANGELOG.md`](docs/CHANGELOG.md) (what changed, verification status) ·
[`ml/README.md`](ml/README.md) and [`ml/reports/ML_FEASIBILITY_REPORT.md`](ml/reports/ML_FEASIBILITY_REPORT.md) (experimental ML).

---

## 1. Methodology

Three separate components. Each can be unknown independently, and **unknown is preserved, never turned into zero or Low.**

### Historical vulnerability (empirical, not a trained model)
* Source: `flood_labels` (one **seasonal** row per district-year, 2019–2023). Labels are never converted to daily labels.
* For a district: the mean class index over its **known** years (`low`=0 … `severe`=3). `reported` + class → that class; `no_reported_impact` → 0 (the lowest band);
  `unknown` years and `reported` rows without a class are **skipped** (never counted as zero).
* A district needs at least **2 known years**; otherwise it has **no vulnerability (Unknown)**.
* Class = `round(mean)` clamped to 0..3 (see *Rounding*). `expected_index` = the unrounded mean.
* Terrain features are stored and served but are **not** used here. Population data is not verified and is **not** used anywhere.

### Rainfall hazard (rule-based)
* Input: observed rainfall accumulated over **3, 7, 15 and 30-day** windows (the windows come from `hazard_config.json`).
* A window total exists only if **at least 80 %** of its days were observed (`min_obs_fraction`, `ceil(w × 0.8)` days); otherwise the total, the hazard and the combined level are Unknown.
  Missing rainfall (`NULL`) is never zero; an observed `0.0` is a real zero.
* Baseline: the district's own historical quantiles (`q75, q90, q97` for the levels) of w-day totals for the same time of year (±15 days, baseline years only), from `climatology`.
* Level = the number of those quantiles the total **strictly exceeds**: 0 Low, 1 Moderate, 2 High, 3 Severe. No baseline → hazard Unknown (`no_climatology`).

### Combined assessment (rule-based, not validated against observed floods)
`points = vulnerability class index (0..3) + hazard level (0..3)` → `0–1 Low`, `2–3 Moderate`, `4–5 High`, `6 Severe`.
`risk_score = (expected vulnerability index + hazard level) / 6` (an ordering index, **not a probability**).
**Unknown whenever hazard or vulnerability is unknown.** The combination has not been validated against observed floods.

### Scenarios
`POST /assess` answers "if the last N days had brought X mm". Hypothetical, not stored, not a forecast (`basis: "scenario"`).

### Unknown handling (summary)
| Situation | Result |
|---|---|
| No rainfall rows for the district | `status: insufficient_rainfall_data`; hazard and combined `null` |
| < 80 % of the window's days observed | same |
| No climatology for the district/window/day | `status: no_climatology`; hazard and combined `null` |
| < 2 known historical years | no vulnerability; hazard may still be shown; `status: vulnerability_unavailable`; combined `null` |
| `unknown` flood-label year | skipped in the history mean, never counted as zero; `affected_population` stays `null` |
| Blank rainfall value in a data file | stored as `NULL`, never `0` |

### Rounding
Existing Python `round()` behaviour is preserved on purpose. Python rounds halves to the nearest **even** number (`round(0.5) == 0`, `round(1.5) == 2`, `round(2.5) == 2`),
which can differ from "round half up" in exact-half cases (for example a mean class index of exactly 2.5 becomes class 2, `high`).
This is a documented limitation, not a bug fix target; it affects only exact halves.

## 2. Data and limitations (as shipped; re-check with `scripts/validate_data.py`)
* Historical flood labels cover **2019–2023**: 165 possible district-years, of which **99 are reported and 66 unknown**. Reporting periods and source quality differ between years;
  **2019 is an incomplete snapshot, not a complete seasonal record**; the 2020 affected-population total does not reconcile with its source memo.
* Historical rainfall covers **13 districts**; climatology covers **9 districts**; recent IMD rainfall covers **31 districts**. Hazard and combined are therefore Unknown for most districts, by design.
* Terrain features exist for all 33 districts but are not used in the main vulnerability. Population data is not sufficiently verified.
* Recent IMD rainfall (`rainfall_imd_recent`) is stored separately from historical rainfall and is not used to compute hazard levels or to train the ML experiment.
* The experimental ML dataset has only **37 usable samples across 13 districts**. Results are exploratory.
* The combined level is a rule-based index. No gauge, river-level or land-cover data are used.

## 3. Experimental ML (separate from the main assessments)
* `GET /ml-experiment/summary` serves the **shipped feasibility report** (`ml/reports/model_comparison.json`, `oof_predictions.csv`): retrospective, out-of-fold, leave-one-district-out.
  The text limitations it returns are computed from the report, so they follow it if it is regenerated. Read `ml/reports/ML_FEASIBILITY_REPORT.md` first.
* **No model is trained or shipped.** `models_artifacts/` is empty. `/model/metadata` answers 503 ("not trained") by default.
* `ALLOW_ML_VULNERABILITY=false` (default). Even if a model were trained with `scripts/train_model.py`, vulnerability calculations only consider it when this flag is
  explicitly `true`; otherwise the empirical history method is used and no model file is even loaded.
* Optional ML packages (`requirements-ml.txt`) are needed only for `scripts/train_model.py` and `ml/scripts/evaluate_models.py`. **`evaluate_models.py` overwrites `ml/reports/*`**; do not run it
  unless you intend to regenerate the reports (copy `ml/reports/` somewhere safe first).

---

## 4. Installation
Python 3.10 or newer (the code uses `int | None` annotations).

```bash
cd flood_risk_backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # runtime only
pip install -r requirements-dev.txt        # runtime + pytest + httpx (to run the tests)
# optional, experimental ML only:  pip install -r requirements-ml.txt
```
| File | Contents |
|---|---|
| `requirements.txt` | runtime: fastapi, uvicorn, sqlalchemy, pydantic, python-dotenv, joblib, numpy, pandas |
| `requirements-dev.txt` | `-r requirements.txt` + pytest, httpx |
| `requirements-ml.txt` | **optional/experimental**: scikit-learn, scipy, xgboost, shap |

## 5. Configuration
Environment variables or a `.env` file in the project root (copy `.env.example`). All are optional.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///<project root>/flood_risk.db` | database; see *Database location* |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | allowed frontend origins (comma-separated) |
| `ALLOW_ML_VULNERABILITY` | `false` | allow the experimental ML model in vulnerability calculations (`true`/`1`/`yes`); keep `false` |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `MODEL_PATH`, `EXPLAINER_PATH`, `FEATURE_LIST_PATH`, `MODEL_METADATA_PATH` | `models_artifacts/…` | optional model artifacts (none shipped) |
| `TOP_N_SHAP_FEATURES` | `5` | only for the optional ML path |

### Database location
With no `DATABASE_URL`, the database is **`<project root>/flood_risk.db`** (an absolute path, wherever you launch from).
**Warning:** `.env.example` no longer sets `DATABASE_URL` because a *relative* URL such as `sqlite:///./flood_risk.db` is resolved against the directory you launch from,
so starting uvicorn or a script from another folder silently opens a different (empty) file. If you set it, use an absolute path (`sqlite:////absolute/path/flood_risk.db`).
Check which file will be used: `python -c "from app.config import settings; print(settings.DATABASE_URL)"`.
The database file (`*.db`) and `backups/` are not part of the source and are git-ignored.

## 6. Safe workflow
Always work on a **copy** first when a database already holds data you care about. Every script below that writes takes a verified backup first (unless `--no-backup`).

```bash
# 0. See what you have (read-only). Exit code 1 if integrity or orphan problems are found.
python scripts/db_snapshot.py report --db flood_risk.db
python scripts/db_snapshot.py backup --db flood_risk.db --backup-dir backups

# 1. Validate the data files (read-only; exit code 1 on serious errors)
python scripts/validate_data.py --data-dir data --db flood_risk.db

# 2. Seed: rehearse first, then apply (transactional)
python scripts/seed_db.py --dry-run
python scripts/seed_db.py

# 3. Compute assessments: dry-run is the default; --apply writes
python scripts/assess_safe.py --start 2023-06-01 --end 2023-09-30                 # dry-run: prints insert/update/unchanged counts
python scripts/assess_safe.py --start 2023-06-01 --end 2023-09-30 --apply
#    --windows 3 7 15 30, --refresh-vulnerability, --replace-range --confirm-replace-range (see below)

# 4. Recent IMD rainfall: dry-run, then upsert
python scripts/import_imd_rainfall.py --dry-run
python scripts/import_imd_rainfall.py

# 5. Serve
uvicorn app.main:app --reload        # http://127.0.0.1:8000/docs ; readiness: /health/ready
```

### What each script does
| Script | Default | Writes | Notes |
|---|---|---|---|
| `db_snapshot.py report` / `backup` | read-only | backup file only | opens the source `mode=ro`; never enables foreign-key enforcement; verifies the copy (integrity + row counts); never overwrites a file |
| `validate_data.py` | read-only | nothing | required columns, types, missing/invalid values, ids, dates, duplicates, rainfall values, label values/granularity, climatology structure, row-count changes (`--baseline`, `--db`); `--strict` fails on warnings |
| `seed_db.py` | applies | `districts`, `flood_labels`, `rainfall_daily`, `climatology`, `normal_seasons`, `meta` | **one transaction** (all or nothing); `--dry-run` rolls back; prints existing/incoming/resulting counts; a present file **replaces** its table, a missing file is skipped, districts are upserted; never touches other tables; validates first (`--skip-validation`) and backs up first (`--no-backup`) |
| `seed_db.py --reset --confirm-reset <db path>` | protected | drops this app's tables | refused unless the database has **zero rows in every table**; a database holding data is treated as real and is never reset |
| `assess_safe.py` | **dry-run** | `risk_assessments` (and `vulnerabilities` only with `--refresh-vulnerability`) | upsert on `(district_id, as_of_date, window_days)` in one transaction; rows outside the requested range/windows are untouched; same hazard/combined functions as before; `--replace-range` deletes existing rows **in the range** first and requires `--confirm-replace-range` (or typing `REPLACE`) |
| `import_imd_rainfall.py` | applies | `rainfall_imd_recent` only | **upsert** on `(district_id, date)`; `--replace` is an explicit full replacement; `--dry-run`; only source `IMD_daily_actual_2026` unless `--allow-source NAME`; strict (any bad row stops the import) unless `--skip-invalid`; reports inserted/updated/skipped/rejected/deleted |
| `compute_assessments.py` | **destructive** | deletes then rebuilds `vulnerabilities` and `risk_assessments` | the original script, kept for reference. A failure part-way leaves partly rebuilt tables. **Do not run it on a real database**; use `assess_safe.py` |
| `train_model.py` | n/a | `models_artifacts/` | optional, experimental, needs `requirements-ml.txt`; not part of the normal workflow |

Exit codes: scripts return `0` on success, `1` for "problems found" (`db_snapshot report`, `validate_data`), `2` for a refusal or failure (nothing written).

### Files in `data/`
Only `districts.csv` is required; every other file is optional, and a missing one is reported and skipped (never faked):
`flood_labels.csv`, `rainfall_daily.csv`, `climatology.csv`, `hazard_config.json`, `label_thresholds.json`, `normal_season_features.csv`, `season_features.csv`, `rainfall_imd_recent.csv`.
`flood_labels.csv` columns: `district_id` **or** `district` (name; Bajali → Barpeta, Tamulpur → Baksa, Sribhumi → Karimganj are mapped, unmatched names are listed and not imported), `year`,
`status` (`reported` | `no_reported_impact` | `unknown`), `impact_class` (`low|moderate|high|severe`), `affected_population` (blank = missing, `0` = explicit zero), `reporting_period`, `caveats`.
Two rows for the same district-year are merged (counts summed, noted in caveats).

## 7. Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q                       # backend suite (pytest.ini sets testpaths = tests)
(cd ml && python -m pytest tests -q)            # optional ML-experiment guards
```
* Every test that writes uses a **temporary** SQLite file (`tmp_path`); the conftest test database is created and removed under `tests/`. No test touches a real database or the shipped datasets.
* `ml/tests`: two tests need the optional files `ml/inputs/{labels_annual,rainfall_daily,static_features}.csv` (not shipped). They are **skipped with a message naming the missing files**.
* `tests/test_vulnerability.py`: two tests need `shap` and `scikit-learn` (`requirements-ml.txt`); without them they are skipped with a message.
* Test files (static counts of test functions incl. parametrisation, not execution results): `test_api.py` 7 · `test_integration.py` 19 · `test_hazard.py` 5 · `test_hazard_golden.py` 1 · `test_vulnerability.py` 5 ·
  `test_imd_rainfall.py` 3 · `test_db_snapshot.py` 9 · `test_assess_safe_logic.py` 8 · `test_assess_safe.py` 13 · `test_validate_data.py` 13 · `test_seed_safety.py` 7 · `test_seed_db_safe.py` 12 ·
  `test_imd_import_logic.py` 9 · `test_imd_import_safe.py` 12 · `test_api_validation.py` 31 · `test_api_errors.py` 22 · `test_api_query_counts.py` 5 · `test_frontend_contract.py` 12 ·
  `test_ml_reports.py` 25 · `test_ml_flag_db.py` 2 (= 220) · `ml/tests/test_ml_dataset.py` 4.
  Execution results for a given delivery are recorded in [`docs/CHANGELOG.md`](docs/CHANGELOG.md); this README does not assert that tests pass.

## 8. Operational behaviour
* **Startup check:** on startup the app logs whether the database is reachable and has every required table. It **never creates, alters or resets tables**. If tables are missing, data endpoints answer `503` with the table names; `GET /health` stays `200`; `GET /health/ready` reports `503`.
* **Errors:** uniform `{"detail": …}` bodies (see `docs/API.md`). Database details never appear in responses; they go to the log.
* **Logging:** standard `logging` (`LOG_LEVEL`): startup, database and unexpected errors, ML report problems.
* **Query behaviour:** list/history endpoints use a fixed number of queries regardless of the number of rows (no N+1).

## 9. Known limitations
* Rounding is Python half-to-even (see §1).
* SQLite foreign keys are declared but not enforced; check orphans with `db_snapshot.py report` before ever enabling enforcement.
* The legacy `compute_assessments.py` remains in the repository and is destructive.
* A request against a missing SQLite file makes SQLite create an empty file (engine behaviour); the API still answers 503 and creates no tables.
* `GET /districts/{id}/history` returns at most 3660 rows per call (headers say if it was truncated).
* Unexpected non-database 500 errors are produced outside the CORS middleware, so browsers may show them as network errors.
* Data coverage limits in §2 mean most districts show Unknown hazard/combined for most dates.
