import { COMPONENT_BADGE } from "../constants";

export function ComponentBadge({ type }: { type: string | null | undefined }) {
  const b = (type && COMPONENT_BADGE[type]) || { text: type ?? "Unknown type", hint: "" };
  return (
    <span className={`badge badge-${type ?? "unknown"}`} title={b.hint} data-component-type={type ?? ""}>
      {b.text}
    </span>
  );
}
