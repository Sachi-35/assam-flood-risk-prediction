import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { MLExperimentSummary } from "../api/types";
import { PageHeader, Section, StatCard } from "../components/ui";

const CHANCE_REFERENCE = 0.25;

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
    return <div className="page"><PageHeader eyebrow="Research · Experiment" title="ML Experiment" /><div className="state state-loading"><span className="spinner" /> Loading ML experiment results…</div></div>;
  }

  const best = data ? data.models.reduce<MLExperimentSummary["models"][number] | null>((m, x) => (!m || x.macro_f1 > m.macro_f1 ? x : m), null) : null;

  if (error || !data) {
    return (
      <div className="page">
        <PageHeader eyebrow="Research · Experiment" title="ML Experiment">Retrospective model feasibility and validation results.</PageHeader>
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
      <PageHeader eyebrow="Research · Experiment" title="ML Experiment">
        A retrospective feasibility study: can the available historical data support a machine-learning model of seasonal district-level flood impact in Assam?
      </PageHeader>

      <div className="ml-status">
        <strong>Experimental only · Not integrated into live assessments</strong>
        <p>
          These results evaluate whether the available historical data support a reliable model. They do not provide current district risk estimates, and no trained
          model feeds the risk map. The operational risk-assessment pages use fixed rules and historical records instead.
        </p>
      </div>

      <section className="ml-stats" aria-label="Dataset summary">
        <StatCard label="Usable samples" value={data.n_rows} sub="District-season records" />
        <StatCard label="Districts" value={data.n_districts} sub="Out of 33 Assam districts" />
        <StatCard label="Labelled records" value={data.attrition.labelled_district_years} sub="Before data filtering" />
        <StatCard label="Retained after filtering" value={data.attrition.with_at_least_30_rain_days} sub="At least 30 reported rainfall days" />
      </section>

      <Section title="Understanding the metrics" subtitle="Plain-language meanings for the terms used in the tables below.">
        <dl className="card metric-list" style={{ marginTop: 0 }}>
          <dt>Macro-F1</dt>
          <dd>A score from 0 to 1 that averages how well the model does on each of the four classes, giving rare classes the same weight as common ones. Higher is better. With four balanced classes, random guessing scores around {CHANCE_REFERENCE.toFixed(2)}.</dd>
          <dt>Accuracy and balanced accuracy</dt>
          <dd>Accuracy is the share of records classified correctly. Balanced accuracy averages the share correct within each class, so a model cannot look good just by favouring the most common class.</dd>
          <dt>Ordinal MAE</dt>
          <dd>The average number of classes a prediction is off by (for example, predicting Low when the actual class was High is 2 classes off). Lower is better.</dd>
          <dt>Leave-One-District-Out (LODO) validation</dt>
          <dd>Each district is held out in turn: the model is trained on the other districts and tested on the held-out one. This checks whether the model works on a district it has never seen.</dd>
          <dt>95% confidence interval</dt>
          <dd>A range of plausible macro-F1 values given the small sample. If the range includes the chance-level reference, the result cannot be told apart from guessing.</dd>
          <dt>Permutation test and p-value</dt>
          <dd>The labels are shuffled many times to see what scores arise by luck alone. The p-value is the share of shuffled runs that scored at least as well as the real one. A large p-value means the real score is not distinguishable from luck.</dd>
        </dl>
      </Section>

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
        {best && (
          <p className="notice warn">
            The {modelName(best.model)} model with {featureName(best.features).toLowerCase()} features had the highest macro-F1 ({best.macro_f1.toFixed(3)})
            {best.macro_f1_ci95
              ? best.macro_f1_ci95[0] <= CHANCE_REFERENCE && CHANCE_REFERENCE <= best.macro_f1_ci95[1]
                ? `, but its 95% confidence interval (${best.macro_f1_ci95[0].toFixed(3)}–${best.macro_f1_ci95[1].toFixed(3)}) includes the ${CHANCE_REFERENCE.toFixed(2)} chance-level reference. This is not sufficient evidence of reliable generalisation.`
                : `. Its 95% confidence interval is ${best.macro_f1_ci95[0].toFixed(3)}–${best.macro_f1_ci95[1].toFixed(3)}. Read this together with the small sample and the limitations below; it does not make the model suitable for operational use.`
              : ". No confidence interval was reported for it, so the score should be treated with caution given the small sample."}
          </p>
        )}
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
          The terrain + rainfall Random Forest permutation-test p-value is {data.permutation_test.static_plus_rain.p_value.toFixed(3)}.{" "}
          {data.permutation_test.static_plus_rain.p_value >= 0.05
            ? "The test does not provide evidence of useful predictive signal."
            : "This is below 0.05 for this test, but with a sample this small it still does not make the model suitable for operational use."}
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
