# ml/ : seasonal flood-vulnerability ML feasibility study (isolated, additive)

Nothing in this folder touches the database, existing routes, IMD rainfall or `compute_assessments.py`.

1. Copy `labels_annual.csv`, `rainfall_daily.csv` (prep version, zone names) and `static_features.csv` from `flood_data_prep` into `ml/inputs/`.
2. `pip install scikit-learn pandas numpy scipy xgboost pytest`
3. From `flood_risk_backend/ml`:
   - `python -m pytest tests -q`        (4 tests)
   - `python scripts/evaluate_models.py` (about 6 minutes; writes `reports/model_comparison.*` and `reports/oof_predictions.csv`)
4. Read `reports/ML_FEASIBILITY_REPORT.md` first.
