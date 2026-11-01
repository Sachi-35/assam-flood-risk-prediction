import { CLASS_ORDER, CLASS_STYLE, COLOR_MODES, type ColorMode } from "../constants";
import { Swatch } from "./MapPatterns";

const MEANING: Record<ColorMode, string> = {
  vulnerability: "Seasonal flood-impact class expected in a normal season.",
  hazard: "Rain in the chosen window compared with this district's own history.",
  combined: "Fixed rule combining vulnerability and rain hazard.",
};

/** Explains every colour on the map, including Unknown. */
export function Legend({ mode }: { mode: ColorMode }) {
  const m = COLOR_MODES.find((x) => x.value === mode)!;
  return (
    <figure className="legend" aria-label={`Legend: ${m.label}`}>
      <figcaption>
        <strong>{m.label}</strong>: {MEANING[mode]}
      </figcaption>
      <ul>
        {CLASS_ORDER.map((c) => (
          <li key={c}>
            <Swatch cls={c} /> {CLASS_STYLE[c].label}
          </li>
        ))}
        <li>
          <Swatch cls="unknown" /> <span><strong>Unknown</strong>: no assessment stored, or not enough data. This is not Low.</span>
        </li>
      </ul>
    </figure>
  );
}
