import { api } from "../api/client";
import type { District } from "../api/types";
import { useAsync } from "./useAsync";

export interface BootData {
  windows: number[];
  windowsMeaning: string;
  districts: District[];
}

/** What every page needs first: the supported windows (GET /windows) and the districts (GET /districts). */
export function useBoot() {
  return useAsync<BootData>(async () => {
    const [w, d] = await Promise.all([api.windows(), api.districts()]);
    return { windows: w.windows, windowsMeaning: w.meaning, districts: d };
  }, []);
}

/** The chosen rainfall window, or null when the backend offers none (the map still works without one). */
export function pickWindow(raw: string | null, windows: number[]): number | null {
  const n = Number(raw);
  if (raw && windows.includes(n)) return n;
  if (windows.includes(7)) return 7;
  return windows[0] ?? null;
}
