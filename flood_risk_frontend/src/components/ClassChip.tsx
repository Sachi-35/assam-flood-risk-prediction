import type { ClassResult } from "../lib/assessment";
import { CLASS_STYLE } from "../constants";

/** A class label with colour, glyph and text; Unknown is grey and always carries its reason. */
export function ClassChip({ result, showReason = false, large = false }: { result: ClassResult; showReason?: boolean; large?: boolean }) {
  const s = CLASS_STYLE[result.cls];
  return (
    <span className="chip-wrap">
      <span
        className={`chip chip-${result.cls}${large ? " chip-lg" : ""}`}
        style={{ background: s.color, color: s.ink }}
        title={result.reason ?? undefined}
        data-class={result.cls}
      >
        <span aria-hidden="true">{s.glyph}</span> {result.label}
      </span>
      {showReason && result.reason && <span className="chip-reason">{result.reason}</span>}
    </span>
  );
}
