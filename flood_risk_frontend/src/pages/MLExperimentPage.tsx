import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { MLExperimentSummary } from "../api/types";

function pct(value: number | null): string {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function modelName(model: string): string {
  return ({
    majority: "Majority baseline",
    logreg: "Logistic Regression",
    random_forest: "Random Forest",
    xgboost: "XGBoost",
  } as Record<string, string>)[model] ?? model;
}

function featureName(features: string): string {
  return ({
    baseline: "Baseline",
    rain_only: "Rainfall",
    static_only: "Terrain",
    static_plus_rain: "Terrain + rainfall",
  } as Record<string, string>)[features] ?? features;
}

function districtName(value: string): string {
  return value.split("_").map((part) =>
    part.charAt(0).toUpperCase() + part.slice(1)
  ).join(" ");
}

export function MLExperimentPage() {
  const [data, setData] = useState<MLExperimentSummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    api.mlExperiment()
      .then((result) => {
        if (active) setData(result);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(
          err instanceof ApiError
            ? err.detail
            : err instanceof Error
              ? err.message
              : "Could not load the ML experiment report."
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  if (loading) {
    return <div className="page"><div className="state state-loading"><span className="spinner" /> Loading ML experiment results…</div></div>;
  }

  if (error || !data) {
    return (
      <div className="page">
        <div className="page-intro">
          <h1>ML Experiment</h1>
          <p>Retrospective model feasibility and validation results.</p>
        </div>
        <div className="state state-error">
          <h3>Could not load the experiment</h3>
          <p>{error || "The backend returned no report."}</p>
          <p className="small">Check that the backend is running and that the ML report files are available.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page ml-page">
      <div className="page-intro">
        <h1>ML Experiment</h1>
        <p>
          Retrospective feasibility study comparing machine-learning approaches
          for seasonal district-level flood-impact classification in Assam.
        </p>
      </div>

      <div className="ml-status">
        <strong>Experimental only · Not integrated into live assessments</strong>
        <p>
          These results evaluate whether the available historical data support
          a reliable model. They do not provide current district risk estimates.
        </p>
      </div>

      <section className="ml-stats" aria-label="Dataset summary">
        <div><span>Usable samples</span><strong>{data.n_rows}</strong><small>District-season records</small></div>
        <div><span>Districts</span><strong>{data.n_districts}</strong><small>Out of 33 Assam districts</small></div>
        <div><span>Labelled records</span><strong>{data.attrition.labelled_district_years}</strong><small>Before data filtering</small></div>
        <div><span>Retained after filtering</span><strong>{data.attrition.with_at_least_30_rain_days}</strong><small>At least 30 reported rainfall days</small></div>
      </section>

      <section className="ml-section">
        <h2>Dataset filtering</h2>
        <p className="muted small">Records remaining after each data-quality requirement.</p>
        <div className="table-scroll ml-table">
          <table>
            <thead><tr><th>Filtering stage</th><th>Records remaining</th></tr></thead>
            <tbody>
              <tr><td>Labelled district-years</td><td>{data.attrition.labelled_district_years}</td></tr>
              <tr><td>After excluding 2019 snapshot records</td><td>{data.attrition.after_excluding_2019_snapshots}</td></tr>
              <tr><td>With any rainfall station data</td><td>{data.attrition.with_any_rainfall_station}</td></tr>
              <tr><td>With at least 30 reported rainfall days</td><td>{data.attrition.with_at_least_30_rain_days}</td></tr>
              <tr><td>Rows missing static features</td><td>{data.attrition.rows_missing_static}</td></tr>
            </tbody>
          </table>
        </div>
        <h3>Class distribution</h3>
        <ul className="ml-class-counts">
          {Object.entries(data.class_counts).map(([label, count]) => (
            <li key={label}><span>{label}</span><strong>{count}</strong></li>
          ))}
        </ul>
      </section>

      <section className="ml-section">
        <h2>Model comparison</h2>
        <p className="muted small">
          Four-class Leave-One-District-Out (LODO) validation. Higher macro-F1
          is better. The approximate chance-level reference is 0.25.
        </p>
        <div className="table-scroll ml-table">
          <table>
            <thead>
              <tr>
                <th>Model</th><th>Features</th><th>Accuracy</th>
                <th>Balanced accuracy</th><th>Macro-F1</th>
                <th>Macro-F1 95% CI</th><th>Ordinal MAE</th>
              </tr>
            </thead>
            <tbody>
              {data.models.map((item, index) => (
                <tr key={`${item.model}-${item.features}-${index}`}>
                  <td>{modelName(item.model)}</td>
                  <td>{featureName(item.features)}</td>
                  <td>{pct(item.accuracy)}</td>
                  <td>{pct(item.balanced_accuracy)}</td>
                  <td><strong>{item.macro_f1.toFixed(3)}</strong></td>
                  <td>{item.macro_f1_ci95 ? `${item.macro_f1_ci95[0].toFixed(3)}–${item.macro_f1_ci95[1].toFixed(3)}` : "—"}</td>
                  <td>{item.ordinal_mae.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="notice warn">
          The Logistic Regression model with terrain and rainfall features had
          the highest macro-F1 (0.407), but its confidence interval
          (0.230–0.513) includes the 0.25 chance-level reference. This is not
          sufficient evidence of reliable generalisation.
        </p>
      </section>

      <section className="ml-section">
        <h2>Random Forest permutation test</h2>
        <p className="muted small">
          Tests whether the Random Forest scores show evidence of signal beyond
          shuffled labels.
        </p>
        <div className="table-scroll ml-table">
          <table>
            <thead><tr><th>Feature set</th><th>Observed macro-F1</th><th>Permutation mean</th><th>Permutation 95th percentile</th><th>p-value</th></tr></thead>
            <tbody>
              <tr>
                <td>Terrain + rainfall</td>
                <td>{data.permutation_test.static_plus_rain.observed_macro_f1.toFixed(3)}</td>
                <td>{data.permutation_test.static_plus_rain.perm_mean.toFixed(3)}</td>
                <td>{data.permutation_test.static_plus_rain.perm_p95.toFixed(3)}</td>
                <td>{data.permutation_test.static_plus_rain.p_value.toFixed(3)}</td>
              </tr>
              <tr>
                <td>Rainfall only</td>
                <td>{data.permutation_test.rain_only.observed_macro_f1.toFixed(3)}</td>
                <td>{data.permutation_test.rain_only.perm_mean.toFixed(3)}</td>
                <td>{data.permutation_test.rain_only.perm_p95.toFixed(3)}</td>
                <td>{data.permutation_test.rain_only.p_value.toFixed(3)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="notice warn">
          The terrain + rainfall Random Forest permutation-test p-value is
          {` ${data.permutation_test.static_plus_rain.p_value.toFixed(3)} `}.
          The test does not provide evidence of useful predictive signal.
        </p>
      </section>

      <section className="ml-section">
        <h2>Retrospective validation samples</h2>
        <p className="muted small">
          Historical actual class compared with out-of-fold model outputs.
          These are validation records, not current district assessments.
        </p>
        <div className="table-scroll ml-table ml-samples">
          <table>
            <thead>
              <tr><th>District</th><th>Year</th><th>Actual class</th><th>Logistic Regression</th><th>Random Forest</th></tr>
            </thead>
            <tbody>
              {data.predictions.map((item, index) => (
                <tr key={`${item.district_id}-${item.year}-${index}`}>
                  <td>{districtName(item.district_id)}</td>
                  <td>{item.year}</td>
                  <td><span className={`ml-class ml-${item.actual_class.toLowerCase()}`}>{item.actual_class}</span></td>
                  <td><span className={`ml-class ml-${item.logreg_prediction.toLowerCase()}`}>{item.logreg_prediction}</span></td>
                  <td><span className={`ml-class ml-${item.random_forest_prediction.toLowerCase()}`}>{item.random_forest_prediction}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">{data.predictions.length} out-of-fold validation records shown.</p>
      </section>

      <section className="ml-section">
        <h2>Limitations and interpretation</h2>
        <ul className="ml-limitations">
          {data.limitations.map((item) => <li key={item}>{item}</li>)}
        </ul>
        <p className="disclaimer">
          Conclusion: the available dataset is too small and incomplete to
          justify integrating a trained ML model into the live assessment
          system. The existing map and assessment methodology remain separate
          from this experiment.
        </p>
      </section>
    </div>
  );
}
