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

  const meanRainfall = filtered.length
    ? filtered.reduce((sum, item) => sum + item.rainfall_mm, 0) / filtered.length
    : null;

  const maxObservation = filtered.reduce<RainfallArchiveObservation | null>(
    (best, item) => (!best || item.rainfall_mm > best.rainfall_mm ? item : best),
    null,
  );

  const chartData = useMemo(() => {
    const grouped = new Map<string, { total: number; count: number }>();

    for (const item of filtered) {
      const current = grouped.get(item.date) ?? { total: 0, count: 0 };
      current.total += item.rainfall_mm;
      current.count += 1;
      grouped.set(item.date, current);
    }

    return [...grouped.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, values]) => ({
        date,
        rainfall: values.total / values.count,
      }));
  }, [filtered]);

  const selectedName = selectedId === "all"
    ? "All Assam districts"
    : districts.find((district) => district.id === Number(selectedId))?.name ?? "Selected district";

  const latestRecords = useMemo(
    () => [...filtered]
      .sort((a, b) => b.date.localeCompare(a.date) || a.district.localeCompare(b.district))
      .slice(0, 20),
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
          District-level daily rainfall records from 1 January 2024 to 1 November 2026
          across all 33 Assam districts.
        </p>
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
          <span>Mean rainfall per district-day</span>
          <strong>{meanRainfall === null ? "—" : `${meanRainfall.toFixed(1)} mm`}</strong>
        </div>
        <div>
          <span>Highest daily value</span>
          <strong>{maxObservation ? `${maxObservation.rainfall_mm.toFixed(1)} mm` : "—"}</strong>
        </div>
      </section>

      <h2>Daily rainfall trend</h2>
      <p className="muted small">
        {selectedId === "all"
          ? "Each point shows the mean daily rainfall across districts with a record on that date."
          : `Daily rainfall values for ${selectedName}.`}
      </p>

      {chartData.length === 0 ? (
        <p className="notice warn">No records are available for this district and date range.</p>
      ) : (
        <div className="chart rainfall-chart" role="img" aria-label={`Daily rainfall trend for ${selectedName}`}>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={chartData} margin={{ top: 12, right: 20, bottom: 8, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#d6dbe2" />
              <XAxis dataKey="date" tickFormatter={shortDate} fontSize={11} minTickGap={28} />
              <YAxis width={65} fontSize={12} unit=" mm" />
              <Tooltip
                labelFormatter={(value) => formatDate(String(value))}
                formatter={(value) => [
                  value === null ? "No records" : `${Number(value).toFixed(1)} mm`,
                  "Mean rainfall",
                ]}
              />
              <Line
                type="monotone"
                dataKey="rainfall"
                name="Mean rainfall"
                stroke="#167d9a"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <h2>Latest records in selected range</h2>
      <div className="table-scroll rainfall-table">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>District</th>
              <th>Rainfall</th>
            </tr>
          </thead>
          <tbody>
            {latestRecords.map((item) => (
              <tr key={`${item.district_id}-${item.date}`}>
                <td>{formatDate(item.date)}</td>
                <td>{item.district}</td>
                <td>{item.rainfall_mm.toFixed(1)} mm</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Showing the latest 20 records in the selected range.</p>

      {maxObservation && (
        <p className="muted small">
          Highest value in this selection: {maxObservation.rainfall_mm.toFixed(1)} mm
          on {formatDate(maxObservation.date)} in {maxObservation.district}.
        </p>
      )}

      <div className="disclaimer">
        <strong>Data interpretation:</strong> Daily rainfall values support rainfall
        monitoring and district assessment calculations. Rainfall values alone do not
        establish inundation, flood occurrence, or affected population.
      </div>
    </div>
  );
}
