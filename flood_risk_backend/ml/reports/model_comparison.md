# Model comparison (seasonal district vulnerability)

Rows: **37** district-seasons, **13** districts. Class counts: {'Low': 10, 'Moderate': 11, 'High': 7, 'Severe': 9}.
Attrition: {'labelled_district_years': 99, 'after_excluding_2019_snapshots': 92, 'with_any_rainfall_station': 41, 'with_at_least_30_rain_days': 37, 'rows_missing_static': 0}

Pooled out-of-fold results. `CI` = 95% district-bootstrap interval of macro-F1. Chance level for 4 balanced classes is ~0.25.


## 4class / LODO

| model | features | acc | bal.acc | macro-F1 | CI | macro-prec | macro-rec | ordinal MAE |
|---|---|---|---|---|---|---|---|---|
| majority | - | 0.11 | 0.09 | 0.07 | 0.02-0.11 | 0.05 | 0.09 | 1.30 |
| logreg | rain_only | 0.30 | 0.32 | 0.28 | 0.14-0.42 | 0.28 | 0.32 | 1.08 |
| random_forest | rain_only | 0.11 | 0.10 | 0.10 | 0.00-0.19 | 0.10 | 0.10 | 1.46 |
| xgboost | rain_only | 0.16 | 0.15 | 0.15 | 0.03-0.27 | 0.15 | 0.15 | 1.35 |
| logreg | static_only | 0.41 | 0.40 | 0.40 | 0.24-0.51 | 0.45 | 0.40 | 0.95 |
| random_forest | static_only | 0.43 | 0.42 | 0.36 | 0.22-0.45 | 0.31 | 0.42 | 0.89 |
| xgboost | static_only | 0.38 | 0.36 | 0.31 | 0.18-0.42 | 0.28 | 0.36 | 1.00 |
| logreg | static_plus_rain | 0.41 | 0.41 | 0.41 | 0.23-0.51 | 0.43 | 0.41 | 1.03 |
| random_forest | static_plus_rain | 0.19 | 0.18 | 0.19 | 0.08-0.27 | 0.20 | 0.18 | 1.19 |
| xgboost | static_plus_rain | 0.30 | 0.28 | 0.27 | 0.13-0.37 | 0.26 | 0.28 | 1.22 |

## 4class / LOYO

| model | features | acc | bal.acc | macro-F1 | CI | macro-prec | macro-rec | ordinal MAE |
|---|---|---|---|---|---|---|---|---|
| majority | - | 0.08 | 0.07 | 0.07 | 0.00-0.14 | 0.08 | 0.07 | 1.86 |
| district_history | - | 0.27 | 0.27 | 0.21 | 0.10-0.32 | 0.19 | 0.27 | 1.08 |
| logreg | rain_only | 0.27 | 0.29 | 0.28 | 0.12-0.41 | 0.30 | 0.29 | 1.11 |
| random_forest | rain_only | 0.08 | 0.07 | 0.07 | 0.00-0.13 | 0.07 | 0.07 | 1.54 |
| xgboost | rain_only | 0.16 | 0.15 | 0.16 | 0.04-0.27 | 0.19 | 0.15 | 1.24 |
| logreg | static_only | 0.32 | 0.32 | 0.31 | 0.17-0.42 | 0.31 | 0.32 | 1.14 |
| random_forest | static_only | 0.41 | 0.40 | 0.39 | 0.18-0.54 | 0.40 | 0.40 | 0.97 |
| xgboost | static_only | 0.32 | 0.31 | 0.31 | 0.11-0.44 | 0.32 | 0.31 | 1.22 |
| logreg | static_plus_rain | 0.32 | 0.31 | 0.32 | 0.13-0.47 | 0.34 | 0.31 | 1.22 |
| random_forest | static_plus_rain | 0.32 | 0.32 | 0.31 | 0.11-0.44 | 0.31 | 0.32 | 1.14 |
| xgboost | static_plus_rain | 0.32 | 0.32 | 0.31 | 0.14-0.44 | 0.32 | 0.32 | 1.14 |

## 2class_high_vs_not / LODO

| model | features | acc | bal.acc | macro-F1 | CI | macro-prec | macro-rec | ordinal MAE |
|---|---|---|---|---|---|---|---|---|
| majority | - | 0.57 | 0.50 | 0.36 | 0.30-0.42 | 0.28 | 0.50 | 0.43 |
| logreg | rain_only | 0.62 | 0.63 | 0.62 | 0.43-0.78 | 0.63 | 0.63 | 0.38 |
| random_forest | rain_only | 0.54 | 0.54 | 0.54 | 0.33-0.74 | 0.54 | 0.54 | 0.46 |
| xgboost | rain_only | 0.46 | 0.45 | 0.45 | 0.28-0.63 | 0.45 | 0.45 | 0.54 |
| logreg | static_only | 0.62 | 0.61 | 0.61 | 0.45-0.76 | 0.61 | 0.61 | 0.38 |
| random_forest | static_only | 0.59 | 0.60 | 0.59 | 0.42-0.73 | 0.60 | 0.60 | 0.41 |
| xgboost | static_only | 0.51 | 0.51 | 0.51 | 0.36-0.67 | 0.51 | 0.51 | 0.49 |
| logreg | static_plus_rain | 0.62 | 0.61 | 0.61 | 0.46-0.74 | 0.61 | 0.61 | 0.38 |
| random_forest | static_plus_rain | 0.49 | 0.49 | 0.48 | 0.33-0.62 | 0.49 | 0.49 | 0.51 |
| xgboost | static_plus_rain | 0.51 | 0.50 | 0.50 | 0.34-0.69 | 0.50 | 0.50 | 0.49 |

## 2class_high_vs_not / LOYO

| model | features | acc | bal.acc | macro-F1 | CI | macro-prec | macro-rec | ordinal MAE |
|---|---|---|---|---|---|---|---|---|
| majority | - | 0.22 | 0.21 | 0.21 | 0.12-0.29 | 0.22 | 0.21 | 0.78 |
| logreg | rain_only | 0.49 | 0.48 | 0.48 | 0.35-0.61 | 0.48 | 0.48 | 0.51 |
| random_forest | rain_only | 0.35 | 0.34 | 0.34 | 0.21-0.47 | 0.34 | 0.34 | 0.65 |
| xgboost | rain_only | 0.38 | 0.37 | 0.37 | 0.25-0.47 | 0.37 | 0.37 | 0.62 |
| logreg | static_only | 0.62 | 0.61 | 0.61 | 0.44-0.75 | 0.61 | 0.61 | 0.38 |
| random_forest | static_only | 0.49 | 0.48 | 0.48 | 0.21-0.69 | 0.48 | 0.48 | 0.51 |
| xgboost | static_only | 0.46 | 0.44 | 0.44 | 0.23-0.66 | 0.44 | 0.44 | 0.54 |
| logreg | static_plus_rain | 0.57 | 0.55 | 0.55 | 0.40-0.68 | 0.55 | 0.55 | 0.43 |
| random_forest | static_plus_rain | 0.57 | 0.55 | 0.55 | 0.40-0.68 | 0.55 | 0.55 | 0.43 |
| xgboost | static_plus_rain | 0.54 | 0.52 | 0.52 | 0.33-0.68 | 0.52 | 0.52 | 0.46 |

## Permutation check (leave-one-district-out, 4-class, Random Forest, labels shuffled within year, 100 runs)

- static_plus_rain: observed macro-F1 0.19; shuffled-label mean 0.23, 95th percentile 0.38; p = 0.63
- rain_only: observed macro-F1 0.10; shuffled-label mean 0.24, 95th percentile 0.38; p = 0.95
