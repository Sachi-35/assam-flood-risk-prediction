/**
 * Converts backend assessments into UI display classes.
 * Missing classifications may use clearly disclosed illustrative placeholders.
 */
import type { Assessment, RiskClass } from "../api/types";
import {
  CLASS_ORDER,
  CLASS_STYLE,
  HAZARD_LEVEL_CLASS,
  STATUS_REASON,
  type ColorMode,
  type DisplayClass,
} from "../constants";

export const NO_ASSESSMENT =
  "No assessment is stored for this district for the chosen window and date.";

const ILLUSTRATIVE_REASON =
  "Illustrative placeholder based on rainfall amount, not a climatology-based hazard assessment.";

const COMBINED_REASON =
  "Illustrative combined placeholder using the higher of vulnerability and rainfall-based hazard. Not a validated risk assessment.";

export interface ClassResult {
  cls: DisplayClass;
  label: string;
  reason: string | null;
}

export function asRiskClass(v: unknown): RiskClass | null {
  return typeof v === "string" && (CLASS_ORDER as string[]).includes(v)
    ? (v as RiskClass)
    : null;
}

export function unknownResult(reason: string): ClassResult {
  return {
    cls: "unknown",
    label: CLASS_STYLE.unknown.label,
    reason,
  };
}

export function knownResult(cls: RiskClass): ClassResult {
  return {
    cls,
    label: CLASS_STYLE[cls].label,
    reason: null,
  };
}

function illustrativeResult(cls: RiskClass, reason: string): ClassResult {
  return {
    cls,
    label: CLASS_STYLE[cls].label,
    reason,
  };
}

export function statusReason(status: string | undefined): string {
  return (
    (status && STATUS_REASON[status]) ||
    "The backend returned no value for this item."
  );
}

/**
 * Display-only fallback thresholds for a rainfall window.
 * These are illustrative and are not calibrated flood-warning thresholds.
 */
function illustrativeRainClass(rainfall: number): RiskClass {
  if (rainfall <= 25) return "low";
  if (rainfall <= 50) return "moderate";
  if (rainfall <= 100) return "high";
  return "severe";
}

export function hazardClass(a: Assessment | undefined | null): ClassResult {
  if (!a) return unknownResult(NO_ASSESSMENT);

  const lvl = a.hazard?.level;

  // Prefer a genuine backend hazard classification when available.
  if (
    typeof lvl === "number" &&
    Number.isInteger(lvl) &&
    lvl >= 0 &&
    lvl < HAZARD_LEVEL_CLASS.length
  ) {
    return knownResult(HAZARD_LEVEL_CLASS[lvl]);
  }

  // Use rainfall only as an explicitly labelled illustrative placeholder.
  const rainfall = a.hazard?.window_rain_mm;

  if (typeof rainfall === "number" && Number.isFinite(rainfall) && rainfall >= 0) {
    return illustrativeResult(
      illustrativeRainClass(rainfall),
      ILLUSTRATIVE_REASON,
    );
  }

  return unknownResult(statusReason(a.status));
}

export function vulnerabilityClass(
  a: Assessment | undefined | null,
): ClassResult {
  if (!a) return unknownResult(NO_ASSESSMENT);

  const c = asRiskClass(a.vulnerability?.risk_class);

  if (c) return knownResult(c);

  return unknownResult(STATUS_REASON.vulnerability_unavailable);
}

export function combinedClass(a: Assessment | undefined | null): ClassResult {
  if (!a) return unknownResult(NO_ASSESSMENT);

  // Prefer a genuine backend combined classification when available.
  const stored = asRiskClass(a.combined?.risk_class);

  if (stored) return knownResult(stored);

  const vulnerability = asRiskClass(a.vulnerability?.risk_class);
  const hazard = hazardClass(a);

  if (!vulnerability) {
    return unknownResult(
      "Combined placeholder unavailable because vulnerability is Unknown.",
    );
  }

  if (hazard.cls === "unknown") {
    return unknownResult(statusReason(a.status));
  }

  const vulnerabilityRank = CLASS_ORDER.indexOf(vulnerability);
  const hazardRank = CLASS_ORDER.indexOf(hazard.cls as RiskClass);
  const combined = CLASS_ORDER[
    Math.max(vulnerabilityRank, hazardRank)
  ];

  return illustrativeResult(combined, COMBINED_REASON);
}

export function classFor(
  a: Assessment | undefined | null,
  mode: ColorMode,
): ClassResult {
  if (mode === "hazard") return hazardClass(a);
  if (mode === "vulnerability") return vulnerabilityClass(a);
  return combinedClass(a);
}

/** Percent with no decimals, or null. */
export function pct(v: number | null | undefined): string | null {
  return typeof v === "number" && Number.isFinite(v)
    ? `${Math.round(v * 100)}%`
    : null;
}

export function mm(v: number | null | undefined): string | null {
  return typeof v === "number" && Number.isFinite(v)
    ? `${v.toFixed(1)} mm`
    : null;
}
