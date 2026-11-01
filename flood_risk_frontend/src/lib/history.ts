/** Builds the daily rainfall-window series for the History charts. Missing days stay null (gaps), never 0. */
import type { Assessment } from "../api/types";
import { HAZARD_LEVEL_CLASS } from "../constants";
import { hazardClass } from "./assessment";
import { eachDay } from "./dates";

export interface HistoryPoint {
  date: string;
  /** 0..3, or null when the hazard is unknown for that date. */
  level: number | null;
  /** Rain total of the window ending on `date`, or null when unknown. */
  rain: number | null;
  /** Why this date has no hazard value; null when it has one. */
  gap: string | null;
}

export function buildHistoryPoints(rows: Assessment[], start: string, end: string): HistoryPoint[] {
  const byDate = new Map(rows.map((a) => [a.as_of_date, a]));
  return eachDay(start, end).map((date) => {
    const a = byDate.get(date);
    const hz = hazardClass(a);
    const rain = a?.hazard?.window_rain_mm;
    return {
      date,
      level: hz.cls === "unknown" ? null : HAZARD_LEVEL_CLASS.indexOf(hz.cls),
      rain: typeof rain === "number" && Number.isFinite(rain) ? rain : null,
      gap: hz.reason,
    };
  });
}
