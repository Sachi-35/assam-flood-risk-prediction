/** Date helpers for YYYY-MM-DD strings, always handled in UTC so no timezone shifts. */

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

export function isIsoDate(s: string): boolean {
  const m = ISO.exec(s);
  if (!m) return false;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
}

export function toIso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function addDays(iso: string, n: number): string {
  const m = ISO.exec(iso)!;
  return toIso(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3] + n)));
}

/** Every calendar day from start to end inclusive. */
export function eachDay(start: string, end: string): string[] {
  const out: string[] = [];
  if (!isIsoDate(start) || !isIsoDate(end) || start > end) return out;
  for (let d = start; d <= end; d = addDays(d, 1)) out.push(d);
  return out;
}

export function formatDate(iso: string): string {
  if (!isIsoDate(iso)) return iso;
  const m = ISO.exec(iso)!;
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** Nearest date in a sorted list (ties go to the earlier one); null if the list is empty. */
export function nearestDate(sorted: string[], target: string): string | null {
  if (!sorted.length) return null;
  let best = sorted[0];
  let bestDiff = Infinity;
  const t = Date.parse(target + "T00:00:00Z");
  for (const d of sorted) {
    const diff = Math.abs(Date.parse(d + "T00:00:00Z") - t);
    if (diff < bestDiff) {
      best = d;
      bestDiff = diff;
    }
  }
  return best;
}
