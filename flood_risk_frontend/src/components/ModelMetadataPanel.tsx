import { api } from "../api/client";
import type { CvScores, ModelMetadata } from "../api/types";
import { BACKEND_COMMANDS } from "../constants";
import { useAsync } from "../hooks/useAsync";
import { formatDate } from "../lib/dates";
import { EmptyState, ErrorState, Loading } from "./StateViews";

const CV_ROWS: { key: "model" | "majority" | "district_mean_other_years"; label: string }[] = [
  { key: "model", label: "The vulnerability model" },
  { key: "majority", label: "Baseline: always the most common class" },
  { key: "district_mean_other_years", label: "Baseline: district's own mean class in the other years" },
];

const fmt = (n: number | undefined) => (typeof n === "number" ? n.toFixed(3) : "n/a");

function SourceExplanation({ source }: { source: string }) {
  if (source === "ml_model")
    return <p className="notice">The model beat both baselines in cross-validation, so districts are shown with an <strong>ML estimate</strong>.</p>;
  if (source === "district_history")
    return (
      <p className="notice warn">
        The model did <strong>not</strong> beat the baselines in cross-validation, so the app uses each district's historical mean class
        (<strong>Empirical history</strong>) instead of model output.
      </p>
    );
  return <p className="notice">Vulnerability source: {source}</p>;
}

export function ModelMetadataView({ meta }: { meta: ModelMetadata }) {
  const cv = meta.cross_validation;
  const qwks = CV_ROWS.map((r) => (cv[r.key] as CvScores | undefined)?.qwk).filter((x): x is number => typeof x === "number");
  const bestQwk = qwks.length ? Math.max(...qwks) : null;
  return (
    <div className="model-meta">
      <SourceExplanation source={meta.vulnerability_source} />
      <dl className="facts">
        <div><dt>Model</dt><dd>{meta.model_type} ({meta.model_version})</dd></div>
        <div><dt>Trained</dt><dd>{meta.trained_at ? formatDate(meta.trained_at.slice(0, 10)) : "Unknown"}</dd></div>
        <div><dt>Training rows (district-years)</dt><dd>{meta.training_rows}</dd></div>
        <div>
          <dt>Class counts in the labels</dt>
          <dd>{Object.entries(meta.class_counts).map(([k, v]) => `${k}: ${v}`).join(" · ") || "n/a"}</dd>
        </div>
        <div><dt>Input features</dt><dd>{meta.feature_list.join(", ")}</dd></div>
        {meta.thresholds && <div><dt>Label thresholds</dt><dd>{meta.thresholds.join(", ")}</dd></div>}
      </dl>

      <h4>Cross-validation against baselines</h4>
      <p className="muted small">
        {cv.scheme ? `Scheme: ${cv.scheme.replace(/_/g, " ")}. ` : ""}
        {typeof cv.n_out_of_fold === "number" ? `${cv.n_out_of_fold} out-of-fold district-years. ` : ""}
        Higher is better for F1, kappa and within-one-class; lower is better for the error.
      </p>
      <div className="table-scroll">
        <table className="cv-table">
          <thead>
            <tr>
              <th scope="col">Method</th>
              <th scope="col" title="Macro-averaged F1">Macro F1</th>
              <th scope="col" title="Quadratic-weighted kappa: agreement that penalises big class misses more">Quadratic kappa</th>
              <th scope="col">Within one class</th>
              <th scope="col">Mean class error</th>
            </tr>
          </thead>
          <tbody>
            {CV_ROWS.map((r) => {
              const s = cv[r.key] as CvScores | undefined;
              const best = bestQwk !== null && s?.qwk === bestQwk;
              return (
                <tr key={r.key} className={best ? "best" : undefined}>
                  <th scope="row">{r.label}{best ? " ★" : ""}</th>
                  <td>{fmt(s?.macro_f1)}</td>
                  <td>{fmt(s?.qwk)}</td>
                  <td>{fmt(s?.within_1_class)}</td>
                  <td>{fmt(s?.ordinal_mae)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">★ = best quadratic kappa, the score the backend uses to decide between the model and the baselines.</p>

      {cv.caveat && <p className="notice warn"><strong>Caveat.</strong> {cv.caveat}</p>}
      <p className="small">{meta.notes}</p>
    </div>
  );
}

/** Fetches /model/metadata. 503 (model not trained) is shown as a normal empty state, not an error. */
export function ModelMetadataPanel() {
  const state = useAsync(() => api.modelMetadata(), []);
  if (state.status === "loading") return <Loading label="Loading model details…" />;
  if (state.status === "error") return <ErrorState error={state.error} onRetry={state.reload} />;
  if (state.data.kind === "untrained") {
    return (
      <EmptyState title="The vulnerability model has not been trained yet" commands={[BACKEND_COMMANDS.train, BACKEND_COMMANDS.seed, BACKEND_COMMANDS.compute]}>
        The backend reports: “{state.data.detail}” Until then there are no cross-validation scores to show.
      </EmptyState>
    );
  }
  return <ModelMetadataView meta={state.data.data} />;
}
