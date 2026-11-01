import type { District } from "../api/types";
import { ELEVATION_NOTE, POPULATION_NOTE } from "../constants";

function fmt(v: number | null | undefined, digits: number, unit: string, scale = 1): string {
  return typeof v === "number" && Number.isFinite(v) ? `${(v * scale).toFixed(digits)}${unit}` : "Not available";
}

/** Elevation, slope and population facts. Always shown for a selected district, with or without an assessment. */
export function DistrictFacts({ district }: { district: District }) {
  const terrain: [string, string][] = [
    ["Mean elevation", fmt(district.mean_elevation_m, 0, " m")],
    ["Elevation spread (std. dev.)", fmt(district.elevation_std_m, 1, " m")],
    ["Mean slope", fmt(district.mean_slope_deg, 1, "°")],
    ["Low-lying share of land", fmt(district.low_lying_frac, 0, "%", 100)],
  ];
  const popValue = fmt(district.pop_density_km2, 0, " per km²");
  return (
    <>
      <dl className="facts">
        {terrain.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd className={v === "Not available" ? "muted" : undefined}>{v}</dd>
          </div>
        ))}
      </dl>
      <p className="muted small">{ELEVATION_NOTE}</p>
      <dl className="facts">
        <div>
          <dt>Population density (unverified)</dt>
          <dd className={popValue === "Not available" ? "muted" : undefined}>{popValue}</dd>
        </div>
      </dl>
      <p className="muted small">{POPULATION_NOTE}</p>
    </>
  );
}
