import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Assessment, District, ScenarioRequest } from "../api/types";
import { AssessmentView } from "../components/DistrictPanel";
import { BootGate } from "../components/BootGate";
import { ErrorState, Loading } from "../components/StateViews";
import { useAvailableDates } from "../hooks/useAvailableDates";
import { pickWindow } from "../hooks/useBoot";
import { formatDate } from "../lib/dates";
import { MAX_RAIN_MM, validateScenario, type ScenarioErrors, type ScenarioFormValues } from "../lib/scenario";

export function ScenarioForm({
  districts,
  windows,
  initial,
  busy = false,
  onSubmit,
  onWindowChange,
}: {
  districts: District[];
  windows: number[];
  initial: ScenarioFormValues;
  busy?: boolean;
  onSubmit: (req: ScenarioRequest) => void;
  onWindowChange?: (windowDays: number) => void;
}) {
  const [values, setValues] = useState<ScenarioFormValues>(initial);
  const [errors, setErrors] = useState<ScenarioErrors>({});

  // Allow the parent to fill in a default end date once it is known, without overwriting the user's input.
  useEffect(() => {
    setValues((v) => (v.endDate === "" && initial.endDate ? { ...v, endDate: initial.endDate } : v));
  }, [initial.endDate]);

  const set = (k: keyof ScenarioFormValues) => (e: { target: { value: string } }) => {
    setValues((v) => ({ ...v, [k]: e.target.value }));
    if (k === "windowDays" && onWindowChange) onWindowChange(Number(e.target.value));
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const res = validateScenario(values, windows);
    setErrors(res.errors);
    if (res.request) onSubmit(res.request);
  };

  const err = (k: keyof ScenarioFormValues) => (errors[k] ? <span className="field-error" id={`err-${k}`} role="alert">{errors[k]}</span> : null);

  return (
    <form className="scenario-form" onSubmit={submit} noValidate>
      <label>
        <span>District</span>
        <select value={values.districtId} onChange={set("districtId")} aria-invalid={!!errors.districtId} aria-describedby={errors.districtId ? "err-districtId" : undefined}>
          <option value="">Choose a district…</option>
          {districts.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        {err("districtId")}
      </label>
      <label>
        <span>Window length</span>
        <select value={values.windowDays} onChange={set("windowDays")} aria-invalid={!!errors.windowDays} aria-describedby={errors.windowDays ? "err-windowDays" : undefined}>
          <option value="">Choose…</option>
          {windows.map((w) => (
            <option key={w} value={w}>
              {w} days
            </option>
          ))}
        </select>
        {err("windowDays")}
      </label>
      <label>
        <span>Window ends on</span>
        <input type="date" value={values.endDate} onChange={set("endDate")} aria-invalid={!!errors.endDate} aria-describedby={errors.endDate ? "err-endDate" : undefined} />
        <small>Only sets the time of year the typed rain total is compared against. It is not a date anything is expected to happen.</small>
        {err("endDate")}
      </label>
      <label>
        <span>Total rain over the window (mm)</span>
        <input
          type="number"
          inputMode="decimal"
          step="any"
          min={0}
          max={MAX_RAIN_MM}
          value={values.rainMm}
          onChange={set("rainMm")}
          aria-invalid={!!errors.rainMm}
          aria-describedby={errors.rainMm ? "err-rainMm" : undefined}
        />
        <small>Between 0 and {MAX_RAIN_MM} mm, summed over the whole window.</small>
        {err("rainMm")}
      </label>
      <button type="submit" className="btn btn-primary" disabled={busy || windows.length === 0}>
        {busy ? "Working…" : "Run hypothetical scenario"}
      </button>
    </form>
  );
}

export function ScenarioPage() {
  return <BootGate>{(boot) => <ScenarioView windows={boot.windows} districts={boot.districts} />}</BootGate>;
}

function ScenarioView({ windows, districts }: { windows: number[]; districts: District[] }) {
  const [params] = useSearchParams();
  const initialWindow = pickWindow(params.get("window"), windows);
  const [windowForDates, setWindowForDates] = useState<number | null>(initialWindow);
  const datesState = useAvailableDates(windowForDates, districts.map((d) => d.id));
  const latest = datesState.status === "ok" && datesState.data.length ? datesState.data[datesState.data.length - 1] : "";

  const districtParam = params.get("district");
  const initial: ScenarioFormValues = {
    districtId: districts.some((d) => String(d.id) === districtParam) ? districtParam! : "",
    windowDays: initialWindow ? String(initialWindow) : "",
    endDate: latest,
    rainMm: "",
  };

  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ req: ScenarioRequest; assessment: Assessment } | null>(null);
  const [error, setError] = useState<unknown>(null);

  const run = async (req: ScenarioRequest) => {
    setBusy(true);
    setError(null);
    try {
      setResult({ req, assessment: await api.scenario(req) });
    } catch (e) {
      setResult(null);
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const name = result ? districts.find((d) => d.id === result.req.district_id)?.name ?? `District ${result.req.district_id}` : "";

  return (
    <div className="page narrow">
      <h1>Rainfall scenario (hypothetical)</h1>
      <aside className="scenario-warning" role="note">
        <strong>This page is illustrative only.</strong> You type in a rain total for a window and the backend rates it with the same fixed rules it uses for observed rain. The number you enter is
        not an observation, not a prediction and not a statement about what will happen. The result is never mixed into the map, the overview or the history, and it says nothing about the
        seasonal flood record.
      </aside>
      <p className="muted">
        The rules compare your total with the district's own rainfall history for the same time of year. If the district has no such baseline (rainfall observations cover only some
        districts), the result is Unknown. The vulnerability shown is the stored seasonal value; it does not change with your input.
      </p>
      <ScenarioForm
        districts={districts}
        windows={windows}
        initial={initial}
        busy={busy}
        onSubmit={run}
        onWindowChange={setWindowForDates}
      />
      {busy && <Loading label="Running scenario…" />}
      {error !== null && <ErrorState error={error} onRetry={result ? () => run(result.req) : undefined} />}
      {result && (
        <section className="scenario-card" aria-label="Scenario result">
          <div className="scenario-ribbon">HYPOTHETICAL SCENARIO: not an observation</div>
          <h2>{name}</h2>
          <p>
            Suppose the {result.req.window_days} days ending {formatDate(result.req.window_end_date)} had brought a total of{" "}
            <strong>{result.req.window_rain_mm} mm</strong> (typed by you):
          </p>
          <AssessmentView assessment={result.assessment} variant="scenario" />
        </section>
      )}
    </div>
  );
}
