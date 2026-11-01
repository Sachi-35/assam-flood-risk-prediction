import { ApiError, api } from "../api/client";
import { useAsync } from "./useAsync";

/** How many districts to try before concluding that no assessment dates exist. */
const MAX_PROBES = 5;

/**
 * The backend has no "which dates exist" endpoint, so the dates are taken from a district's history for the window.
 * The first district may have no rows (rainfall covers only some districts), so up to MAX_PROBES districts are tried in order.
 * Sorted ascending, YYYY-MM-DD. Empty when none of them has any.
 */
export function useAvailableDates(windowDays: number | null, probeDistrictIds: number[]) {
  const key = probeDistrictIds.slice(0, MAX_PROBES).join(",");
  return useAsync<string[]>(async () => {
    if (windowDays === null) return [];
    for (const id of probeDistrictIds.slice(0, MAX_PROBES)) {
      try {
        const rows = await api.history(id, windowDays);
        const dates = Array.from(new Set(rows.map((r) => r.as_of_date))).sort();
        if (dates.length) return dates;
      } catch (e) {
        // 404 means nothing stored for this district; any other failure is real and should surface.
        if (!(e instanceof ApiError && e.status === 404)) throw e;
      }
    }
    return [];
  }, [windowDays, key]);
}
