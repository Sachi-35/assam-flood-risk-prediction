/**
 * Historical flood impact: turns raw per-year records into display cells.
 * Three states are kept apart and must never be merged:
 *   reported      a known impact (class and/or affected count)
 *   none_reported the source explicitly reports no impact (an actual zero)
 *   unknown       no record, or a record without usable information (NOT zero, NOT Low)
 */
import type { FloodImpactRecord, RiskClass } from "../api/types";
import { LABEL_YEARS } from "../constants";
import { asRiskClass } from "./assessment";

export type ImpactKind = "reported" | "none_reported" | "unknown";

export interface ImpactCell {
  year: number;
  kind: ImpactKind;
  /** Only for kind "reported" when the backend supplied a valid class. */
  cls: RiskClass | null;
  /** Source count; null whenever it was missing (never defaulted to 0). */
  affected: number | null;
  period: string | null;
  caveats: string[];
  /** Why the cell is unknown; null otherwise. */
  reason: string | null;
}

function validCount(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null;
}

function text(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

const NO_RECORD = "No record for this year in the processed flood labels.";

export function unknownCell(year: number, reason: string = NO_RECORD): ImpactCell {
  return { year, kind: "unknown", cls: null, affected: null, period: null, caveats: [], reason };
}

/** null when the record has no usable year (it cannot be placed on the timeline). */
export function normalizeImpact(raw: unknown): ImpactCell | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as FloodImpactRecord;
  const year = typeof r.year === "number" && Number.isInteger(r.year) ? r.year : null;
  if (year === null) return null;

  const caveats = Array.isArray(r.caveats) ? r.caveats.filter((c): c is string => typeof c === "string" && c.trim() !== "") : [];
  const base = { year, affected: validCount(r.affected_population), period: text(r.reporting_period), caveats };
  const status = typeof r.status === "string" ? r.status : null;
  const cls = asRiskClass(r.impact_class);

  if (status === "no_reported_impact") return { ...base, kind: "none_reported", cls: null, reason: null };
  if (status === "reported" || status === null) {
    if (cls || (status === "reported" && base.affected !== null)) return { ...base, kind: "reported", cls, reason: null };
    return { ...base, kind: "unknown", cls: null, reason: status === "reported" ? "The record is marked reported but has no class or count." : "The record has no usable impact information." };
  }
  return { ...base, kind: "unknown", cls: null, reason: "The source did not give a usable impact for this year." };
}

/** One cell per year from `first` to `last` (plus any extra years the backend returned). Missing years become unknown cells. */
export function impactTimeline(
  records: unknown[] | null | undefined,
  first: number = LABEL_YEARS.first,
  last: number = LABEL_YEARS.last,
): ImpactCell[] {
  const byYear = new Map<number, ImpactCell>();
  for (const raw of records ?? []) {
    const cell = normalizeImpact(raw);
    if (!cell) continue;
    const prev = byYear.get(cell.year);
    // If a year appears twice, keep the one that carries information.
    if (!prev || (prev.kind === "unknown" && cell.kind !== "unknown")) byYear.set(cell.year, cell);
  }
  const years = new Set<number>(byYear.keys());
  for (let y = first; y <= last; y++) years.add(y);
  return [...years].sort((a, b) => a - b).map((y) => byYear.get(y) ?? unknownCell(y));
}

export function countImpact(cells: ImpactCell[]): Record<ImpactKind, number> {
  const out: Record<ImpactKind, number> = { reported: 0, none_reported: 0, unknown: 0 };
  for (const c of cells) out[c.kind]++;
  return out;
}
