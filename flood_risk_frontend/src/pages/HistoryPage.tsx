import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipProps } from "recharts";
import { api } from "../api/client";
import type { Assessment, District } from "../api/types";
import { BootGate } from "../components/BootGate";
import { FloodImpactSection } from "../components/FloodImpactSection";
import { EmptyState, ErrorState, Loading } from "../components/StateViews";
import { BACKEND_COMMANDS, CLASS_STYLE, HAZARD_LEVEL_CLASS } from "../constants";
import { useAsync } from "../hooks/useAsync";
import { useAvailableDates } from "../hooks/useAvailableDates";
import { pickWindow } from "../hooks/useBoot";
import { addDays, formatDate, isIsoDate } from "../lib/dates";
import { buildHistoryPoints, type HistoryPoint } from "../lib/history";

const DEFAULT_DAYS = 90;

export function HistoryPage() {
  return <BootGate>{(boot) => <HistoryView windows={boot.windows} districts={boot.districts} />}</BootGate>;
}

function HistoryView({ windows, districts }: { windows: number[]; districts: District[] }) {
  const [params, setParams] = useSearchParams();
  const districtParam = Number(params.get("district"));
  const district = districts.find((d) => d.id === districtParam) ?? districts[0];
  const windowDays = pickWindow(params.get("window"), windows);
  const update = (patch: Record<string, string | null>) =>
    setParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) (v === null ? n.delete(k) : n.set(k, v));
        return n;
      },
      { replace: true },
    );

  const datesState = useAvailableDates(windowDays, [district.id]);
  const available = datesState.status === "ok" ? datesState.data : [];
  const min = available[0];
  const max = available[available.length - 1];
  const endParam = params.get("end");
  const startParam = params.get("start");
  const end = endParam && isIsoDate(endParam) ? endParam : max;
  const start = startParam && isIsoDate(startParam) ? startParam : max ? (addDays(max, -(DEFAULT_DAYS - 1)) < min ? min : addDays(max, -(DEFAULT_DAYS - 1))) : undefined;
  const rangeInvalid = !!(start && end && start > end);

  const hist = useAsync(
    async () => (windowDays !== null && start && end && !rangeInvalid ? api.history(district.id, windowDays, start, end) : ([] as Assessment[])),
    [district.id, windowDays, start, end, rangeInvalid],
  );

  const points = useMemo<HistoryPoint[]>(() => (hist.status !== "ok" || !start || !end ? [] : buildHistoryPoints(hist.data, start, end)), [hist, start, end]);
  const unknownDays = points.filter((p) => p.level === null).length;

  return (
    <div className="page">
      <h1>History</h1>
      <p>Two different kinds of record for one district. They are kept apart because they are different things.</p>
      <div className="controls" role="group" aria-label="District">
        <label>
          <span>District</span>
          <select value={district.id} onChange={(e) => update({ district: e.target.value })}>
            {districts.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <h2>1. Historical flood impact (seasonal, by year)</h2>
      <FloodImpactSection districtId={district.id} districtName={district.name} />

      <h2>2. Rainfall record (stored rainfall windows)</h2>
      <p className="muted">
        Each point is the total rain over the chosen window <em>ending</em> on that date, compared with this district's own history. It describes rain that was observed, not floods. Dates without
        enough rainfall observations are gaps, not zero.
      </p>
      {windowDays === null ? (
        <EmptyState title="No rainfall window offered">The backend returned no window lengths, so there is no rainfall record to chart.</EmptyState>
      ) : (
        <>
          <div className="controls" role="group" aria-label="Rainfall record controls">
            <label>
              <span>Window</span>
              <select value={windowDays} onChange={(e) => update({ window: e.target.value })}>
                {windows.map((w) => (
                  <option key={w} value={w}>
                    Last {w} days
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>From</span>
              <input type="date" value={start ?? ""} min={min} max={max} disabled={!available.length} onChange={(e) => e.target.value && update({ start: e.target.value })} />
            </label>
            <label>
              <span>To</span>
              <input type="date" value={end ?? ""} min={min} max={max} disabled={!available.length} onChange={(e) => e.target.value && update({ end: e.target.value })} />
            </label>
          </div>

          {datesState.status === "loading" && <Loading label="Looking up available dates…" />}
          {datesState.status === "error" && <ErrorState error={datesState.error} onRetry={datesState.reload} />}
          {datesState.status === "ok" && available.length === 0 && (
            <EmptyState title={`No rainfall record stored for ${district.name}`} commands={[BACKEND_COMMANDS.compute]}>
              Rainfall observations cover only some districts, so many districts have nothing here. That is a data gap, not dry weather.
            </EmptyState>
          )}
          {rangeInvalid && (
            <p className="field-error" role="alert">
              “From” must not be after “To”.
            </p>
          )}

          {datesState.status === "ok" && available.length > 0 && !rangeInvalid && (
            <>
              {hist.status === "loading" && <Loading label="Loading history…" />}
              {hist.status === "error" && <ErrorState error={hist.error} onRetry={hist.reload} />}
              {hist.status === "ok" && hist.data.length === 0 && (
                <EmptyState title="No assessments in this range">
                  {district.name} has no stored {windowDays}-day assessments between {start && formatDate(start)} and {end && formatDate(end)}.
                </EmptyState>
              )}
              {hist.status === "ok" && hist.data.length > 0 && (
                <>
                  <p className="muted small">
                    {district.name} · {windowDays}-day window · {start && formatDate(start)} to {end && formatDate(end)}. <strong>{unknownDays}</strong> of {points.length} days are Unknown and
                    appear as gaps in the lines (a gap is not zero rain and not Low).
                  </p>
                  <h3>Hazard level</h3>
                  <HazardChart data={points} />
                  <h3>Rain in the window (mm)</h3>
                  <RainChart data={points} />
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

const shortDate = (d: string) => formatDate(d).replace(/ \d{4}$/, "");

function HistoryTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as HistoryPoint;
  const label = p.level === null ? "Unknown" : CLASS_STYLE[HAZARD_LEVEL_CLASS[p.level]].label;
  return (
    <div className="chart-tip">
      <strong>{formatDate(p.date)}</strong>
      <div>Hazard: {label}</div>
      {p.level === null && p.gap && <div className="small">{p.gap}</div>}
      <div>Rain in window: {p.rain === null ? "Unknown" : `${p.rain.toFixed(1)} mm`}</div>
    </div>
  );
}

interface DotProps {
  cx?: number;
  cy?: number;
  payload?: HistoryPoint;
}
function LevelDot({ cx, cy, payload }: DotProps) {
  if (cx === undefined || cy === undefined || !payload || payload.level === null) return <g />;
  return <circle cx={cx} cy={cy} r={3.5} fill={CLASS_STYLE[HAZARD_LEVEL_CLASS[payload.level]].color} stroke="#1f2937" strokeWidth={1} />;
}

function HazardChart({ data }: { data: HistoryPoint[] }) {
  return (
    <div className="chart chart-history" role="img" aria-label="Step chart of hazard level over time; gaps mean Unknown">
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} syncId="history" margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#d6dbe2" />
          <XAxis dataKey="date" tickFormatter={shortDate} fontSize={11} minTickGap={36} />
          <YAxis domain={[0, 3]} ticks={[0, 1, 2, 3]} width={74} fontSize={12} tickFormatter={(v: number) => CLASS_STYLE[HAZARD_LEVEL_CLASS[v]]?.label ?? String(v)} />
          <Tooltip content={<HistoryTooltip />} />
          <Line type="stepAfter" dataKey="level" stroke="#0f6a78" strokeWidth={2} connectNulls={false} isAnimationActive={false} dot={<LevelDot />} activeDot={{ r: 5 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function RainChart({ data }: { data: HistoryPoint[] }) {
  return (
    <div className="chart chart-history" role="img" aria-label="Line chart of window rain in millimetres over time; gaps mean Unknown">
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} syncId="history" margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#d6dbe2" />
          <XAxis dataKey="date" tickFormatter={shortDate} fontSize={11} minTickGap={36} />
          <YAxis width={74} fontSize={12} unit=" mm" />
          <Tooltip content={<HistoryTooltip />} />
          <Line type="linear" dataKey="rain" stroke="#2a6db0" strokeWidth={2} connectNulls={false} isAnimationActive={false} dot={{ r: 2 }} activeDot={{ r: 5 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
