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
import type { District, RainfallArchiveObservation } from "../api/types";
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

export function RainfallArchivePage() {
  return (
    <BootGate>
      {(boot) => <RainfallArchiveView districts={boot.districts} />}
    </BootGate>
  );
}

function RainfallArchiveView({ districts }: { districts: District[] }) {
  const [observations, setObservations] = useState<RainfallArchiveObservation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [selectedId, setSelectedId] = useState("all");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  useEffect(() => {
    let active = true;

    api.rainfallArchive()
      .then((response) => {
        if (active) setObservations(response.observations);
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err : new Error("Could not load the rainfall archive."));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const minDate = "2024-01-01";
  const maxDate = "2026-11-01";
  const from = start || minDate;
  const to = end || maxDate;
  const invalidRange = Boolean(from && to && from > to);

  const filtered = useMemo(() => {
    if (invalidRange) return [];

    return observations.filter((item) => {
      const districtMatches = selectedId === "all" || item.district_id === Number(selectedId);
      return districtMatches && item.date >= from && item.date <= to;
    });
  }, [observations, selectedId, from, to, invalidRange]);

  const actualCount = filtered.filter((item) => !item.is_estimated).length;
  const estimatedCount = filtered.length - actualCount;
  const meanRainfall = filtered.length
    ? filtered.reduce((sum, item) => sum + item.rainfall_mm, 0) / filtered.length
    : null;

  const maxObservation = filtered.reduce<RainfallArchiveObservation | null>(
    (best, item) => (!best || item.rainfall_mm > best.rainfall_mm ? item : best),
    null,
  );

  const chartData = useMemo(() => {
    const grouped = new Map<string, { actualTotal: number; actualCount: number; estimatedTotal: number; estimatedCount: number }>();

    for (const item of filtered) {
      const current = grouped.get(item.date) ?? {
        actualTotal: 0,
        actualCount: 0,
        estimatedTotal: 0,
        estimatedCount: 0,
      };

      if (item.is_estimated) {
        current.estimatedTotal += item.rainfall_mm;
        current.estimatedCount += 1;
      } else {
        current.actualTotal += item.rainfall_mm;
        current.actualCount += 1;
      }

      grouped.set(item.date, current);
    }

    return [...grouped.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, values]) => ({
        date,
        actual: values.actualCount ? values.actualTotal / values.actualCount : null,
        estimated: values.estimatedCount ? values.estimatedTotal / values.estimatedCount : null,
      }));
  }, [filtered]);

  const selectedName = selectedId === "all"
    ? "All Assam districts"
    : districts.find((district) => district.id === Number(selectedId))?.name ?? "Selected district";

  const latestRecords = useMemo(
    () => [...filtered].sort((a, b) => b.date.localeCompare(a.date) || a.district.localeCompare(b.district)).slice(0, 20),
    [filtered],
  );

  if (loading) {
    return <div className="page"><h1>2024–2026 rainfall archive</h1><Loading label="Loading district rainfall archive…" /></div>;
  }

  if (error) {
    return (
      <div className="page">
        <h1>2024–2026 rainfall archive</h1>
        <ErrorState error={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-intro">
        <h1>2024–2026 rainfall archive</h1>
        <p>
          District-level daily rainfall coverage from 1 January 2024 to 1 November 2026.
          This archive combines a limited set of IMD daily actual observations with
          historical climatology-based estimates. It is not a daily rainfall observation
          record for the entire period.
        </p>
      </div>

      <div className="notice warn">
        <strong>Important:</strong> Most records in this archive are estimates, not observed
        rainfall. The estimates use historical day-of-year averages and must not be interpreted
        as actual rainfall, a rainfall forecast, or evidence of flooding.
      </div>

      <div className="controls rainfall-controls" role="group" aria-label="Rainfall archive filters">
        <label>
          <span>District</span>
          <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
            <option value="all">All 33 districts</option>
            {[...districts].sort((a, b) => a.name.localeCompare(b.name)).map((district) => (
              <option key={district.id} value={district.id}>{district.name}</option>
            ))}
          </select>
        </label>

        <label>
          <span>From</span>
          <input type="date" value={from} min={minDate} max={maxDate} onChange={(e) => setStart(e.target.value)} />
        </label>

        <label>
          <span>To</span>
          <input type="date" value={to} min={minDate} max={maxDate} onChange={(e) => setEnd(e.target.value)} />
        </label>

        <button className="btn" type="button" onClick={() => { setStart(""); setEnd(""); }}>
          Reset dates
        </button>
      </div>

      {invalidRange && (
        <p className="field-error" role="alert">The start date must not be after the end date.</p>
      )}

      <p className="muted small rainfall-coverage">
        {selectedName} · {filtered.length.toLocaleString("en-IN")} district-day records · {formatDate(from)} to {formatDate(to)}
      </p>

      <section className="rainfall-stats" aria-label="Rainfall archive summary">
        <div>
          <span>Total records</span>
          <strong>{filtered.length.toLocaleString("en-IN")}</strong>
        </div>
        <div>
          <span>IMD actual observations</span>
          <strong>{actualCount.toLocaleString("en-IN")}</strong>
        </div>
        <div>
          <span>Climatology estimates</span>
          <strong>{estimatedCount.toLocaleString("en-IN")}</strong>
        </div>
        <div>
          <span>Mean per district-day record</span>
          <strong>{meanRainfall === null ? "—" : `${meanRainfall.toFixed(1)} mm`}</strong>
        </div>
      </section>

      <h2>Daily rainfall trend</h2>
      <p className="muted small">
        {selectedId === "all"
          ? "For All Assam districts, each point is the mean across districts with a record on that date. Actual and estimated records are averaged separately."
          : "Actual IMD observations and climatology estimates are displayed as separate series."}
      </p>

      {chartData.length === 0 ? (
        <p className="notice warn">No records are available for this district and date range.</p>
      ) : (
        <div className="chart rainfall-chart" role="img" aria-label={`Daily rainfall archive trend for ${selectedName}`}>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={chartData} margin={{ top: 12, right: 20, bottom: 8, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#d6dbe2" />
              <XAxis dataKey="date" tickFormatter={shortDate} fontSize={11} minTickGap={28} />
              <YAxis width={65} fontSize={12} unit=" mm" />
              <Tooltip
                labelFormatter={(value) => formatDate(String(value))}
                formatter={(value, name) => [
                  value === null ? "No records" : `${Number(value).toFixed(1)} mm`,
                  name === "actual" ? "IMD actual mean" : "Estimated mean",
                ]}
              />
              <Line
                type="monotone"
                dataKey="actual"
                name="actual"
                stroke="#167d9a"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="estimated"
                name="estimated"
                stroke="#c28a36"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="muted small">
        <span style={{ color: "#167d9a" }}>●</span> IMD actual observations
        {" · "}
        <span style={{ color: "#c28a36" }}>●</span> Historical climatology estimates
      </div>

      <h2>Latest records in selected range</h2>
      <div className="table-scroll rainfall-table">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>District</th>
              <th>Rainfall</th>
              <th>Record type</th>
              <th>Source</th>
              <th>Stations</th>
            </tr>
          </thead>
          <tbody>
            {latestRecords.map((item) => (
              <tr key={`${item.district_id}-${item.date}`}>
                <td>{formatDate(item.date)}</td>
                <td>{item.district}</td>
                <td>{item.rainfall_mm.toFixed(1)} mm</td>
                <td>{item.is_estimated ? "Climatology estimate" : "Observed (IMD)"}</td>
                <td>{item.source}</td>
                <td>{item.n_stations}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Showing the latest 20 records in the selected range.</p>

      {maxObservation && (
        <p className="muted small">
          Highest value in this selection: {maxObservation.rainfall_mm.toFixed(1)} mm
          on {formatDate(maxObservation.date)} in {maxObservation.district}
          ({maxObservation.is_estimated ? "estimate" : "IMD observation"}).
        </p>
      )}

      <div className="disclaimer">
        <strong>Data interpretation and limitations:</strong> The archive contains
        2,294 IMD daily actual observations and 31,894 climatology-based estimates in
        the full dataset. Estimated values are derived from historical day-of-year
        averages, including district-specific, nearest-day, or statewide fallback
        averages. They are not observations for the dates shown. A value of 0.0 mm
        in an IMD record is an observed zero; estimated values must remain identified
        as estimates. This archive is kept separate from the existing rainfall hazard
        calculations and district risk assessments. Rainfall values alone do not
        establish inundation, flood occurrence, or affected population.
      </div>
    </div>
  );
}
