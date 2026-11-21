/** Counts only classes present in stored assessments. Unknown is never added to Low. */
import type { Assessment, District, RiskClass } from "../api/types";
import { CLASS_ORDER, type ColorMode } from "../constants";
import { classFor, hazardClass } from "./assessment";

export interface MapSummary {
  total: number;
  assessed: number;
  unknown: number;
  noAssessment: number;
  byClass: Record<RiskClass, number>;
  withRainHazard: number;
}

export function summarize(
  districts: District[],
  byDistrict: Map<number, Assessment>,
  mode: ColorMode,
): MapSummary {
  const byClass = Object.fromEntries(
    CLASS_ORDER.map((riskClass) => [riskClass, 0]),
  ) as Record<RiskClass, number>;

  let assessed = 0;
  let noAssessment = 0;
  let withRainHazard = 0;

  for (const district of districts) {
    const assessment = byDistrict.get(district.id);

    if (!assessment) noAssessment++;

    const result = classFor(assessment, mode);

    if (result.cls !== "unknown") {
      assessed++;
      byClass[result.cls]++;
    }

    if (hazardClass(assessment).cls !== "unknown") {
      withRainHazard++;
    }
  }

  return {
    total: districts.length,
    assessed,
    unknown: districts.length - assessed,
    noAssessment,
    byClass,
    withRainHazard,
  };
}
