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
import type { CombinedRainfallObservation, District } from "../api/types";
import { BootGate } from "../components/BootGate";
import { ErrorState, Loading } from "../components/StateViews";
import { InfoNote, PageHeader, Section, StatCard } from "../components/ui";

const RANGE_START = "2019-01-01";
const RANGE_END = "2026-11-01";

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
    year: "2-digit",
  });

const formatMm = (value: number) => `${value.toFixed(1)} mm`;

export function RecentRainfallPage() {
  return (
    <BootGate>
      {(boot) => <RecentRainfallView districts={boot.districts} />}
    </BootGate>
  );
}

function RecentRainfallView({ districts }: { districts: District[] }) {
  const [observations, setObservations] = useState<CombinedRainfallObservation[]>([]);
  const [disclaimer, setDisclaimer] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [start, setStart] = useState(RANGE_START);
  const [end, setEnd] = useState(RANGE_END);

  useEffect(() => {
    let active = true;

    api.rainfallCombined(null, RANGE_START, RANGE_END, 50000)
      .then((response) => {
        if (!active) return;
        setObservations(response.observations);
        setDisclaimer(response.disclaimer);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err : new Error("Could not load rainfall observations."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const activeId = selectedId === "" ? null : Number(selectedId);
  const invalidRange = Boolean(start && end && start > end);

  const filtered = useMemo(
    () =>
      invalidRange
        ? []
        : observations.filter((item) =>
            (activeId === null || item.district_id === activeId)
            && item.date >= start
            && item.date <= end
          ),
    [observations, activeId, start, end, invalidRange],
  );

  const summary = useMemo(() => {
    const total = filtered.reduce((sum, item) => sum + item.rainfall_mm, 0);
    const highest = filtered.reduce<CombinedRainfallObservation | null>(
      (best, item) => (!best || item.rainfall_mm > best.rainfall_mm ? item : best),
      null,
    );
    const districtCount = new Set(filtered.map((item) => item.district_id)).size;

    return {
      total,
      count: filtered.length,
      mean: filtered.length ? total / filtered.length : null,
      highest,
      districtCount,
    };
  }, [filtered]);

  const chartData = useMemo(() => {
    const byDate = new Map<string, { total: number; count: number }>();

    for (const item of filtered) {
      const current = byDate.get(item.date) ?? { total: 0, count: 0 };
      current.total += item.rainfall_mm;
      current.count += 1;
      byDate.set(item.date, current);
    }

    return [...byDate.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, value]) => ({
        date,
        rainfall_mm: value.total / value.count,
        district_count: value.count,
      }));
  }, [filtered]);

  const selectedName = activeId === null
    ? "All districts"
    : districts.find((district) => district.id === activeId)?.name ?? "Selected district";

  const resetFilters = () => {
    setSelectedId("");
    setStart(RANGE_START);
    setEnd(RANGE_END);
  };

  if (loading) {
    return <div className="page"><PageHeader eyebrow="Explore · Rainfall" title="Recent Rainfall" /><Loading label="Loading district rainfall records…" /></div>;
  }

  if (error) {
    return (
      <div className="page">
        <PageHeader eyebrow="Explore · Rainfall" title="Recent Rainfall" />
        <ErrorState error={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader eyebrow="Explore · Rainfall" title="Recent Rainfall">
        Daily district-level rainfall observations from 2019 to 2026. Choose a district and a date range to explore the records. Coverage varies between
        districts and years, so every figure on this page describes only the observations that were recorded.
      </PageHeader>

      <div className="controls rainfall-controls" role="group" aria-label="Rainfall filters">
        <label>
          <span>District</span>
          <select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
            <option value="">All districts</option>
            {[...districts]
              .sort((a, b) => a.name.localeCompare(b.name))
              .map((district) => (
                <option key={district.id} value={district.id}>{district.name}</option>
              ))}
          </select>
        </label>

        <label>
          <span>From</span>
          <input type="date" value={start} min={RANGE_START} max={RANGE_END} onChange={(event) => setStart(event.target.value)} />
        </label>

        <label>
          <span>To</span>
          <input type="date" value={end} min={RANGE_START} max={RANGE_END} onChange={(event) => setEnd(event.target.value)} />
        </label>

        <button className="btn" type="button" onClick={resetFilters}>
          Reset filters
        </button>
      </div>

      {invalidRange && (
        <p className="field-error" role="alert">The start date must not be after the end date.</p>
      )}

      <p className="muted small rainfall-coverage">
        {selectedName} · {summary.count.toLocaleString("en-IN")} district-day observations ·
        {` ${formatDate(start)} to ${formatDate(end)}`}
      </p>

      <Section title="Summary of the selected records" subtitle="Each figure is calculated only from district-day observations that were recorded in the selected range.">
        <section className="rainfall-stats" aria-label="Rainfall summary">
          <StatCard
            label="Cumulative district-day rainfall"
            value={formatMm(summary.total)}
            note={
              activeId === null
                ? "The sum of every recorded district-day measurement. It is not a statewide rainfall total."
                : "The sum of this district's recorded daily measurements in the range."
            }
          />
          <StatCard label="Recorded district-day observations" value={summary.count.toLocaleString("en-IN")} note="One observation is one district on one date. Dates with no record are not counted." />
          <StatCard label="Average per recorded observation" value={summary.mean === null ? "—" : formatMm(summary.mean)} note="Cumulative rainfall divided by the number of recorded observations." />
          <StatCard
            label="Highest daily rainfall"
            value={summary.highest ? formatMm(summary.highest.rainfall_mm) : "—"}
            sub={summary.highest ? `${summary.highest.district} · ${formatDate(summary.highest.date)}` : undefined}
            note="The largest single recorded district-day value in the range."
          />
          <StatCard label="Districts represented" value={`${summary.districtCount} / 33`} note="Districts with at least one recorded observation in the range." />
        </section>
      </Section>

      <Section
        title={activeId === null ? "Average daily rainfall across reporting districts" : `Daily rainfall trend · ${selectedName}`}
        subtitle={
          activeId === null
            ? "Each point is the mean rainfall across the districts that have a recorded observation on that date. It is an average, not a sum across districts."
            : `Each point is ${selectedName}'s recorded rainfall for that day.`
        }
      >
        {chartData.length === 0 ? (
          <p className="notice warn">No rainfall observations are available for the selected filters.</p>
        ) : (
          <div className="chart rainfall-chart" role="img" aria-label={`Daily rainfall trend for ${selectedName}, in millimetres`}>
            <ResponsiveContainer width="100%" height={340}>
              <LineChart data={chartData} margin={{ top: 12, right: 20, bottom: 8, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#d6dbe2" />
                <XAxis dataKey="date" tickFormatter={shortDate} fontSize={11} minTickGap={28} />
                <YAxis width={70} fontSize={12} unit=" mm" />
                <YAxis yAxisId="right" orientation="right" hide domain={[0, 33]} />
                <Tooltip
                  labelFormatter={(value) => formatDate(String(value))}
                  formatter={(value, name) => {
                    if (name === "Districts with records") {
                      return [String(value), String(name)];
                    }
                    return [formatMm(Number(value)), "Average daily rainfall"];
                  }}
                />
                <Line type="monotone" dataKey="rainfall_mm" name="Average daily rainfall" stroke="#0f6a78" strokeWidth={2} dot={false} activeDot={{ r: 5 }} isAnimationActive={false} />
                {activeId === null && (
                  <Line type="monotone" dataKey="district_count" name="Districts with records" stroke="#8a6bbd" strokeWidth={1.5} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} yAxisId="right" hide />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        <InfoNote title="Reading this chart">
          <p>
            {activeId === null
              ? "The number of reporting districts differs from date to date, so a change in the line can reflect which districts reported as well as how much rain fell. "
              : ""}
            Dates without a record are left out of the line. They are not filled with zero. A recorded 0.0 mm is a real observed zero; a missing observation is unknown.
          </p>
        </InfoNote>
      </Section>

      <Section title="Daily observations" subtitle="The most recent records in the selected range.">
        {filtered.length === 0 ? (
          <p className="notice warn">No observations match the selected filters.</p>
        ) : (
          <div className="table-scroll rainfall-table">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>District</th>
                  <th>Daily rainfall</th>
                </tr>
              </thead>
              <tbody>
                {[...filtered]
                  .sort((a, b) => b.date.localeCompare(a.date) || a.district.localeCompare(b.district))
                  .slice(0, 20)
                  .map((item) => (
                    <tr key={`${item.district_id}-${item.date}`}>
                      <td>{formatDate(item.date)}</td>
                      <td>{item.district}</td>
                      <td>{formatMm(item.rainfall_mm)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small">Showing the latest 20 records in the selected range, ordered by date.</p>
      </Section>

      <div className="disclaimer">
        <strong>Data interpretation:</strong> {disclaimer} A recorded 0.0 mm is an observed
        zero; a missing observation is not treated as zero. For all-district summaries,
        rainfall totals are sums of recorded district-day values and should not be interpreted
        as a measured statewide rainfall total. Rainfall alone does not establish flood
        occurrence, inundation, vulnerability, or an official warning.
      </div>
    </div>
  );
}
