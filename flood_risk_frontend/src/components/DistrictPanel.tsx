import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Assessment, District } from "../api/types";
import { BASIS_LABEL, STATUS_REASON } from "../constants";
import { useAsync } from "../hooks/useAsync";
import { NO_ASSESSMENT, combinedClass, hazardClass, mm, pct, vulnerabilityClass } from "../lib/assessment";
import { formatDate } from "../lib/dates";
import { ClassChip } from "./ClassChip";
import { ComponentBadge } from "./ComponentBadge";
import { Disclaimer } from "./Disclaimer";
import { DistrictFacts } from "./DistrictFacts";
import { FloodImpactSection } from "./FloodImpactSection";
import { ProbabilityChart } from "./ProbabilityChart";
import { ShapChart } from "./ShapChart";
import { ErrorState, Loading, isNotFound } from "./StateViews";

function Section({ title, badge, children }: { title: string; badge?: string | null; children: ReactNode }) {
  return (
    <section className="component-card">
      <header>
        <h3>{title}</h3>
        {badge !== undefined && <ComponentBadge type={badge} />}
      </header>
      {children}
    </section>
  );
}

/**
 * The three parts of one assessment, shown separately: vulnerability, rain hazard, combined level.
 * Pure: takes the assessment as a prop. `variant="scenario"` is used by the what-if page.
 */
export function AssessmentView({ assessment: a, variant = "observed" }: { assessment: Assessment; variant?: "observed" | "scenario" }) {
  const hz = hazardClass(a);
  const vu = vulnerabilityClass(a);
  const co = combinedClass(a);
  const v = a.vulnerability;
  const statusNote = a.status !== "ok" ? (STATUS_REASON[a.status] ?? `Status: ${a.status}`) : null;
  const scenario = variant === "scenario";

  return (
    <div className="assessment-view">
      <p className="basis-line">
        <strong>Rainfall window: {a.window_days} days</strong> ending {formatDate(a.as_of_date)} · {BASIS_LABEL[a.basis] ?? a.basis}
      </p>
      {scenario && (
        <p className="status-note" role="note">
          <strong>Hypothetical.</strong> The rain total was typed in; it is not an observed event. Vulnerability below is the stored value and does not change with your input.
        </p>
      )}
      {statusNote && (
        <p className="status-note" role="note" data-status={a.status}>
          <strong>Some values are Unknown.</strong> {statusNote}
        </p>
      )}
      <p className="muted small">
        These are three separate parts, not three model predictions. Only vulnerability can come from a machine-learning model; rain hazard and the combined level follow fixed rules.
      </p>

      <Section title="District vulnerability" badge={v?.component_type ?? "empirical_history"}>
        <ClassChip result={vu} showReason large />
        {v ? (
          <>
            <p className="muted small">
              Seasonal flood-impact class expected in a <em>normal</em> season, not tied to the rainfall window. Expected class index {Number.isFinite(v.expected_index) ? v.expected_index.toFixed(2) : "not available"} on a 0–3 scale
              {v.model_version ? ` · model ${v.model_version}` : ""}.
            </p>
            {v.proba ? (
              <>
                <h4>Class probabilities</h4>
                <ProbabilityChart proba={v.proba} />
                <p className="muted small">Probabilities are model output, not calibrated and not validated against floods.</p>
              </>
            ) : (
              <p className="notice">
                This district uses its historical mean class (empirical history), so there are no class probabilities and no SHAP explanation.
              </p>
            )}
            {v.shap_top_features && v.shap_top_features.length > 0 && (
              <>
                <h4>Top features behind the estimate</h4>
                <ShapChart features={v.shap_top_features} />
              </>
            )}
          </>
        ) : (
          <p className="muted small">No vulnerability has been computed for this district.</p>
        )}
      </Section>

      <Section title="Rain hazard" badge={a.hazard?.component_type ?? "rule_based"}>
        <ClassChip result={hz} showReason large />
        <ul className="metrics">
          <li>
            Rain in window: <strong>{mm(a.hazard?.window_rain_mm) ?? "Unknown"}</strong>
          </li>
          <li>
            Days with rainfall data: <strong>{pct(a.hazard?.obs_fraction) ?? "Unknown"}</strong>
          </li>
          {a.hazard?.exceeded && (
            <li>
              Exceeded: <strong>{a.hazard.exceeded}</strong>
            </li>
          )}
        </ul>
        <p className="muted small">
          Compared with this district's own rainfall history for the same time of year. A day without an observation is missing, not zero rain.
        </p>
      </Section>

      <Section title="Combined risk category" badge={a.combined?.component_type ?? "rule_based_combination"}>
        <ClassChip result={co} showReason large />
        <p className="muted small">
          {typeof a.combined?.risk_score === "number"
            ? `Ordering index ${a.combined.risk_score.toFixed(2)} (0–1). It ranks districts; it is not a probability.`
            : "No ordering index without a combined level."}{" "}
          Rule-based and not validated against observed floods.
        </p>
      </Section>

      <Disclaimer text={a.disclaimer} />
    </div>
  );
}

/** Side panel for a selected district. Terrain, history and the "no assessment" state all work without an assessment. */
export function DistrictPanel({
  district,
  windowDays,
  date,
  onClose,
}: {
  district: District;
  windowDays: number | null;
  date: string | null;
  onClose: () => void;
}) {
  const state = useAsync(
    async () => (windowDays === null ? null : api.districtAssessment(district.id, windowDays, date)),
    [district.id, windowDays, date],
  );
  const missing = state.status === "ok" && state.data === null;

  return (
    <aside className="panel" aria-label={`Assessment for ${district.name}`}>
      <header className="panel-head">
        <div>
          <h2>{district.name}</h2>
          <p className="muted small">{district.state}</p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={onClose} aria-label="Close panel">
          ✕
        </button>
      </header>

      {state.status === "loading" && <Loading label="Loading assessment…" />}
      {state.status === "error" &&
        (isNotFound(state.error) ? (
          <NoAssessment name={district.name} windowDays={windowDays} date={date} />
        ) : (
          <ErrorState error={state.error} onRetry={state.reload} />
        ))}
      {missing && <NoAssessment name={district.name} windowDays={null} date={null} />}
      {state.status === "ok" && state.data && <AssessmentView assessment={state.data} />}

      <FloodImpactSection districtId={district.id} districtName={district.name} />

      <section className="component-card">
        <header>
          <h3>Terrain and population</h3>
        </header>
        <DistrictFacts district={district} />
      </section>

      <p className="panel-links">
        <Link to={`/history?district=${district.id}${windowDays ? `&window=${windowDays}` : ""}`}>History for {district.name}</Link>
        <Link to="/about#model">How these values are produced</Link>
      </p>
    </aside>
  );
}

function NoAssessment({ name, windowDays, date }: { name: string; windowDays: number | null; date: string | null }) {
  return (
    <div className="state state-empty" role="status">
      <h3>No assessment available</h3>
      <p>
        {windowDays === null
          ? "The backend offers no rainfall window, so nothing was requested."
          : `Nothing is stored for ${name} with a ${windowDays}-day window${date ? ` ending ${formatDate(date)}` : ""}.`}{" "}
        {NO_ASSESSMENT} On the map this district is grey (Unknown), which does not mean Low risk. Its terrain and history are still shown below.
      </p>
    </div>
  );
}
