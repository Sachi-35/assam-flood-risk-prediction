import { Link } from "react-router-dom";
import { CLASS_ORDER, CLASS_STYLE, COLOR_MODES, EXPECTED_DISTRICTS, type ColorMode } from "../constants";
import type { MapSummary } from "../lib/summary";
import { Swatch } from "./MapPatterns";

/** Dashboard overview: counts of known and unknown districts for the chosen view, and the data-versus-scenario rule. */
export function SummaryStrip({
  summary,
  mode,
  periodLabel,
  undrawn,
}: {
  summary: MapSummary;
  mode: ColorMode;
  /** e.g. "Last 7 days ending 12 Aug 2023", or an explanation that none is available. */
  periodLabel: string;
  /** How many districts could not be drawn on the map. */
  undrawn: number;
}) {
  const modeLabel = COLOR_MODES.find((m) => m.value === mode)!.label;
  return (
    <section className="summary" aria-label="Overview of available information">
      <dl className="stats">
        <div>
          <dt>Districts available</dt>
          <dd>{summary.total}</dd>
        </div>
        <div>
          <dt>{modeLabel}: assessed</dt>
          <dd>{summary.assessed}</dd>
        </div>
        <div className={summary.unknown > 0 ? "stat-unknown" : undefined}>
          <dt>Unknown or unavailable</dt>
          <dd>{summary.unknown}</dd>
        </div>
        <div className="stat-wide">
          <dt>Rainfall window shown</dt>
          <dd className="stat-text">{periodLabel}</dd>
        </div>
      </dl>
      <ul className="summary-classes" aria-label={`${modeLabel} districts by level`}>
        {CLASS_ORDER.map((c) => (
          <li key={c}>
            <Swatch cls={c} size={14} /> {CLASS_STYLE[c].label}: <strong>{summary.byClass[c]}</strong>
          </li>
        ))}
        <li>
          <Swatch cls="unknown" size={14} /> Unknown: <strong>{summary.unknown}</strong>
          {summary.noAssessment > 0 && <span className="muted"> ({summary.noAssessment} with no stored assessment)</span>}
        </li>
      </ul>
      <p className="muted small">
        Rain hazard is known for {summary.withRainHazard} of {summary.total} districts; rainfall observations are not available everywhere.
      </p>
      {summary.total !== EXPECTED_DISTRICTS && (
        <p className="status-note" role="status">
          The project boundary file has {EXPECTED_DISTRICTS} districts, but the backend returned {summary.total}. Check that the real boundaries were loaded into the database.
        </p>
      )}
      {undrawn > 0 && (
        <p className="status-note" role="status">
          {undrawn} district(s) have unusable geometry and are not drawn on the map. They are still listed in the table below and can be selected there.
        </p>
      )}
      <p className="data-vs-scenario">
        <strong>Everything on this page is stored data.</strong> Hypothetical rainfall scenarios are on the <Link to="/scenario">Rainfall scenario</Link> page and are never shown on the map.
      </p>
    </section>
  );
}
