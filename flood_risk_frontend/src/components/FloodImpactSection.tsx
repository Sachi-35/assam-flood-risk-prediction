import { api } from "../api/client";
import { CLASS_STYLE, LABEL_YEARS, YEAR_NOTES } from "../constants";
import { useAsync } from "../hooks/useAsync";
import { countImpact, impactTimeline, unknownCell, type ImpactCell } from "../lib/impact";
import { EmptyState, ErrorState, Loading } from "./StateViews";

const count = new Intl.NumberFormat("en-IN");

function cellTitle(c: ImpactCell): string {
  if (c.kind === "reported") return c.cls ? CLASS_STYLE[c.cls].label : "Reported";
  if (c.kind === "none_reported") return "No reported impact";
  return "Unknown";
}

/** One box per year. Known = colour of the class. No reported impact = white with a dashed border. Unknown = grey hatched. */
export function ImpactCellView({ cell }: { cell: ImpactCell }) {
  const style = cell.kind === "reported" && cell.cls ? { background: CLASS_STYLE[cell.cls].color, color: CLASS_STYLE[cell.cls].ink } : undefined;
  const note = YEAR_NOTES[cell.year];
  return (
    <li className={`impact-cell impact-${cell.kind}`} style={style} data-kind={cell.kind} data-year={cell.year}>
      <span className="impact-year">{cell.year}</span>
      <strong className="impact-label">{cellTitle(cell)}</strong>
      {cell.kind === "reported" && !cell.cls && <span className="impact-sub">class not available</span>}
      {cell.kind === "reported" && (
        <span className="impact-sub">Affected: {cell.affected === null ? "not available" : count.format(cell.affected)}</span>
      )}
      {cell.kind === "unknown" && cell.reason && <span className="impact-sub">{cell.reason}</span>}
      {cell.period && <span className="impact-sub">{cell.period}</span>}
      {[...cell.caveats, ...(note ? [note] : [])].map((t) => (
        <span key={t} className="impact-sub impact-caveat">
          ⚠ {t}
        </span>
      ))}
    </li>
  );
}

/** Pure view over already-fetched records (testable without the network). */
export function ImpactTimelineView({ records }: { records: unknown[] }) {
  const cells = impactTimeline(records);
  const n = countImpact(cells);
  return (
    <>
      <ul className="impact-strip" aria-label="Flood impact by year">
        {cells.map((c) => (
          <ImpactCellView key={c.year} cell={c} />
        ))}
      </ul>
      <p className="muted small">
        {n.reported} year(s) with a reported impact, {n.none_reported} with no reported impact, <strong>{n.unknown} unknown</strong>. Unknown years are not zero and are not Low;
        they are missing from the source data. Absolute affected counts are not comparable between districts of different size.
      </p>
    </>
  );
}

/** Historical flood impact for one district, from the (proposed) /districts/{id}/flood-impact endpoint. */
export function FloodImpactSection({ districtId, districtName }: { districtId: number; districtName: string }) {
  const state = useAsync(() => api.floodImpact(districtId), [districtId]);
  return (
    <section className="component-card" aria-label={`Historical flood impact for ${districtName}`}>
      <header>
        <h3>Historical flood impact</h3>
        <span className="badge badge-empirical_history" title="Reported seasonal impact from source reports; no model involved.">
          Source records
        </span>
      </header>
      <p className="muted small">
        Seasonal impact by year, {LABEL_YEARS.first} to {LABEL_YEARS.last}. Not a daily record.
      </p>
      {state.status === "loading" && <Loading label="Loading flood-impact records…" />}
      {state.status === "error" && <ErrorState error={state.error} onRetry={state.reload} />}
      {state.status === "ok" && state.data.kind === "unavailable" && (
        <>
          <ul className="impact-strip" aria-label="Flood impact by year">
            {Array.from({ length: LABEL_YEARS.last - LABEL_YEARS.first + 1 }, (_, i) => (
              <ImpactCellView key={i} cell={unknownCell(LABEL_YEARS.first + i, "The backend does not provide yearly flood-impact records yet.")} />
            ))}
          </ul>
          <EmptyState title="Yearly flood-impact records are not available from the backend">
            This is a gap in the backend, not a finding: the grey boxes mean <em>unknown</em>, not “no flooding”. See BACKEND_NOTES.md for the endpoint to add.
          </EmptyState>
        </>
      )}
      {state.status === "ok" && state.data.kind === "ok" && <ImpactTimelineView records={state.data.records} />}
    </section>
  );
}
