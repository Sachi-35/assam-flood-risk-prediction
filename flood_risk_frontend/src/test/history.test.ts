import { describe, expect, it } from "vitest";
import { buildHistoryPoints } from "../lib/history";
import { insufficientRain, makeAssessment } from "./fixtures";

describe("rainfall history series (synthetic rows)", () => {
  it("leaves dates with no row, or insufficient data, as null gaps and never 0", () => {
    const rows = [
      makeAssessment({ as_of_date: "2023-07-10" }),
      { ...insufficientRain, as_of_date: "2023-07-12" },
    ];
    const pts = buildHistoryPoints(rows, "2023-07-10", "2023-07-13");
    expect(pts.map((p) => p.date)).toEqual(["2023-07-10", "2023-07-11", "2023-07-12", "2023-07-13"]);
    expect(pts[0]).toMatchObject({ level: 1, rain: 72.5, gap: null });
    for (const p of [pts[1], pts[2], pts[3]]) {
      expect(p.level).toBeNull();
      expect(p.rain).toBeNull();
      expect(p.gap).toBeTruthy();
    }
  });

  it("keeps a real zero rain total and a real Low level", () => {
    const row = makeAssessment({ as_of_date: "2023-07-10", hazard: { ...makeAssessment().hazard, level: 0, window_rain_mm: 0 } });
    expect(buildHistoryPoints([row], "2023-07-10", "2023-07-10")[0]).toMatchObject({ level: 0, rain: 0 });
  });

  it("returns nothing for an invalid range", () => {
    expect(buildHistoryPoints([], "2023-07-12", "2023-07-10")).toEqual([]);
  });
});
