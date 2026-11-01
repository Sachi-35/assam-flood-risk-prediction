/**
 * Turns a backend assessment into what the UI shows. The one rule that matters here:
 * missing data is "Unknown" with a reason, never "Low".
 */
import type { Assessment, RiskClass } from "../api/types";
import { CLASS_ORDER, CLASS_STYLE, HAZARD_LEVEL_CLASS, STATUS_REASON, type ColorMode, type DisplayClass } from "../constants";

/** Reason shown when the backend has no stored assessment row for a district. */
export const NO_ASSESSMENT = "No assessment is stored for this district for the chosen window and date.";

export interface ClassResult {
  cls: DisplayClass;
  label: string;
  /** Why the value is Unknown; null when known. */
  reason: string | null;
}

export function asRiskClass(v: unknown): RiskClass | null {
  return typeof v === "string" && (CLASS_ORDER as string[]).includes(v) ? (v as RiskClass) : null;
}

export function unknownResult(reason: string): ClassResult {
  return { cls: "unknown", label: CLASS_STYLE.unknown.label, reason };
}

export function knownResult(cls: RiskClass): ClassResult {
  return { cls, label: CLASS_STYLE[cls].label, reason: null };
}

export function statusReason(status: string | undefined): string {
  return (status && STATUS_REASON[status]) || "The backend returned no value for this item.";
}

export function hazardClass(a: Assessment | undefined | null): ClassResult {
  if (!a) return unknownResult(NO_ASSESSMENT);
  const lvl = a.hazard?.level;
  if (typeof lvl === "number" && Number.isInteger(lvl) && lvl >= 0 && lvl < HAZARD_LEVEL_CLASS.length) {
    return knownResult(HAZARD_LEVEL_CLASS[lvl]);
  }
  return unknownResult(statusReason(a.status));
}

export function vulnerabilityClass(a: Assessment | undefined | null): ClassResult {
  if (!a) return unknownResult(NO_ASSESSMENT);
  const c = asRiskClass(a.vulnerability?.risk_class);
  if (c) return knownResult(c);
  return unknownResult(STATUS_REASON.vulnerability_unavailable);
}

export function combinedClass(a: Assessment | undefined | null): ClassResult {
  if (!a) return unknownResult(NO_ASSESSMENT);
  const c = asRiskClass(a.combined?.risk_class);
  if (c) return knownResult(c);
  return unknownResult(statusReason(a.status));
}

export function classFor(a: Assessment | undefined | null, mode: ColorMode): ClassResult {
  if (mode === "hazard") return hazardClass(a);
  if (mode === "vulnerability") return vulnerabilityClass(a);
  return combinedClass(a);
}

/** Percent with no decimals, or null. */
export function pct(v: number | null | undefined): string | null {
  return typeof v === "number" && Number.isFinite(v) ? `${Math.round(v * 100)}%` : null;
}

export function mm(v: number | null | undefined): string | null {
  return typeof v === "number" && Number.isFinite(v) ? `${v.toFixed(1)} mm` : null;
}
