/** Counts the classes currently displayed. Unknown is never added to Low. */
import type { Assessment, District, RiskClass } from "../api/types";
import { CLASS_ORDER, type ColorMode } from "../constants";
import { displayedClass } from "./demoRainfall";

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

    const result = displayedClass(assessment, mode, district.name);

    if (result.cls !== "unknown") {
      assessed++;
      byClass[result.cls]++;
    }

    if (displayedClass(assessment, "hazard", district.name).cls !== "unknown") {
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
