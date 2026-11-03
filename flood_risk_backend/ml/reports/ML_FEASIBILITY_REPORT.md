# Seasonal flood-vulnerability ML: data audit, design and verdict

**Verdict: supervised ML is not defensible on this data. No model was integrated into the backend or frontend.**
On 37 district-seasons from 13 districts, no model reliably beats chance on the 4-class target, and no trained model should be shown as a "ML-generated vulnerability". The experiment is kept as a documented negative result.

## 1. Data audit (Phase 1)

**Labels: the two files are the same data.** Backend `flood_labels.csv` and prep `labels_annual.csv` match on all 165 district-years: same 99 reported and 66 unknown rows, identical affected population, and identical classes (0 mismatches). Use `labels_annual.csv` as the authoritative file because it also carries `metric_value` (affected %), `risk_class` and `quality_flags`.

**How classes were generated** (verified, not assumed): `affected_pct = affected_population / pop_total x 100`, binned at the 0.4 / 0.7 / 0.9 quantiles of reporting years <= 2021: **1.64 %, 6.72 %, 18.82 %** (`label_thresholds.json`). I re-applied the thresholds and reproduced all 99 classes. So the classes are *relative severity bands of reported impact*, not official categories, and they depend on the population denominator, whose units and year are flagged **UNVERIFIED** in `population_check.md`.

**Reporting periods differ by year**, so labels are not like-for-like:

| year | period | days | labelled districts |
|---|---|---|---|
| 2019 | 27 Oct - 1 Nov | 5 | 7 |
| 2020 | 22 May - 28 Oct | 159 | 10 |
| 2021 | 1 Jun - 18 Sep | 109 | 21 |
| 2022 | 6 Apr - 28 Oct | 205 | 33 |
| 2023 | 1 May - 31 Oct | 183 | 28 |

**Rainfall:** the prep and backend rainfall files are identical (17,797 rows, 13 districts; backend ids are `dt_code`). Observations are intermittent (median gap 1 day within runs, but long gaps between runs), and the file contains **no zero-rain values** (min 0.02 mm), so absent days cannot be read as either dry or missing. 2019-2023 coverage is uneven: e.g. Nagaon 2023 has 11 reported days in Jun-Sep.

**Terrain:** `static_features.csv` is complete for 33 districts (0 missing, 100 % valid DEM). `pop_total` and `pop_density_km2` are the **denominator of the target**, so they would leak the label and are excluded.

### Exact usable sample (attrition)

| step | rows |
|---|---|
| labelled district-years | 99 |
| drop 2019 (5-day snapshot, not a season) | 92 |
| districts with any rainfall station | 41 |
| >= 30 reported rainfall days in 1 Jun - 30 Sep | **37** |

- 37 rows, **13 districts**; years 2020: 6, 2021: 11, 2022: 12, 2023: 8 (rainfall file has no station for 20 of 33 districts).
- Classes: Low 10, Moderate 11, High 7, Severe 9. Each class has enough rows to be present in folds, but only 7-11 rows each, with 2-5 per class per year.
- The 20 districts without rainfall stations can never receive an ML estimate (the model would need an input it does not have).
- Climatology (9 districts, 3-4 years of baseline) was **not** used as a feature: it is derived from the same short record and would add temporal dependence.

### Why the labels are hard to predict
Share of label variance explained by group means (R^2, 92 labelled rows): **district 0.42, year 0.24**. The district's own previous classes barely predict its next one (district-history baseline, leave-one-year-out: 21-27 % accuracy, 4-class chance is 25 %). Year-level shifts (2022 severe, 2023 mild) and the changing reporting period dominate, and the rainfall file cannot explain them with 13 districts.

## 2. Design (Phase 2)

- **Row / target:** district-season, 4-class `risk_class` from the authoritative labels (plus a 2-class sensitivity: High/Severe vs Low/Moderate, a defended merge because classes are relative bands, not because of counts).
- **Rainfall window:** fixed 1 Jun - 30 Sep each year, so features are comparable although labels cover different periods.
- **Features** (computed on reported days only; missing is never zero; district-seasons with < 30 reported days are dropped, not imputed):
  rain: mean, p90, max of reported-day rainfall, fraction of reported days >= 64.5 mm, coefficient of variation.
  terrain: mean elevation, elevation SD, mean slope, low-lying fraction, area.
  Rolling 3/7-day maxima were **not** built: the record is not continuous enough.
- **Excluded:** pop_total, pop_density (target denominator), centroid lat/lon and district id (identifiers), year, coverage count, climatology.
- **Validation:** leave-one-district-out (unseen districts) and leave-one-year-out (new season), pooled out-of-fold; district-cluster bootstrap CIs; within-year label-permutation test; no oversampling, no synthetic labels.
- **Baselines:** majority class of the training fold, district-history (modal class in other years). Note: with balanced classes, leave-one-group-out majority prediction scores *below* chance by construction, so compare against 0.25, not only against it.
- **Models:** Logistic Regression (balanced), Random Forest (500 trees, depth 3, leaf >= 2, balanced), XGBoost (depth 2, 150 trees), seed 42.

## 3. Results (Phase 3), `reports/model_comparison.md`

4-class macro-F1, leave-one-district-out (chance ~ 0.25), 95 % CI in brackets:

| model | rain only | terrain only | terrain + rain |
|---|---|---|---|
| Logistic Regression | 0.28 (0.14-0.42) | 0.40 (0.24-0.51) | 0.41 (0.23-0.51) |
| Random Forest | 0.10 (0.00-0.19) | 0.36 (0.22-0.45) | 0.19 (0.08-0.27) |
| XGBoost | 0.15 (0.03-0.27) | 0.31 (0.18-0.42) | 0.27 (0.13-0.37) |

- Every interval includes chance-level performance (~0.25), apart from models that are worse than chance. The Random Forest with terrain + rain, the intended primary model, scored macro-F1 0.19 (leave-one-district-out) and 0.31 (leave-one-year-out); label-permutation p = 0.63. Rainfall-only models do not beat chance.
- The only mild signal is in terrain-only models (elevation correlates -0.34 with class). With 13 districts and static terrain, that is indistinguishable from the model recognising district identity, and says nothing about rainfall hazard.
- 2-class sensitivity: best leave-one-district-out macro-F1 0.62 (CI 0.43-0.78, Logistic Regression, rainfall only), but the CI covers 0.50 chance, and it does not hold for the Random Forest (0.48-0.59).
- Within-year, rainfall mean/p90/max correlate only weakly with class (Spearman ~ 0.25).

Because the primary model fails validation, I did **not** produce feature importances, SHAP plots, model artifacts or sample predictions. They would be explanations of a model that does not predict, and would read as evidence it does.

## 4. Backend / frontend integration (Phases 4-5)
Not done, by design. Nothing existing was modified: no database, route, IMD recent-rainfall code, `compute_assessments.py`, or frontend file. Everything is under `flood_risk_backend/ml/`.
Tests: `ml/tests` 4 passed (no leaky features, exact counts, no zero-filling, thresholds reproduce classes). The backend and frontend were not available to me, so their existing tests were not run.

## 5. Recommended defensible approach for the capstone
1. Keep the current vulnerability (district history, unknown when < 2 known years) and rainfall hazard + combined rule; describe them as transparent, rule-based.
2. Present this ML study as a **feasibility analysis with a negative result**: grouped validation, leakage controls, permutation test, and why it fails (n = 37, 13 districts, year-dependent relative labels, unverified denominator).
3. To make ML defensible later: add rainfall for the 20 uncovered districts (gridded CHIRPS/IMD, area-weighted), label every year with the same reporting window, verify the population denominator (or use affected-people counts), and re-run `scripts/evaluate_models.py`. A model only becomes worth integrating if it beats chance in leave-one-district-out with a CI above ~0.25-0.30.

## 6. Limitations of this study
Relative classes; 4 seasons; 2019 excluded (changes the sample by 2 rows); station-mean thresholds (64.5 mm) are approximate; classes come from thresholds computed on <= 2021 labels, which slightly overlaps the test fold (3 numbers from 99 rows, unlikely to matter at this noise level); the permutation test uses 100 runs and 100 trees.
