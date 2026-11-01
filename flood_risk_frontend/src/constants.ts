/**
 * Single place for presentation constants and documented project facts.
 * Nothing here is data from the backend, except DATA_FACTS and YEAR_NOTES, which restate limitations
 * the project team documented during data preparation (update them if data preparation changes).
 */
import type { RiskClass } from "./api/types";

export const CLASS_ORDER: RiskClass[] = ["low", "moderate", "high", "severe"];

/** Display classes: the four real classes plus "unknown" (missing data, never shown as Low). */
export type DisplayClass = RiskClass | "unknown";

export interface ClassStyle {
  label: string;
  /** Fill colour: a sequential pale-yellow -> orange -> red -> dark plum ramp (lightness steps down monotonically). */
  color: string;
  /** Text colour that meets contrast on `color`. */
  ink: string;
  /** Pattern drawn over the colour so classes are distinguishable without colour (see MapPatterns). */
  pattern: "none" | "stripes" | "cross" | "dots" | "hatch";
  glyph: string;
}

export const CLASS_STYLE: Record<DisplayClass, ClassStyle> = {
  low: { label: "Low", color: "#f6e7a3", ink: "#3b3200", pattern: "none", glyph: "●" },
  moderate: { label: "Moderate", color: "#f2a649", ink: "#3a2000", pattern: "stripes", glyph: "◆" },
  high: { label: "High", color: "#d4472a", ink: "#ffffff", pattern: "cross", glyph: "▲" },
  severe: { label: "Severe", color: "#6f1d4b", ink: "#ffffff", pattern: "dots", glyph: "■" },
  unknown: { label: "Unknown", color: "#c9ced6", ink: "#2b3340", pattern: "hatch", glyph: "?" },
};

export const UNKNOWN_COLOR = CLASS_STYLE.unknown.color;

/** Hazard level 0..3 -> class (same four bands as the other components). */
export const HAZARD_LEVEL_CLASS: RiskClass[] = ["low", "moderate", "high", "severe"];

export type ColorMode = "combined" | "hazard" | "vulnerability";

/** Seasonal vulnerability is listed (and defaulted) first: it does not depend on the rainfall window. */
export const COLOR_MODES: { value: ColorMode; label: string; help: string }[] = [
  {
    value: "vulnerability",
    label: "District vulnerability",
    help: "Seasonal flood-impact class expected in a normal season: an ML estimate or the district's own historical class. Does not depend on the rainfall window.",
  },
  {
    value: "hazard",
    label: "Rain hazard",
    help: "Rain over the chosen window compared with this district's own history for the same time of year (fixed rules). Needs rainfall observations, which exist for only some districts.",
  },
  {
    value: "combined",
    label: "Combined",
    help: "Fixed rule combining vulnerability and rain hazard. Unknown whenever either part is unknown. Not validated against observed floods.",
  },
];
export const DEFAULT_MODE: ColorMode = "vulnerability";

/** Badge text per backend `component_type`. */
export const COMPONENT_BADGE: Record<string, { text: string; hint: string }> = {
  rule_based: { text: "Rule-based", hint: "Computed with fixed rules from rainfall data; no model is involved." },
  rule_based_combination: { text: "Rule-based", hint: "Fixed rule combining vulnerability class and hazard level." },
  ml_estimate: { text: "ML estimate", hint: "Estimated by a machine-learning model trained on a small set of district-year labels." },
  empirical_history: { text: "Empirical history", hint: "The district's own historical mean impact class; no model is used." },
};

/** Why a value is Unknown, keyed by the backend `status`. */
export const STATUS_REASON: Record<string, string> = {
  insufficient_rainfall_data:
    "Too few days in this window have rainfall data. Rainfall observations cover only some districts and have gaps; a missing day is never treated as zero rain.",
  no_climatology:
    "There is no historical baseline for this district, window length and day of year, so the rain total cannot be compared.",
  vulnerability_unavailable:
    "No vulnerability has been computed for this district, so a combined level cannot be given.",
};

export const BASIS_LABEL: Record<string, string> = {
  observed_window: "Stored rainfall observations",
  scenario: "Hypothetical scenario (rain total typed by the user)",
};

/** Plain-language names for the model's input features (names from the backend feature list). */
export const FEATURE_LABEL: Record<string, string> = {
  season_total_mm: "Season total rain (mm)",
  season_anomaly_pct: "Season rain vs normal (%)",
  season_max1d_mm: "Heaviest single day (mm)",
  season_max3d_mm: "Heaviest 3-day total (mm)",
  season_max7d_mm: "Heaviest 7-day total (mm)",
  season_heavy_days: "Number of heavy-rain days",
  hazard_max_level_7d: "Peak 7-day hazard level",
  hazard_days_high_7d: "Days at high 7-day hazard",
  hazard_max_level_30d: "Peak 30-day hazard level",
  hazard_days_high_30d: "Days at high 30-day hazard",
  mean_elevation_m: "Mean elevation (m)",
  elevation_std_m: "Elevation spread (m)",
  mean_slope_deg: "Mean slope (°)",
  low_lying_frac: "Low-lying share of land",
  pop_density_km2: "Population density (/km²)",
};

export function featureLabel(name: string): string {
  return FEATURE_LABEL[name] ?? name.replace(/_/g, " ");
}

/** Colours for SHAP bars (also encoded by sign and label, not colour alone). */
export const SHAP_COLOR = { increases: "#b4381d", decreases: "#2a6db0" };

/**
 * The commands that fill the backend with data, shown in empty states.
 * NOTE: they need prepared feature files that are not in the data-preparation project yet.
 */
export const BACKEND_COMMANDS = {
  train: "python scripts/train_model.py",
  seed: "python scripts/seed_db.py --reset",
  compute: "python scripts/compute_assessments.py --start 2023-06-01 --end 2023-09-30",
  run: "uvicorn app.main:app --reload",
};

/* ---------------------------------------------------------------------------------------------
 * Documented project facts (from the data-preparation work). Shown on the About page.
 * -------------------------------------------------------------------------------------------- */

/** The boundary file has 33 polygons. Used only to warn when the backend returns a different number. */
export const EXPECTED_DISTRICTS = 33;

/** Years covered by the processed seasonal flood labels. Years outside this span are shown only if the backend returns them. */
export const LABEL_YEARS = { first: 2019, last: 2023 };

export const DATA_FACTS = {
  boundaryPolygons: 33,
  labelYears: "2019 to 2023",
  sourceRecords: 103,
  districtYearRecords: 99,
  possibleDistrictYears: 165,
  unknownDistrictYears: 66,
  rainfallStations: 43,
  rainfallDistricts: 13,
};

/** Caveats that apply to a whole reporting year, shown next to that year whatever the backend returns. */
export const YEAR_NOTES: Record<number, string> = {
  2019: "Some 2019 records are a fourth-wave snapshot, not a complete season.",
  2020: "The 2020 affected-population total does not reconcile with the source memo.",
};

export const ELEVATION_NOTE =
  "Elevation comes from Copernicus GLO-30, a digital surface model (it includes buildings and vegetation canopy), not bare-earth terrain.";
export const POPULATION_NOTE =
  "Population density comes from a raster whose year and units have not been verified yet. Treat it as unverified.";
