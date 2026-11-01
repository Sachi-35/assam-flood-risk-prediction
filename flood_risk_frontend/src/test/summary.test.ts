import { describe, expect, it } from "vitest";
import { summarize } from "../lib/summary";
import { insufficientRain, makeAssessment } from "./fixtures";
import { make33Districts } from "./fixtures";

/** Synthetic districts and assessments. */
describe("overview counts", () => {
  const districts = make33Districts();

  it("counts districts with no assessment as Unknown, never as Low", () => {
    const s = summarize(districts, new Map(), "vulnerability");
    expect(s).toMatchObject({ total: 33, assessed: 0, unknown: 33, noAssessment: 33, withRainHazard: 0 });
    expect(s.byClass).toEqual({ low: 0, moderate: 0, high: 0, severe: 0 });
  });

  it("splits known and unknown, and the buckets add up", () => {
    const m = new Map([
      [1, makeAssessment({ district_id: 1 })], // vulnerability high, hazard moderate, combined high
      [2, { ...insufficientRain, district_id: 2 }], // vulnerability high, hazard + combined unknown
    ]);
    const vul = summarize(districts, m, "vulnerability");
    expect(vul.assessed).toBe(2);
    expect(vul.byClass.high).toBe(2);
    expect(vul.unknown).toBe(31);
    expect(vul.noAssessment).toBe(31);

    const comb = summarize(districts, m, "combined");
    expect(comb.assessed).toBe(1);
    expect(comb.unknown).toBe(32);
    expect(comb.noAssessment).toBe(31); // district 2 has a row, but its combined level is unknown

    const haz = summarize(districts, m, "hazard");
    expect(haz.withRainHazard).toBe(1);
    for (const s of [vul, comb, haz]) {
      const known = Object.values(s.byClass).reduce((a, b) => a + b, 0);
      expect(known).toBe(s.assessed);
      expect(s.assessed + s.unknown).toBe(s.total);
    }
  });

  it("ignores assessments for districts that are not in the list", () => {
    const m = new Map([[999, makeAssessment({ district_id: 999 })]]);
    expect(summarize(districts, m, "combined").assessed).toBe(0);
  });
});
