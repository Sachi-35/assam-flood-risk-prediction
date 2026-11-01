/** Counts for the dashboard overview. Unknown is its own bucket: it is never added to Low. */
import type { Assessment, District, RiskClass } from "../api/types";
import { CLASS_ORDER, type ColorMode } from "../constants";
import { classFor, hazardClass } from "./assessment";

export interface MapSummary {
  /** Districts the backend returned. */
  total: number;
  /** Districts with a known level in the chosen colour mode. */
  assessed: number;
  /** total - assessed (includes districts with no stored assessment). */
  unknown: number;
  /** Districts with no stored assessment row at all (a subset of `unknown`). */
  noAssessment: number;
  byClass: Record<RiskClass, number>;
  /** Districts whose rain hazard is known (rainfall observations were sufficient). */
  withRainHazard: number;
}

export function summarize(districts: District[], byDistrict: Map<number, Assessment>, mode: ColorMode): MapSummary {
  const byClass = Object.fromEntries(CLASS_ORDER.map((c) => [c, 0])) as Record<RiskClass, number>;
  let assessed = 0;
  let noAssessment = 0;
  let withRainHazard = 0;
  for (const d of districts) {
    const a = byDistrict.get(d.id);
    if (!a) noAssessment++;
    const res = classFor(a, mode);
    if (res.cls !== "unknown") {
      assessed++;
      byClass[res.cls]++;
    }
    if (hazardClass(a).cls !== "unknown") withRainHazard++;
  }
  return { total: districts.length, assessed, unknown: districts.length - assessed, noAssessment, byClass, withRainHazard };
}
