import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Assessment, District } from "../api/types";
import { BootGate } from "../components/BootGate";
import { ChoroplethMap } from "../components/ChoroplethMap";
import { DistrictPanel } from "../components/DistrictPanel";
import { DistrictTable } from "../components/DistrictTable";
import { Legend } from "../components/Legend";
import { SummaryStrip } from "../components/SummaryStrip";
import { EmptyState, ErrorState, Loading, isNotFound } from "../components/StateViews";
import { BACKEND_COMMANDS, COLOR_MODES, DEFAULT_MODE, type ColorMode } from "../constants";
import { useAsync } from "../hooks/useAsync";
import { useAvailableDates } from "../hooks/useAvailableDates";
import { pickWindow } from "../hooks/useBoot";
import { formatDate, nearestDate } from "../lib/dates";
import { buildDistrictFeatures } from "../lib/geo";
import { summarize } from "../lib/summary";

export function MapPage() {
  return <BootGate>{(boot) => <MapView windows={boot.windows} meaning={boot.windowsMeaning} districts={boot.districts} />}</BootGate>;
}

function MapView({ windows, meaning, districts }: { windows: number[]; meaning: string; districts: District[] }) {
  const [params, setParams] = useSearchParams();
  const [notice, setNotice] = useState<string | null>(null);

  const windowDays = pickWindow(params.get("window"), windows);
  const modeParam = params.get("mode");
  const mode: ColorMode = COLOR_MODES.some((m) => m.value === modeParam) ? (modeParam as ColorMode) : DEFAULT_MODE;
  const selectedId = Number(params.get("district")) || null;
  const selected = districts.find((d) => d.id === selectedId) ?? null;

  const update = (patch: Record<string, string | null>) =>
    setParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) (v === null ? n.delete(k) : n.set(k, v));
        return n;
      },
      { replace: true },
    );

  // Every district the backend returns goes on the map; the ones that cannot be drawn are reported, not hidden.
  const geo = useMemo(() => buildDistrictFeatures(districts), [districts]);

  const probeIds = useMemo(() => districts.map((d) => d.id), [districts]);
  const datesState = useAvailableDates(windowDays, probeIds);
  const available = datesState.status === "ok" ? datesState.data : [];
  const latest = available.length ? available[available.length - 1] : null;
  const dateParam = params.get("date");
  const effectiveDate = dateParam && available.includes(dateParam) ? dateParam : latest;

  const assessState = useAsync(
    async () => (windowDays !== null && datesState.status === "ok" && effectiveDate ? api.assessments(windowDays, effectiveDate) : ([] as Assessment[])),
    [windowDays, effectiveDate, datesState.status],
  );
  const byDistrict = useMemo(
    () => new Map((assessState.status === "ok" ? assessState.data : []).map((a) => [a.district_id, a])),
    [assessState],
  );
  const summary = useMemo(() => summarize(districts, byDistrict, mode), [districts, byDistrict, mode]);

  const idx = effectiveDate ? available.indexOf(effectiveDate) : -1;
  const setDate = (d: string) => {
    setNotice(null);
    update({ date: d });
  };
  const onDateInput = (v: string) => {
    if (!v) return;
    if (available.includes(v)) return setDate(v);
    const near = nearestDate(available, v);
    if (near) {
      update({ date: near });
      setNotice(`No assessments exist for ${formatDate(v)} with a ${windowDays}-day window; showing the nearest date, ${formatDate(near)}.`);
    }
  };

  const staleDateNote =
    dateParam && datesState.status === "ok" && available.length > 0 && !available.includes(dateParam) && !notice
      ? `No assessments exist for ${formatDate(dateParam)} with a ${windowDays}-day window; showing the latest date.`
      : null;

  const loading = datesState.status === "loading" || assessState.status === "loading";
  const noAssessments = datesState.status === "ok" && available.length === 0;
  const periodLabel =
    windowDays === null
      ? "None offered by the backend"
      : effectiveDate
        ? `Last ${windowDays} days ending ${formatDate(effectiveDate)}`
        : loading
          ? "Loading…"
          : "No stored assessments";
  const select = (id: number) => update({ district: String(id) });

  return (
    <div className="map-page">
      <header className="page-intro">
        <h1>Assam seasonal flood-risk assessment</h1>
        <p>
          District-level view combining each district's <strong>vulnerability</strong> (seasonal flood-impact class) with an optional <strong>rain hazard</strong> where rainfall observations exist.
          It does not predict floods day by day. <span className="proto-tag">Academic prototype, not an official warning service.</span>
        </p>
      </header>

      <SummaryStrip summary={summary} mode={mode} periodLabel={periodLabel} undrawn={geo.skipped.length} />

      <div className="controls" role="group" aria-label="Map controls">
        <fieldset className="segmented">
          <legend>Colour districts by</legend>
          {COLOR_MODES.map((m) => (
            <label key={m.value} title={m.help} className={mode === m.value ? "on" : ""}>
              <input type="radio" name="mode" value={m.value} checked={mode === m.value} onChange={() => update({ mode: m.value })} />
              {m.label}
            </label>
          ))}
        </fieldset>

        {windows.length > 0 && (
          <div className="control-group" role="group" aria-label="Rainfall window (used by rain hazard and combined only)">
            <label>
              <span>Rainfall window</span>
              <select value={windowDays ?? ""} onChange={(e) => update({ window: e.target.value })}>
                {windows.map((w) => (
                  <option key={w} value={w}>
                    Last {w} days
                  </option>
                ))}
              </select>
            </label>
            <div className="date-control">
              <label>
                <span>Window ends on</span>
                <input
                  type="date"
                  value={effectiveDate ?? ""}
                  min={available[0]}
                  max={latest ?? undefined}
                  disabled={available.length === 0}
                  onChange={(e) => onDateInput(e.target.value)}
                />
              </label>
              <div className="btn-row">
                <button type="button" className="btn" disabled={idx <= 0} onClick={() => setDate(available[idx - 1])} aria-label="Previous available date">
                  ◀
                </button>
                <button type="button" className="btn" disabled={idx < 0 || idx >= available.length - 1} onClick={() => setDate(available[idx + 1])} aria-label="Next available date">
                  ▶
                </button>
                <button type="button" className="btn" disabled={!latest || effectiveDate === latest} onClick={() => setDate(latest!)}>
                  Latest
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <p className="muted small window-meaning">
        {COLOR_MODES.find((m) => m.value === mode)!.help} {meaning}
        {latest ? ` Dates offered: ${formatDate(available[0])} to ${formatDate(latest)} (${available.length} days).` : ""}
      </p>
      {(notice || staleDateNote) && (
        <p className="status-note" role="status">
          {notice ?? staleDateNote}
        </p>
      )}
      {datesState.status === "error" && <ErrorState error={datesState.error} onRetry={datesState.reload} />}
      {noAssessments && (
        <EmptyState title="No assessments are stored yet" commands={[BACKEND_COMMANDS.train, BACKEND_COMMANDS.seed, BACKEND_COMMANDS.compute]}>
          {windowDays === null
            ? "The backend offers no rainfall window and has no stored assessments."
            : `The backend has no stored assessments for the ${windowDays}-day window.`}{" "}
          Every district is shown as Unknown (grey), which does not mean Low risk. You can still select a district to see its terrain. These steps need the prepared feature files from the data-preparation project.
        </EmptyState>
      )}

      <div className={`map-layout${selected ? " with-panel" : ""}`}>
        <div className="map-col">
          <div className="map-wrap">
            <ChoroplethMap
              features={geo.features}
              assessments={byDistrict}
              mode={mode}
              selectedId={selected?.id ?? null}
              dataKey={`${windowDays}|${effectiveDate}|${assessState.status}|${geo.features.length}`}
              onSelect={select}
            />
            {loading && (
              <div className="map-overlay">
                <Loading label="Loading assessments…" />
              </div>
            )}
          </div>
          <Legend mode={mode} />
          {geo.skipped.length > 0 && (
            <div className="state state-error" role="alert">
              <h3>{geo.skipped.length} district(s) cannot be drawn</h3>
              <ul>
                {geo.skipped.map((s) => (
                  <li key={s.id}>
                    <button type="button" className="link-btn" onClick={() => select(s.id)}>
                      {s.name}
                    </button>
                    : {s.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {assessState.status === "error" &&
            (isNotFound(assessState.error) ? (
              <EmptyState title="No assessments for this date" commands={[BACKEND_COMMANDS.compute]}>
                The backend has none for {effectiveDate ? formatDate(effectiveDate) : "this date"} with a {windowDays}-day window, so every district is Unknown.
              </EmptyState>
            ) : (
              <ErrorState error={assessState.error} onRetry={assessState.reload} />
            ))}
          <DistrictTable districts={districts} byDistrict={byDistrict} selectedId={selected?.id ?? null} onSelect={select} />
        </div>
        {selected && <DistrictPanel district={selected} windowDays={windowDays} date={effectiveDate} onClose={() => update({ district: null })} />}
      </div>
    </div>
  );
}
