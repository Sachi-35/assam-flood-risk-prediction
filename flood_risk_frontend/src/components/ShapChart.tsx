import { Bar, BarChart, Cell, LabelList, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import type { ShapFeature } from "../api/types";
import { SHAP_COLOR, featureLabel } from "../constants";

/** Top SHAP features: bars to the right push the estimated class up, bars to the left push it down. */
export function ShapChart({ features }: { features: ShapFeature[] }) {
  const data = features.map((f) => ({
    name: featureLabel(f.feature_name),
    value: f.contribution_value,
    up: f.contribution_value > 0,
  }));
  const bound = Math.max(0.001, ...data.map((d) => Math.abs(d.value))) * 1.35;
  const summary = data.map((d) => `${d.name} ${d.up ? "raises" : "lowers"} by ${Math.abs(d.value).toFixed(3)}`).join("; ");
  return (
    <div>
      <div role="img" aria-label={`Top features: ${summary}`} className="chart chart-shap">
        <ResponsiveContainer width="100%" height={Math.max(120, data.length * 34 + 34)}>
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
            <XAxis type="number" domain={[-bound, bound]} tickFormatter={(v: number) => v.toFixed(2)} fontSize={11} />
            <YAxis type="category" dataKey="name" width={168} fontSize={12} tickLine={false} />
            <ReferenceLine x={0} stroke="#3b4658" />
            <Bar dataKey="value" isAnimationActive={false} stroke="#1f2937" strokeWidth={0.6}>
              {data.map((d) => (
                <Cell key={d.name} fill={d.up ? SHAP_COLOR.increases : SHAP_COLOR.decreases} />
              ))}
              <LabelList
                dataKey="value"
                position="right"
                formatter={(v: number) => `${v > 0 ? "▲ +" : "▼ "}${v.toFixed(3)}`}
                fontSize={11}
                fill="#14202e"
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="legend-note">
        <span className="key" style={{ background: SHAP_COLOR.increases }} /> ▲ pushes the estimate toward a higher class{" "}
        <span className="key" style={{ background: SHAP_COLOR.decreases }} /> ▼ pushes it toward a lower class. Values are SHAP
        contributions to the estimated class.
      </p>
    </div>
  );
}
