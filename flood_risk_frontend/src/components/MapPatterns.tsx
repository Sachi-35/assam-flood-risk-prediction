import { CLASS_ORDER, CLASS_STYLE, type DisplayClass } from "../constants";

export const patternId = (cls: DisplayClass) => `fp-${cls}`;
/** Value usable as an SVG `fill` (and as Leaflet's fillColor) for a class: colour + pattern. */
export const patternFill = (cls: DisplayClass) => `url(#${patternId(cls)})`;

function PatternBody({ cls }: { cls: DisplayClass }) {
  const s = CLASS_STYLE[cls];
  const ink = cls === "moderate" ? "#5a3300" : cls === "low" ? "#6b5b00" : cls === "unknown" ? "#6b7380" : "#ffffff";
  switch (s.pattern) {
    case "stripes":
      return <path d="M-2,2 l4,-4 M0,8 l8,-8 M6,10 l4,-4" stroke={ink} strokeWidth="1.4" opacity="0.55" />;
    case "cross":
      return <path d="M-2,2 l4,-4 M0,8 l8,-8 M6,10 l4,-4 M-2,6 l4,4 M0,0 l8,8 M6,-2 l4,4" stroke={ink} strokeWidth="1.1" opacity="0.5" />;
    case "dots":
      return (
        <>
          <circle cx="2" cy="2" r="1.3" fill={ink} opacity="0.6" />
          <circle cx="6" cy="6" r="1.3" fill={ink} opacity="0.6" />
        </>
      );
    case "hatch":
      return <path d="M-2,2 l4,-4 M0,8 l8,-8 M6,10 l4,-4" stroke={ink} strokeWidth="1" strokeDasharray="2 2" opacity="0.8" />;
    default:
      return null;
  }
}

/** Mount once near the app root. Defines the fill patterns referenced by map polygons and legend swatches. */
export function MapPatterns() {
  const all: DisplayClass[] = [...CLASS_ORDER, "unknown"];
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true" focusable="false">
      <defs>
        {all.map((cls) => (
          <pattern key={cls} id={patternId(cls)} width="8" height="8" patternUnits="userSpaceOnUse">
            <rect width="8" height="8" fill={CLASS_STYLE[cls].color} />
            <PatternBody cls={cls} />
          </pattern>
        ))}
      </defs>
    </svg>
  );
}

export function Swatch({ cls, size = 18 }: { cls: DisplayClass; size?: number }) {
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" className="swatch">
      <rect x="0.5" y="0.5" width={size - 1} height={size - 1} rx="3" fill={patternFill(cls)} stroke="#3b4658" strokeWidth="1" />
    </svg>
  );
}
