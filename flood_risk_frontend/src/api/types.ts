/**
 * Types mirroring the backend's pydantic schemas
 * (flood_risk_backend/app/schemas/{assessment,district,model_metadata}.py).
 */

export type ComponentType =
  | "rule_based"
  | "rule_based_combination"
  | "ml_estimate"
  | "empirical_history";

/** Seasonal flood-impact / combined class. */
export type RiskClass = "low" | "moderate" | "high" | "severe";

export type AssessmentStatus =
  | "ok"
  | "insufficient_rainfall_data"
  | "no_climatology"
  | "vulnerability_unavailable";

export type Basis = "observed_window" | "scenario";

export interface Hazard {
  component_type: "rule_based";
  /** 0 Low, 1 Moderate, 2 High, 3 Severe; null when unknown. */
  level: number | null;
  label: string | null;
  /** Human-readable text, e.g. "baseline quantile q90" or "none of the baseline quantiles". */
  exceeded: string | null;
  window_rain_mm: number | null;
  /** Share (0..1) of the window's days that have rainfall data. */
  obs_fraction: number | null;
}

export interface ShapFeature {
  feature_name: string;
  contribution_value: number;
  direction: "increases_risk" | "decreases_risk" | string;
}

export interface Vulnerability {
  component_type: "ml_estimate" | "empirical_history";
  risk_class: RiskClass | string;
  expected_index: number;
  /** Class probabilities; null for empirical_history. */
  proba: Record<string, number> | null;
  /** Null for empirical_history. */
  shap_top_features: ShapFeature[] | null;
  model_version: string | null;
}

export interface Combined {
  component_type: "rule_based_combination";
  risk_class: RiskClass | string | null;
  /** 0..1 ordering index, NOT a probability. */
  risk_score: number | null;
}

export interface Assessment {
  district_id: number;
  district_name: string | null;
  as_of_date: string; // YYYY-MM-DD
  window_days: number;
  basis: Basis;
  status: AssessmentStatus | string;
  hazard: Hazard;
  vulnerability: Vulnerability | null;
  combined: Combined;
  disclaimer: string;
}

export interface ScenarioRequest {
  district_id: number;
  window_days: number;
  window_end_date: string; // YYYY-MM-DD
  window_rain_mm: number; // 0..2000
}

export interface WindowsResponse {
  windows: number[];
  meaning: string;
}

export interface GeoJsonGeometry {
  type: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  coordinates: any;
}

export interface District {
  id: number;
  name: string;
  state: string;
  geometry: GeoJsonGeometry;
  mean_elevation_m: number | null;
  elevation_std_m: number | null;
  mean_slope_deg: number | null;
  low_lying_frac: number | null;
  pop_density_km2: number | null;
}

export interface CvScores {
  macro_f1: number;
  qwk: number;
  within_1_class: number;
  ordinal_mae: number;
}

export interface CrossValidation {
  scheme?: string;
  n_out_of_fold?: number;
  caveat?: string;
  model?: CvScores;
  majority?: CvScores;
  district_mean_other_years?: CvScores;
  [key: string]: unknown;
}

export interface ModelMetadata {
  model_version: string;
  model_type: string;
  trained_at: string;
  training_rows: number;
  feature_list: string[];
  class_counts: Record<string, number>;
  /** "ml_model", or "district_history" when the model did not beat the baselines. */
  vulnerability_source: string;
  cross_validation: CrossValidation;
  thresholds: number[] | null;
  notes: string;
}

/** Result of GET /model/metadata: either metadata or the "not trained" (503) state. */
export type ModelMetadataResult =
  | { kind: "ok"; data: ModelMetadata }
  | { kind: "untrained"; detail: string };

/**
 * PROPOSED endpoint (not in the backend contract reported so far): GET /districts/{id}/flood-impact.
 * One record per district-year. Every field except `year` may be missing or null; the frontend
 * never turns a missing value into zero (see lib/impact.ts).
 */
export interface FloodImpactRecord {
  year: number;
  /** "reported" | "no_reported_impact" | "unknown". Anything else is treated as unknown. */
  status?: string | null;
  /** Seasonal impact class, only meaningful when status is "reported". */
  impact_class?: string | null;
  /** Absolute count from the source report. Not comparable across districts of different size. */
  affected_population?: number | null;
  /** Free text, e.g. "Reporting period 1 Jun to 30 Sep (fourth-wave snapshot)". */
  reporting_period?: string | null;
  caveats?: string[] | null;
}

/** Result of the flood-impact request: records, or "the backend does not provide this endpoint". */
export type FloodImpactResult =
  | { kind: "ok"; records: FloodImpactRecord[] }
  | { kind: "unavailable"; detail: string };


export interface RecentRainfallObservation {
  district_id: number;
  district: string;
  date: string;
  rainfall_mm: number;
  source: string;
}

export interface RecentRainfallResponse {
  dataset: string;
  total_matching: number;
  returned: number;
  limit: number;
  filters: {
    district_id: number | null;
    start: string | null;
    end: string | null;
  };
  observations: RecentRainfallObservation[];
  disclaimer: string;
}


export interface MLExperimentModel {
  model: string;
  features: string;
  accuracy: number;
  balanced_accuracy: number;
  macro_f1: number;
  macro_f1_ci95: [number, number] | null;
  ordinal_mae: number;
}

export interface MLExperimentPrediction {
  district_id: string;
  year: number;
  actual_class: string;
  logreg_prediction: string;
  random_forest_prediction: string;
}

export interface MLExperimentSummary {
  status: string;
  n_rows: number;
  n_districts: number;
  attrition: {
    labelled_district_years: number;
    after_excluding_2019_snapshots: number;
    with_any_rainfall_station: number;
    with_at_least_30_rain_days: number;
    rows_missing_static: number;
  };
  class_counts: Record<string, number>;
  models: MLExperimentModel[];
  permutation_test: {
    static_plus_rain: {
      observed_macro_f1: number;
      perm_mean: number;
      perm_p95: number;
      p_value: number;
    };
    rain_only: {
      observed_macro_f1: number;
      perm_mean: number;
      perm_p95: number;
      p_value: number;
    };
  };
  predictions: MLExperimentPrediction[];
  limitations: string[];
}
