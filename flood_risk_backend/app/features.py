"""Single source of truth for feature names and class order (backend v3, seasonal/hybrid design).

SEASON_FEATURES : rainfall features of one district-season (from the data-prep export `season_features.csv`)
STATIC_FEATURES : one value per district (table `districts`)
OPTIONAL_STATIC : may be empty for every district (no population raster); the trainer drops a feature that has any gap.
The model's actual input list is written by the trainer to models_artifacts/feature_list.json and is what the API uses.
Keep SEASON_FEATURES identical to floodprep.climatology.SEASON_FEATURES.
"""

SEASON_FEATURES = [
    "season_total_mm", "season_anomaly_pct", "season_max1d_mm", "season_max3d_mm", "season_max7d_mm",
    "season_heavy_days", "hazard_max_level_7d", "hazard_days_high_7d", "hazard_max_level_30d", "hazard_days_high_30d",
]
STATIC_FEATURES = ["mean_elevation_m", "elevation_std_m", "mean_slope_deg", "low_lying_frac", "pop_density_km2"]
OPTIONAL_STATIC = ["pop_density_km2"]
ALL_FEATURES = SEASON_FEATURES + STATIC_FEATURES

CLASS_ORDER = ["low", "moderate", "high", "severe"]      # seasonal impact severity (relative bands, see label_thresholds.json)
LEVEL_NAMES = ["Low", "Moderate", "High", "Severe"]       # rainfall hazard level 0..3
QUANTILE_COLS = ["q50", "q75", "q90", "q95", "q97", "q99"]
