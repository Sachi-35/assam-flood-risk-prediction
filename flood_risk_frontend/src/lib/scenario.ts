/** Validation for the scenario form; mirrors the backend's ScenarioIn (rain 0..2000 mm, window from /windows). */
import type { ScenarioRequest } from "../api/types";
import { isIsoDate } from "./dates";

export const MAX_RAIN_MM = 2000;

export interface ScenarioFormValues {
  districtId: string;
  windowDays: string;
  endDate: string;
  rainMm: string;
}

export type ScenarioErrors = Partial<Record<keyof ScenarioFormValues, string>>;

export interface ScenarioValidation {
  errors: ScenarioErrors;
  /** Present only when there are no errors. */
  request?: ScenarioRequest;
}

export function validateScenario(v: ScenarioFormValues, allowedWindows: number[]): ScenarioValidation {
  const errors: ScenarioErrors = {};

  const districtId = Number(v.districtId);
  if (!v.districtId || !Number.isInteger(districtId)) errors.districtId = "Choose a district.";

  const windowDays = Number(v.windowDays);
  if (!v.windowDays || !Number.isInteger(windowDays)) errors.windowDays = "Choose a window length.";
  else if (!allowedWindows.includes(windowDays)) errors.windowDays = `Window must be one of ${allowedWindows.join(", ")} days.`;

  if (!v.endDate) errors.endDate = "Enter the date the window ends on.";
  else if (!isIsoDate(v.endDate)) errors.endDate = "Enter a valid date (YYYY-MM-DD).";

  const rainText = v.rainMm.trim();
  const rain = Number(rainText);
  if (rainText === "") errors.rainMm = "Enter the total rain in mm.";
  else if (!Number.isFinite(rain)) errors.rainMm = "Rain must be a number.";
  else if (rain < 0) errors.rainMm = "Rain cannot be negative.";
  else if (rain > MAX_RAIN_MM) errors.rainMm = `Rain must be at most ${MAX_RAIN_MM} mm.`;

  if (Object.keys(errors).length) return { errors };
  return {
    errors,
    request: { district_id: districtId, window_days: windowDays, window_end_date: v.endDate, window_rain_mm: rain },
  };
}
