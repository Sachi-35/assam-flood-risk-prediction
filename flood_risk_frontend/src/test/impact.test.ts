import { describe, expect, it } from "vitest";
import { countImpact, impactTimeline, normalizeImpact } from "../lib/impact";

/** Records below are hand-written test inputs, not project data. */
describe("historical flood impact", () => {
  it("fills every missing year as unknown, never as zero or Low", () => {
    const cells = impactTimeline([{ year: 2021, status: "reported", impact_class: "high", affected_population: 1200 }]);
    expect(cells.map((c) => c.year)).toEqual([2019, 2020, 2021, 2022, 2023]);
    for (const c of cells.filter((c) => c.year !== 2021)) {
      expect(c.kind).toBe("unknown");
      expect(c.cls).toBeNull();
      expect(c.affected).toBeNull();
    }
    expect(cells.find((c) => c.year === 2021)).toMatchObject({ kind: "reported", cls: "high", affected: 1200 });
  });

  it("keeps 'no reported impact' separate from unknown and from Low", () => {
    const none = normalizeImpact({ year: 2022, status: "no_reported_impact" })!;
    expect(none.kind).toBe("none_reported");
    expect(none.cls).toBeNull();
    const unknown = normalizeImpact({ year: 2022, status: "unknown" })!;
    expect(unknown.kind).toBe("unknown");
    const low = normalizeImpact({ year: 2022, status: "reported", impact_class: "low" })!;
    expect(low.kind).toBe("reported");
    expect(low.cls).toBe("low");
  });

  it("never turns a missing or invalid affected count into 0", () => {
    expect(normalizeImpact({ year: 2020, status: "reported", impact_class: "moderate" })!.affected).toBeNull();
    expect(normalizeImpact({ year: 2020, status: "reported", impact_class: "moderate", affected_population: null })!.affected).toBeNull();
    expect(normalizeImpact({ year: 2020, status: "reported", impact_class: "moderate", affected_population: -5 })!.affected).toBeNull();
    expect(normalizeImpact({ year: 2020, status: "reported", impact_class: "moderate", affected_population: Number.NaN })!.affected).toBeNull();
    expect(normalizeImpact({ year: 2020, status: "reported", impact_class: "moderate", affected_population: 0 })!.affected).toBe(0);
  });

  it("treats unusable records as unknown", () => {
    expect(normalizeImpact({ year: 2021, status: "reported" })!.kind).toBe("unknown");
    expect(normalizeImpact({ year: 2021, status: "banana", impact_class: "high" })!.kind).toBe("unknown");
    expect(normalizeImpact({ year: 2021 })!.kind).toBe("unknown");
    expect(normalizeImpact({ year: 2021, status: "reported", impact_class: "banana" })!.kind).toBe("unknown");
  });

  it("ignores records without a usable year and tolerates junk", () => {
    expect(normalizeImpact({ status: "reported", impact_class: "high" })).toBeNull();
    expect(normalizeImpact(null)).toBeNull();
    const cells = impactTimeline([null, 5, "x", { year: "2021" }] as unknown[]);
    expect(cells).toHaveLength(5);
    expect(cells.every((c) => c.kind === "unknown")).toBe(true);
  });

  it("returns an all-unknown timeline for null or empty input", () => {
    for (const input of [null, undefined, []]) {
      const n = countImpact(impactTimeline(input));
      expect(n).toEqual({ reported: 0, none_reported: 0, unknown: 5 });
    }
  });

  it("keeps the informative record when a year is duplicated, and shows years outside the default span", () => {
    const cells = impactTimeline([
      { year: 2021, status: "unknown" },
      { year: 2021, status: "reported", impact_class: "severe" },
      { year: 2024, status: "reported", impact_class: "low" },
    ]);
    expect(cells.find((c) => c.year === 2021)!.cls).toBe("severe");
    expect(cells.map((c) => c.year)).toEqual([2019, 2020, 2021, 2022, 2023, 2024]);
  });
});
