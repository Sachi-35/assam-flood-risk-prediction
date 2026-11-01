/**
 * TEST FIXTURES ONLY (never imported by app code). Objects shaped like the backend's AssessmentOut,
 * built by hand to exercise specific states.
 */
import type { Assessment } from "../api/types";

const DISCLAIMER = "Test disclaimer text.";

export function makeAssessment(over: Partial<Assessment> = {}): Assessment {
  return {
    district_id: 1,
    district_name: "Test District",
    as_of_date: "2023-07-10",
    window_days: 7,
    basis: "observed_window",
    status: "ok",
    hazard: { component_type: "rule_based", level: 1, label: "Moderate", exceeded: "baseline quantile q75", window_rain_mm: 72.5, obs_fraction: 1 },
    vulnerability: {
      component_type: "ml_estimate",
      risk_class: "high",
      expected_index: 2.1,
      proba: { low: 0.1, moderate: 0.2, high: 0.6, severe: 0.1 },
      shap_top_features: [
        { feature_name: "season_total_mm", contribution_value: 0.12, direction: "increases_risk" },
        { feature_name: "mean_elevation_m", contribution_value: -0.05, direction: "decreases_risk" },
      ],
      model_version: "rf_test",
    },
    combined: { component_type: "rule_based_combination", risk_class: "high", risk_score: 0.52 },
    disclaimer: DISCLAIMER,
    ...over,
  };
}

/** A window with too little rainfall data: hazard and combined are unknown, vulnerability is still present. */
export const insufficientRain: Assessment = makeAssessment({
  status: "insufficient_rainfall_data",
  hazard: { component_type: "rule_based", level: null, label: null, exceeded: null, window_rain_mm: null, obs_fraction: 0.4 },
  combined: { component_type: "rule_based_combination", risk_class: null, risk_score: null },
});

/** Same, with the empirical-history vulnerability (no probabilities, no SHAP). */
export const historyVulnerability: Assessment = makeAssessment({
  vulnerability: { component_type: "empirical_history", risk_class: "moderate", expected_index: 1, proba: null, shap_top_features: null, model_version: null },
});

/* ---------------------------------------------------------------------------------------------
 * SYNTHETIC GEOMETRY AND DISTRICTS. TEST-ONLY: these are not Assam's real boundaries and prove
 * nothing about the real 33-district GeoJSON. They only exercise the code paths.
 * ------------------------------------------------------------------------------------------- */
import type { District, GeoJsonGeometry } from "../api/types";

/** A closed square ring starting at (x, y). Coordinates are plausible lon/lat so range checks pass. */
export function squareRing(x: number, y: number, size = 0.1): number[][] {
  return [[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]];
}

export const polygon = (x: number, y: number): GeoJsonGeometry => ({ type: "Polygon", coordinates: [squareRing(x, y)] });
export const multiPolygon = (x: number, y: number): GeoJsonGeometry => ({
  type: "MultiPolygon",
  coordinates: [[squareRing(x, y)], [squareRing(x + 0.3, y)]],
});

export function makeDistrict(id: number, geometry: GeoJsonGeometry = polygon(90 + (id % 10) * 0.2, 25 + Math.floor(id / 10) * 0.2), over: Partial<District> = {}): District {
  return {
    id,
    name: `Synthetic ${id}`,
    state: "Assam",
    geometry,
    mean_elevation_m: null,
    elevation_std_m: null,
    mean_slope_deg: null,
    low_lying_frac: null,
    pop_density_km2: null,
    ...over,
  };
}

/** 33 synthetic districts, alternating Polygon and MultiPolygon. */
export function make33Districts(): District[] {
  return Array.from({ length: 33 }, (_, i) => {
    const id = i + 1;
    const x = 90 + (i % 7) * 0.5;
    const y = 25 + Math.floor(i / 7) * 0.3;
    return makeDistrict(id, i % 2 === 0 ? polygon(x, y) : multiPolygon(x, y));
  });
}
