import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { CLASS_ORDER, CLASS_STYLE } from "../constants";

/** Class probabilities of the vulnerability ML estimate (one bar per class, low to severe). */
export function ProbabilityChart({ proba }: { proba: Record<string, number> }) {
  const data = CLASS_ORDER.map((c) => ({ cls: c, name: CLASS_STYLE[c].label, value: typeof proba[c] === "number" && Number.isFinite(proba[c]) ? proba[c] : null }));
  const summary = data.map((d) => `${d.name} ${d.value === null ? "not available" : `${Math.round(d.value * 100)}%`}`).join(", ");
  return (
    <div role="img" aria-label={`Class probabilities: ${summary}`} className="chart chart-prob">
      <ResponsiveContainer width="100%" height={158}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 44, bottom: 4, left: 4 }}>
          <XAxis type="number" domain={[0, 1]} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} fontSize={11} />
          <YAxis type="category" dataKey="name" width={74} fontSize={12} tickLine={false} />
          <Bar dataKey="value" isAnimationActive={false} radius={[0, 3, 3, 0]} stroke="#3b4658" strokeWidth={0.6}>
            {data.map((d) => (
              <Cell key={d.cls} fill={CLASS_STYLE[d.cls].color} />
            ))}
            <LabelList dataKey="value" position="right" formatter={(v: number | null) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "n/a")} fontSize={12} fill="#14202e" />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
