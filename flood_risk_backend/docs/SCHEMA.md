# Database schema

Defined in `app/models/` (SQLAlchemy). Default engine: SQLite. Nine tables. **Tables are created only by `scripts/seed_db.py`** (`create_all`: creates
missing tables, never alters or drops) or by `scripts/import_imd_rainfall.py` when applying. The API never creates tables; it answers 503 if they are missing.

## Relationships and constraint notes

```
districts (id) ─┬─< flood_labels         (district_id)   unique (district_id, year)
                ├─< rainfall_daily       (district_id)   unique (district_id, date)
                ├─< climatology          (district_id)   unique (district_id, window_days, doy)
                ├─< rainfall_imd_recent  (district_id)   unique (district_id, date)
                ├─< risk_assessments     (district_id)   unique (district_id, as_of_date, window_days)
                ├─1 normal_seasons       (district_id = primary key)
                └─1 vulnerabilities      (district_id = primary key)
meta (key)   stand-alone key/value store
```

* **Foreign keys are declared but NOT enforced.** SQLite ignores `FOREIGN KEY` clauses unless `PRAGMA foreign_keys=ON`, and the application never turns it on
  (a deliberate decision: enforcement should not be enabled on a real database before its orphan rows have been reviewed). Check for orphans, read-only, with
  `python scripts/db_snapshot.py report --db <file>`.
* The unique constraints above are what makes the importers idempotent (`assess_safe.py` upserts on `(district_id, as_of_date, window_days)`;
  `import_imd_rainfall.py` upserts on `(district_id, date)`).
* Missing values are stored as `NULL`, never as 0 (rainfall, affected population, terrain). `NULL` rainfall means "not observed".
* Dates are stored as SQLite `DATE` (ISO text).

## Tables

### `districts`  (written by `seed_db.py`; upserted by id, never deleted by seeding)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | district id from the data-prep export (indexed) |
| `name` | VARCHAR | no | indexed |
| `state` | VARCHAR | no | |
| `geometry` | TEXT | no | GeoJSON Polygon/MultiPolygon string |
| `mean_elevation_m`, `elevation_std_m`, `mean_slope_deg`, `low_lying_frac` | FLOAT | yes | terrain statistics (stored/served, not used in the main vulnerability) |
| `pop_density_km2` | FLOAT | yes | unverified; not used in any calculation |

### `flood_labels`  (seasonal historical impact per district-year; a present `flood_labels.csv` REPLACES the table)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `district_id` | INTEGER | no | FK `districts.id`, indexed |
| `year` | INTEGER | no | indexed. One **seasonal** row per district-year; labels are never daily |
| `status` | VARCHAR | no | `reported` \| `no_reported_impact` \| `unknown` |
| `impact_class` | VARCHAR | yes | `low|moderate|high|severe`, only with `reported` |
| `affected_population` | FLOAT | yes | NULL = missing; 0 only when the source states zero |
| `reporting_period` | VARCHAR | yes | |
| `caveats` | JSON | yes | list of strings |

Unique: `uq_flood_label (district_id, year)`.

### `rainfall_daily`  (historical station rainfall; REPLACED by `seed_db.py` when `rainfall_daily.csv` is present)
`id` INTEGER PK · `district_id` INTEGER FK, indexed · `date` DATE indexed · `rainfall_mm` FLOAT **nullable** · `n_stations` INTEGER nullable.
Unique: `uq_rain_district_date (district_id, date)`.

### `climatology`  (baseline quantiles; REPLACED by `seed_db.py` when `climatology.csv` is present)
`id` INTEGER PK · `district_id` INTEGER FK, indexed · `window_days` INTEGER indexed · `doy` INTEGER (day of year) · `n_values` INTEGER nullable ·
`n_years` INTEGER nullable · `q50, q75, q90, q95, q97, q99` FLOAT. Quantiles of the district's own window totals, baseline years only.
Unique: `uq_clim (district_id, window_days, doy)`.

### `normal_seasons`  (REPLACED by `seed_db.py` when its file is present; input of the optional ML vulnerability only)
`district_id` INTEGER PK, FK · `features` JSON (not null).

### `meta`  (upserted by key by `seed_db.py`)
`key` VARCHAR PK · `value` JSON (not null). Keys in use: `hazard_config` (windows, `level_quantiles`, `min_obs_fraction`, …), `label_thresholds`.

### `vulnerabilities`  (derived; written by `assess_safe.py --refresh-vulnerability` or the legacy `compute_assessments.py`)
| Column | Type | Null | Notes |
|---|---|---|---|
| `district_id` | INTEGER | PK, FK | one row per district; a district without enough history has **no row** (unknown) |
| `source` | VARCHAR | no | `district_history` (default) or `ml_model` (only if `ALLOW_ML_VULNERABILITY=true` and a model exists) |
| `risk_class` | VARCHAR | no | `low|moderate|high|severe` |
| `class_index` | INTEGER | no | 0..3; for history: the district's mean class index rounded with Python `round` (half-to-even) and clamped to 0..3 |
| `expected_index` | FLOAT | no | for history: the unrounded mean class index over the district's known years (4 decimals); for ML: the probability-weighted index |
| `proba`, `shap_top_features` | JSON | yes | NULL for history |
| `model_version` | VARCHAR | yes | |

### `risk_assessments`  (derived; written by `assess_safe.py` or the legacy `compute_assessments.py`)
| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `district_id` | INTEGER | no | FK, indexed |
| `as_of_date` | DATE | no | indexed; the last day of the window |
| `window_days` | INTEGER | no | indexed |
| `window_rain_mm` | FLOAT | yes | NULL when too few days were observed |
| `obs_fraction` | FLOAT | yes | share of the window's days observed |
| `hazard_level` | INTEGER | yes | 0..3, NULL = unknown |
| `status` | VARCHAR | no | `ok` \| `insufficient_rainfall_data` \| `no_climatology` \| `vulnerability_unavailable` |
| `combined_class` | VARCHAR | yes | NULL = unknown |
| `combined_score` | FLOAT | yes | 0..1 ordering index |
| `model_version` | VARCHAR | yes | |

Unique: `uq_assessment (district_id, as_of_date, window_days)`. This table is **derived data** and can be recomputed from the others; `assess_safe.py` is the safe way to do so.

### `rainfall_imd_recent`  (recent IMD rainfall; upserted by `import_imd_rainfall.py`; separate from `rainfall_daily`)
`id` INTEGER PK · `district_id` INTEGER FK, indexed · `date` DATE indexed · `rainfall_mm` FLOAT nullable (the importer never stores NULL) ·
`source` VARCHAR not null, default `IMD_daily_actual_2026`. Unique: `uq_imd_rain_district_date (district_id, date)`.
Not used to compute hazard levels and never used to train the ML experiment.

## Which command touches which table

| Command | Tables written | Notes |
|---|---|---|
| `seed_db.py` | `districts` (upsert), `flood_labels`, `rainfall_daily`, `climatology`, `normal_seasons` (replace if file present), `meta` (upsert) | one transaction; never touches `risk_assessments`, `vulnerabilities`, `rainfall_imd_recent` or unrelated tables |
| `assess_safe.py --apply` | `risk_assessments` (upsert in range); `vulnerabilities` only with `--refresh-vulnerability` | one transaction |
| `import_imd_rainfall.py` | `rainfall_imd_recent` only | upsert, or `--replace` |
| `compute_assessments.py` (legacy) | deletes and rebuilds `vulnerabilities` and `risk_assessments` | **destructive**; avoid |
| API | none | read-only |
