import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import type { RecentRainfallObservation, District } from "../api/types";
import { BootGate } from "../components/BootGate";
import { ErrorState, Loading } from "../components/StateViews";

const formatDate = (value: string) =>
  new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });

const shortDate = (value: string) =>
  new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
  });

export function RecentRainfallPage() {
  return (
    <BootGate>
      {(boot) => <RecentRainfallView districts={boot.districts} />}
    </BootGate>
  );
}

function RecentRainfallView({ districts }: { districts: District[] }) {
  const [observations, setObservations] = useState<RecentRainfallObservation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [selectedId, setSelectedId] = useState("");

  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  useEffect(() => {
    let active = true;

    api.recentRainfall(10000)
      .then((response) => {
        if (!active) return;
        setObservations(response.observations);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err : new Error("Could not load IMD rainfall data."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const availableDistrictIds = useMemo(
    () => [...new Set(observations.map((item) => item.district_id))].sort((a, b) => a - b),
    [observations],
  );

  const activeId = selectedId || String(availableDistrictIds[0] ?? "");

  const districtOptions = useMemo(
    () =>
      availableDistrictIds.map((id) => ({
        id,
        name: districts.find((district) => district.id === id)?.name
          ?? observations.find((item) => item.district_id === id)?.district
          ?? `District ${id}`,
      })),
    [availableDistrictIds, districts, observations],
  );

  const districtObservations = useMemo(
    () =>
      observations
        .filter((item) => item.district_id === Number(activeId))
        .sort((a, b) => a.date.localeCompare(b.date)),
    [observations, activeId],
  );

  const minDate = districtObservations[0]?.date ?? "";
  const maxDate = districtObservations[districtObservations.length - 1]?.date ?? "";

  const from = start || minDate;
  const to = end || maxDate;
  const invalidRange = Boolean(from && to && from > to);

  const filtered = useMemo(
    () =>
      invalidRange
        ? []
        : districtObservations.filter((item) => item.date >= from && item.date <= to),
    [districtObservations, from, to, invalidRange],
  );

  const totalRain = filtered.reduce((sum, item) => sum + item.rainfall_mm, 0);
  const maxObservation = filtered.reduce<RecentRainfallObservation | null>(
    (best, item) => (!best || item.rainfall_mm > best.rainfall_mm ? item : best),
    null,
  );

  const selectedName =
    districtOptions.find((item) => String(item.id) === activeId)?.name ?? "District";

  if (loading) {
    return <div className="page"><h1>Recent observed rainfall</h1><Loading label="Loading IMD rainfall observations…" /></div>;
  }

  if (error) {
    return (
      <div className="page">
        <h1>Recent observed rainfall</h1>
        <ErrorState error={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }

  if (observations.length === 0) {
    return (
      <div className="page">
        <h1>Recent observed rainfall</h1>
        <p className="notice warn">The backend returned no recent IMD rainfall observations.</p>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-intro">
        <h1>Recent observed rainfall</h1>
        <p>
          Daily rainfall observations published in the IMD district-wise dataset. 
          This is a separate recent-data view, not an official flood warning or a flood-risk classification.
        </p>
      </div>

      <div className="controls rainfall-controls" role="group" aria-label="Recent rainfall filters">
        <label>
          <span>District</span>
          <select value={activeId} onChange={(e) => { setSelectedId(e.target.value); setStart(""); setEnd(""); }}>
            {districtOptions.map((district) => (
              <option key={district.id} value={district.id}>{district.name}</option>
            ))}
          </select>
        </label>

        <label>
          <span>From</span>
          <input
            type="date"
            value={from}
            min={minDate}
            max={maxDate}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>

        <label>
          <span>To</span>
          <input
            type="date"
            value={to}
            min={minDate}
            max={maxDate}
            onChange={(e) => setEnd(e.target.value)}
          />
        </label>

        <button className="btn" type="button" onClick={() => { setStart(""); setEnd(""); }}>
          Reset dates
        </button>
      </div>

      {invalidRange && (
        <p className="field-error" role="alert">The start date must not be after the end date.</p>
      )}

      <p className="muted small rainfall-coverage">
        {selectedName} · {filtered.length} daily observations ·
        {from && to ? ` ${formatDate(from)} to ${formatDate(to)}` : ""}
      </p>

      <section className="rainfall-stats" aria-label="Rainfall summary">
        <div>
          <span>Total observed rainfall</span>
          <strong>{totalRain.toFixed(1)} mm</strong>
        </div>
        <div>
          <span>Daily observations</span>
          <strong>{filtered.length}</strong>
        </div>
        <div>
          <span>Highest daily rainfall</span>
          <strong>{maxObservation ? `${maxObservation.rainfall_mm.toFixed(1)} mm` : "—"}</strong>
          {maxObservation && <small>{formatDate(maxObservation.date)}</small>}
        </div>
      </section>

      <h2>Daily rainfall trend</h2>
      {filtered.length === 0 ? (
        <p className="notice warn">No observations are available for this district and date range.</p>
      ) : (
        <div className="chart rainfall-chart" role="img" aria-label={`Daily observed rainfall in ${selectedName}, in millimetres`}>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={filtered} margin={{ top: 12, right: 20, bottom: 8, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#d6dbe2" />
              <XAxis dataKey="date" tickFormatter={shortDate} fontSize={11} minTickGap={28} />
              <YAxis width={65} fontSize={12} unit=" mm" />
              <Tooltip
                labelFormatter={(value) => formatDate(String(value))}
                formatter={(value) => [`${Number(value).toFixed(1)} mm`, "Daily rainfall"]}
              />
              <Line
                type="monotone"
                dataKey="rainfall_mm"
                name="Daily rainfall"
                stroke="#167d9a"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <h2>Daily observations</h2>
      <div className="table-scroll rainfall-table">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>District</th>
              <th>Daily actual rainfall</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {[...filtered].reverse().slice(0, 20).map((item) => (
              <tr key={`${item.district_id}-${item.date}`}>
                <td>{formatDate(item.date)}</td>
                <td>{item.district}</td>
                <td>{item.rainfall_mm.toFixed(1)} mm</td>
                <td>IMD</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Showing the latest 20 observations in the selected range.
      </p>

      <div className="disclaimer">
        <strong>Data interpretation:</strong> Values are daily actual rainfall in millimetres.
        A recorded 0.0 mm is an observed zero; a missing observation is not treated as zero.
        These recent 2026 observations are kept separate from the historical rainfall and
        climatology used by the existing assessment. They do not independently establish 
        flood hazard, vulnerability, or an official warning.
      </div>
    </div>
  );
}
