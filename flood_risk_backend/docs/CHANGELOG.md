# Changelog and delivery notes

Relative to the original backend you supplied (`claude_backend_bundle.zip`). Methodology, thresholds, quantiles, class definitions, the datasets in `data/`,
the reports in `ml/reports/` and `models_artifacts/` are **unchanged** (verified file-by-file against the original; see *Final audit*).

## Phase 1: database safety
* New `scripts/db_snapshot.py`: read-only `report` (integrity, foreign-key orphans, table row counts) and verified `backup`. Foreign-key enforcement is never enabled.
* New `scripts/assess_safe.py`: dry-run by default; upsert on `(district_id, as_of_date, window_days)`; one transaction; `--replace-range` needs confirmation; vulnerability refreshed only with `--refresh-vulnerability`; reuses the existing hazard/combined functions.
* `scripts/compute_assessments.py`: docstring marks it destructive; ML route gated behind `ALLOW_ML_VULNERABILITY` (see Phase 3). Calculations unchanged.
* `app/config.py` / `.env.example`: `ALLOW_ML_VULNERABILITY=false`.

## Phase 2: validation and imports
* New `scripts/validate_data.py` (read-only) and `scripts/seed_safety.py` (reset guard, count table).
* `scripts/seed_db.py`: single transaction, `--dry-run`, existing/incoming/resulting counts, never drops tables in normal use, protected `--reset`, pre-validation and pre-backup. Replacement semantics preserved.
  Behaviour change: districts are no longer committed if a later table fails (before: partial commits).
* `scripts/import_imd_rainfall.py`: upsert by default, explicit `--replace`, `--dry-run`, validation, source allow-list, strict mode / `--skip-invalid`, one transaction, counts. The function `import_imd_rainfall(db, csv_path)` keeps its call signature and result keys (`rows`, `districts`, …).

## Phase 3: API and reliability
* Unknown district → 404; `start > end` → 422; bounded query parameters; history `limit` with `X-Total-Count` / `X-Result-Truncated`.
* N+1 removed from `/assessments` and `/districts/{id}/history`; district names no longer load boundary geometry.
* Database startup check (log only), 503 for missing tables / unavailable database, uniform error bodies, minimal logging, `GET /health/ready`.
* `app/services/ml_reports.py`: validated report loader; limitation text computed from the shipped report. The previous hard-coded sentence "all four-class intervals include chance (~0.25)" was inaccurate for the shipped report (the majority baseline and the random forest on rain only lie entirely below 0.25) and was replaced.
* ML tests skip clearly when optional inputs are absent.
* Behaviour changes: `/districts/{id}/history` and `/rainfall/recent?district_id=` now return 404 for an unknown district (previously `200 []`); `window_days` outside 1–366 is rejected by validation.

## Phase 4: documentation and integration
* `README.md` rewritten; new `docs/API.md`, `docs/SCHEMA.md`, `docs/INTEGRATION.md`, this file.
* Dependencies split: `requirements.txt` (runtime), `requirements-dev.txt` (tests), `requirements-ml.txt` (optional experiment). `pytest.ini` (`testpaths = tests`).
* Audit fixes: `.env.example` no longer sets a relative `DATABASE_URL`; `tests/test_vulnerability.py` skips its two ML tests (and the xgboost one) instead of failing to import when optional ML packages are missing; `backups/` added to `.gitignore`; the legacy script's docstring no longer says "unchanged".

## Complete file list (vs the original backend)
**New:** `app/errors.py`, `app/services/db_health.py`, `app/services/ml_reports.py`, `docs/API.md`, `docs/SCHEMA.md`, `docs/INTEGRATION.md`, `docs/CHANGELOG.md`, `pytest.ini`,
`requirements-dev.txt`, `requirements-ml.txt`, `scripts/assess_safe.py`, `scripts/db_snapshot.py`, `scripts/seed_safety.py`, `scripts/validate_data.py`,
`tests/api_fixtures.py`, `tests/test_api_errors.py`, `tests/test_api_query_counts.py`, `tests/test_api_validation.py`, `tests/test_assess_safe.py`, `tests/test_assess_safe_logic.py`,
`tests/test_db_snapshot.py`, `tests/test_frontend_contract.py`, `tests/test_imd_import_logic.py`, `tests/test_imd_import_safe.py`, `tests/test_ml_flag_db.py`, `tests/test_ml_reports.py`,
`tests/test_seed_db_safe.py`, `tests/test_seed_safety.py`, `tests/test_validate_data.py`.

**Modified:** `.env.example`, `.gitignore`, `README.md`, `requirements.txt`, `app/api/routes/{assessments,health,info,ml_experiment,model}.py`, `app/config.py`, `app/main.py`,
`app/schemas/assessment.py` (only `ScenarioIn.window_days` bounds 1–366), `ml/tests/test_ml_dataset.py`, `scripts/compute_assessments.py`, `scripts/import_imd_rainfall.py`, `scripts/seed_db.py`, `tests/test_vulnerability.py`.

**Removed:** nothing.

## Final audit
**Methodology preserved.** Byte-identical to the original: `app/features.py`, `app/services/{hazard,risk_rules,labels,vulnerability,model_loader,ordinal_xgb,assessment}.py`, `app/models/*`,
`app/schemas/{model_metadata,district}.py`; `data/*`, `ml/reports/*`, `models_artifacts/*`. The only schema change is the bound on `ScenarioIn.window_days`. Rounding is unchanged (Python half-to-even; documented).
**Data safety.** Destructive operations in code: `seed_db.py` table replacement (original semantics, now transactional and dry-runnable), `seed_db.py --reset` (protected), `assess_safe.py --replace-range` (confirmation required),
`import_imd_rainfall.py --replace` (explicit), and the legacy `compute_assessments.py` (documented destructive, not recommended). The API itself is read-only. No script creates data outside a transaction.
**API compatibility.** Same routes plus `GET /health/ready`; same response models and field names; every field of the supplied `types.ts` present (checked mechanically against the contract spec). Differences are listed in `docs/API.md` and Phase 3 above.
**Consistency.** README, API/schema docs, script help texts and `.env.example` now agree on: the default database path, the safe workflow (`assess_safe.py` instead of `compute_assessments.py`, no routine `--reset`), the ML flag default and test commands.

## Verification status at delivery (honest account)
The delivery environment had **no network access and no `pytest`, `fastapi`, `sqlalchemy`, `httpx`, `shap` or `scikit-learn`**, so **the real pytest suite could not be run**.
What was executed instead used a small stand-in test runner (not pytest) on the tests that need only the standard library, pandas and numpy:

| Result | Count | Files |
|---|---|---|
| **Passed** | 79 in `tests/` + 2 in `ml/tests` = **81** | `test_db_snapshot` 9, `test_assess_safe_logic` 8, `test_validate_data` 13, `test_seed_safety` 7, `test_imd_import_logic` 9, `test_ml_reports` 25, `test_hazard` 5, `test_hazard_golden` 1, `test_vulnerability` 2, `ml/tests/test_ml_dataset` 2 |
| **Failed** | 0 | |
| **Skipped** | **5** | `test_vulnerability` 3 (shap, scikit-learn, xgboost absent), `ml/tests/test_ml_dataset` 2 (optional `ml/inputs/` files absent) |
| **Not run** | **138** | `test_api` 7, `test_integration` 19, `test_imd_rainfall` 3, `test_assess_safe` 13, `test_seed_db_safe` 12, `test_imd_import_safe` 12, `test_api_validation` 31, `test_api_errors` 22, `test_api_query_counts` 5, `test_frontend_contract` 12, `test_ml_flag_db` 2 |

All Python files compile (`python -m compileall`). The 138 not-run tests need FastAPI/SQLAlchemy/pytest and were **only syntax-checked and scanned for undefined names**. A passing result for them is **not** claimed.
Exact commands to run everything locally are in the README, §7.
